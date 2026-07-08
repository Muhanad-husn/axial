"""Shared pytest fixtures for tests/ (test-author owned; see CLAUDE.md).

Cross-test isolation for the persisted-state directories acceptance tests
write into: data/trees/ and data/envelopes/ (issue #45, tree-cache).

Why this exists
-----------------------------------------------------------------------
Several acceptance tests write real files into data/trees/<source_id>.json
and data/envelopes/<source_id>.json as a side effect of exercising `axial
extract`/`axial envelope`/etc. against the SAME committed PDF fixtures (e.g.
tests/fixtures/extract/prose_and_table.pdf is shared by tests/test_extract.py,
tests/test_artifacts.py, and tests/test_xref.py). Because source_id is
deterministic (a hash of the fixture's own bytes -- see
axial.envelope.compute_source_id), two different tests touching the same
fixture land on the exact same path under data/trees/ or data/envelopes/.

A prior, narrower fixture (tests/test_tree_persist.py's own `clean_trees`)
only removed paths that were NEWLY CREATED by end of test. That is not
enough: if an earlier test already created the real persisted tree for a
shared fixture, and a later test then OVERWRITES that existing file's
CONTENT (e.g. test_tree_persist.py's reuse test deliberately writes a
fabricated sentinel tree to prove verbatim reuse), the file is not "new" --
so the weak fixture left the sentinel behind, silently poisoning every
subsequent test that reuses the same fixture (observed: a clean-`data/`
`pytest tests -m "not slow"` run failed test_xref.py's arrange step, which
got zero chunks back because it unknowingly reused test_tree_persist.py's
leftover sentinel tree for prose_and_table.pdf).

This fixture closes that gap generically, for both directories, for every
acceptance test in this suite: it snapshots each protected directory's files
byte-for-byte before the test runs, and after the test:
  - restores any pre-existing file whose content changed (byte-for-byte, not
    just "put a file back") to its original bytes;
  - deletes any file that did not exist before the test.

This is deliberately autouse and directory-content-based (not per-test-file
opt-in and not merely path-existence-based), so no future test -- including
ones that overwrite an existing path's content rather than only adding new
paths -- can leak state to another test that happens to share a source_id.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories acceptance tests persist source-keyed JSON into, shared across
# tests via deterministic source_id filenames (PRD §7.3 / §7.4).
_PROTECTED_DIRS = (
    REPO_ROOT / "data" / "trees",
    REPO_ROOT / "data" / "envelopes",
)


def _snapshot(directory: Path) -> dict[Path, bytes]:
    """Map every *.json file directly under `directory` to its current
    bytes. Returns an empty mapping if the directory doesn't exist yet."""
    if not directory.exists():
        return {}
    return {path: path.read_bytes() for path in directory.glob("*.json") if path.is_file()}


@pytest.fixture(autouse=True)
def _isolate_persisted_tree_and_envelope_state():
    """Snapshot data/trees/*.json and data/envelopes/*.json content before
    every test in this suite and restore it exactly afterward: a pre-existing
    file's original bytes are restored even if the test overwrote its
    content in place, and any file the test newly created is removed. See
    module docstring for the pollution this closes."""
    before = {directory: _snapshot(directory) for directory in _PROTECTED_DIRS}

    yield

    for directory in _PROTECTED_DIRS:
        before_snapshot = before[directory]
        after_snapshot = _snapshot(directory)

        # Pre-existing files: restore original bytes if changed (or if the
        # test deleted the file outright).
        for path, original_bytes in before_snapshot.items():
            if after_snapshot.get(path) != original_bytes:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original_bytes)

        # Files the test newly created: remove them.
        for path in after_snapshot:
            if path not in before_snapshot:
                path.unlink(missing_ok=True)
