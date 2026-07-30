"""Inner-test fixtures for src/axial/test_*.py (issue #81).

The chunk-artifact checkpoint (`axial.chunk.run_chunk_recursive`/
`read_chunks`) persists source-keyed files under the cwd-relative
`data/chunks/` directory by default. Inner unit tests run in-process with cwd
at the repo root and frequently reuse the same fixture bytes (hence the same
content-hashed source_id), so without isolation those tests would write into
the real `data/` tree and read each other's (or a previous run's)
checkpoints -- making assertions order- and run-dependent.

This autouse fixture redirects the checkpoint directory to a fresh temp
location per test (the module-global default `_default_chunks_dir` falls
back to, since `config/pipeline.yaml` declares no `chunks_dir` key), so
every in-process test that exercises the real `run_chunk_recursive`/
`read_chunks` is isolated with no per-test edits. It only affects in-process
tests; the acceptance tests under tests/ spawn `axial` as a subprocess with
cwd set to their own isolated staging root and are unaffected.

Same reasoning covers `axial.intake.SOURCE_META_DIR` (issue #285, §7.12):
`axial.intake.intake()` now writes the persisted source-metadata record as
an unconditional side effect of every successful call, including
`extract()`'s own internal validation-only call -- so any in-process test
that exercises `extract()`/`run_envelope()`/`run_chunk_recursive()` etc.
would otherwise write a real record into the repo's `data/source_meta/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import axial.chunk as _chunk_mod
import axial.intake as _intake_mod
import axial.runlog as _runlog_mod
from axial.llm import PROVIDER_ENV_VAR as _PROVIDER_ENV_VAR


@pytest.fixture(autouse=True)
def _isolate_checkpoint_dirs(tmp_path_factory, monkeypatch):
    base = tmp_path_factory.mktemp("checkpoints")
    monkeypatch.setattr(_chunk_mod, "CHUNKS_DIR", base / "chunks")
    monkeypatch.setattr(_intake_mod, "SOURCE_META_DIR", base / "source_meta")


@pytest.fixture(autouse=True)
def _isolate_runlog_root(tmp_path_factory, monkeypatch):
    """Redirect `axial.runlog.LOGS_ROOT` to a fresh temp directory for every
    in-process test. `run_context(name, root=None, ...)` -- the shape every
    CLI subcommand's own call site uses (`_extract`, `_envelope`,
    `_interrogate` when `--data-dir` is absent, `_gather_eval_score`,
    `_eval`) -- falls back to this module global, so a test that drives the
    CLI through `main()` with no injected root (e.g. `cli_mod.main(["eval"])`)
    would otherwise create a real timestamped run directory in the operator's
    own `data/logs/` on every run of this suite. Confirmed: 79 such
    directories accumulated there between 2026-07-25 and 2026-07-30, one per
    commit-gate run, all carrying `model: "stub"` and a fixture `source_id`.

    Only the `root=None` default path is affected: a test that injects its
    own `root=` (`src/axial/test_runlog.py`, `tests/test_runlog_passes.py`)
    never reads this global and is untouched."""
    monkeypatch.setattr(_runlog_mod, "LOGS_ROOT", tmp_path_factory.mktemp("runlog"))


@pytest.fixture(autouse=True)
def _offline_llm_provider_by_default(monkeypatch):
    """Default these in-process tests to the no-network stub provider.

    Issue #303 made `extract()` construct a client of its own for a source
    whose §7.11/§7.13 judgment has not been made yet -- and the isolation
    above gives every test a fresh, empty `source_meta` dir, so every
    `extract()` here looks unjudged. On a developer machine with real API
    credentials configured (unlike CI, which has none) that would otherwise
    reach a live provider from the per-commit gate. Tests that exercise
    provider resolution itself set or clear `AXIAL_LLM_PROVIDER` explicitly
    and are unaffected."""
    monkeypatch.setenv(_PROVIDER_ENV_VAR, "stub")


# --- shared chunk-tree test helpers ------------------------------------------
#
# Used by both test_chunk_examine.py and test_chunk_recursive_unit.py (moved
# here, issue #191, when the embedding mechanism -- and its own dedicated
# test_chunk_embedding.py, the original home of these helpers -- was retired).


def tree_with_sections(section_bodies: dict[str, list[str]]) -> dict:
    """Build a minimal persisted-tree fixture: one top-level section node per
    (heading, body-list) pair, in order."""
    children = []
    for index, (heading, bodies) in enumerate(section_bodies.items(), start=1):
        children.append(
            {
                "type": "prose",
                "order": str(index),
                "text": heading,
                "children": [
                    {"type": "prose", "order": f"{index}.{i + 1}", "text": body}
                    for i, body in enumerate(bodies)
                ],
            }
        )
    return {"children": children}


def patch_tree(monkeypatch, tmp_path: Path, tree: dict) -> None:
    """Monkeypatch `axial.chunk.tree_path`/`load_persisted_tree` so a chunk
    call reads `tree` instead of the real cwd-relative `data/trees/` cache."""
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(_chunk_mod, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(_chunk_mod, "load_persisted_tree", lambda path: tree)
