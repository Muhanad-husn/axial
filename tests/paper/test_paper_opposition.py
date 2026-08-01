"""Acceptance for the opposition gap-and-repair pass (specs/PHASE-C.md
§7.1x/§7.3/§7.11, issue #570).

Offline, stubbed, no network -- like `test_paper_pipeline.py`. The "vault" and
"names" fixtures below are small, hand-built directories (a few prose notes,
a name-layer index and one name page), never a real corpus and never
`data/`, exercising `axial.query.names.who_argues_against` and
`axial.validators.coverage.compute_coverage_map` exactly as a real run would.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from axial.paper.brief import PaperBrief
from axial.paper.intake import run_intake
from axial.paper.opposition import (
    OPPOSITION_GAP_SCOPE_NOTE,
    REPAIR_BRIEF_ID,
    extend_intake,
    run_opposition_repair,
)
from axial.paper.record import run_paper
from axial.paper.render import render_paper
from axial.paths import name_page_filename

PIN = "sim-2026-07-30"


# -- shared fixture helpers, matching test_paper_pipeline.py's own shapes ----


def _claim(claim_id, kind, text, band, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": kind,
        "text": text,
        "confidence": band,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


def _record(brief_id, claims, coverage_map, *, pin=PIN, trajectory=None):
    return {
        "brief_id": brief_id,
        "corpus_pin": pin,
        "lens": "state-formation",
        "interrogation": {"disposition": "proceed"},
        "claims": claims,
        "coverage_map": coverage_map,
        "counter_position": {
            "present": True,
            "stance": "the opposing account",
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "confidence": {"overall_band": "high", "rationale": "..."},
        "trajectory": trajectory or [],
    }


@pytest.fixture
def analyses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses"
    directory.mkdir()
    a = _record(
        "brief-a",
        [
            _claim(
                "a1",
                "a",
                "Tilly makes war the mechanism.",
                "high",
                "tilly-1978-aaa_1_war_001",
                ["Charles Tilly"],
            )
        ],
        {
            "Charles Tilly": {
                "corpus_note_count": 154,
                "evidence_note_count": 8,
                "coverage_band": "dense",
            }
        },
    )
    (directory / "brief-a.json").write_text(json.dumps(a), encoding="utf-8")
    return directory


@pytest.fixture
def lenses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "lenses"
    directory.mkdir()
    (directory / "state-formation.yaml").write_text(
        "name: state-formation\ndescription: Reads for how state capacity was built.\n",
        encoding="utf-8",
    )
    return directory


def _write_names_layer(names_dir: Path, canonicals: list[str]) -> None:
    names_dir.mkdir(parents=True, exist_ok=True)
    nodes = [{"canonical": name, "kind": "person", "aliases": []} for name in canonicals]
    (names_dir / "index.json").write_text(
        json.dumps({"version": 1, "names": canonicals}), encoding="utf-8"
    )
    (names_dir / "alias_map.json").write_text(
        json.dumps({"version": 1, "nodes": nodes}), encoding="utf-8"
    )


def _write_opposition_note(
    vault_dir: Path, chunk_id: str, *, arguing_against: list[str], claim: str | None
) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "A Section",
        "chunk_text": f"{chunk_id} text.",
        "source_meta": {"author": "Critic", "title": "A Critique", "date": 2020},
        "answers": {
            "arguing_against": arguing_against,
            "position_of": "the author",
            "claim": claim,
        },
    }
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    (prose_dir / f"{chunk_id}.md").write_text(f"---\n{rendered}---\nBody.\n", encoding="utf-8")


def _write_name_page(vault_dir: Path, canonical: str, member_count: int) -> None:
    names_dir = vault_dir / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {"name": canonical, "kind": "person", "aliases": [], "member_count": member_count}
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    path = names_dir / name_page_filename(names_dir, canonical)
    path.write_text(f"---\n{rendered}---\nBody.\n", encoding="utf-8")


GAP_CHUNK_ID = "critic-2021-ccc_1_a_001"
GAP_CLAIM_TEXT = "War-making alone cannot explain state formation absent an external threat."


@pytest.fixture
def gap_vault(tmp_path: Path) -> tuple[Path, Path]:
    """A vault/names pair carrying exactly ONE opposing note that brief-a's
    own claim grounds never read -- a genuine, non-zero gap on `Charles
    Tilly`, plus a real name page so the earned coverage map's band is
    computed rather than defaulted."""
    vault_dir = tmp_path / "gap_vault"
    names_dir = tmp_path / "gap_names"
    _write_names_layer(names_dir, ["Charles Tilly"])
    _write_opposition_note(
        vault_dir, GAP_CHUNK_ID, arguing_against=["Charles Tilly"], claim=GAP_CLAIM_TEXT
    )
    _write_name_page(vault_dir, "Charles Tilly", 150)  # >= dense_floor (100)
    return vault_dir, names_dir


@pytest.fixture
def empty_vault(tmp_path: Path) -> tuple[Path, Path]:
    """No prose notes, no name layer at all -- `who_argues_against` degrades
    to `([], 0)` for every name, and the pass must cost nothing."""
    return tmp_path / "empty_vault", tmp_path / "empty_names"


# -- unit tests: axial.paper.opposition directly ------------------------------


def test_zero_gap_repairs_nothing_and_extend_intake_is_a_no_op(analyses_dir, empty_vault):
    vault_dir, names_dir = empty_vault
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)

    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)

    assert repair.gap_found == 0
    assert repair.gap_repaired == 0
    assert repair.trajectory == ()
    assert repair.repair_claims == ()
    assert repair.coverage_map == {}
    # "costs nothing": a zero-gap run leaves the intake untouched, not merely
    # equal to it -- no synthetic record, no extra inventory entries.
    assert extend_intake(intake, repair) is intake


def test_a_non_zero_gap_produces_real_chunk_ids_never_invented_ones(analyses_dir, gap_vault):
    vault_dir, names_dir = gap_vault
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)

    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)

    assert repair.gap_found == 1
    assert repair.gap_repaired == 1
    assert repair.skipped_abstentions == 0
    assert len(repair.trajectory) == 1
    assert repair.trajectory[0]["tool"] == "who_argues_against"
    assert repair.trajectory[0]["args"] == {"canonical": "Charles Tilly"}
    assert repair.trajectory[0]["result_ids"] == [GAP_CHUNK_ID]

    entry = repair.repair_claims[0]
    assert entry.brief_id == REPAIR_BRIEF_ID
    assert entry.claim_id == GAP_CHUNK_ID
    # The id and the text both come out of the query API together -- nothing
    # the layer invented (#570 rule 1).
    assert entry.claim["grounds"] == [{"ref_type": "chunk", "ref_id": GAP_CHUNK_ID}]
    assert entry.claim["text"] == GAP_CLAIM_TEXT
    assert entry.claim["kind"] == "a"
    assert entry.claim["names_touched"] == ["Charles Tilly"]

    # The earned coverage map is computed from the REAL name page (150 >=
    # dense_floor), not defaulted.
    assert repair.coverage_map["Charles Tilly"]["coverage_band"] == "dense"

    extended = extend_intake(intake, repair)
    assert (REPAIR_BRIEF_ID, GAP_CHUNK_ID) in extended.by_key()
    assert extended.records[REPAIR_BRIEF_ID]["coverage_map"] == repair.coverage_map


def test_an_already_read_note_is_not_a_gap_even_though_who_argues_against_finds_it(
    analyses_dir, tmp_path
):
    """ "Already read" is read off a source record's own claim grounds --
    the same chunk id `who_argues_against` returns must not count as unread
    just because it also opposes the anchor name."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_names_layer(names_dir, ["Charles Tilly"])
    _write_opposition_note(
        vault_dir,
        "tilly-1978-aaa_1_war_001",  # brief-a's own a1 grounds id
        arguing_against=["Charles Tilly"],
        claim="A claim.",
    )
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)

    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)

    assert repair.gap_found == 0
    assert repair.repair_claims == ()
    assert repair.trajectory == ()


