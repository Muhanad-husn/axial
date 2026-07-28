"""Outer acceptance test for issue #415 (Phase A v1 slice 04 -- the name
inventory and similarity view, spec §7.16, P0-12's first two bullets).

Locked behavioural contract, read off `specs/PRODUCT.md` §7.16/§6 and D10
(`docs/DECISIONS.md`):

Given slice 02's per-note interrogation answers on disk
      (`data/answers/<source_id>.jsonl`)
When  the operator runs `axial names build`
Then  every distinct name surface form is collected from exactly `names[]`
      (with its own `kind`) and `citations[].cited` -- §7.16's own field
      list -- with its occurrence count and the chunk_ids it came from,
      written losslessly to `data/names/inventory.jsonl` in the exact
      `{surface, kind, count, chunk_ids[]}` shape
And   `uses`/`defines`/`arguing_against`/`position_of` values never appear
      as an inventory entry -- they carry argumentative clauses, not name
      surface forms (module docstring, `axial.names`)
And   D7 abstentions (`not-in-passage`) never appear as an inventory entry
And   each surface form is embedded with a local sentence-transformer and
      assigned an HDBSCAN cluster label, persisted to a LanceDB table
      (`data/names/embeddings.lance`) plus a JSON manifest
      (`data/names/similarity_manifest.json`)
And   `axial names examine` reads that persisted result back and reports the
      cluster-size and nearest-neighbour similarity distribution, with zero
      further model/embedding calls
And   zero LLM (text-generation) calls happen anywhere in this pass
      (`AXIAL_LLM_PROVIDER=explode` poisons any such call)

Seam decisions
-----------------------------------------------------------------------
1. **Answer records are written directly**, not produced by a real
   `axial interrogate` run (which needs an LLM provider) -- the fixture's
   own subject matter is `data/answers/<source_id>.jsonl`'s documented shape
   (`axial.interrogate.build_answer_record`), not the interrogation pass
   itself (already covered by its own acceptance test,
   `tests/ingestion/test_interrogate.py`).
2. **Real embedding model, no other LLM call** -- mirrors `tests/distill/
   test_embedding_pass.py`'s own seam decision exactly: this pass genuinely
   calls a local sentence-transformer (that IS the behavior under test),
   but is run under the poison-client env var so any text-generating LLM
   call crashes the run instead of silently succeeding.

Requires the `distill` dependency group (`uv sync --group distill`):
`lancedb`/`sentence-transformers`/`hdbscan`/`scikit-learn` are optional, not
part of `dependencies`/`dev`. `importorskip` below skips this whole module
cleanly on an environment that never synced the group.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

lancedb = pytest.importorskip("lancedb")
pytest.importorskip("sentence_transformers")
pytest.importorskip("hdbscan")
pytest.importorskip("sklearn")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"


def _run_axial(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def _answers(**overrides) -> dict:
    base = {
        "about": ["x"],
        "claim": "x",
        "move": "x",
        "ranges_over": "not-in-passage",
        "stops_holding": "not-in-passage",
        "position_of": "not-in-passage",
        "arguing_against": [],
        "names": [],
        "citations": [],
        "mechanism": "not-in-passage",
        "evidence": "not-in-passage",
        "comparison": "not-in-passage",
        "defines": [],
        "uses": [],
        "concedes": "not-in-passage",
        "assumes": "not-in-passage",
    }
    base.update(overrides)
    return base


def _record(chunk_id: str, source_id: str, **overrides) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": "Introduction",
        "pass": "note_interrogate",
        "model": "stub",
        "frame_version": "0.1",
        "answered_at": "2026-01-01T00:00:00Z",
        "answers": _answers(**overrides),
    }


def _build_fixture_answers(root: Path) -> None:
    answers_dir = root / "data" / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)

    records = [
        _record(
            "src1_000_intro_001",
            "src1",
            names=[
                {"name": "Kevin Attell", "kind": "person"},
                {"name": "University of Chicago Press", "kind": "institution/group"},
            ],
            uses=["SENTINEL_CLAUSE_never_a_name -- uses is not collected (§7.16)"],
            arguing_against=[
                "SENTINEL_CLAUSE_never_a_name -- jurists who regard this as a quaestio facti"
            ],
            position_of="SENTINEL_CLAUSE_never_a_name -- the translator of the book",
        ),
        _record(
            "src1_001_body_002",
            "src1",
            defines=["SENTINEL_CLAUSE_never_a_name -- defines is not collected (§7.16)"],
            citations=[{"cited": "Gellner 1992", "stance": "authority", "about": "nationalism"}],
        ),
        _record(
            "src2_000_intro_001",
            "src2",
            names=[{"name": "Kevin Attell", "kind": "person"}],
        ),
    ]
    with (answers_dir / "src1.jsonl").open("w", encoding="utf-8") as handle:
        for record in records[:2]:
            handle.write(json.dumps(record) + "\n")
    with (answers_dir / "src2.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(records[2]) + "\n")


def _assert_ran_the_real_subcommand(result: subprocess.CompletedProcess) -> None:
    combined_output = result.stdout + result.stderr
    assert (
        "invalid choice" not in combined_output and "unrecognized arguments" not in combined_output
    ), (
        "expected a real 'axial names' run, not an argparse fallback -- this means "
        "the `axial names` CLI subcommand does not exist yet:\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )


def test_names_build_then_examine_over_real_answer_records(isolated_vault_root):
    root = isolated_vault_root
    _build_fixture_answers(root)

    build_result = _run_axial(root, "names", "build")
    _assert_ran_the_real_subcommand(build_result)
    assert build_result.returncode == 0, (
        f"expected exit 0, got {build_result.returncode}\n"
        f"stdout: {build_result.stdout!r}\nstderr: {build_result.stderr!r}"
    )

    manifest_path = root / "data" / "names" / "similarity_manifest.json"
    assert manifest_path.is_file(), f"expected a manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Distinct surface forms: "Kevin Attell", "University of Chicago Press",
    # "Gellner 1992" -- three, never the four SENTINEL clauses
    # (uses/defines/arguing_against/position_of).
    assert manifest["entry_count"] == 3
    assert manifest["occurrence_count"] == 4  # every raw names[]/citations[] mention
    assert isinstance(manifest["embedding_dim"], int) and manifest["embedding_dim"] > 0

    inventory_path = root / "data" / "names" / "inventory.jsonl"
    assert inventory_path.is_file(), f"expected a lossless inventory at {inventory_path}"
    inventory = {
        record["surface"]: record
        for record in (json.loads(line) for line in inventory_path.read_text("utf-8").splitlines())
    }
    assert set(inventory) == {"Kevin Attell", "University of Chicago Press", "Gellner 1992"}
    assert not any("SENTINEL_CLAUSE_never_a_name" in surface for surface in inventory)
    assert inventory["Kevin Attell"] == {
        "surface": "Kevin Attell",
        "kind": "person",
        "count": 2,
        "chunk_ids": ["src1_000_intro_001", "src2_000_intro_001"],
    }
    assert inventory["Gellner 1992"]["kind"] is None

    embeddings_dir = root / "data" / "names" / "embeddings.lance"
    db = lancedb.connect(embeddings_dir)
    rows = db.open_table("names").to_arrow().to_pylist()
    surface_forms = {row["surface_form"] for row in rows}
    assert surface_forms == set(inventory)
    for row in rows:
        assert isinstance(row["vector"], list) and row["vector"]
        assert isinstance(row["cluster_label"], int)

    examine_result = _run_axial(root, "names", "examine")
    _assert_ran_the_real_subcommand(examine_result)
    assert examine_result.returncode == 0, (
        f"expected exit 0, got {examine_result.returncode}\n"
        f"stdout: {examine_result.stdout!r}\nstderr: {examine_result.stderr!r}"
    )
    report = examine_result.stdout
    assert "3 distinct surface form(s)" in report
    assert "4 total occurrence(s)" in report
    assert "nearest-neighbour cosine similarity spread" in report
    # The tightness sweep (founder ask, spec §7.16/P0-12): the default
    # candidates all show up as their own section, re-clustered from the
    # SAME persisted vectors -- no re-embedding.
    assert "tightness sweep (4 candidate(s))" in report
    for min_cluster_size in (2, 5, 10, 20):
        assert f"min_cluster_size={min_cluster_size} min_samples=1" in report
    assert "cluster size distribution" in report
    assert "largest clusters" in report
    assert "borderline pairs" in report


def test_names_examine_min_cluster_sizes_and_min_samples_are_cli_overridable(isolated_vault_root):
    """The founder's own dial (min_cluster_size/min_samples), not a baked-in
    tuned set -- exercised end to end through the real CLI flags, over the
    same persisted vectors `build` already wrote."""
    root = isolated_vault_root
    _build_fixture_answers(root)
    build_result = _run_axial(root, "names", "build")
    assert build_result.returncode == 0, build_result.stderr

    examine_result = _run_axial(
        root, "names", "examine", "--min-cluster-sizes", "2,3", "--min-samples", "1"
    )
    assert examine_result.returncode == 0, (
        f"expected exit 0, got {examine_result.returncode}\n"
        f"stdout: {examine_result.stdout!r}\nstderr: {examine_result.stderr!r}"
    )
    report = examine_result.stdout
    assert "tightness sweep (2 candidate(s))" in report
    assert "min_cluster_size=2 min_samples=1" in report
    assert "min_cluster_size=3 min_samples=1" in report
    assert "min_cluster_size=5" not in report


def test_names_build_min_cluster_size_and_min_samples_are_cli_overridable(isolated_vault_root):
    root = isolated_vault_root
    _build_fixture_answers(root)

    build_result = _run_axial(
        root, "names", "build", "--min-cluster-size", "2", "--min-samples", "1"
    )

    assert build_result.returncode == 0, (
        f"expected exit 0, got {build_result.returncode}\n"
        f"stdout: {build_result.stdout!r}\nstderr: {build_result.stderr!r}"
    )
    manifest = json.loads(
        (root / "data" / "names" / "similarity_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["config"]["min_cluster_size"] == 2
    assert manifest["config"]["min_samples"] == 1


def test_names_examine_before_build_fails_loudly(isolated_vault_root):
    root = isolated_vault_root

    result = _run_axial(root, "names", "examine")

    assert result.returncode == 1
    assert "error:" in result.stderr


def _build_locator_fixture_answers(root: Path) -> None:
    """Issue #445: "Table 4.1" named in two unrelated books (the actual
    bug), "Figure 9.1" named only in one (306 of 358 real locator surfaces,
    already correct), and a non-locator surface ("Kevin Attell") spanning
    the same two books, which must never be scoped."""
    answers_dir = root / "data" / "answers"
    answers_dir.mkdir(parents=True, exist_ok=True)

    with (answers_dir / "src1.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                _record(
                    "src1_000_intro_001",
                    "src1",
                    names=[
                        {"name": "Kevin Attell", "kind": "person"},
                        {"name": "Table 4.1", "kind": "table"},
                        {"name": "Figure 9.1", "kind": "figure"},
                    ],
                )
            )
            + "\n"
        )
    with (answers_dir / "src2.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                _record(
                    "src2_000_intro_001",
                    "src2",
                    names=[
                        {"name": "Kevin Attell", "kind": "person"},
                        {"name": "Table 4.1", "kind": "table"},
                    ],
                )
            )
            + "\n"
        )


def test_names_build_scopes_a_locator_shaped_surface_that_spans_two_sources(isolated_vault_root):
    root = isolated_vault_root
    _build_locator_fixture_answers(root)

    build_result = _run_axial(root, "names", "build")
    _assert_ran_the_real_subcommand(build_result)
    assert build_result.returncode == 0, (
        f"expected exit 0, got {build_result.returncode}\n"
        f"stdout: {build_result.stdout!r}\nstderr: {build_result.stderr!r}"
    )

    inventory_path = root / "data" / "names" / "inventory.jsonl"
    inventory = {
        record["surface"]: record
        for record in (json.loads(line) for line in inventory_path.read_text("utf-8").splitlines())
    }

    # The actual bug: "Table 4.1" must never survive as one entry spanning
    # both books -- it becomes two, each scoped to its own source.
    assert "Table 4.1" not in inventory
    assert inventory["Table 4.1 (src1)"] == {
        "surface": "Table 4.1 (src1)",
        "kind": "table",
        "count": 1,
        "chunk_ids": ["src1_000_intro_001"],
    }
    assert inventory["Table 4.1 (src2)"] == {
        "surface": "Table 4.1 (src2)",
        "kind": "table",
        "count": 1,
        "chunk_ids": ["src2_000_intro_001"],
    }

    # 306 of 358 real locator surfaces are single-source already -- must
    # keep their bare identity, no rename.
    assert inventory["Figure 9.1"]["chunk_ids"] == ["src1_000_intro_001"]

    # A genuine cross-book name is not a locator and must never be scoped.
    assert inventory["Kevin Attell"]["chunk_ids"] == [
        "src1_000_intro_001",
        "src2_000_intro_001",
    ]
