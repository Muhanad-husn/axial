"""Outer acceptance test for issue #237 (drive-connector slice 01: list,
download, and stream a Drive source into ingestion).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fake Drive client seeded for folder "BOOKS" with two files --
      "alpha.pdf" (a candidate) and "notes.txt" (not a candidate) --
  And a valid [drive] secrets section pointing at a service-account key
When  the drive connector's library entry point runs with the fake client
      and a spy ingest callable injected
Then  only "alpha.pdf" is downloaded to the cache and handed to the ingest
      callable, "notes.txt" is filtered out and never downloaded
  And the command exits 0

Given a [drive] secrets section that is absent or missing books_folder_id
When  the connector runs
Then  the command exits non-zero with a logged reason naming the missing
      secret
  And no Drive client call and no download is attempted

See specs/PRODUCT.md Sec. 7.10 (Google Drive source contract) and Sec. 8
P0-11, and plans/drive-connector/01-skeleton-list-download-stream.md, for
the source of truth.

Boundary / seam
-----------------------------------------------------------------------
This test targets the LIBRARY entry point, not a CLI subprocess, because it
must inject fakes for both the Drive client and the ingest callable:

    axial.drive.run_drive_ingest(
        folder_id, *, client, ingest_fn, secrets_path, cache_dir,
    ) -> int

Injectable Drive client protocol (Sec. 7.10's "injectable client
protocol", mirrored by FakeDriveClient below):

    list_files(folder_id, page_token) -> (records, next_page_token)
        `records` is a list of dicts, each carrying at least the Sec. 7.10
        fields: id, name, mimeType, modifiedTime, md5Checksum.
        `next_page_token` is None once the folder is exhausted.
    download(file_id) -> bytes

This module imports only `axial.drive` (plus stdlib/pytest) at module load,
never `google-*` libraries, so it stays runnable before those deps are
installed -- the real client must be constructed lazily inside the
production path, never at import time.

Message-channel choice for the "logged reason" (missing-secrets scenario)
-----------------------------------------------------------------------
Nothing under src/axial/ uses the stdlib `logging` module today; the
codebase's existing "clear logged message" convention (see
src/axial/intake.py's *Error classes, surfaced by src/axial/cli.py as
`print(f"error: {exc}", file=sys.stderr)`) is a message on the failure
path, printed to stderr. Since `run_drive_ingest` returns an int rather
than raising, it is the library function itself that must emit this
message. This test therefore asserts on captured stdout/stderr (`capsys`),
matching that existing convention, rather than `caplog`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FOLDER_ID = "BOOKS"


def _write_secrets(
    path: Path,
    *,
    section: bool = True,
    service_account_json: str | None = None,
    books_folder_id: str | None = FOLDER_ID,
) -> None:
    """Write a tmp `[drive]` secrets TOML file. `section=False` omits the
    `[drive]` table entirely (the "absent section" case); either key can be
    individually omitted (the "incomplete section" case) by leaving it
    None."""
    lines: list[str] = []
    if section:
        lines.append("[drive]")
        if service_account_json is not None:
            # TOML literal string (single-quoted): no escape processing, so
            # a Windows path's backslashes (e.g. "C:\Users\...") are taken
            # verbatim instead of being parsed as TOML escape sequences (the
            # double-quoted "basic string" form would raise
            # tomllib.TOMLDecodeError on such paths). Cross-platform-safe.
            lines.append(f"service_account_json = '{service_account_json}'")
        if books_folder_id is not None:
            lines.append(f'books_folder_id = "{books_folder_id}"')
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _fixture_key_path(tmp_path: Path) -> Path:
    """A real (fixture) service-account JSON key file on disk, so the
    happy-path scenarios never trip over a real-path-readability check --
    only the two secrets-validation halts under test (absent section,
    missing books_folder_id) are asserted here."""
    key_path = tmp_path / "service-account.json"
    key_path.write_text('{"type": "service_account"}', encoding="utf-8")
    return key_path


def _record(file_id: str, name: str, mime_type: str) -> dict[str, str]:
    """A Drive file record carrying the Sec. 7.10 fields the connector
    relies on: id (fetch-state key), name + mimeType (candidate filter and
    provenance), modifiedTime + md5Checksum (change tokens, slice 02)."""
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "modifiedTime": "2026-07-01T00:00:00.000Z",
        "md5Checksum": f"checksum-{file_id}",
    }


class FakeDriveClient:
    """Injectable double for the Sec. 7.10 Drive client protocol. Seeded
    with a page map (page_token-or-None -> (records, next_page_token)) and
    a blob map (file_id -> bytes); records every list_files/download call
    it receives so tests can assert exactly what the connector touched."""

    def __init__(
        self,
        pages: dict[str | None, tuple[list[dict[str, str]], str | None]],
        blobs: dict[str, bytes],
    ) -> None:
        self._pages = pages
        self._blobs = blobs
        self.list_calls: list[tuple[str, str | None]] = []
        self.download_calls: list[str] = []

    def list_files(
        self, folder_id: str, page_token: str | None = None
    ) -> tuple[list[dict[str, str]], str | None]:
        self.list_calls.append((folder_id, page_token))
        return self._pages[page_token]

    def download(self, file_id: str) -> bytes:
        self.download_calls.append(file_id)
        return self._blobs[file_id]


class SpyIngest:
    """Spy ingest callable: records every local path handed to it, never
    runs the real ingestion pipeline."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, local_path) -> None:
        self.calls.append(Path(local_path))


