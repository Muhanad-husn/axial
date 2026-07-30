"""Shared fixtures for `tests/analysis/`."""

from __future__ import annotations

import pytest

from axial.query import names as names_module


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
