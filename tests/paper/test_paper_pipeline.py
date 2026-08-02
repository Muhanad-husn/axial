"""Phase-C acceptance: a paper brief over two analysis records becomes a
record and a rendered paper (specs/PHASE-C.md §7.1-§7.11, §8 P0-1..P0-7).

Runs the whole pipeline against a scripted stub client and fixture records --
no network, no vault, no corpus. What it asserts is the contract, not the
prose: the three intake rejections, that a carried claim takes its origin's
CLAMPED band, that a new (b) claim must span two records, that the record's
claims are exactly what the prose cited, and that rendering is deterministic.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from axial.paper.brief import PaperBrief
from axial.paper.intake import (
    MixedCorpusPinError,
    RefusedAnalysisError,
    UnresolvableAnalysisError,
    run_intake,
)
from axial.paper.record import run_paper
from axial.paper.render import render_paper
from axial.paper.shape import SelfGradingError, ShapeParseError

PIN = "sim-2026-07-30"


def _claim(claim_id, kind, text, band, chunk_id, names):
    return {
        "claim_id": claim_id,
        "kind": kind,
        "text": text,
        "confidence": band,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "names_touched": names,
    }


def _record(
    brief_id, claims, coverage_map, *, pin=PIN, disposition="proceed", lens="state-formation"
):
    return {
        "brief_id": brief_id,
        "corpus_pin": pin,
        "lens": lens,
        "interrogation": {"disposition": disposition},
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
    }


@pytest.fixture
def analyses_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "analyses"
    directory.mkdir()

    # `Tilly` is dense in A and thin in B's own map. A claim's clamp reads its
    # OWN record's map, which is what makes the two differ.
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
            ),
            _claim(
                "a2",
                "a",
                "Extraction follows coercion.",
                "high",
                "tilly-1978-aaa_2_extraction_001",
                ["Charles Tilly"],
            ),
        ],
        {
            "Charles Tilly": {
                "corpus_note_count": 154,
                "evidence_note_count": 8,
                "coverage_band": "dense",
            }
        },
    )
    b = _record(
        "brief-b",
        [
            # Emitted `high`, but its only name is thin -- so its CLAMPED band
            # is `low`, and that is what a carried claim must take.
            _claim(
                "b1",
                "a",
                "Bayat sees revolution without revolutionaries.",
                "high",
                "bayat-2017-bbb_3_refolution_001",
                ["Asef Bayat"],
            ),
        ],
        {"Asef Bayat": {"corpus_note_count": 4, "evidence_note_count": 1, "coverage_band": "thin"}},
    )
    (directory / "brief-a.json").write_text(json.dumps(a), encoding="utf-8")
    (directory / "brief-b.json").write_text(json.dumps(b), encoding="utf-8")
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


# The default shape-check response every pipeline test gets unless it asks
# for something else: `strong`, no defects -- the check does its own job
# (issue #578) without perturbing tests that only care about earlier stages.
SHAPE_RESPONSE = {"band": "strong", "defects": []}


class StubClient:
    """Returns scripted JSON per pass, and records what it was asked."""

    # `paper_shape` deliberately resolves to a DIFFERENT model than
    # `paper_draft`: the shape check's own self-grading guard (issue #578)
    # raises if the two ever match.
    model_by_pass = {
        "paper_plan": "stub/plan",
        "paper_draft": "stub/draft",
        "paper_shape": "stub/shape",
    }

    def __init__(self, plan, drafts, shape=None):
        self._plan = plan
        self._drafts = list(drafts)
        self._shape = shape if shape is not None else SHAPE_RESPONSE
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt, pass_name=None, **_):
        self.prompts.append((pass_name, prompt))
        if pass_name == "paper_plan":
            return json.dumps(self._plan)
        if pass_name == "paper_shape":
            return json.dumps(self._shape)
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def usage_for_pass(self, pass_name=None):
        return None


PLAN = {
    "thesis_statement": "Organized challengers explain the outcome better than mass mobilization alone.",
    "sections": [
        {
            "section_id": "s1",
            "heading": "The bellicist account",
            "role": "claim",
            "assigned_claims": [
                {"brief_id": "brief-a", "claim_id": "a1"},
                {"brief_id": "brief-a", "claim_id": "a2"},
            ],
        },
        {
            "section_id": "s2",
            "heading": "The case against",
            "role": "counter-position",
            "assigned_claims": [{"brief_id": "brief-b", "claim_id": "b1"}],
        },
    ],
}

DRAFTS = [
    {"prose": "War made the state [pc-001]. Extraction followed [pc-002].", "new_claims": []},
    {
        "prose": "Mobilization did not convert [pc-003]. The two accounts diverge on organization [n1].",
        "new_claims": [
            {
                "local_id": "n1",
                "text": "The accounts disagree about what organization is for.",
                "derived_from": ["pc-001", "pc-003"],
            }
        ],
    },
]


def test_intake_rejects_an_unresolvable_record(analyses_dir: Path):
    with pytest.raises(UnresolvableAnalysisError) as excinfo:
        run_intake(("brief-a", "brief-missing"), analyses_dir=analyses_dir)
    assert "brief-missing" in str(excinfo.value)
    assert "Phase C never runs Phase B" in str(excinfo.value)


def test_intake_rejects_a_refusal(analyses_dir: Path):
    refused = _record("brief-r", [], {}, disposition="refuse")
    (analyses_dir / "brief-r.json").write_text(json.dumps(refused), encoding="utf-8")
    with pytest.raises(RefusedAnalysisError):
        run_intake(("brief-a", "brief-r"), analyses_dir=analyses_dir)


def test_intake_rejects_a_mixed_pin_set(analyses_dir: Path):
    stale = _record("brief-s", [], {}, pin="sim-2026-01-01")
    (analyses_dir / "brief-s.json").write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(MixedCorpusPinError) as excinfo:
        run_intake(("brief-a", "brief-s"), analyses_dir=analyses_dir)
    assert "brief-a" in str(excinfo.value) and "brief-s" in str(excinfo.value)


def test_contradicting_records_are_never_rejected(analyses_dir: Path):
    """§7.14: contradiction is the scholarly substance, not an intake error."""
    intake = run_intake(("brief-a", "brief-b"), analyses_dir=analyses_dir)
    assert intake.corpus_pin == PIN
    assert len(intake.inventory) == 3


def _run(tmp_path, analyses_dir, lenses_dir, drafts=None, shape=None):
    client = StubClient(PLAN, drafts if drafts is not None else DRAFTS, shape=shape)
    brief = PaperBrief(
        paper_brief_id="pb-test",
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="state-formation",
    )
    record = run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=tmp_path / "source_meta",
        papers_dir=tmp_path / "papers",
    )
    return record, client


def test_a_carried_claim_takes_its_origins_clamped_band(tmp_path, analyses_dir, lenses_dir):
    """§7.4: the clamped band, not the band the record persisted."""
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    by_origin = {
        (claim["origin"]["brief_id"], claim["origin"]["claim_id"]): claim
        for claim in record["claims"]
        if claim.get("origin")
    }
    # b1 was persisted `high`; its only name is thin, so the paper carries `low`.
    assert by_origin[("brief-b", "b1")]["confidence"] == "low"
    # a1 was persisted `high` against a dense name, so it is unchanged.
    assert by_origin[("brief-a", "a1")]["confidence"] == "high"


def test_a_new_b_claim_spans_two_records_and_is_capped(tmp_path, analyses_dir, lenses_dir):
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    new_claims = [claim for claim in record["claims"] if claim["origin"] is None]
    assert len(new_claims) == 1
    new = new_claims[0]
    assert new["kind"] == "b"
    # Grounds are the union of what it derives from, never the drafter's.
    assert len(new["grounds"]) == 2
    # Capped at the weakest it stands on: pc-003 carries `low`.
    assert new["confidence"] == "low"


def test_a_single_record_b_proposal_is_retried_not_fatal(tmp_path, analyses_dir, lenses_dir):
    """Issue #616: the §7.4 span check now runs INSIDE `draft_section`'s
    bounded retry (issue #598) rather than after `run_paper` has already
    returned. Before this fix a single-record (b) proposal raised
    `SingleRecordInferenceError` straight out of `run_paper`, fatal on first
    occurrence and discarding every section already drafted -- which is what
    made #605's D1 multi-record briefs fail outright. Both `derived_from`
    ids in the rejected proposal (`pc-001`, `pc-002`) come from `brief-a`
    alone; the retry succeeds with a section that introduces no new claim."""
    single_record_proposal = {
        "prose": "War made the state [pc-001]. And so [n1].",
        "new_claims": [
            {"local_id": "n1", "text": "A restatement.", "derived_from": ["pc-001", "pc-002"]}
        ],
    }
    corrected_draft = {
        "prose": "War made the state [pc-001]. Extraction followed [pc-002].",
        "new_claims": [],
    }
    drafts = [single_record_proposal, corrected_draft, DRAFTS[1]]

    record, client = _run(tmp_path, analyses_dir, lenses_dir, drafts)

    # The run completed: no PaperClaimError escaped, and the (b) claim from
    # section 2's own draft (spanning brief-a and brief-b) still landed.
    new_claims = [claim for claim in record["claims"] if claim["origin"] is None]
    assert len(new_claims) == 1
    assert record["retries"]["paper_draft"] == 1

    draft_prompts = [prompt for name, prompt in client.prompts if name == "paper_draft"]
    retry_prompt = draft_prompts[1]
    assert "distinct source record" in retry_prompt
    assert "attempt 1 of 3" in retry_prompt


def test_a_new_c_claim_reaches_a_verdict_resting_on_a_single_record(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #577: a paper can carry someone else's (c) claim but must also be
    able to reach one of its own -- exempt from the two-distinct-records rule
    a (b) claim needs, since a verdict is judgment, not cross-source synthesis.
    Both `derived_from` claims here (pc-001, pc-002) come from `brief-a` alone."""
    drafts = [
        {"prose": "War made the state [pc-001]. Extraction followed [pc-002].", "new_claims": []},
        {
            "prose": (
                "Mobilization did not convert [pc-003]. On balance, the bellicist "
                "account holds [n1]."
            ),
            "new_claims": [
                {
                    "local_id": "n1",
                    "kind": "c",
                    "text": "The bellicist account is the stronger explanation here.",
                    "derived_from": ["pc-001", "pc-002"],
                }
            ],
        },
    ]
    record, _ = _run(tmp_path, analyses_dir, lenses_dir, drafts)

    verdicts = [claim for claim in record["claims"] if claim["kind"] == "c" and not claim["origin"]]
    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict["derived_from"] == ["pc-001", "pc-002"]
    assert len(verdict["grounds"]) == 2
    # Both parents carry `high` (dense Tilly coverage), so the verdict does too.
    assert verdict["confidence"] == "high"

    rendered = render_paper(record)
    assert "(this paper's verdict)" in rendered
    assert "(this paper's inference)" not in rendered  # no new (b) claim here


def test_claims_are_exactly_what_the_prose_cited(tmp_path, analyses_dir, lenses_dir):
    """§7.5: a claim assigned but never cited is dropped, not carried."""
    drafts = [
        {"prose": "War made the state [pc-001].", "new_claims": []},
        {"prose": "Mobilization did not convert [pc-003].", "new_claims": []},
    ]
    record, _ = _run(tmp_path, analyses_dir, lenses_dir, drafts)
    cited = {claim["paper_claim_id"] for claim in record["claims"]}
    assert cited == {"pc-001", "pc-003"}
    assert all(citation["paper_claim_id"] in cited for citation in record["citations"])


def test_the_drafter_is_called_once_per_section_and_never_sees_the_whole_inventory(
    tmp_path, analyses_dir, lenses_dir
):
    """§4: one call per section, over that section's claims alone."""
    _, client = _run(tmp_path, analyses_dir, lenses_dir)
    draft_prompts = [prompt for pass_name, prompt in client.prompts if pass_name == "paper_draft"]
    assert len(draft_prompts) == len(PLAN["sections"])
    # Section 1's call must not carry section 2's claim text.
    assert "revolution without revolutionaries" not in draft_prompts[0]


def test_the_shape_check_makes_exactly_one_call_after_every_draft(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #578 acceptance criterion 1: one call regardless of section
    count, made after the drafting calls, never before."""
    _, client = _run(tmp_path, analyses_dir, lenses_dir)
    pass_names = [pass_name for pass_name, _ in client.prompts]
    shape_calls = [name for name in pass_names if name == "paper_shape"]
    assert len(shape_calls) == 1
    # It runs after every draft call, not interleaved with them.
    assert pass_names.index("paper_shape") == len(pass_names) - 1
    assert pass_names.count("paper_draft") == len(PLAN["sections"])


def test_the_shape_result_is_persisted_on_the_record(tmp_path, analyses_dir, lenses_dir):
    """Issue #578 acceptance criterion 6: band, defects, model and cost."""
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    shape = record["shape"]
    assert shape["band"] == "strong"
    assert shape["defects"] == []
    assert shape["model"] == "stub/shape"
    assert "cost" in shape
    # model_by_pass gains the shape pass alongside planning and drafting.
    assert record["model_by_pass"]["paper_shape"] == "stub/shape"


def test_the_record_carries_a_zero_retry_count_when_nothing_was_rejected(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #598: a paper that never hit a validator rejection still carries
    the field, at zero -- so its presence is not itself a sign of trouble."""
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    assert record["retries"] == {"paper_plan": 0, "paper_draft": 0}


class RetryingStubClient(StubClient):
    """Rejects the first arc-planning draw and the first section's first
    drafting draw -- the exact §7.2 empty-section shape issue #598 measured
    failing 2 of 7 real draws -- before returning the scripted good
    response, so the record's own `retries` field can be pinned end to
    end."""

    def __init__(self, plan, drafts):
        super().__init__(plan, drafts)
        self._plan_attempts = 0
        self._draft_attempts = 0

    def complete(self, prompt, pass_name=None, **_):
        if pass_name == "paper_plan":
            self._plan_attempts += 1
            self.prompts.append((pass_name, prompt))
            if self._plan_attempts == 1:
                return json.dumps(
                    {
                        "thesis_statement": "x",
                        "sections": [
                            {
                                "section_id": "s1",
                                "heading": "h",
                                "role": "claim",
                                "assigned_claims": [],
                            }
                        ],
                    }
                )
            return json.dumps(self._plan)
        if pass_name == "paper_draft":
            self._draft_attempts += 1
            self.prompts.append((pass_name, prompt))
            if self._draft_attempts == 1:
                return json.dumps({"new_claims": []})  # no 'prose'
            return json.dumps(self._drafts.pop(0))
        return super().complete(prompt, pass_name=pass_name)


def test_the_record_carries_a_nonzero_retry_count_per_pass(tmp_path, analyses_dir, lenses_dir):
    """Issue #598: retry cost is visible in the same place as run cost
    (#591/#594) -- one rejected plan draw and one rejected drafting draw,
    summed across sections onto the record's `paper_draft` entry."""
    client = RetryingStubClient(PLAN, list(DRAFTS))
    brief = PaperBrief(
        paper_brief_id="pb-test",
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="state-formation",
    )
    record = run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=tmp_path / "source_meta",
        papers_dir=tmp_path / "papers",
    )
    assert record["retries"] == {"paper_plan": 1, "paper_draft": 1}


class CostReportingStubClient(StubClient):
    """A `StubClient` that also reports real per-pass token usage, and is
    configured with Phase-B pass names alongside Phase C's own three -- the
    shape a client wired for the whole app actually carries. Pins issue
    #591: the record's `cost` field must draw only the passes THIS paper
    ran, never the client's whole configured mapping."""

    model_by_pass = {
        "paper_plan": "deepseek/deepseek-v4-flash",
        "paper_draft": "deepseek/deepseek-v4-flash",
        "paper_shape": "stub/shape",
        "interrogate": "deepseek/deepseek-v4-flash",
        "retrieve": "deepseek/deepseek-v4-flash",
        "synthesize": "deepseek/deepseek-v4-flash",
    }

    def usage_for_pass(self, pass_name=None):
        return {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}


def test_the_cost_field_carries_real_usage_scoped_to_the_papers_own_passes(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #591: `cost` was `getattr(client, "cost_report", lambda: {})()`
    -- no client ever defines `cost_report`, so this always took the `{}`
    default. The fix reads real usage through `client.usage_for_pass`,
    scoped to Phase C's own three passes -- never every pass a shared
    client happens to be configured with."""
    client = CostReportingStubClient(PLAN, list(DRAFTS))
    brief = PaperBrief(
        paper_brief_id="pb-test",
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="state-formation",
    )
    record = run_paper(
        client,
        brief,
        analyses_dir=analyses_dir,
        lenses_dir=lenses_dir,
        source_meta_dir=tmp_path / "source_meta",
        papers_dir=tmp_path / "papers",
    )

    # Exactly Phase C's own passes -- not `{}`, and not the client's other
    # (Phase-B) configured passes.
    assert set(record["model_by_pass"]) == {"paper_plan", "paper_draft", "paper_shape"}
    assert set(record["cost"]["by_pass"]) == {"paper_plan", "paper_draft", "paper_shape"}

    for pass_name in ("paper_plan", "paper_draft", "paper_shape"):
        entry = record["cost"]["by_pass"][pass_name]
        assert entry["prompt_tokens"] == 1000
        assert entry["completion_tokens"] == 500
        assert entry["total_tokens"] == 1500

    # `paper_plan`/`paper_draft` resolve to a priced model: real dollars.
    plan_usd = record["cost"]["by_pass"]["paper_plan"]["usd"]
    draft_usd = record["cost"]["by_pass"]["paper_draft"]["usd"]
    assert plan_usd is not None and plan_usd > 0
    assert draft_usd is not None and draft_usd > 0
    # `paper_shape` resolves to an unpriced model ("stub/shape" is not in
    # the real price table): null, never a fabricated zero.
    assert record["cost"]["by_pass"]["paper_shape"]["usd"] is None
    # The total sums whatever priced -- the one unpriced pass does not
    # blank it out.
    assert record["cost"]["total_usd"] == pytest.approx(plan_usd + draft_usd)


def test_the_cost_field_is_never_empty_even_under_a_client_reporting_no_usage(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #591's actual regression: `cost` was `{}` unconditionally,
    because `getattr(client, "cost_report", ...)` always took its default.
    Even a client reporting no usage at all must produce the real per-pass
    shape -- null tokens/dollars honestly, never a fabricated zero and
    never a bare `{}`."""
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    assert record["cost"] != {}
    assert set(record["cost"]["by_pass"]) == {"paper_plan", "paper_draft", "paper_shape"}
    for entry in record["cost"]["by_pass"].values():
        assert entry["prompt_tokens"] == 0
        assert entry["usd"] is None
    assert record["cost"]["total_usd"] is None


def test_a_weak_band_with_no_defects_is_a_parse_error_and_aborts_the_run(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #578 acceptance criterion 3, exercised end to end."""
    with pytest.raises(ShapeParseError):
        _run(tmp_path, analyses_dir, lenses_dir, shape={"band": "weak", "defects": []})


def test_the_shape_check_refuses_to_run_on_the_drafting_model(tmp_path, analyses_dir, lenses_dir):
    """Issue #578 acceptance criterion 4: configuring the same model for both
    raises, naming both passes."""
    client = StubClient(PLAN, list(DRAFTS))
    client.model_by_pass = {"paper_plan": "stub/plan", "paper_draft": "same/model"}
    # `paper_shape` absent from `model_by_pass` resolves to the client's own
    # default model via `model_for_pass` -- give it explicitly here so the
    # guard has something concrete to compare.
    client.model_by_pass["paper_shape"] = "same/model"
    brief = PaperBrief(
        paper_brief_id="pb-test",
        thesis="Which account explains the outcome?",
        analysis_ids=("brief-a", "brief-b"),
        lens="state-formation",
    )
    with pytest.raises(SelfGradingError) as excinfo:
        run_paper(
            client,
            brief,
            analyses_dir=analyses_dir,
            lenses_dir=lenses_dir,
            source_meta_dir=tmp_path / "source_meta",
            papers_dir=tmp_path / "papers",
        )
    assert "paper_shape" in str(excinfo.value)
    assert "paper_draft" in str(excinfo.value)
    # No paper was written: the guard fires before any of stage 4/5 runs.
    assert not (tmp_path / "papers").exists()


def test_the_rendered_output_is_byte_identical_but_for_the_added_shape_block(
    tmp_path, analyses_dir, lenses_dir
):
    """Issue #578 acceptance criterion 5: adding the shape check changes the
    rendered paper by exactly one new block and nothing else."""
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    with_shape = render_paper(record)

    without_shape_record = dict(record)
    without_shape_record.pop("shape")
    without_shape = render_paper(without_shape_record)

    start = with_shape.index("## Shape check")
    end = with_shape.index("## Citations")
    stripped = with_shape[:start] + with_shape[end:]
    assert stripped == without_shape


def test_the_lens_reaches_the_model_with_its_description(tmp_path, analyses_dir, lenses_dir):
    """§0: a lens is not a filename."""
    _, client = _run(tmp_path, analyses_dir, lenses_dir)
    plan_prompt = next(p for name, p in client.prompts if name == "paper_plan")
    assert "Reads for how state capacity was built." in plan_prompt


def test_rendering_is_deterministic_and_discloses_bands_with_counts(
    tmp_path, analyses_dir, lenses_dir
):
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    first = render_paper(record)
    assert first == render_paper(record)

    assert "Organized challengers explain" in first
    assert "## Confidence and coverage" in first
    # A band never renders alone (§7.10).
    assert "corpus notes" in first and "cited claims" in first
    # Kind is legible in the citation table -- extended from two states to
    # three by issue #577: carried, this paper's (b) inference, and this
    # paper's (c) verdict (none of the latter here, so only the first two
    # are asserted; the third is pinned in test_a_new_c_claim_reaches_a_verdict).
    assert "(carried)" in first and "(this paper's inference)" in first
    # Engine telemetry belongs to examine, never to the reader's paper (§0).
    assert "usage_ratio" not in first


def test_the_record_and_the_paper_are_persisted_side_by_side(tmp_path, analyses_dir, lenses_dir):
    record, _ = _run(tmp_path, analyses_dir, lenses_dir)
    papers = tmp_path / "papers"
    assert (papers / "pb-test.json").is_file()
    assert (papers / "pb-test.md").is_file()
    assert record["corpus_pin"] == PIN
    assert record["lens"] == "state-formation"
    assert record["source_lenses"] == {"brief-a": "state-formation", "brief-b": "state-formation"}


def test_the_no_phase_b_import_guarantee_still_holds():
    """Phase C never runs Phase B (§3 non-goal 1) -- relocated here from the
    deleted `test_paper_opposition.py` (issue #577 riders): this guarantee is
    about the whole `axial.paper` package, not about the opposition pass that
    file was named for, and it must survive that file's deletion.

    Runs in a CLEAN interpreter, and has to. `sys.modules` is process-wide, so
    an in-process version of this test asserts about whatever the same worker
    imported before it: any test that touches `axial.cli` -- which wires every
    Phase-B subcommand at module load -- makes it fail without Phase C having
    imported anything. Under `-n auto` that is decided by which worker gets
    which file, so the guarantee would pass or fail by luck. A structural
    guarantee that flakes gets marked xfail and then deleted."""
    probe = (
        "import sys, json\n"
        "import axial.paper.record\n"
        "print(json.dumps(sorted(\n"
        "    name for name in sys.modules\n"
        "    if name.startswith(('axial.answer', 'axial.analyze', 'axial.brief'))\n"
        ")))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert json.loads(completed.stdout) == []