def test_happy_path_downloads_only_pdf_candidate_and_filters_non_candidate(tmp_path):
    """Acceptance criterion, scenario 1: two files in folder "BOOKS" --
    alpha.pdf (a candidate) and notes.txt (not a candidate). Only
    alpha.pdf is downloaded and handed to the ingest callable; notes.txt is
    never downloaded; the command exits 0."""
    from axial.drive import run_drive_ingest

    alpha_bytes = b"%PDF-1.4 fixture bytes for alpha\n"
    client = FakeDriveClient(
        pages={
            None: (
                [
                    _record("f-alpha", "alpha.pdf", "application/pdf"),
                    _record("f-notes", "notes.txt", "text/plain"),
                ],
                None,
            )
        },
        blobs={"f-alpha": alpha_bytes},
    )
    spy = SpyIngest()
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"

    exit_code = run_drive_ingest(
        FOLDER_ID,
        client=client,
        ingest_fn=spy,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
    )

    assert exit_code == 0, "happy path with a valid candidate must exit 0"

    assert client.download_calls == ["f-alpha"], (
        f"expected download() to be called for alpha.pdf only, never for "
        f"notes.txt (filtered by name/mime type before download); got "
        f"{client.download_calls!r}"
    )

    assert len(spy.calls) == 1, (
        f"expected exactly one source handed to the ingest callable "
        f"(notes.txt must never reach it), got {spy.calls!r}"
    )
    local_path = spy.calls[0]
    assert cache_dir in local_path.parents, (
        f"expected the local path handed to ingest_fn to live under "
        f"cache_dir {cache_dir}, got {local_path}"
    )
    assert local_path.suffix == ".pdf", (
        f"expected the cached local path for alpha.pdf to preserve its "
        f".pdf extension (downstream intake needs it), got {local_path.name}"
    )
    assert local_path.is_file(), f"expected downloaded bytes to be written to {local_path}"
    assert local_path.read_bytes() == alpha_bytes, (
        "expected the bytes written at the cache path to be exactly the "
        "bytes download() returned for alpha.pdf"
    )


