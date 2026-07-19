"""Outer acceptance test for issue #239 (drive-connector slice 03: the
English-only language gate).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a fake Drive client for folder "BOOKS" with two candidates --
      "english.pdf" (a text-layer source whose probe text is clear English
      prose) and "french.pdf" (a text-layer source whose probe text is
      clear French prose)
  And an injected probe-text function that returns each candidate's known
      prose, keyed by its downloaded local path
  And a valid [drive] secrets section and a spy ingest callable
When  the drive connector's library entry point runs
Then  "english.pdf" IS handed to the ingest callable
  And "french.pdf" is NOT handed to the ingest callable -- rejected before
      the (spy-stood-in) extraction/ingest handoff, not merely filtered
      pre-download
  And a stderr line names "french.pdf", its detected language, and a
      confidence value -- never a silent pass-through
  And the command exits 0 (a non-English source is a recorded skip, not a
      crash)

See specs/PRODUCT.md Sec. 7.10 ("Language-gate tunables" paragraph) and
Sec. 8 P0-11c, and plans/drive-connector/03-english-only-gate.md, for the
source of truth.

Boundary / seam
-----------------------------------------------------------------------
This test targets the LIBRARY entry point (not a CLI subprocess), for the
same fake-injection reasons as slices 01/02's outer tests
(tests/test_drive_ingest.py, tests/test_drive_incremental.py):

    axial.drive.run_drive_ingest(
        folder_id, *, client, ingest_fn, secrets_path, cache_dir,
        probe_text_fn,
    ) -> int

Seam pinned for this slice: a new keyword-only `probe_text_fn: Callable[
[Path], str] | None = None` parameter. In production it defaults to a real
bounded text-layer probe (reusing intake's text extraction, reading at
most `language_probe_chars` leading characters); this test overrides it
with a fake keyed by the DOWNLOADED LOCAL PATH so each candidate's probe
text is fully test-controlled, without needing a real .pdf/.docx on disk.

This is the recommended seam, and deliberately does NOT stub out the
language detector itself: the real `langdetect` library runs, deterministic
(fixed-seed), on whatever text `probe_text_fn` returns. That is the
faithful thing to exercise here -- a test that mocked `langdetect`'s
verdict directly would only prove the gate wires *a* verdict through, not
that it correctly separates English from non-English text. `langdetect` is
already resolvable in this environment (a transitive dependency today,
per `uv.lock`); the slice's own definition of done still requires it (or
an equivalent deterministic detector) to be added as a direct, stated
dependency (plan Sec. "Definition of done").

Keying convention: `_cache_path` (src/axial/drive.py, locked by slice 01)
names each downloaded local path `f"{record['id']}{suffix}"`, so the fake
below keys its probe-text map by Drive file `id` (`local_path.stem`) --
the same stable identity slice 01/02 already rely on, not a new
implementation detail this test invents.

Non-goal here (left to inner unit tests, per the plan's own inner-loop
list): the exact `language_accept_threshold` boundary (an English
detection just below threshold), the `language_probe_chars` bound itself,
and composition with slice 02's fetch-state skip. Expressing threshold-
boundary or fetch-state-interaction behavior hermetically at the outer
level would mean asserting on langdetect's raw confidence score for
borderline invented text, which is not a stable behavioral contract --
the CLEAR pass/reject split asserted here is.
"""

from __future__ import annotations

import re
from pathlib import Path

FOLDER_ID = "BOOKS"

ENGLISH_PROBE_TEXT = (
    "This book examines the political economy of state formation in the "
    "modern Middle East, tracing how colonial administrative structures "
    "shaped post-independence institutions. The argument proceeds through "
    "several case studies drawn from primary archival sources collected "
    "across four countries, and situates each case within a comparative "
    "framework of contentious politics."
)

FRENCH_PROBE_TEXT = (
    "Ce livre examine l'economie politique de la formation de l'Etat dans "
    "le Moyen-Orient moderne, en retracant comment les structures "
    "administratives coloniales ont faconne les institutions "
    "post-independance. L'argument se developpe a travers plusieurs "
    "etudes de cas tirees de sources d'archives primaires, situees dans "
    "un cadre comparatif de politique contestataire."
)


