"""Inner unit tests for the stage-5 corpus-pin staleness seam (issue #296,
DEC-35). No optional `distill` dependency (`lancedb`/`sentence-transformers`)
is needed here -- this module only wraps `axial.eval.corpus_pin`, itself
dependency-light -- so these tests run unconditionally, unlike
`test_embed_unit.py`'s `lancedb`-gated ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.distill.staleness import check_staleness, resolve_current_pin
from axial.eval import corpus_pin
from axial.eval.corpus_pin import write_pin
from axial.vault import render_note


def _write_note(prose_dir: Path, chunk_id: str) -> Path:
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Introduction",
        "chunk_text": f"body text for {chunk_id}",
        "source_meta": {"author": "A", "title": "T"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "state", "secondary": []},
    }
    path = prose_dir / f"{chunk_id}.md"
    path.write_text(render_note(frontmatter, "# Introduction\n\nbody\n"), encoding="utf-8")
    return path


def _stage_pin(tmp_path: Path, name: str = "baseline") -> tuple[Path, Path]:
    """Write a minimal corpus pin (empty sources list, one vault note) and
    return `(evals_dir, vault_dir)`."""
    vault_dir = tmp_path / "data" / "vault"
    envelopes_dir = tmp_path / "data" / "envelopes"
    envelopes_dir.mkdir(parents=True, exist_ok=True)
    evals_dir = tmp_path / "evals" / "corpus_pin"
    _write_note(vault_dir / "prose", "c1")

    write_pin(name, vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir)
    return evals_dir, vault_dir


def test_resolve_current_pin_reads_the_written_pin_id_and_hash(tmp_path: Path):
    evals_dir, _vault_dir = _stage_pin(tmp_path, "baseline")

    snapshot = resolve_current_pin(evals_dir)

    assert snapshot["corpus_pin_id"] == "baseline"
    on_disk = json.loads((evals_dir / "baseline.json").read_text(encoding="utf-8"))
    assert snapshot["vault_snapshot_hash"] == on_disk["vault_snapshot_hash"]


def test_resolve_current_pin_missing_pin_raises_corpus_pin_error(tmp_path: Path):
    evals_dir = tmp_path / "evals" / "corpus_pin"
    with pytest.raises(corpus_pin.MissingCorpusPinError):
        resolve_current_pin(evals_dir)


def test_check_staleness_true_when_recorded_pin_matches_current(tmp_path: Path):
    evals_dir, _vault_dir = _stage_pin(tmp_path, "baseline")
    snapshot = resolve_current_pin(evals_dir)

    assert check_staleness(snapshot["corpus_pin_id"], snapshot["vault_snapshot_hash"], evals_dir)


def test_check_staleness_false_when_pin_name_differs(tmp_path: Path):
    evals_dir, _vault_dir = _stage_pin(tmp_path, "baseline")
    snapshot = resolve_current_pin(evals_dir)

    assert not check_staleness("a-different-pin-name", snapshot["vault_snapshot_hash"], evals_dir)


def test_check_staleness_false_when_vault_snapshot_hash_differs(tmp_path: Path):
    """Same pin name, but the vault moved under it (e.g. a re-tag) --
    recorded artifacts built against the old hash must read as stale."""
    evals_dir, vault_dir = _stage_pin(tmp_path, "baseline")
    snapshot = resolve_current_pin(evals_dir)

    # Mutate a note's tag and rewrite the pin under the SAME name.
    _write_note(vault_dir / "prose", "c2")
    envelopes_dir = vault_dir.parent / "envelopes"
    write_pin("baseline", vault_dir=vault_dir, envelopes_dir=envelopes_dir, evals_dir=evals_dir)

    assert not check_staleness(
        snapshot["corpus_pin_id"], snapshot["vault_snapshot_hash"], evals_dir
    )
