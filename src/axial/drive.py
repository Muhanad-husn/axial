"""Google Drive source connector (issue #237, slice 01: list, download, and
stream a Drive source into ingestion) -- see `specs/PRODUCT.md` Sec. 7.10
(Google Drive source contract) and Sec. 8 P0-11.

The connector is a first-class source provider: it lists the shared "Books"
folder through an injectable Drive client, filters listed files to
`.pdf`/`.docx` candidates, downloads each candidate's bytes to a local cache
path (docling needs a file path; the cache is an implementation detail, not
a staging contract), and hands each downloaded local path to an injectable
ingest callable.

By default, `ingest_fn` runs the FULL source-to-vault chain for a freshly
downloaded file -- `axial.extract.extract` -> `axial.envelope.run_envelope`
-> `axial.chunk.run_chunk_recursive` -> `axial.vault.run_vault_write`.
`run_vault_write` alone is only the pipeline TAIL: it reads a pre-existing
stored envelope (raising `MissingEnvelopeError` if one hasn't been produced
yet) and pre-built chunks (`axial.chunk.read_chunks`, never recomputed) --
it never runs extraction, the envelope pass, or the chunk pass itself. A
Drive-downloaded source has been through none of those yet, so the default
handoff must drive the whole chain, not just its tail (issue #237 review
finding). Each candidate's chain runs in isolation: a failure at any stage
is caught, logged to stderr, and the loop continues to the next candidate --
one bad source never aborts the whole folder (mirrors
`axial.ingest.run_ingest`'s per-source `FAIL` isolation). When `ingest_fn`
is injected (tests), it is used as-is -- the chain orchestrator never
overrides an explicit injection.

Auth is a Google service account: the `[drive]` section of
`secrets/secrets.toml` names the service-account JSON key path
(`service_account_json`) and the Books folder id (`books_folder_id`),
mirroring the `[openrouter]` secrets pattern (`axial.llm`). Missing or
incomplete `[drive]` secrets halt the connector with a clear message on
stderr and a non-zero exit -- before any Drive client call (P0-11).

This module imports the `google-auth` / `google-api-python-client` libraries
lazily, inside `DriveClient.__init__`, so `import axial.drive` and the
injectable-client code path stay runnable without those libraries installed
(the same offline guarantee as `specs/PRODUCT.md` Sec. 7.6).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import Any, Callable, Protocol

from axial.chunk import ChunkError, run_chunk_recursive
from axial.envelope import EnvelopeError, run_envelope
from axial.extract import ExtractError, extract
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.tag import DEFAULT_DOMAIN_DIR
from axial.vault import VaultError, run_vault_write

# The full taxonomy of errors any stage of the default source-to-vault chain
# (extract -> envelope -> chunk -> vault write) can raise. Caught per
# candidate so one bad source never aborts the whole folder (module
# docstring).
CHAIN_ERRORS = (ExtractError, EnvelopeError, ChunkError, VaultError)

# Default locations, mirroring the module-level default conventions already
# used across the codebase (e.g. `axial.llm.DEFAULT_SECRETS_PATH`,
# `axial.ingest.RESULTS_PATH`): plain paths relative to the process cwd.
DEFAULT_SECRETS_PATH = Path("secrets/secrets.toml")
DEFAULT_CACHE_DIR = Path("data/drive/cache")

# Candidate filter (Sec. 7.10 / plan slice 01): by name suffix and/or mime
# type. Neither replaces intake's own format/text-layer validation (P0-1) --
# this filter only decides what is worth downloading at all.
CANDIDATE_EXTENSIONS = {".pdf", ".docx"}
CANDIDATE_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class DriveError(Exception):
    """Base class for all drive-connector errors."""


class DriveSecretsError(DriveError):
    """Raised when `[drive]` secrets are absent, incomplete, or point at an
    unreadable key file. The message names the specific missing/invalid
    secret so the halt reason is actionable (P0-11)."""


class DriveClientProtocol(Protocol):
    """The injectable Drive client protocol (Sec. 7.10). The real
    implementation is `DriveClient`; tests inject a fake."""

    def list_files(
        self, folder_id: str, page_token: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    def download(self, file_id: str) -> bytes: ...


def _load_drive_secrets(secrets_path: Path) -> dict[str, str]:
    """Read and validate the `[drive]` section of `secrets_path`. Raises
    `DriveSecretsError`, naming the specific missing/invalid secret, on:
    an absent secrets file, an absent `[drive]` section, an absent or
    unreadable `service_account_json` key path, or an absent
    `books_folder_id`. Never touches the Drive client -- this is a pure,
    local, pre-network check (P0-11's "halts before any network call")."""
    if not secrets_path.is_file():
        raise DriveSecretsError(
            f"no secrets file at '{secrets_path}': missing [drive] section "
            "(service_account_json, books_folder_id)"
        )

    with secrets_path.open("rb") as handle:
        try:
            document = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise DriveSecretsError(
                f"secrets file '{secrets_path}' is not valid TOML: {exc}"
            ) from exc

    section = document.get("drive")
    if not section:
        raise DriveSecretsError(f"missing [drive] section in secrets file '{secrets_path}'")

    service_account_json = section.get("service_account_json")
    if not service_account_json:
        raise DriveSecretsError(
            f"missing 'service_account_json' in [drive] section of '{secrets_path}'"
        )
    key_path = Path(service_account_json)
    if not key_path.is_file():
        raise DriveSecretsError(
            f"[drive] service_account_json path '{key_path}' does not exist or is not readable"
        )

    books_folder_id = section.get("books_folder_id")
    if not books_folder_id:
        raise DriveSecretsError(f"missing 'books_folder_id' in [drive] section of '{secrets_path}'")

    return {
        "service_account_json": str(key_path),
        "books_folder_id": books_folder_id,
    }


def _is_candidate(record: dict[str, Any]) -> bool:
    """A Drive file record is a candidate if its name carries a `.pdf`/
    `.docx` suffix (case-insensitive) or its mime type matches one of the
    two formats intake accepts. Everything else is skipped -- never
    downloaded (plan slice 01)."""
    name = record.get("name", "") or ""
    suffix = Path(name).suffix.lower()
    mime_type = record.get("mimeType", "") or ""
    return suffix in CANDIDATE_EXTENSIONS or mime_type in CANDIDATE_MIME_TYPES


def _list_all_candidates(client: DriveClientProtocol, folder_id: str) -> list[dict[str, Any]]:
    """Paginate `client.list_files` to exhaustion (`next_page_token is
    None`), returning every listed record that passes `_is_candidate`."""
    candidates: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        records, page_token = client.list_files(folder_id, page_token=page_token)
        candidates.extend(record for record in records if _is_candidate(record))
        if page_token is None:
            break
    return candidates


def _cache_path(cache_dir: Path, record: dict[str, Any]) -> Path:
    """A deterministic local cache path for a candidate record: keyed by
    Drive file id (stable across runs) and preserving the source name's
    extension (downstream intake's format check reads it)."""
    suffix = Path(record.get("name", "") or "").suffix
    return cache_dir / f"{record['id']}{suffix}"


def _build_drive_client(service_account_json: str) -> "DriveClient":
    return DriveClient(service_account_json)


def _run_full_ingest_chain(
    source_path: Path,
    *,
    client: LLMClient | None,
    config_path: Path,
    domain_dir: str | Path,
    envelopes_dir: Path | None,
    chunks_dir: Path | None,
    tags_dir: Path | None,
    artifacts_dir: Path | None,
    xref_dir: Path | None,
    vault_dir: Path | None,
) -> list[Path]:
    """Run the full source-to-vault chain for one freshly-downloaded Drive
    source: extract -> envelope -> chunk -> vault write (module docstring).
    `run_vault_write` alone only reads pre-existing artifacts from the three
    passes ahead of it; a Drive-downloaded source has never been through
    them, so the default handoff must run every stage, not just the tail.
    Each pass persists its own artifact by `source_id`, so this is safe to
    call even when an earlier pass already ran for this source (e.g. a
    partial prior attempt) -- every pass is itself no-recompute/cached."""
    extract(source_path)
    run_envelope(source_path, client=client, envelopes_dir=envelopes_dir, config_path=config_path)
    run_chunk_recursive(source_path, chunks_dir=chunks_dir, config_path=config_path, client=client)
    return run_vault_write(
        source_path,
        client=client,
        envelopes_dir=envelopes_dir,
        vault_dir=vault_dir,
        config_path=config_path,
        domain_dir=domain_dir,
        chunks_dir=chunks_dir,
        tags_dir=tags_dir,
        artifacts_dir=artifacts_dir,
        xref_dir=xref_dir,
    )


def _default_ingest_fn(
    *,
    client: LLMClient | None,
    config_path: Path,
    domain_dir: str | Path,
    envelopes_dir: Path | None,
    chunks_dir: Path | None,
    tags_dir: Path | None,
    artifacts_dir: Path | None,
    xref_dir: Path | None,
    vault_dir: Path | None,
) -> Callable[[Path], list[Path]]:
    """Build the default `ingest_fn`: a closure over the threaded LLM
    client/config/dirs that runs `_run_full_ingest_chain` for one
    downloaded local path."""

    def _ingest_one(local_path: Path) -> list[Path]:
        return _run_full_ingest_chain(
            local_path,
            client=client,
            config_path=config_path,
            domain_dir=domain_dir,
            envelopes_dir=envelopes_dir,
            chunks_dir=chunks_dir,
            tags_dir=tags_dir,
            artifacts_dir=artifacts_dir,
            xref_dir=xref_dir,
            vault_dir=vault_dir,
        )

    return _ingest_one


def run_drive_ingest(
    folder_id: str,
    *,
    client: DriveClientProtocol | None = None,
    ingest_fn: Callable[[Path], Any] | None = None,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    llm_client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    envelopes_dir: Path | None = None,
    chunks_dir: Path | None = None,
    tags_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    xref_dir: Path | None = None,
    vault_dir: Path | None = None,
) -> int:
    """List `folder_id` through `client` (paginated to exhaustion), filter to
    `.pdf`/`.docx` candidates, download each candidate's bytes to a
    deterministic path under `cache_dir`, and hand each downloaded local
    path to `ingest_fn`. Returns 0 unless a fatal error prevents the run
    from happening at all (missing/incomplete `[drive]` secrets); a single
    candidate's ingest failure is caught, logged, and does not affect the
    overall exit code (module docstring's per-candidate isolation).

    `[drive]` secrets are loaded and validated FIRST, before any client
    construction or client call -- an absent/incomplete section halts with a
    non-zero exit and a stderr message naming the missing secret, making no
    client call and no download (P0-11).

    `client=None` lazily constructs the real `DriveClient` from the
    validated `service_account_json`. `ingest_fn=None` defaults to the full
    source-to-vault chain orchestrator (module docstring); `llm_client`,
    `config_path`, `domain_dir`, and the `*_dir` parameters are threaded
    into that default's closure and ignored when `ingest_fn` is injected
    (an injected callable owns its own configuration, if any).
    """
    secrets_path = Path(secrets_path)
    cache_dir = Path(cache_dir)

    try:
        secrets = _load_drive_secrets(secrets_path)
    except DriveSecretsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if client is None:
        client = _build_drive_client(secrets["service_account_json"])

    if ingest_fn is None:
        ingest_fn = _default_ingest_fn(
            client=llm_client,
            config_path=config_path,
            domain_dir=domain_dir,
            envelopes_dir=envelopes_dir,
            chunks_dir=chunks_dir,
            tags_dir=tags_dir,
            artifacts_dir=artifacts_dir,
            xref_dir=xref_dir,
            vault_dir=vault_dir,
        )

    candidates = _list_all_candidates(client, folder_id)

    cache_dir.mkdir(parents=True, exist_ok=True)
    for record in candidates:
        data = client.download(record["id"])
        local_path = _cache_path(cache_dir, record)
        local_path.write_bytes(data)
        try:
            ingest_fn(local_path)
        except CHAIN_ERRORS as exc:
            name = record.get("name") or local_path.name
            print(f"error: {name}: {exc}", file=sys.stderr)
            continue

    return 0


class DriveClient:
    """Real Drive v3 client, wrapping `google-auth` (service-account
    credentials) and `google-api-python-client` (the `drive` service),
    satisfying `DriveClientProtocol`. Imports the google libraries lazily,
    here in `__init__`, so `import axial.drive` and every non-real-client
    code path stay runnable without those libraries installed."""

    def __init__(self, service_account_json: str) -> None:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        credentials = service_account.Credentials.from_service_account_file(
            service_account_json, scopes=[DRIVE_READONLY_SCOPE]
        )
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def list_files(
        self, folder_id: str, page_token: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        response = (
            self._service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                pageToken=page_token,
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, md5Checksum)",
                spaces="drive",
            )
            .execute()
        )
        return response.get("files", []) or [], response.get("nextPageToken")

    def download(self, file_id: str) -> bytes:
        import io

        from googleapiclient.http import MediaIoBaseDownload

        request = self._service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()
