"""Shared pytest fixtures for tests/ (test-author owned; see CLAUDE.md).

Cross-test isolation for the persisted-state directories acceptance tests
write into: data/trees/, data/envelopes/, and data/chunks/ (issue #45,
tree-cache; issue #151, chunk-stage artifact).

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

This fixture closes that gap generically, for every protected directory, for
every acceptance test in this suite: it snapshots each protected directory's
files byte-for-byte before the test runs, and after the test:
  - restores any pre-existing file whose content changed (byte-for-byte, not
    just "put a file back") to its original bytes;
  - deletes any file that did not exist before the test.

This is deliberately autouse and directory-content-based (not per-test-file
opt-in and not merely path-existence-based), so no future test -- including
ones that overwrite an existing path's content rather than only adding new
paths -- can leak state to another test that happens to share a source_id.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories acceptance tests persist source-keyed JSON/JSONL into, shared
# across tests via deterministic source_id filenames (PRD §7.3 / §7.4 / §7.7).
# data/chunks/ holds the chunk stage's on-disk artifact (issue #151,
# <source_id>.jsonl -- newline-delimited JSON, not a single *.json document
# like the tree/envelope caches), so it needs the same shared-fixture
# cross-test hygiene as data/trees/ and data/envelopes/: the chunk-stage
# outer test (tests/test_chunk.py) pre-places a tree fixture under a
# real/committed source's source_id and writes real chunk output next to it,
# and could otherwise leak a stale data/chunks/<source_id>.jsonl into any
# later test that computes the same source_id.
_PROTECTED_DIRS = (
    REPO_ROOT / "data" / "trees",
    REPO_ROOT / "data" / "envelopes",
    REPO_ROOT / "data" / "chunks",
)

# Extensions snapshotted/restored per protected directory: *.json for the
# tree/envelope caches (single-document JSON), *.jsonl for the chunk
# artifact (newline-delimited JSON, PRD §7.7).
_SNAPSHOT_GLOBS = ("*.json", "*.jsonl")


def _snapshot(directory: Path) -> dict[Path, bytes]:
    """Map every *.json/*.jsonl file directly under `directory` to its
    current bytes. Returns an empty mapping if the directory doesn't exist
    yet."""
    if not directory.exists():
        return {}
    snapshot: dict[Path, bytes] = {}
    for glob_pattern in _SNAPSHOT_GLOBS:
        for path in directory.glob(glob_pattern):
            if path.is_file():
                snapshot[path] = path.read_bytes()
    return snapshot


@pytest.fixture(autouse=True)
def _isolate_persisted_tree_and_envelope_state():
    """Snapshot data/trees/*.json, data/envelopes/*.json, and
    data/chunks/*.jsonl content before every test in this suite and restore
    it exactly afterward: a pre-existing file's original bytes are restored
    even if the test overwrote its content in place, and any file the test
    newly created is removed. See module docstring for the pollution this
    closes."""
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


# ---------------------------------------------------------------------------
# Isolated vault root (issue #68) -- opt-in, NOT autouse.
# ---------------------------------------------------------------------------
#
# tests/test_vault_write.py, tests/test_vault_tag_frontmatter.py, and
# tests/test_vault_artifacts.py exercise `axial vault write`, which persists
# one note per chunk/artifact under `<vault_dir>/prose/` and
# `<vault_dir>/artifacts/`. Several of those tests assert an EXACT file
# count under the vault directory (e.g. "exactly one prose note per chunk"),
# not just "our own notes are present" -- so simply cleaning up after the
# fact (the `_isolate_persisted_tree_and_envelope_state` pattern above) is
# not enough once real content already lives in `data/vault/`: the count
# assertions fail WHILE the test runs, before any teardown gets a chance to
# restore anything (verified directly: 4/7 vault tests fail against the
# real, now-populated `data/vault/prose/`, all on file-count assertions).
#
# `axial vault write` (and every pass it composes internally --
# `axial.envelope`, `axial.chunk`, `axial.tag`, `axial.artifacts`) resolves
# `vault_dir`/`envelopes_dir`/`domain_dir` from `config/pipeline.yaml`
# and/or hardcoded defaults, all expressed as PLAIN paths relative to the
# process's current working directory (see src/axial/vault.py's
# `_default_vault_dir`, src/axial/envelope.py's `_default_envelopes_dir`,
# src/axial/extract.py's module-level `TREES_DIR`, and src/axial/tag.py's/
# src/axial/artifacts.py's module-level `DEFAULT_DOMAIN_DIR`) -- none of
# them read an env-var override, and the CLI exposes no `--vault-dir`/
# `--config` flag (verified by reading src/axial/cli.py). So the one seam
# available from tests/ ALONE, without editing src/ or the real
# `config/pipeline.yaml` (both out of bounds for the test-author role, and
# the latter is live production config a concurrent ingestion run also
# reads), is to run the CLI subprocess from a different working directory:
# a fresh, isolated staging root where `data/trees/`, `data/envelopes/`,
# and `data/vault/` all resolve to empty, private locations that never
# alias the real `data/` tree the ingestion run is writing into.
#
# This fixture builds exactly that staging root, one per test
# (`tmp_path` is pytest's own per-test temp directory, created outside this
# repo entirely -- so it can never collide with a concurrent worker writing
# into the real `data/vault/`, and nothing here ever reads, moves, or
# deletes a single byte under the real `data/vault/`). The only thing
# copied in is a read-only snapshot of the domain schema/codebook
# (`config/domains/syria/{schema.yaml,codebook.yaml}`), needed because
# `axial tag`/`axial artifacts`/`axial vault write` resolve the default
# domain directory as the plain relative path `config/domains/syria`, which
# must physically exist under the staging cwd for the internal
# tag/artifacts passes `axial vault write` composes to find it.
_DOMAIN_DIR_PARTS = ("config", "domains", "syria")
_DOMAIN_FILES = ("schema.yaml", "codebook.yaml")


@pytest.fixture
def isolated_vault_root(tmp_path: Path) -> Path:
    """An isolated staging root (opt-in -- pass this fixture explicitly to
    the tests that write the vault): a fresh directory, private to this one
    test, that the vault-write acceptance tests run the `axial` CLI
    subprocess from (as `cwd`) instead of the real repo root. `data/trees/`,
    `data/envelopes/`, and `data/vault/` under this root all start empty and
    are torn down with `tmp_path` itself -- no cleanup step is needed, and
    the real `data/vault/` is never touched. See module docstring above for
    why this is the isolation seam (issue #68)."""
    domain_src = REPO_ROOT.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dst = tmp_path.joinpath(*_DOMAIN_DIR_PARTS)
    domain_dst.mkdir(parents=True, exist_ok=True)
    for filename in _DOMAIN_FILES:
        shutil.copyfile(domain_src / filename, domain_dst / filename)
    return tmp_path
