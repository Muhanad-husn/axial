"""Inner unit tests for the intake fork-check (issue #649, specs/PHASE-B.md
§7, DEC-62). Co-located under src/axial/brief/ per the repo's existing test
layout (mirrors src/axial/brief/test_interrogate.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.brief.fork import (
    ConceptMeasurement,
    ForkAnswer,
    ForkCheckParseError,
    ForkCheckResult,
    ForkConstraint,
    ForkOption,
    QuestionMeasurement,
    assess_fork,
    compile_constraint,
    compose_fork_prompt,
    describe_effect,
    measure_question,
    parse_fork_response,
)
from axial.brief.intake import Brief
from axial.llm import FORK_CHECK_PASS_NAME
from axial.query import store as note_store

SOURCE_A = "alpha-2005-aaaaaaaaaaaa"
SOURCE_B = "beta-2019-bbbbbbbbbbbb"


def _write_fixture_store(vault_dir: Path) -> None:
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=[
            (SOURCE_A, "A. Author", "A Title", "2005", 2005),
            (SOURCE_B, "B. Author", "B Title", "2019", 2019),
        ],
        notes=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Introduction", None, "claim one", None),
            (f"{SOURCE_A}_001_intro_002", SOURCE_A, "Introduction", None, "claim two", None),
            (f"{SOURCE_B}_000_intro_001", SOURCE_B, "Introduction", None, "claim three", None),
        ],
        names=[("Syria", "place", "syria")],
        note_names=[
            (f"{SOURCE_A}_000_intro_001", SOURCE_A, "Syria", "place"),
            (f"{SOURCE_A}_001_intro_002", SOURCE_A, "Syria", "place"),
            (f"{SOURCE_B}_000_intro_001", SOURCE_B, "Syria", "place"),
        ],
        note_arguing_against=[],
        note_citations=[],
    )


def _brief(case: str = "Syria", request: str = "Coverage of Syria") -> Brief:
    return Brief(brief_id="deadbeefcafef00d", case=case, request=request)


def _measurement() -> QuestionMeasurement:
    sources = (
        note_store.SourceShare(SOURCE_A, "A. Author", 2005, 2),
        note_store.SourceShare(SOURCE_B, "B. Author", 2019, 1),
    )
    concept = ConceptMeasurement(
        canonical="Syria",
        matched_on="Syria",
        note_count=3,
        source_count=2,
        sources=sources,
        top_share=2 / 3,
    )
    return QuestionMeasurement(concepts=(concept,), silent_terms=())


# --- measurement -------------------------------------------------------------


def test_measure_question_reports_source_breakdown_and_silence(tmp_path: Path):
    vault = tmp_path / "vault"
    _write_fixture_store(vault)

    measurement = measure_question(_brief(), vault_dir=vault)

    assert [c.canonical for c in measurement.concepts] == ["Syria"]
    concept = measurement.concepts[0]
    assert concept.note_count == 3
    assert concept.source_count == 2
    assert concept.top_share == pytest.approx(2 / 3)
    assert [s.source_id for s in concept.sources] == [SOURCE_A, SOURCE_B]
    assert "Coverage" in measurement.silent_terms


def test_measure_question_is_empty_when_the_vault_has_no_store(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)

    measurement = measure_question(_brief(), vault_dir=vault)

    assert measurement == QuestionMeasurement()


# --- assess_fork: zero-model-call gate ----------------------------------------


def test_assess_fork_skips_the_model_call_when_nothing_was_measured(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)

    class _ExplodingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise AssertionError("no model call should be made when nothing was measured")

    result = assess_fork(_brief(), client=_ExplodingClient(), vault_dir=vault)

    assert result == ForkCheckResult(is_fork=False, measured=False)


def test_assess_fork_calls_the_model_under_its_own_registered_pass_name(tmp_path: Path):
    vault = tmp_path / "vault"
    _write_fixture_store(vault)
    seen_pass_names: list[str | None] = []

    class _RecordingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            seen_pass_names.append(pass_name)
            return json.dumps({"is_fork": False})

    result = assess_fork(_brief(), client=_RecordingClient(), vault_dir=vault)

    assert result == ForkCheckResult(is_fork=False, measured=True)
    assert seen_pass_names == [FORK_CHECK_PASS_NAME]


# --- compose_fork_prompt -------------------------------------------------------


def test_compose_fork_prompt_names_the_measured_concept_and_dec_62():
    prompt = compose_fork_prompt(_brief(), _measurement(), question_scope=None)

    assert "Syria" in prompt
    assert "DEC-62" in prompt
    assert "no fork found" in prompt.lower()


def test_compose_fork_prompt_states_the_absence_when_nothing_was_measured():
    prompt = compose_fork_prompt(_brief(), QuestionMeasurement(), question_scope=None)

    assert "no concept in this question resolved" in prompt


# --- parse_fork_response: the deterministic wrapper ---------------------------


def test_parse_fork_response_false_short_circuits_regardless_of_other_fields():
    raw = json.dumps({"is_fork": False, "concept": "Syria", "question": "should be ignored"})

    result = parse_fork_response(raw, _measurement())

    assert result == ForkCheckResult(is_fork=False)


def test_parse_fork_response_true_parses_options():
    raw = json.dumps(
        {
            "is_fork": True,
            "concept": "Syria",
            "kind": "source_imbalance",
            "question": "78% of this is one source -- background only, or full voices?",
            "options": [
                {
                    "label": "background only",
                    "drop_source_ids": [],
                    "per_source_cap": 1,
                    "guidance": "treat as background",
                },
                {
                    "label": "full voices",
                    "drop_source_ids": [],
                    "per_source_cap": None,
                    "guidance": "read as equal",
                },
            ],
        }
    )

    result = parse_fork_response(raw, _measurement())

    assert result.is_fork is True
    assert result.concept == "Syria"
    assert result.kind == "source_imbalance"
    assert len(result.options) == 2
    assert result.options[0].per_source_cap == 1


def test_parse_fork_response_rejects_a_concept_the_measurement_does_not_carry():
    raw = json.dumps(
        {"is_fork": True, "concept": "Nobody Home", "question": "q", "options": [{"label": "x"}]}
    )

    with pytest.raises(ForkCheckParseError):
        parse_fork_response(raw, _measurement())


def test_parse_fork_response_rejects_a_drop_source_id_not_in_the_measurement():
    raw = json.dumps(
        {
            "is_fork": True,
            "concept": "Syria",
            "question": "q",
            "options": [{"label": "x", "drop_source_ids": ["not-a-real-source"]}],
        }
    )

    with pytest.raises(ForkCheckParseError):
        parse_fork_response(raw, _measurement())


def test_parse_fork_response_rejects_an_out_of_vocabulary_kind():
    raw = json.dumps(
        {
            "is_fork": True,
            "concept": "Syria",
            "kind": "made_up",
            "question": "q",
            "options": [{"label": "x"}],
        }
    )

    with pytest.raises(ForkCheckParseError):
        parse_fork_response(raw, _measurement())


def test_parse_fork_response_rejects_a_fork_with_no_options():
    raw = json.dumps({"is_fork": True, "concept": "Syria", "question": "q", "options": []})

    with pytest.raises(ForkCheckParseError):
        parse_fork_response(raw, _measurement())


# --- compile_constraint: pure and deterministic --------------------------------


def _fork_with_options() -> ForkCheckResult:
    return ForkCheckResult(
        is_fork=True,
        concept="Syria",
        kind="source_imbalance",
        question="background only, or full voices?",
        options=(
            ForkOption(
                label="background only", drop_source_ids=(), per_source_cap=1, guidance="cap it"
            ),
            ForkOption(
                label="full voices", drop_source_ids=(), per_source_cap=None, guidance="no cap"
            ),
        ),
    )


def test_compile_constraint_matches_an_option_by_label_case_insensitively():
    constraint = compile_constraint(_fork_with_options(), ForkAnswer(option="Background Only"))

    assert constraint.per_source_cap == 1
    assert constraint.guidance == "cap it"


def test_compile_constraint_with_free_text_only_carries_no_drop_or_cap():
    constraint = compile_constraint(_fork_with_options(), ForkAnswer(free_text="read them all"))

    assert constraint.drop_source_ids == frozenset()
    assert constraint.per_source_cap is None
    assert constraint.guidance == "read them all"


def test_compile_constraint_appends_free_text_to_an_options_own_guidance():
    constraint = compile_constraint(
        _fork_with_options(), ForkAnswer(option="background only", free_text="and note the gap")
    )

    assert constraint.guidance == "cap it\nand note the gap"


def test_compile_constraint_an_unmatched_option_label_falls_back_to_no_constraint():
    constraint = compile_constraint(
        _fork_with_options(), ForkAnswer(option="something else entirely")
    )

    assert constraint == ForkConstraint()


def test_a_temporal_forks_default_option_carries_guidance_alone():
    """DEC-62's own rule (dates assign roles, not cutoffs): a temporal
    fork's default option has no drop_source_ids at all, so compiling it
    produces a constraint that is pure guidance -- no evidence-set
    filtering."""
    fork = ForkCheckResult(
        is_fork=True,
        concept="Syria",
        kind="temporal_role",
        question="pre-2011 sources are rooted older -- read as full voices on the roots?",
        options=(
            ForkOption(
                label="keep both as full voices",
                drop_source_ids=(),
                per_source_cap=None,
                guidance="pre-2011 sources witness the roots; post-2011 witness the war itself",
            ),
        ),
    )
    constraint = compile_constraint(fork, ForkAnswer(option="keep both as full voices"))

    assert constraint.drop_source_ids == frozenset()
    assert constraint.per_source_cap is None
    assert "witness" in constraint.guidance


# --- describe_effect ------------------------------------------------------------


def test_describe_effect_counts_notes_and_sources_before_and_after():
    before = [f"{SOURCE_A}_000_a_001", f"{SOURCE_A}_001_a_002", f"{SOURCE_B}_000_a_001"]
    after = [f"{SOURCE_A}_000_a_001"]

    effect = describe_effect(before, after)

    assert effect == {
        "notes_before": 3,
        "notes_after": 1,
        "sources_before": 2,
        "sources_after": 1,
    }