def test_an_already_read_note_via_trajectory_is_also_excluded(tmp_path):
    """ "Already read" also covers a chunk id the source record's own §7.6
    trajectory surfaced, even when no claim ever cited it as grounds."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    analyses_dir = tmp_path / "analyses"
    analyses_dir.mkdir()
    _write_names_layer(names_dir, ["Charles Tilly"])
    _write_opposition_note(
        vault_dir, GAP_CHUNK_ID, arguing_against=["Charles Tilly"], claim=GAP_CLAIM_TEXT
    )
    record = _record(
        "brief-a",
        [_claim("a1", "a", "Tilly.", "high", "tilly-1978-aaa_1_war_001", ["Charles Tilly"])],
        {
            "Charles Tilly": {
                "corpus_note_count": 154,
                "evidence_note_count": 1,
                "coverage_band": "dense",
            }
        },
        trajectory=[
            {
                "step": 1,
                "tool": "who_argues_against",
                "args": {"canonical": "Charles Tilly"},
                "result_ids": [GAP_CHUNK_ID],
                "result_count": 1,
                "total": 1,
                "detail": None,
            }
        ],
    )
    (analyses_dir / "brief-a.json").write_text(json.dumps(record), encoding="utf-8")
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)

    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)

    assert repair.gap_found == 0


def test_an_abstained_note_counts_as_gap_but_is_not_repaired(analyses_dir, tmp_path):
    """The real-corpus `not-in-passage` abstention (2.3% of live notes,
    measured 2026-08-01) is skipped rather than shaped into an invented
    claim -- but the note itself still counts as unread opposition."""
    vault_dir = tmp_path / "vault"
    names_dir = tmp_path / "names"
    _write_names_layer(names_dir, ["Charles Tilly"])
    _write_opposition_note(
        vault_dir, GAP_CHUNK_ID, arguing_against=["Charles Tilly"], claim="not-in-passage"
    )
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)

    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)

    assert repair.gap_found == 1
    assert repair.gap_repaired == 0
    assert repair.skipped_abstentions == 1
    assert repair.repair_claims == ()
    # A gap that could not be repaired still leaves a trajectory entry: the
    # lookup happened and is auditable, even though nothing came of it.
    assert len(repair.trajectory) == 1


def test_gap_restricted_to_a_name_subset(analyses_dir, gap_vault):
    vault_dir, names_dir = gap_vault
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)
    repair = run_opposition_repair(intake, vault_dir=vault_dir, names_dir=names_dir)

    assert repair.gap_restricted_to({"Charles Tilly"}) == 1
    assert repair.gap_restricted_to({"Someone Else"}) == 0


def test_the_lookup_is_an_injectable_seam_not_a_hardcoded_call(analyses_dir, empty_vault):
    """founder direction, 2026-08-01: a future opposition-resolution pass
    (recovering targets `who_argues_against` cannot exact-match) must slot in
    as a `lookup` override with no change to the gap arithmetic, the repair
    shaping, or the record shape. Proven here with a fake lookup that never
    touches the vault at all -- `empty_vault` would report zero through the
    real query API, but the injected lookup still drives a real repair."""
    from axial.query.names import OppositionEdge

    vault_dir, names_dir = empty_vault
    intake = run_intake(("brief-a",), analyses_dir=analyses_dir)

    calls: list[str] = []

    def fake_lookup(canonical, limit=10, *, vault_dir=None, names_dir=None):
        calls.append(canonical)
        if canonical != "Charles Tilly":
            return [], 0
        edge = OppositionEdge(
            chunk_id=GAP_CHUNK_ID,
            source_id="critic-2021-ccc",
            arguing_against="Charles Tilly",
            position="a macro-structural Weberianism that gives no room to agency",
            claim=GAP_CLAIM_TEXT,
        )
        return [edge], 1

    repair = run_opposition_repair(
        intake, vault_dir=vault_dir, names_dir=names_dir, lookup=fake_lookup
    )

    assert calls == ["Charles Tilly"]
    assert repair.gap_found == 1
    assert repair.gap_repaired == 1
    assert repair.repair_claims[0].claim["grounds"] == [
        {"ref_type": "chunk", "ref_id": GAP_CHUNK_ID}
    ]


# -- integration: the full run_paper pipeline ---------------------------------


class StubClient:
    model_by_pass = {"paper_plan": "stub/plan", "paper_draft": "stub/draft"}

    def __init__(self, plan, drafts):
        self._plan = plan
        self._drafts = list(drafts)
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(self._plan)
        return json.dumps(self._drafts.pop(0))

    def cost_report(self):
        return {"total_usd": 0.0, "by_pass": {}}


def _plan_citing_repair_claim():
    return {
        "thesis_statement": "War-making alone does not explain the outcome.",
        "sections": [
            {
                "section_id": "s1",
                "heading": "The bellicist account",
                "role": "claim",
                "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
            },
            {
                "section_id": "s2",
                "heading": "The case against",
                "role": "counter-position",
                "assigned_claims": [{"brief_id": REPAIR_BRIEF_ID, "claim_id": GAP_CHUNK_ID}],
            },
        ],
    }


DRAFTS_CITING_REPAIR = [
    {"prose": "War made the state [pc-001].", "new_claims": []},
    {"prose": "But that account does not hold everywhere [pc-002].", "new_claims": []},
]


def _run(tmp_path, analyses_dir, lenses_dir, vault_dir, names_dir, *, plan=None, drafts=None):
    client = StubClient(plan or _plan_citing_repair_claim(), drafts or DRAFTS_CITING_REPAIR)
    brief = PaperBrief(
        paper_brief_id="pb-opposition-test",
        thesis="Does war-making alone explain the outcome?",
        analysis_ids=("brief-a",),
        lens="state-formation",
    )
    record = run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=tmp_path / "source_meta",
        vault_dir=vault_dir,
        names_dir=names_dir,
        papers_dir=tmp_path / "papers",
    )
    return record, client


def test_a_repaired_claim_reaches_the_inventory_the_record_and_the_render(
    tmp_path, analyses_dir, lenses_dir, gap_vault
):
    vault_dir, names_dir = gap_vault
    record, _ = _run(tmp_path, analyses_dir, lenses_dir, vault_dir, names_dir)

    repaired = [
        claim
        for claim in record["claims"]
        if isinstance(claim.get("origin"), dict)
        and claim["origin"].get("brief_id") == REPAIR_BRIEF_ID
    ]
    assert len(repaired) == 1
    assert repaired[0]["origin"] == {"brief_id": REPAIR_BRIEF_ID, "claim_id": GAP_CHUNK_ID}
    assert repaired[0]["kind"] == "a"
    assert repaired[0]["grounds"] == [{"ref_type": "chunk", "ref_id": GAP_CHUNK_ID}]

    gap = record["exact_match_opposition_gap"]
    assert gap["scope_note"] == OPPOSITION_GAP_SCOPE_NOTE
    assert gap["gap_found"] == 1
    assert gap["gap_repaired"] == 1
    # Both source-side and cited-side numbers, per #570's placement decision.
    assert gap["gap_found_cited_scope"] == 1
    assert gap["gap_repaired_cited"] == 1

    assert len(record["trajectory"]) == 1
    assert record["trajectory"][0]["tool"] == "who_argues_against"

    assert "Charles Tilly" in record["coverage_map_earned"]
    assert record["coverage_map_earned"]["Charles Tilly"]["coverage_band"] == "dense"

    rendered = render_paper(record)
    assert "## Opposition check (exact-match join)" in rendered
    assert "Found **1**" in rendered
    assert "repaired **1**" in rendered
    assert "4.7%" in rendered  # the scope note's magnitude travels into the render
    assert "| Charles Tilly | earned |" in rendered
    # A repaired run must never report a clean zero (#570 rule 3).
    assert "Found **0**" not in rendered


def test_a_zero_gap_run_reports_the_real_zero_and_costs_nothing(
    tmp_path, analyses_dir, lenses_dir, empty_vault
):
    vault_dir, names_dir = empty_vault
    plan = {
        "thesis_statement": "War-making explains the outcome.",
        "sections": [
            {
                "section_id": "s1",
                "heading": "The bellicist account",
                "role": "claim",
                "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
            },
            {
                "section_id": "s2",
                "heading": "The case against",
                "role": "counter-position",
                # No repair claim exists to cite (the gap is zero), so this
                # section reasons over the same claim already in hand.
                "assigned_claims": [{"brief_id": "brief-a", "claim_id": "a1"}],
            },
        ],
    }
    drafts = [
        {"prose": "War made the state [pc-001].", "new_claims": []},
        {"prose": "Even so, the account has limits [pc-001].", "new_claims": []},
    ]
    record, _ = _run(
        tmp_path, analyses_dir, lenses_dir, vault_dir, names_dir, plan=plan, drafts=drafts
    )

    gap = record["exact_match_opposition_gap"]
    assert gap["gap_found"] == 0
    assert gap["gap_repaired"] == 0
    assert gap["gap_found_cited_scope"] == 0
    assert record["trajectory"] == []
    assert record["coverage_map_earned"] == {}
    assert not any(
        isinstance(claim.get("origin"), dict) and claim["origin"].get("brief_id") == REPAIR_BRIEF_ID
        for claim in record["claims"]
    )

    rendered = render_paper(record)
    # The real zero renders plainly -- never omitted, never silently hidden.
    assert "## Opposition check (exact-match join)" in rendered
    assert "Found **0**" in rendered
    assert OPPOSITION_GAP_SCOPE_NOTE in rendered


def test_the_no_phase_b_import_guarantee_still_holds():
    """Phase C never runs Phase B (§3 non-goal 1) -- reading the name layer
    and the coverage validator must not have dragged the run path in."""
    import axial.paper.record  # noqa: F401
    import axial.paper.opposition  # noqa: F401

    dragged = [
        name
        for name in sys.modules
        if name.startswith("axial.answer")
        or name.startswith("axial.analyze")
        or name.startswith("axial.brief")
    ]
    assert dragged == []
