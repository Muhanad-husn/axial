"""Google Drive source connector (issue #237 slice 01: list, download, and
stream a Drive source into ingestion; issue #238 slice 02: incremental
fetch-state; issue #239 slice 03: English-only language gate) -- see
`specs/PRODUCT.md` Sec. 7.10 (Google Drive source contract) and Sec. 8
P0-11 / P0-11b / P0-11c.

The connector is a first-class source provider: it lists the shared "Books"
folder through an injectable Drive client, filters listed files to
`.pdf`/`.docx` candidates, downloads each candidate's bytes to a local cache
path (docling needs a file path; the cache is an implementation detail, not
a staging contract), and hands each downloaded local path to an injectable
ingest callable.

Re-runs are incremental (P0-11b): a persisted fetch-state manifest at
`fetch_state_path` (`id -> {modifiedTime, md5Checksum, fetched_at}`) lets a
candidate whose change tokens are unchanged since its last successful
fetch+ingest be skipped BEFORE download -- no bytes fetched, no `ingest_fn`
call. The manifest entry is written only AFTER `ingest_fn` returns without
raising, so an interrupted or failed run re-fetches that candidate next
time rather than recording a false success. This composes with, and does
not replace, the ingest-level `vault_status=OK` skip
(`axial.ingest.run_ingest`).

Every downloaded candidate passes through an English-only language gate
(P0-11c) BEFORE the ingest handoff (and before any fetch-state manifest
write): a bounded text probe (`language_probe_chars` leading characters of
the source's text layer) is classified by `langdetect` (seeded for
reproducibility). A source whose top detected language is English at or
above `language_accept_threshold` proceeds; anything else is rejected --
logged to stderr naming the file, the detected language, and the
confidence -- and `continue`s to the next candidate without ever reaching
`ingest_fn`. A rejected candidate gets no fetch-state entry, so it is
re-checked (not silently skipped) on the next run, mirroring slice 02's
write-after-success discipline. `language_probe_chars` and
`language_accept_threshold` are read from `config/pipeline.yaml`'s
`drive:` block (`_language_gate_config`), never hardcoded, falling back to
this module's own `DEFAULT_LANGUAGE_PROBE_CHARS` /
`DEFAULT_LANGUAGE_ACCEPT_THRESHOLD` when the block/keys are absent.

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

import json
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import yaml
from langdetect import DetectorFactory, LangDetectException, detect_langs

from axial.chunk import ChunkError, run_chunk_recursive
from axial.envelope import EnvelopeError, run_envelope
from axial.extract import ExtractError, extract
from axial.intake import check_extension, extract_text_layer
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.tag import DEFAULT_DOMAIN_DIR
from axial.vault import VaultError, run_vault_write

# Deterministic language detection (issue #239, P0-11c): langdetect is not
# seeded by default (it draws pseudo-random n-gram samples internally), so
# fix its seed once at import time -- every `detect_langs` call in this
# process is then reproducible, matching the module's "deterministic
# detector" requirement (Sec. 7.10).
DetectorFactory.seed = 0

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
DEFAULT_FETCH_STATE_PATH = Path("data/drive/fetch_state.json")

# Candidate filter (Sec. 7.10 / plan slice 01): by name suffix and/or mime
# type. Neither replaces intake's own format/text-layer validation (P0-1) --
# this filter only decides what is worth downloading at all.
CANDIDATE_EXTENSIONS = {".pdf", ".docx"}
CANDIDATE_MIME_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"

# English-only language-gate tunables (issue #239, P0-11c). These are the
# fallback values when `config/pipeline.yaml`'s `drive:` block or its keys
# are absent -- see `_language_gate_config`, which mirrors
# `axial.envelope._default_envelopes_dir`'s "config, falling back to a
# module default" pattern.
DEFAULT_LANGUAGE_PROBE_CHARS = 4000
DEFAULT_LANGUAGE_ACCEPT_THRESHOLD = 0.9
ENGLISH_LANGUAGE_CODE = "en"

# Sentinel `_detect_language` return for "no usable probe text" (a blank
# probe or one `langdetect` couldn't classify) -- distinct from a
# confident non-English verdict. See `_detect_language`'s docstring.
UNKNOWN_LANGUAGE_CODE = "unknown"


class DriveError(Exception):
    """Base class for all drive-connector errors."""


class DriveSecretsError(DriveError):
    """Raised when `[drive]` secrets are absent, incomplete, or point at an
    unreadable key file. The message names the specific missing/invalid
    secret so the halt reason is actionable (P0-11)."""


class FetchStateError(DriveError):
    """Raised when the fetch-state manifest at `fetch_state_path` exists
    but cannot be read as the expected JSON object shape (issue #238,
    P0-11b). Malformed state is reported, never silently treated as empty
    -- silently discarding it would trigger a full, possibly expensive,
    re-fetch of the whole folder without telling the operator why."""


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


def _load_fetch_state(fetch_state_path: Path) -> dict[str, dict[str, str]]:
    """Load the fetch-state manifest (`id -> {modifiedTime, md5Checksum,
    fetched_at}`, Sec. 7.10) from `fetch_state_path`. An absent or
    empty/blank file loads as `{}` -- nothing has been fetched yet, not an
    error. A present-but-malformed file (unparseable JSON, or JSON that
    isn't an object) raises `FetchStateError` naming the path (module
    docstring) rather than being silently treated as empty."""
    if not fetch_state_path.is_file():
        return {}
    text = fetch_state_path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FetchStateError(
            f"fetch-state manifest '{fetch_state_path}' is not valid JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise FetchStateError(
            f"fetch-state manifest '{fetch_state_path}' must be a JSON object "
            f"(id -> change-token record), got {type(document).__name__}"
        )
    return document


def _write_fetch_state(fetch_state_path: Path, manifest: dict[str, dict[str, str]]) -> None:
    """Persist `manifest` to `fetch_state_path`, creating parent dirs as
    needed. Called once per successfully fetched+ingested candidate
    (write-after-success, P0-11b) so an interrupted run loses at most the
    one file in flight, never previously recorded successes."""
    fetch_state_path.parent.mkdir(parents=True, exist_ok=True)
    fetch_state_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _is_unchanged(record: dict[str, Any], manifest: dict[str, dict[str, str]]) -> bool:
    """A candidate is unchanged (skip before download, P0-11b) only when
    its Drive `id` is already in `manifest` AND both `modifiedTime` and
    `md5Checksum` match the recorded entry. A record absent from the
    manifest, or differing on either token, is fetched -- this is a
    pre-download skip that composes with, and does not replace, the
    ingest-level `vault_status=OK` skip (`axial.ingest.run_ingest`)."""
    entry = manifest.get(record["id"])
    if entry is None:
        return False
    return entry.get("modifiedTime") == record.get("modifiedTime") and entry.get(
        "md5Checksum"
    ) == record.get("md5Checksum")


def _fetch_state_entry(record: dict[str, Any]) -> dict[str, str]:
    """The manifest entry to record for `record` once its fetch+ingest has
    succeeded: its current change tokens plus a UTC fetch timestamp
    (mirrors `axial.ingest`'s `datetime.now(timezone.utc).isoformat()`
    convention)."""
    return {
        "modifiedTime": record.get("modifiedTime"),
        "md5Checksum": record.get("md5Checksum"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _language_gate_config(config_path: Path) -> tuple[int, float]:
    """Read `(language_probe_chars, language_accept_threshold)` from
    `config_path`'s `drive:` block, falling back to
    `DEFAULT_LANGUAGE_PROBE_CHARS` / `DEFAULT_LANGUAGE_ACCEPT_THRESHOLD` for
    an absent file, block, or key -- never hardcoded elsewhere (Sec. 7.10),
    mirroring `axial.envelope._default_envelopes_dir`'s config-with-
    fallback pattern."""
    probe_chars = DEFAULT_LANGUAGE_PROBE_CHARS
    accept_threshold = DEFAULT_LANGUAGE_ACCEPT_THRESHOLD
    if not config_path.is_file():
        return probe_chars, accept_threshold

    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    drive_config = document.get("drive", {}) or {}
    probe_chars = drive_config.get("language_probe_chars", probe_chars)
    accept_threshold = drive_config.get("language_accept_threshold", accept_threshold)
    return probe_chars, accept_threshold


def _default_probe_text(local_path: Path, *, probe_chars: int) -> str:
    """The real production `probe_text_fn`: read `local_path`'s text layer
    via `axial.intake.extract_text_layer` (reusing intake's own extraction,
    never reimplementing pdf/docx parsing here) and cap it to `probe_chars`
    leading characters -- large enough for `langdetect` to classify
    reliably, small enough to stay cheap per source.

    A downloaded candidate whose bytes can't be parsed as a real pdf/docx
    (a corrupted transfer, truncated download, etc.) yields empty probe
    text rather than raising: `pypdf`/`python-docx` raise a variety of
    library-specific exception types for malformed input (mirrors
    `axial.extract`'s own "docling can raise a variety of internal errors"
    broad catch), and every one of them means the same thing here -- no
    usable text to classify. `_detect_language("")` already treats blank
    text as an `("unknown", 0.0)` rejection, so this folds into the
    language gate's normal reject-and-log path instead of crashing the
    whole folder over one bad file."""
    try:
        fmt = check_extension(local_path)
        text = extract_text_layer(local_path, fmt)
    except Exception:  # noqa: BLE001 -- see docstring: any parse failure means "no probe text"
        return ""
    return text[:probe_chars]


def _detect_language(probe_text: str) -> tuple[str, float]:
    """The top detected language code and confidence for `probe_text`, via
    `langdetect.detect_langs` (deterministic: `DetectorFactory.seed = 0` is
    set at module import). Blank/whitespace-only text, or text `langdetect`
    itself can't classify (`LangDetectException`, e.g. no alphabetic
    features), yields `(UNKNOWN_LANGUAGE_CODE, 0.0)` -- NOT a confident
    non-English verdict. There is no language signal at all here (most
    commonly: `_default_probe_text` couldn't parse the downloaded bytes as
    a real pdf/docx), so the caller must not report this as "detected
    French" or similar -- see `run_drive_ingest`'s gate application, which
    treats `UNKNOWN_LANGUAGE_CODE` as "let the pipeline's own error
    handling judge this file," not as a language-gate rejection."""
    if not probe_text or not probe_text.strip():
        return UNKNOWN_LANGUAGE_CODE, 0.0
    try:
        candidates = detect_langs(probe_text)
    except LangDetectException:
        return UNKNOWN_LANGUAGE_CODE, 0.0
    top = candidates[0]
    return top.lang, top.prob


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
    fetch_state_path: Path = DEFAULT_FETCH_STATE_PATH,
    probe_text_fn: Callable[[Path], str] | None = None,
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

    `fetch_state_path` names the incremental fetch-state manifest (issue
    #238, P0-11b): a candidate whose Drive `id` is already recorded there
    with matching `modifiedTime` AND `md5Checksum` is skipped BEFORE
    `client.download` -- no bytes fetched, no `ingest_fn` call. The
    manifest entry for a candidate is written only after its `ingest_fn`
    call returns without raising, so a candidate whose ingest fails (caught
    by `CHAIN_ERRORS`, per-candidate isolation) is re-fetched on the next
    run rather than falsely recorded as done. This pre-download skip
    composes with, and does not replace, the ingest-level `vault_status=OK`
    skip (`axial.ingest.run_ingest`).

    `probe_text_fn` names the English-only language gate's bounded text
    probe (issue #239, P0-11c): `probe_text_fn=None` defaults to
    `_default_probe_text` (reads the downloaded local path's real text
    layer, capped at `language_probe_chars`, both read from
    `config_path`'s `drive:` block via `_language_gate_config`); when
    injected (tests), it is used as-is, keyed by the downloaded local path.
    The gate runs AFTER download and BEFORE `ingest_fn` (and before any
    fetch-state manifest write): a candidate whose top detected language
    isn't English, or whose confidence is below `language_accept_threshold`,
    is rejected -- logged to stderr naming the file, detected language, and
    confidence -- and never reaches `ingest_fn` or the manifest.
    """
    secrets_path = Path(secrets_path)
    cache_dir = Path(cache_dir)
    fetch_state_path = Path(fetch_state_path)

    try:
        secrets = _load_drive_secrets(secrets_path)
    except DriveSecretsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        manifest = _load_fetch_state(fetch_state_path)
    except FetchStateError as exc:
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

    probe_chars, accept_threshold = _language_gate_config(config_path)
    if probe_text_fn is None:

        def probe_text_fn(local_path: Path, _probe_chars: int = probe_chars) -> str:
            return _default_probe_text(local_path, probe_chars=_probe_chars)

    candidates = _list_all_candidates(client, folder_id)

    cache_dir.mkdir(parents=True, exist_ok=True)
    for record in candidates:
        if _is_unchanged(record, manifest):
            continue

        data = client.download(record["id"])
        local_path = _cache_path(cache_dir, record)
        local_path.write_bytes(data)
        name = record.get("name") or local_path.name

        detected_lang, confidence = _detect_language(probe_text_fn(local_path))
        # UNKNOWN_LANGUAGE_CODE means "no usable probe text" (most commonly
        # a probe that couldn't parse the downloaded bytes at all) -- not a
        # confident non-English verdict, so it is deliberately NOT rejected
        # here. The pipeline's own error handling (extract -> intake,
        # caught by CHAIN_ERRORS below) is what judges whether such a file
        # is actually processable; the language gate only judges LANGUAGE.
        if detected_lang != UNKNOWN_LANGUAGE_CODE and (
            detected_lang != ENGLISH_LANGUAGE_CODE or confidence < accept_threshold
        ):
            print(
                f"reject: {name}: detected language={detected_lang!r} "
                f"confidence={confidence:.3f} (English-only gate, threshold="
                f"{accept_threshold})",
                file=sys.stderr,
            )
            continue

        try:
            ingest_fn(local_path)
        except CHAIN_ERRORS as exc:
            print(f"error: {name}: {exc}", file=sys.stderr)
            continue

        manifest[record["id"]] = _fetch_state_entry(record)
        _write_fetch_state(fetch_state_path, manifest)

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
