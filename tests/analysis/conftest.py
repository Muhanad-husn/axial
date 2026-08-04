"""Shared fixtures for `tests/analysis/`."""

from __future__ import annotations

import pytest

from axial.answer import record as record_module
from axial.answer import run_report as run_report_module
from axial.query import names as names_module
from axial.query import reader as reader_module


@pytest.fixture(autouse=True)
def _isolate_default_names_dir(tmp_path_factory, monkeypatch):
    """Redirect `axial.query.names`'s own default `names_dir` resolution to a
    fresh, empty per-test directory, so a name-layer call (`find_names`,
    `get_name`, `name_neighbors`, `who_cites`, `who_argues_against`,
    `where_names_meet`) that omits `names_dir=` reads nothing rather than the
    operator's live `data/names/` (issue #538: a test that built its own
    fixture layer, where `Israel-Palestine` is its own canonical, forgot to
    pass `names_dir=` on two `get_name` calls; on a machine with a real
    `data/names/` present, the live layer folded the query onto a different
    canonical and the test read the wrong page -- invisible in this repo's
    own worktrees and CI, where `data/` never exists, so it passed there by
    the fixture's own default resolving to nothing).

    Mirrors `tests/conftest.py`'s `_isolate_runlog_root` (issue #516), which
    closes the same shape of leak for the run-log directory.

    Only the DEFAULT this module falls back to when a caller omits
    `names_dir=` is patched -- a test that passes its own `names_dir=`
    explicitly is untouched, since it never reaches this function at all."""
    empty = tmp_path_factory.mktemp("names-default")
    monkeypatch.setattr(names_module, "default_names_dir", lambda *args, **kwargs: empty)


@pytest.fixture(autouse=True)
def _isolate_default_vault_dir(tmp_path_factory, monkeypatch):
    """The same fix as `_isolate_default_names_dir` above, for `vault_dir`:
    every name-layer function in `axial.query.names` (the same six listed
    above, plus the door lookups `find_names`/`where_names_meet` route
    through) and every reader function in `axial.query.reader` (`get_chunk`,
    `get_artifact`, `query_by_source`, `find_chunk_ids_ending_with`, etc.)
    falls back to `axial.paths.default_vault_dir()` -- `data/vault` relative
    to the process's cwd -- when a caller omits `vault_dir=`.

    Measured, not hypothetical: five `test_where_names_meet_*` tests failed
    exactly this way for a session that had the operator's live 6,148-note
    vault (and its 54 MB relational store) reachable from its cwd, and
    passed again once it was not -- invisible in this repo's own worktrees
    and CI, where `data/` never exists, for the same reason
    `_isolate_default_names_dir` above was invisible until #538.

    Patched on both modules directly (each imports `default_vault_dir` from
    `axial.paths` into its own namespace, so patching `axial.paths` itself
    would not reach either call site) -- this is the one default every
    higher-level caller in this suite (`build_record`'s `source_usage`,
    `find_names`' store path, the door index) ultimately resolves through,
    so patching it here closes the leak for all of them at once rather than
    chasing each intermediate module that merely forwards `vault_dir=None`."""
    empty = tmp_path_factory.mktemp("vault-default")
    monkeypatch.setattr(names_module, "default_vault_dir", lambda *args, **kwargs: empty)
    monkeypatch.setattr(reader_module, "default_vault_dir", lambda *args, **kwargs: empty)


@pytest.fixture(autouse=True)
def _isolate_default_analyses_and_runs_dirs(tmp_path_factory, monkeypatch):
    """Same fix, for `analyses_dir`/`runs_dir`: `axial.answer.record.run_brief`
    (via `persist_record`/`persist_markdown`) and `axial.answer.run_report.
    persist_run_report` (which `run_brief` also calls) each fall back to
    `axial.paths.default_analyses_dir()`/`default_runs_dir()` -- `data/
    analyses`/`data/runs` relative to cwd -- when a caller omits
    `analyses_dir=`/`runs_dir=`.

    Measured, not hypothetical: `tests/analysis/test_argmap_corridor.py`'s
    `run_brief(use_map=True)` calls omit both, and running them from this
    repo's own root (where `config/pipeline.yaml` is real) writes real
    `data/analyses/corridor_wiring_001.json` and `data/runs/
    corridor_wiring_001.json` files into the checkout -- the exact write-side
    counterpart of the read-side leak `_isolate_default_vault_dir` closes
    above."""
    empty_analyses = tmp_path_factory.mktemp("analyses-default")
    empty_runs = tmp_path_factory.mktemp("runs-default")
    monkeypatch.setattr(
        record_module, "default_analyses_dir", lambda *args, **kwargs: empty_analyses
    )
    monkeypatch.setattr(run_report_module, "default_runs_dir", lambda *args, **kwargs: empty_runs)