def _write_secrets(path: Path, *, service_account_json: str) -> None:
    """Write a tmp `[drive]` secrets TOML file (mirrors
    tests/test_drive_ingest.py's helper of the same name)."""
    lines = [
        "[drive]",
        # TOML literal string (single-quoted): a Windows path's
        # backslashes are taken verbatim rather than parsed as escape
        # sequences -- cross-platform-safe.
        f"service_account_json = '{service_account_json}'",
        f'books_folder_id = "{FOLDER_ID}"',
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fixture_key_path(tmp_path: Path) -> Path:
    key_path = tmp_path / "service-account.json"
    key_path.write_text('{"type": "service_account"}', encoding="utf-8")
    return key_path


def _record(file_id: str, name: str) -> dict[str, str]:
    """A Drive file record carrying the Sec. 7.10 fields the connector
    relies on (mirrors tests/test_drive_ingest.py's helper)."""
    return {
        "id": file_id,
        "name": name,
        "mimeType": "application/pdf",
        "modifiedTime": "2026-07-01T00:00:00.000Z",
        "md5Checksum": f"checksum-{file_id}",
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
    """Spy ingest callable: records every local path handed to it, never
    runs the real ingestion pipeline (mirrors tests/test_drive_ingest.py's
    spy of the same name)."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, local_path) -> None:
        self.calls.append(Path(local_path))


def test_english_source_passes_and_non_english_source_is_rejected_and_logged(tmp_path, capsys):
    """Acceptance criterion (plan Sec. "Acceptance criterion", P0-11c):
    given "english.pdf" (English probe text) and "french.pdf" (French
    probe text) in folder "BOOKS", the connector hands ONLY "english.pdf"
    to the ingest callable, rejects "french.pdf" before that handoff,
    logs the rejection naming the file and its detected language +
    confidence, and still exits 0."""
    from axial.drive import run_drive_ingest

    english_bytes = b"%PDF-1.4 fixture bytes for the english source\n"
    french_bytes = b"%PDF-1.4 fixture bytes for the french source\n"

    client = FakeDriveClient(
        pages={
            None: (
                [
                    _record("f-english", "english.pdf"),
                    _record("f-french", "french.pdf"),
                ],
                None,
            )
        },
        blobs={"f-english": english_bytes, "f-french": french_bytes},
    )
    spy = SpyIngest()
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"

    # Keyed by Drive file id (`local_path.stem`, per `_cache_path`'s
    # naming convention, src/axial/drive.py) so each candidate's downloaded
    # local path resolves to its OWN known-language probe text, regardless
    # of the on-disk bytes -- the probe never needs a real .pdf/.docx.
    probe_texts = {
        "f-english": ENGLISH_PROBE_TEXT,
        "f-french": FRENCH_PROBE_TEXT,
    }

    def fake_probe_text(local_path: Path) -> str:
        return probe_texts[Path(local_path).stem]

    exit_code = run_drive_ingest(
        FOLDER_ID,
        client=client,
        ingest_fn=spy,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        probe_text_fn=fake_probe_text,
    )

    assert exit_code == 0, (
        "a non-English source is a recorded skip, not a crash -- the run must still exit 0"
    )

    # Both candidates are still downloaded: the gate runs on the
    # downloaded local path (it needs bytes on disk to probe), so
    # rejection happens AFTER download and BEFORE the ingest handoff --
    # it is not a pre-download filter (that is slice 01's candidate
    # filter, a different mechanism).
    assert set(client.download_calls) == {"f-english", "f-french"}, (
        f"expected BOTH candidates to be downloaded (the language gate "
        f"runs on downloaded bytes, not before download), got "
        f"{client.download_calls!r}"
    )

    assert len(spy.calls) == 1, (
        f"expected exactly ONE source handed to the ingest callable "
        f"(french.pdf must never reach it), got {spy.calls!r}"
    )
    handed_off = spy.calls[0]
    assert handed_off.stem == "f-english", (
        f"expected the ONE source handed to the ingest callable to be the "
        f"English candidate (f-english), got {handed_off!r}"
    )
    assert handed_off.read_bytes() == english_bytes, (
        "expected the source handed to the ingest callable to be the "
        "downloaded english.pdf bytes, not a substitute"
    )

    captured = capsys.readouterr()
    message = (captured.out + captured.err).lower()
    assert "french.pdf" in message, (
        f"expected the rejection to name the rejected file (french.pdf); "
        f"got stdout={captured.out!r} stderr={captured.err!r}"
    )
    assert "english.pdf" not in message, (
        f"expected NO rejection message for english.pdf (it passed the "
        f"gate); got stdout={captured.out!r} stderr={captured.err!r}"
    )
    assert re.search(r"\bfr\b|french", message), (
        f"expected the rejection reason to name the DETECTED language "
        f"(French, e.g. langdetect's 'fr' code or the word 'french'); "
        f"got stdout={captured.out!r} stderr={captured.err!r}"
    )
    assert re.search(r"0?\.\d+", message), (
        f"expected the rejection reason to carry a numeric confidence "
        f"value; got stdout={captured.out!r} stderr={captured.err!r}"
    )


def test_english_only_source_still_passes_when_no_rejection_is_possible(tmp_path, capsys):
    """A narrower sanity check isolating the pass side: a folder with only
    an English candidate produces no rejection message at all and the sole
    candidate reaches the ingest callable -- the gate is not a blanket
    reject, only a language-conditioned one."""
    from axial.drive import run_drive_ingest

    english_bytes = b"%PDF-1.4 fixture bytes for a solo english source\n"
    client = FakeDriveClient(
        pages={None: ([_record("f-english", "english.pdf")], None)},
        blobs={"f-english": english_bytes},
    )
    spy = SpyIngest()
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets(secrets_path, service_account_json=str(_fixture_key_path(tmp_path)))
    cache_dir = tmp_path / "cache"

    def fake_probe_text(local_path: Path) -> str:
        assert Path(local_path).stem == "f-english"
        return ENGLISH_PROBE_TEXT

    exit_code = run_drive_ingest(
        FOLDER_ID,
        client=client,
        ingest_fn=spy,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        probe_text_fn=fake_probe_text,
    )

    assert exit_code == 0
    assert len(spy.calls) == 1, (
        f"expected the sole English candidate to reach the ingest callable, got {spy.calls!r}"
    )
    captured = capsys.readouterr()
    message = (captured.out + captured.err).lower()
    assert "reject" not in message and "english.pdf" not in message, (
        f"expected no rejection message when the only candidate is "
        f"English; got stdout={captured.out!r} stderr={captured.err!r}"
    )
