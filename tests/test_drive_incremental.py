"""Outer acceptance test for issue #238 (drive-connector slice 02:
incremental fetch-state -- re-runs pull only new or changed files).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fake Drive client for folder "BOOKS" with one file "alpha.pdf"
  And a first `run_drive_ingest("BOOKS", ...)` run has completed and
      written the fetch-state manifest
When  `run_drive_ingest("BOOKS", ...)` runs a second time over the
      unchanged folder (fresh call-recorders so the assertion is
      unambiguous)
Then  zero bytes are downloaded (the fake client's download is never
      called)
  And zero sources are handed to the ingest callable
  And the command exits 0

Given the same manifest but the fake client now reports a DIFFERENT
      md5Checksum for "alpha.pdf"
When  `run_drive_ingest` runs again
Then  "alpha.pdf" is re-downloaded and handed to the ingest callable

Given a first run whose ingest callable raises for "alpha.pdf" (a
      stand-in for a pipeline failure -- no real docling/LLM involved)
When  `run_drive_ingest` runs again over the unchanged folder
Then  "alpha.pdf" is fetched again, because the manifest was never
      written for a file that failed fetch+ingest -- proving the
      manifest write happens only AFTER a successful fetch+ingest, not
      before

See specs/PRODUCT.md Sec. 7.10 ("Fetch-state manifest" paragraph) and
Sec. 8 P0-11b, and plans/drive-connector/02-incremental-fetch-state.md,
for the source of truth.

Boundary / endpoint
-----------------------------------------------------------------------
This test targets the LIBRARY entry point (not a CLI subprocess), for
the same fake-injection reasons as slice 01's outer test
(tests/test_drive_ingest.py):

    axial.drive.run_drive_ingest(
        folder_id, *, client, ingest_fn, secrets_path, cache_dir,
        fetch_state_path,
    ) -> int

Seam pinned for this slice: a new keyword-only `fetch_state_path: Path`
parameter, defaulting in production to `data/drive/fetch_state.json`
(Sec. 7.10) but overridable so tests can point it at an isolated tmp
path per test -- the same test-controllability rationale as slice 01's
`cache_dir`/`secrets_path` params. This is the recommended seam named
in the slice brief; a manifest living at a fixed name under the
existing `cache_dir` was considered and rejected, since it would
conflate the download cache (candidate bytes, keyed by file id) with
the fetch-state manifest (change tokens, keyed by file id) -- two
different artifacts with different lifecycles (the manifest survives
even when the cache is cleared).

Manifest shape pinned (Sec. 7.10 "Fetch-state manifest" paragraph):
a JSON object, `id -> {modifiedTime, md5Checksum, fetched_at}`, written
to `fetch_state_path` only after a file's fetch+ingest succeeds.

This module duplicates (rather than imports) the small fake-client /
secrets-file helpers already established in tests/test_drive_ingest.py,
per the test-author boundary (outer tests are self-contained and never
depend on each other) and so slice 01's locked file is never touched.

Scenario 4 (composability with the ingest-level `vault_status=OK`
skip, Sec. 7.10) is intentionally NOT encoded here: expressing it
without a real ingestion pipeline (docling/LLM) would not be hermetic,
and the plan's own inner-loop unit list carries it explicitly
("The pre-download skip composes with the ingest-level vault_status=OK
skip"). Left to inner unit tests during the slice.
"""

from __future__ import annotations

import json
from pathlib import Path

FOLDER_ID = "BOOKS"


def _write_secrets(
    path: Path,
    *,
    section: bool = True,
    service_account_json: str | None = None,
    books_folder_id: str | None = FOLDER_ID,
) -> None:
    """Write a tmp `[drive]` secrets TOML file (mirrors
    tests/test_drive_ingest.py's helper of the same name)."""
    lines: list[str] = []
    if section:
        lines.append("[drive]")
        if service_account_json is not None:
            # TOML literal string (single-quoted): a Windows path's
            # backslashes are taken verbatim rather than parsed as escape
            # sequences -- cross-platform-safe.
            lines.append(f"service_account_json = '{service_account_json}'")
        if books_folder_id is not None:
            lines.append(f'books_folder_id = "{books_folder_id}"')
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _fixture_key_path(tmp_path: Path) -> Path:
    key_path = tmp_path / "service-account.json"
    key_path.write_text('{"type": "service_account"}', encoding="utf-8")
    return key_path


def _record(
    file_id: str, name: str, mime_type: str, *, modified_time: str, md5: str
) -> dict[str, str]:
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "modifiedTime": modified_time,
        "md5Checksum": md5,
    }


