"""Regression test for `src/axial/query/conftest.py`'s own vault/names-dir
isolation -- the same leak shape `tests/analysis/conftest.py` closes for its
suite, closed here for this co-located one since it has no isolation of its
own otherwise: a `find_names`/`get_name`/etc. call that omits `vault_dir=`/
`names_dir=` falls back to `data/vault`/`data/names` relative to cwd, which
in this repo's own worktrees and CI never exists -- so the leak is invisible
here too until a machine has a real (or, as built below, a decoy) `data/`
reachable from the test process's cwd.

DEC-75 (issue #853): `get_name` answers from the store (`notes.db`) alone
now, never a name page, so the decoy this test plants is a decoy STORE."""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.query import store as note_store
from axial.query.names import NameNotFoundError, get_name


def test_get_name_default_vault_dir_never_reads_a_reachable_decoy_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vault_dir = tmp_path / "data" / "vault"
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[],
        notes=[],
        names=[("Decoy Canonical", "concept", "decoy canonical")],
        note_names=[],
        note_arguing_against=[],
        note_citations=[],
    )

    monkeypatch.chdir(tmp_path)

    # `vault_dir=`/`names_dir=` both omitted -- the decoy store above is
    # reachable from this cwd's `data/vault` exactly like a leaking default
    # would read it; the isolated default (this module's own conftest
    # fixture) has no such store.
    with pytest.raises(NameNotFoundError):
        get_name("Decoy Canonical")
