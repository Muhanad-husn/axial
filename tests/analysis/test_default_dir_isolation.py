"""Regression test for the live-vault/live-analyses test-isolation leak this
conftest fix closes.

A test that calls a query or persistence function and omits `vault_dir=`/
`analyses_dir=`/`runs_dir=` falls back to `axial.paths.default_vault_dir()`/
`default_analyses_dir()`/`default_runs_dir()`, each a plain `data/...`
literal resolved relative to the process's cwd. In this repo's own
worktrees and CI, `data/` never exists there, so the fallback silently
resolves to nothing and every existing test passes -- which is exactly why
this shape of leak went unnoticed until a session with the operator's live
`data/` reachable from its cwd hit it (`tests/analysis/
test_argmap_corridor.py`'s `run_brief(use_map=True)` calls independently
measured to write real `data/analyses/corridor_wiring_001.json` and
`data/runs/corridor_wiring_001.json` files into this very checkout when run
from its root).

This test builds the honest repro `tests/analysis/conftest.py`'s own
`_isolate_default_vault_dir`/`_isolate_default_analyses_and_runs_dirs`
fixtures exist to defeat: a decoy `data/vault/`, `data/analyses/`, and
`data/runs/` reachable from cwd that would answer differently than "nothing"
-- and asserts the query/persistence calls above never reach it. Verified to
fail with the conftest fix reverted (the decoy store is read back verbatim,
and the decoy `data/analyses`/`data/runs` gain the persisted files) and to
pass with it restored, since those autouse fixtures apply to every test in
this module."""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.answer import record as record_module
from axial.answer import run_report as run_report_module
from axial.query import NameNotFoundError, get_name
from axial.query import store as note_store


def _write_decoy_store(vault_dir: Path, canonical: str) -> None:
    """A store a leaking `default_vault_dir()` would read -- carrying a
    `member_count` no isolated (empty) vault could ever answer with. DEC-75
    (issue #853): `get_name` answers from the store alone now, never a name
    page, so the decoy this test plants is a decoy STORE."""
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[],
        notes=[],
        names=[(canonical, "concept", canonical.casefold())],
        note_names=[],
        note_arguing_against=[],
        note_citations=[],
    )


def test_get_name_default_vault_dir_never_reads_a_reachable_decoy_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _write_decoy_store(tmp_path / "data" / "vault", "Decoy Canonical")
    monkeypatch.chdir(tmp_path)

    # `vault_dir=`/`names_dir=` both omitted -- the exact shape the leak
    # needs. A leaking default would resolve `data/vault` to the decoy
    # above (real, on disk, reachable from this cwd) and find a door there;
    # the isolated default has no such store at all.
    with pytest.raises(NameNotFoundError):
        get_name("Decoy Canonical")


def test_run_brief_default_analyses_and_runs_dir_never_write_a_reachable_decoy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    decoy_analyses = tmp_path / "data" / "analyses"
    decoy_runs = tmp_path / "data" / "runs"
    decoy_analyses.mkdir(parents=True)
    decoy_runs.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    # The exact two calls `run_brief` makes internally (`persist_record`/
    # `persist_run_report`) with `analyses_dir=`/`runs_dir=` omitted --
    # proven by the measured real leak in `test_argmap_corridor.py`. A
    # leaking default would create `<cwd>/data/analyses/decoy-brief.json`/
    # `<cwd>/data/runs/decoy-brief.json` right inside the reachable decoy
    # directories built above.
    record_path = record_module.persist_record("decoy-brief", {"brief_id": "decoy-brief"})
    report_path = run_report_module.persist_run_report("decoy-brief", {"brief_id": "decoy-brief"})

    assert list(decoy_analyses.iterdir()) == [], "the decoy analyses/ dir must stay untouched"
    assert list(decoy_runs.iterdir()) == [], "the decoy runs/ dir must stay untouched"
    assert record_path.resolve() != (decoy_analyses / "decoy-brief.json").resolve()
    assert report_path.resolve() != (decoy_runs / "decoy-brief.json").resolve()