class FakeDriveClient:
    """Injectable double for the Sec. 7.10 Drive client protocol (mirrors
    tests/test_drive_ingest.py's fake of the same name)."""

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
    """Spy ingest callable: records every local path handed to it."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, local_path) -> None:
        self.calls.append(Path(local_path))


class RaisingIngest:
    """Ingest callable stand-in for a pipeline failure: raises one of
    `axial.drive.CHAIN_ERRORS` (per-candidate isolation, module docstring
    of src/axial/drive.py) for every file handed to it. Used only to prove
    the fetch-state manifest is written after success, never before --
    no real docling/LLM chain runs."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, local_path) -> None:
        from axial.extract import ExtractError

        self.calls.append(Path(local_path))
        raise ExtractError(f"simulated pipeline failure for {local_path.name}")


def _read_manifest(fetch_state_path: Path) -> dict:
    if not fetch_state_path.is_file():
        return {}
    return json.loads(fetch_state_path.read_text(encoding="utf-8"))


def test_second_run_skips_unchanged_file_before_download(tmp_path):
    """Acceptance criterion, scenario 1 (skip-on-unchanged, P0-11b): a
    first run fetches and ingests "alpha.pdf" and writes the fetch-state
    manifest. A second run over the SAME unchanged folder must download
    ZERO bytes and hand ZERO sources to the ingest callable -- proven
    with fresh call-recorders (a new FakeDriveClient/SpyIngest pair) on
    the second run, so an empty list is unambiguous."""
    from axial.drive import run_drive_ingest

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"
    fetch_state_path = tmp_path / "fetch_state.json"

    record = _record(
        "f-alpha",
        "alpha.pdf",
        "application/pdf",
        modified_time="2026-07-01T00:00:00.000Z",
        md5="checksum-v1",
    )
    alpha_bytes = b"%PDF-1.4 fixture bytes for alpha\n"

    client1 = FakeDriveClient(pages={None: ([record], None)}, blobs={"f-alpha": alpha_bytes})
    spy1 = SpyIngest()

    exit_code_1 = run_drive_ingest(
        FOLDER_ID,
        client=client1,
        ingest_fn=spy1,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code_1 == 0, "first run over a fresh folder must exit 0"
    assert client1.download_calls == ["f-alpha"], (
        f"expected the first run to download alpha.pdf, got {client1.download_calls!r}"
    )
    assert len(spy1.calls) == 1, (
        f"expected the first run to hand alpha.pdf to the ingest callable, got {spy1.calls!r}"
    )

    manifest_after_run_1 = _read_manifest(fetch_state_path)
    assert "f-alpha" in manifest_after_run_1, (
        f"expected the fetch-state manifest at {fetch_state_path} to carry an entry for "
        f"f-alpha after a successful fetch+ingest, got {manifest_after_run_1!r}"
    )
    entry = manifest_after_run_1["f-alpha"]
    assert entry["modifiedTime"] == record["modifiedTime"]
    assert entry["md5Checksum"] == record["md5Checksum"]
    assert entry.get("fetched_at"), "expected the manifest entry to carry a non-empty fetched_at"

    # Second run: SAME record (unchanged modifiedTime/md5Checksum), but a
    # fresh client and spy so "zero calls" on THIS run is unambiguous.
    client2 = FakeDriveClient(pages={None: ([record], None)}, blobs={"f-alpha": alpha_bytes})
    spy2 = SpyIngest()

    exit_code_2 = run_drive_ingest(
        FOLDER_ID,
        client=client2,
        ingest_fn=spy2,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code_2 == 0, "a re-run over an unchanged folder must still exit 0"
    assert client2.download_calls == [], (
        f"expected ZERO download() calls on the second run over an unchanged folder "
        f"(P0-11b pre-download skip), got {client2.download_calls!r}"
    )
    assert spy2.calls == [], (
        f"expected ZERO sources handed to the ingest callable on the second run, got {spy2.calls!r}"
    )


def test_second_run_refetches_file_whose_checksum_changed(tmp_path):
    """Acceptance criterion, scenario 2 (re-fetch-on-change, P0-11b): after
    a first run records "alpha.pdf" in the manifest, a second run whose
    listed record carries a DIFFERENT md5Checksum for the same file id
    must re-download it and hand it to the ingest callable -- the
    pre-download skip only fires when BOTH modifiedTime and md5Checksum
    match."""
    from axial.drive import run_drive_ingest

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"
    fetch_state_path = tmp_path / "fetch_state.json"

    record_v1 = _record(
        "f-alpha",
        "alpha.pdf",
        "application/pdf",
        modified_time="2026-07-01T00:00:00.000Z",
        md5="checksum-v1",
    )
    alpha_bytes_v1 = b"%PDF-1.4 fixture bytes for alpha v1\n"

    client1 = FakeDriveClient(pages={None: ([record_v1], None)}, blobs={"f-alpha": alpha_bytes_v1})
    spy1 = SpyIngest()
    run_drive_ingest(
        FOLDER_ID,
        client=client1,
        ingest_fn=spy1,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )
    assert client1.download_calls == ["f-alpha"], "sanity: first run must fetch alpha.pdf"

    # Second run: same file id and modifiedTime, but a DIFFERENT
    # md5Checksum -- the file changed on Drive since the manifest was
    # written.
    record_v2 = _record(
        "f-alpha",
        "alpha.pdf",
        "application/pdf",
        modified_time="2026-07-01T00:00:00.000Z",
        md5="checksum-v2-changed",
    )
    alpha_bytes_v2 = b"%PDF-1.4 fixture bytes for alpha v2 CHANGED\n"

    client2 = FakeDriveClient(pages={None: ([record_v2], None)}, blobs={"f-alpha": alpha_bytes_v2})
    spy2 = SpyIngest()

    exit_code_2 = run_drive_ingest(
        FOLDER_ID,
        client=client2,
        ingest_fn=spy2,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code_2 == 0
    assert client2.download_calls == ["f-alpha"], (
        f"expected alpha.pdf to be RE-downloaded once its md5Checksum changed, "
        f"got {client2.download_calls!r}"
    )
    assert len(spy2.calls) == 1, (
        f"expected the changed alpha.pdf to be handed to the ingest callable again, "
        f"got {spy2.calls!r}"
    )

    manifest_after_run_2 = _read_manifest(fetch_state_path)
    assert manifest_after_run_2["f-alpha"]["md5Checksum"] == "checksum-v2-changed", (
        "expected the manifest to be updated to the new change token after the re-fetch"
    )


def test_manifest_entry_written_only_after_successful_ingest(tmp_path):
    """Acceptance criterion, scenario 3 (write-after-success, P0-11b): a
    first run whose ingest callable raises for "alpha.pdf" (simulating a
    pipeline failure, per-candidate isolation) must NOT write a manifest
    entry for it. A subsequent run over the SAME unchanged listing must
    therefore fetch "alpha.pdf" again -- an interrupted/failed run
    re-fetches rather than recording a false success."""
    from axial.drive import run_drive_ingest

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"
    fetch_state_path = tmp_path / "fetch_state.json"

    record = _record(
        "f-alpha",
        "alpha.pdf",
        "application/pdf",
        modified_time="2026-07-01T00:00:00.000Z",
        md5="checksum-v1",
    )
    alpha_bytes = b"%PDF-1.4 fixture bytes for alpha\n"

    client1 = FakeDriveClient(pages={None: ([record], None)}, blobs={"f-alpha": alpha_bytes})
    failing_ingest = RaisingIngest()

    exit_code_1 = run_drive_ingest(
        FOLDER_ID,
        client=client1,
        ingest_fn=failing_ingest,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    # Per-candidate isolation (mirrors slice 01 / axial.ingest.run_ingest):
    # one failing candidate does not fail the whole run's exit code.
    assert exit_code_1 == 0
    assert client1.download_calls == ["f-alpha"], (
        "sanity: the file must still be downloaded before the ingest callable runs and fails"
    )
    assert len(failing_ingest.calls) == 1, (
        "sanity: the failing ingest callable must have been invoked"
    )

    manifest_after_failure = _read_manifest(fetch_state_path)
    assert "f-alpha" not in manifest_after_failure, (
        f"expected NO manifest entry for a file whose ingest failed (write-after-success), "
        f"got {manifest_after_failure!r}"
    )

    # Second run, same unchanged listing: since no manifest entry exists,
    # the file must be fetched again rather than skipped.
    client2 = FakeDriveClient(pages={None: ([record], None)}, blobs={"f-alpha": alpha_bytes})
    spy2 = SpyIngest()

    exit_code_2 = run_drive_ingest(
        FOLDER_ID,
        client=client2,
        ingest_fn=spy2,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code_2 == 0
    assert client2.download_calls == ["f-alpha"], (
        f"expected alpha.pdf to be RE-fetched after a prior failed ingest left no manifest "
        f"entry, got {client2.download_calls!r}"
    )
    assert len(spy2.calls) == 1, (
        f"expected alpha.pdf to reach the ingest callable again on the re-run, got {spy2.calls!r}"
    )

    manifest_after_success = _read_manifest(fetch_state_path)
    assert "f-alpha" in manifest_after_success, (
        "expected the manifest to finally carry an entry once the retry's ingest succeeds"
    )
