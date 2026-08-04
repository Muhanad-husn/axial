"""Regression test for `src/axial/query/conftest.py`'s own vault/names-dir
isolation -- the same leak shape `tests/analysis/conftest.py` closes for its
suite, closed here for this co-located one since it has no isolation of its
own otherwise: a `find_names`/`get_name`/etc. call that omits `vault_dir=`/
`names_dir=` falls back to `data/vault`/`data/names` relative to cwd, which
in this repo's own worktrees and CI never exists -- so the leak is invisible
here too until a machine has a real (or, as built below, a decoy) `data/`
reachable from the test process's cwd."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from axial.paths import name_page_filename
from axial.query.names import NameNotFoundError, get_name


def test_get_name_default_vault_dir_never_reads_a_reachable_decoy_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    names_dir = tmp_path / "data" / "vault" / "names"
    names_dir.mkdir(parents=True)
    frontmatter = {"name": "Decoy Canonical", "kind": "concept", "aliases": [], "member_count": 99}
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    path = names_dir / name_page_filename(names_dir, "Decoy Canonical")
    path.write_text(f"---\n{rendered}---\nDECOY BODY -- never read by an isolated test.\n")

    monkeypatch.chdir(tmp_path)

    # `vault_dir=`/`names_dir=` both omitted -- the decoy above is reachable
    # from this cwd's `data/vault` exactly like a leaking default would read
    # it; the isolated default (this module's own conftest fixture) has no
    # such page.
    with pytest.raises(NameNotFoundError):
        get_name("Decoy Canonical")
