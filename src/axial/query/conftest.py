"""Shared fixtures for `src/axial/query/`'s co-located unit tests.

Mirrors `tests/analysis/conftest.py`'s `_isolate_default_names_dir`/
`_isolate_default_vault_dir` (issue #538, and the live-vault leak these
close): `axial.query.names` and `axial.query.reader` each fall back to
`axial.paths.default_names_dir()`/`default_vault_dir()` -- `data/names`/
`data/vault` relative to the process's cwd -- when a caller omits
`names_dir=`/`vault_dir=`. This module has no such conftest at all before
this fix, so a test written here that forgot the kwarg (the exact #538
shape) would read the operator's live name layer or 6,148-note vault on any
machine where `data/` is reachable from cwd, same as `tests/analysis/`'s own
tests did -- invisible in this repo's own worktrees and CI, where `data/`
never exists, so the fixture's own default resolves to nothing there.

Every test in `test_names.py`/`test_reader.py` happens to pass its own
`names_dir=`/`vault_dir=` today, so this is a preventive close, not a fix
for an observed failure here -- the same shape of leak `tests/analysis/
conftest.py` already guards against for its own suite."""

from __future__ import annotations

import pytest

from axial.query import names as names_module
from axial.query import reader as reader_module


@pytest.fixture(autouse=True)
def _isolate_default_names_dir(tmp_path_factory, monkeypatch):
    empty = tmp_path_factory.mktemp("names-default")
    monkeypatch.setattr(names_module, "default_names_dir", lambda *args, **kwargs: empty)


@pytest.fixture(autouse=True)
def _isolate_default_vault_dir(tmp_path_factory, monkeypatch):
    empty = tmp_path_factory.mktemp("vault-default")
    monkeypatch.setattr(names_module, "default_vault_dir", lambda *args, **kwargs: empty)
    monkeypatch.setattr(reader_module, "default_vault_dir", lambda *args, **kwargs: empty)
