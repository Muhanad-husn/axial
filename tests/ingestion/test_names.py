"""Outer acceptance test for issue #415 (Phase A v1 slice 04 -- the name
inventory and similarity view, spec §7.16, P0-12's first two bullets).

Locked behavioural contract, read off `specs/PRODUCT.md` §7.16/§6, D10
(`docs/DECISIONS.md`) and issue #508's cut set:

Given slice 02's per-note interrogation answers on disk
      (`data/answers/<source_id>.jsonl`)
When  the operator runs `axial names build`
Then  every distinct name surface form is collected from `names[]` alone
      (with its own `kind`), with its occurrence count and the chunk_ids it
      came from, written to `data/names/inventory.jsonl` in the exact
      `{surface, kind, count, chunk_ids[]}` shape
And   `citations[].cited` contributes NOTHING to the name space (issue #508
      row A) -- the field keeps being recorded on the answer record, and a
      citation string never becomes a page
And   a surface matching the cut set's shape rows (issue #508 rows C-H, P,
      S) never appears as an inventory entry either
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
And   a name seen only in the source's back-matter run -- the sections at or
      after the boundary its own cached structural tree puts the
      bibliography/index at -- never becomes a page (issue #511, row B),
      while a name in the endnotes, which sit before that boundary, keeps
      its page
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


def _record(chunk_id: str, source_id: str, section: str = "Introduction", **overrides) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": source_id,
        "section": section,
        "pass": "note_interrogate",
        "model": "stub",
        "frame_version": "0.1",
        "answered_at": "2026-01-01T00:00:00Z",
        "answers": _answers(**overrides),
    }


#: What the fixture's inventory holds once the cut set has run: the two
#: ordinary names and the lowercase concept. `Hanna Batatu` is named only in
#: src2's bibliography section, which sits inside that source's back-matter
#: run, so row B (issue #511) takes it.
_SURVIVING_SURFACES = {
    "Kevin Attell",
    "University of Chicago Press",
    "negative sovereignty",
}


def _build_fixture_trees(root: Path) -> None:
    """src2's cached structural tree (`axial.extract`'s own shape): the
    endnotes sit before the bibliography, so the back-matter boundary is the
    `Bibliography` section and the endnote section is outside it. src1 has no
    tree at all -- a source whose tree is missing is simply not cut."""
    trees_dir = root / "data" / "trees"
    trees_dir.mkdir(parents=True, exist_ok=True)
    tree = {
        "children": [
            {
                "order": order,
                "text": heading,
                "label": "section_header",
                "children": [{"type": "prose", "text": "body"}],
            }
            for order, heading in (("000", "N O T E S"), ("001", "Bibliography"))
        ]
    }
    (trees_dir / "src2.json").write_text(json.dumps(tree), encoding="utf-8")


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
            # A lowercase concept survives (deliberately NOT cut, issue
            # #508); the four beside it are one cut-set row each.
            names=[
                {"name": "negative sovereignty", "kind": "concept"},
                {"name": "Chapter 5", "kind": "concept"},  # row D
                {"name": "Gellner (1983)", "kind": "person"},  # row H
                {"name": "1917-1918", "kind": "period"},  # row F
                {"name": "not-in-passage", "kind": "concept"},  # row S
            ],
            # Row A: the citation channel contributes nothing to the name
            # space, however well-formed the citation is.
            citations=[{"cited": "Gellner 1992", "stance": "authority", "about": "nationalism"}],
        ),
        _record(
            "src2_000_intro_001",
            "src2",
            section="N O T E S",
            names=[{"name": "Kevin Attell", "kind": "person"}],
        ),
        _record(
            "src2_001_back_003",
            "src2",
            section="Bibliography",
            names=[{"name": "Hanna Batatu", "kind": "person"}],
        ),
    ]
    with (answers_dir / "src1.jsonl").open("w", encoding="utf-8") as handle:
        for record in records[:2]:
            handle.write(json.dumps(record) + "\n")
    with (answers_dir / "src2.jsonl").open("w", encoding="utf-8") as handle:
        for record in records[2:]:
            handle.write(json.dumps(record) + "\n")


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
    _build_fixture_trees(root)

    build_result = _run_axial(root, "names", "build")
    _assert_ran_the_real_subcommand(build_result)
    assert build_result.returncode == 0, (
        f"expected exit 0, got {build_result.returncode}\n"
        f"stdout: {build_result.stdout!r}\nstderr: {build_result.stderr!r}"
    )

    manifest_path = root / "data" / "names" / "similarity_manifest.json"
    assert manifest_path.is_file(), f"expected a manifest at {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Three distinct surface forms survive the cut set; the SENTINEL clauses
    # (uses/defines/arguing_against/position_of) were never collected at
    # all, five more surfaces are cut by rows A, D, F, H and S, and one by
    # row B.
    assert manifest["entry_count"] == 3
    assert manifest["occurrence_count"] == 4  # every surviving names[] mention
    assert isinstance(manifest["embedding_dim"], int) and manifest["embedding_dim"] > 0

    inventory_path = root / "data" / "names" / "inventory.jsonl"
    assert inventory_path.is_file(), f"expected an inventory at {inventory_path}"
    inventory = {
        record["surface"]: record
        for record in (json.loads(line) for line in inventory_path.read_text("utf-8").splitlines())
    }
    assert set(inventory) == _SURVIVING_SURFACES
    assert not any("SENTINEL_CLAUSE_never_a_name" in surface for surface in inventory)
    assert inventory["Kevin Attell"] == {
        "surface": "Kevin Attell",
        "kind": "person",
        "count": 2,
        "chunk_ids": ["src1_000_intro_001", "src2_000_intro_001"],
    }
    # Issue #508 row A: the one citation the fixture carries is recorded on
    # the answer record and is not a name.
    assert "Gellner 1992" not in inventory
    # Rows D, F, H and S, each named by the issue's own cut-set table.
    for cut in ("Chapter 5", "1917-1918", "Gellner (1983)", "not-in-passage"):
        assert cut not in inventory, f"{cut!r} should have left the name space"
    # ...and the lowercase concept the issue deliberately refuses to cut.
    assert inventory["negative sovereignty"]["kind"] == "concept"
    # Row B (issue #511): `Hanna Batatu` is named only in src2's
    # `Bibliography` section, which its cached tree puts inside the
    # back-matter run, so the surface never reaches the inventory. The
    # `N O T E S` section in the same book sits before that boundary, so the
    # name it carries (`Kevin Attell`, above) keeps both its occurrences.
    assert "Hanna Batatu" not in inventory
    assert "src2_000_intro_001" in inventory["Kevin Attell"]["chunk_ids"]

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
    _build_fixture_trees(root)
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
    _build_fixture_trees(root)

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
    """Issue #445's own fixture, kept: "Table 4.1" named in two unrelated
    books, "Figure 9.1" named only in one, and a non-locator surface
    ("Kevin Attell") spanning the same two books. Issue #508 row E changed
    what happens to the first two -- see the test below."""
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
                        {"name": "Charles Tilly", "kind": "person"},
                        {"name": "negative sovereignty", "kind": "concept"},
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


def test_names_build_drops_every_locator_shaped_surface(isolated_vault_root):
    """Issue #508 row E supersedes #445's source-scoping outcome: a locator
    is not a name at all, so neither the scoped nor the bare form reaches
    the inventory. 441 surfaces and 431 pages on the corpus of record. The
    scoping rule itself is untouched in `axial.names.build_inventory`; row E
    simply means nothing reaches it."""
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

    assert set(inventory) == {"Kevin Attell", "Charles Tilly", "negative sovereignty"}
    for cut in ("Table 4.1", "Table 4.1 (src1)", "Table 4.1 (src2)", "Figure 9.1"):
        assert cut not in inventory, f"{cut!r} should have left the name space"

    # A genuine cross-book name is not a locator and is untouched.
    assert inventory["Kevin Attell"]["chunk_ids"] == [
        "src1_000_intro_001",
        "src2_000_intro_001",
    ]


def test_names_build_reports_unit_counters_and_recluster_forces_a_refit(isolated_vault_root):
    """Issue #677 end to end through the real CLI: the four `units_*`
    counters `axial names build` reports, and `--recluster`'s own contract
    (a forced full re-fit, never `units_reused`)."""
    root = isolated_vault_root
    _build_fixture_answers(root)
    _build_fixture_trees(root)

    first = _run_axial(root, "names", "build")
    _assert_ran_the_real_subcommand(first)
    assert first.returncode == 0, first.stderr
    assert "units_total: 3" in first.stdout
    assert "units_reused: 0" in first.stdout
    assert "units_asked: 3" in first.stdout
    fit_path = root / "data" / "names" / "fit.joblib"
    assert fit_path.is_file(), "a full fit over the real pipeline must persist a fit artifact"
    fit_mtime_after_first = fit_path.stat().st_mtime_ns

    # A second build with no corpus change: every entry keeps the label the
    # first build already gave it, so nothing is asked about.
    second = _run_axial(root, "names", "build")
    assert second.returncode == 0, second.stderr
    assert "units_total: 3" in second.stdout
    assert "units_reused: 3" in second.stdout
    assert "units_asked: 0" in second.stdout
    assert "units_asked_touching_new: 0" in second.stdout
    assert fit_path.stat().st_mtime_ns == fit_mtime_after_first, (
        "an incremental run with nothing new must not touch the persisted fit"
    )

    # `--recluster` forces a full re-fit regardless -- every entry is asked
    # about again, and the persisted fit artifact is refreshed.
    reclustered = _run_axial(root, "names", "build", "--recluster")
    assert reclustered.returncode == 0, reclustered.stderr
    assert "units_reused: 0" in reclustered.stdout
    assert "units_asked: 3" in reclustered.stdout
    assert fit_path.stat().st_mtime_ns != fit_mtime_after_first