def test_pagination_enumerates_every_candidate_across_pages(tmp_path):
    """Acceptance criterion, scenario 2 (pagination, Sec. 7.10 / P0-11):
    the connector paginates list_files to exhaustion -- a candidate that
    only appears on page 2 (reachable via the page-1 next_page_token) must
    still be downloaded and handed to the ingest callable."""
    from axial.drive import run_drive_ingest

    alpha_bytes = b"%PDF-1.4 alpha page one\n"
    beta_bytes = b"PK\x03\x04 beta page two docx bytes\n"
    client = FakeDriveClient(
        pages={
            None: (
                [_record("f-alpha", "alpha.pdf", "application/pdf")],
                "page-2-token",
            ),
            "page-2-token": (
                [
                    _record(
                        "f-beta",
                        "beta.docx",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                ],
                None,
            ),
        },
        blobs={"f-alpha": alpha_bytes, "f-beta": beta_bytes},
    )
    spy = SpyIngest()
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"

    exit_code = run_drive_ingest(
        FOLDER_ID,
        client=client,
        ingest_fn=spy,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
    )

    assert exit_code == 0

    assert client.list_calls == [(FOLDER_ID, None), (FOLDER_ID, "page-2-token")], (
        f"expected list_files to be called first with no token, then with "
        f"the page-1 next_page_token, and to stop once a page returns "
        f"next_page_token=None; got {client.list_calls!r}"
    )
    assert set(client.download_calls) == {"f-alpha", "f-beta"}, (
        f"expected every candidate across BOTH pages to be downloaded, got "
        f"{client.download_calls!r}"
    )

    assert len(spy.calls) == 2, (
        f"expected both the page-1 and the page-2 candidate to reach the "
        f"ingest callable, got {spy.calls!r}"
    )
    ingested_bytes = {path.read_bytes() for path in spy.calls}
    assert ingested_bytes == {alpha_bytes, beta_bytes}, (
        "expected both alpha.pdf (page 1) and beta.docx (page 2) to be "
        "downloaded to the cache with their correct bytes on disk"
    )


@pytest.mark.parametrize(
    ("case", "section", "with_key", "books_folder_id", "expected_missing"),
    [
        ("absent_drive_section", False, False, None, "drive"),
        ("missing_books_folder_id_key", True, True, None, "books_folder_id"),
    ],
)
def test_missing_or_incomplete_drive_secrets_halts_before_any_client_call(
    tmp_path, capsys, case, section, with_key, books_folder_id, expected_missing
):
    """Acceptance criterion, scenario 3: a [drive] secrets section that is
    absent, or present but missing books_folder_id, halts the connector
    with a non-zero exit and a message naming the missing secret -- before
    any Drive client call, download, or ingest handoff."""
    from axial.drive import run_drive_ingest

    client = FakeDriveClient(pages={}, blobs={})
    spy = SpyIngest()
    secrets_path = tmp_path / "secrets.toml"
    key_path = str(_fixture_key_path(tmp_path)) if with_key else None
    _write_secrets(
        secrets_path,
        section=section,
        service_account_json=key_path,
        books_folder_id=books_folder_id,
    )
    cache_dir = tmp_path / "cache"

    exit_code = run_drive_ingest(
        FOLDER_ID,
        client=client,
        ingest_fn=spy,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
    )

    assert exit_code != 0, (
        f"[{case}] expected a non-zero exit for missing/incomplete [drive] secrets"
    )
    assert client.list_calls == [], (
        f"[{case}] expected NO Drive client list_files call before secrets are validated, "
        f"got {client.list_calls!r}"
    )
    assert client.download_calls == [], (
        f"[{case}] expected NO download before secrets are validated, got {client.download_calls!r}"
    )
    assert spy.calls == [], (
        f"[{case}] expected NO source handed to the ingest callable, got {spy.calls!r}"
    )

    captured = capsys.readouterr()
    message = (captured.out + captured.err).lower()
    assert expected_missing in message, (
        f"[{case}] expected the halt reason to name the missing secret "
        f"({expected_missing!r}); got stdout={captured.out!r} stderr={captured.err!r}"
    )
