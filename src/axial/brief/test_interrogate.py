"""Inner unit tests for the brief-interrogation pre-pass (issue #252,
specs/PHASE-B.md §7.2). Co-located under src/axial/brief/ per the repo's
existing test layout (mirrors src/axial/brief/test_intake.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from axial.brief.intake import Brief
from axial.brief.interrogate import (
    InterrogationFailedError,
    InterrogationParseError,
    InvalidAssessmentError,
    PremiseAssessment,
    compose_prompt,
    disposition_for,
    interrogate,
    parse_interrogation_response,
    persist_interrogation,
    render_coverage_section,
)
from axial.llm import INTERROGATE_PASS_NAME
from axial.model_json import ModelJsonError


def _brief(case: str = "Syria", request: str = "How did local order change?") -> Brief:
    return Brief(brief_id="deadbeefcafef00d", case=case, request=request, lens=None)


# -- parsing ------------------------------------------------------------------


def test_parse_well_formed_response_returns_all_three_fields():
    raw = json.dumps(
        {
            "premises_found": [
                {"premise": "Tunisia is well covered", "assessment": "contradicts"},
                {"premise": "Syria has coverage", "assessment": "supports"},
            ],
            "bounds_applied": ["covers Syria, not the wider region"],
            "refusal": None,
            "disposition": "proceed_bounded",  # must be ignored by the parser
        }
    )
    premises_found, bounds_applied, refusal = parse_interrogation_response(raw)

    assert premises_found == [
        PremiseAssessment(premise="Tunisia is well covered", assessment="contradicts"),
        PremiseAssessment(premise="Syria has coverage", assessment="supports"),
    ]
    assert bounds_applied == ["covers Syria, not the wider region"]
    assert refusal is None


def test_parse_well_formed_refusal():
    raw = json.dumps(
        {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": {"reason": "the corpus holds nothing on this polity"},
        }
    )
    premises_found, bounds_applied, refusal = parse_interrogation_response(raw)
    assert premises_found == []
    assert bounds_applied == []
    assert refusal == {"reason": "the corpus holds nothing on this polity"}


def test_parse_rejects_out_of_vocabulary_assessment():
    raw = json.dumps(
        {
            "premises_found": [{"premise": "some premise", "assessment": "probably-true"}],
            "bounds_applied": [],
            "refusal": None,
        }
    )
    with pytest.raises(InvalidAssessmentError):
        parse_interrogation_response(raw)


def test_parse_malformed_json_raises_named_error_not_silent_proceed():
    with pytest.raises(ModelJsonError):
        parse_interrogation_response("not json at all {{{")


def test_parse_rejects_non_object_top_level():
    with pytest.raises(InterrogationParseError):
        parse_interrogation_response(json.dumps(["premises_found"]))


def test_parse_rejects_non_list_premises_found():
    raw = json.dumps({"premises_found": "not a list", "bounds_applied": [], "refusal": None})
    with pytest.raises(InterrogationParseError):
        parse_interrogation_response(raw)


# -- disposition rule -----------------------------------------------------


@pytest.mark.parametrize(
    "premises, bounds, refusal, expected",
    [
        pytest.param([], [], None, "proceed", id="nothing-found"),
        pytest.param([PremiseAssessment("p", "supports")], [], None, "proceed", id="only-supports"),
        pytest.param([PremiseAssessment("p", "silent")], [], None, "proceed", id="only-silent"),
        pytest.param(
            [PremiseAssessment("p", "contradicts")],
            [],
            None,
            "proceed_bounded",
            id="a-contradiction",
        ),
        pytest.param(
            [], ["covers X, not Y"], None, "proceed_bounded", id="a-stated-bound-no-contradiction"
        ),
        pytest.param(
            [PremiseAssessment("p", "supports")],
            [],
            {"reason": "cannot answer as posed"},
            "refuse",
            id="refusal-wins-even-with-only-supports",
        ),
        pytest.param(
            [PremiseAssessment("p", "contradicts")],
            ["covers X, not Y"],
            {"reason": "cannot answer as posed"},
            "refuse",
            id="refusal-wins-over-everything",
        ),
    ],
)
def test_disposition_for_is_total_and_table_driven(premises, bounds, refusal, expected):
    assert disposition_for(premises, bounds, refusal) == expected


def test_disposition_for_ignores_any_model_supplied_disposition():
    """The wrapper decides, the model does not (issue #252's ratified rule):
    a response with empty premises_found, empty bounds_applied, and a null
    refusal must resolve to "proceed" regardless of what the model itself
    wrote under the (parsed-then-discarded) `disposition` key."""
    raw = json.dumps(
        {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None,
            "disposition": "refuse",  # the model's own claim -- must be discarded
        }
    )
    premises_found, bounds_applied, refusal = parse_interrogation_response(raw)
    assert disposition_for(premises_found, bounds_applied, refusal) == "proceed"


# -- coverage lookup --------------------------------------------------------


def test_render_coverage_section_renders_every_real_polity_coverage_count_names():
    """`render_coverage_section` shows `coverage_count()`'s own real key
    set in full -- no free-text guessing at which polities a premise
    names, so a polity's real (possibly large) count is never overwritten
    by a fabricated one."""
    section = render_coverage_section({"Tunisia": 200, "Freedonia": 3})
    assert "Tunisia: 200 chunks" in section
    assert "Freedonia: 3 chunks" in section


def test_render_coverage_section_never_fabricates_a_row_for_an_unnamed_polity():
    """Regression (root-caused 2026-07-23): a place absent from `counts`
    must never get a synthesized row -- the earlier design injected the
    brief's raw `case` string at count 0, which fired as a false "zero
    coverage" signal on almost every real brief because a `case` usually
    bundles a place with a date range the coverage table has no way to
    speak to. `render_coverage_section` now takes only `counts` and
    renders exactly its real keys, nothing else."""
    section = render_coverage_section({"Syria": 2653})
    assert "Syria: 2653 chunks" in section
    assert "Tunisia" not in section
    assert section.count("\n") == 0  # exactly one line: no synthesized second row


def test_compose_prompt_carries_real_coverage_counts_not_a_fabricated_one():
    """The regression this test locks (issue #252 review): an adjectival/
    merged free-text guess ("Does Tunisia", "Egyptian") must never stand in
    for the corpus's real count -- the prompt must carry
    `coverage_counts`' own real value for a polity the corpus DOES cover,
    even though the request phrases it awkwardly ("Does Tunisia's ...")."""
    brief = _brief(
        case="Syria",
        request="Does Tunisia's transition follow the same broad sequence as Syria's?",
    )
    prompt = compose_prompt(brief, {"Tunisia": 200, "Syria": 7})
    assert "Tunisia: 200 chunks" in prompt
    assert "Syria: 7 chunks" in prompt
    # The request text itself legitimately contains "Does Tunisia" (verbatim
    # quoted above) -- the regression this guards is a fabricated COVERAGE
    # LINE keyed on that merged phrase, not the phrase's mere presence.
    assert "Does Tunisia:" not in prompt


def test_compose_prompt_never_fabricates_a_row_for_a_date_qualified_case():
    """Regression for the false-refusal bug root-caused 2026-07-23: a real
    `case` bundles a place with a date range ("Syria, 2011-2024"); that
    full string must never appear as its own fabricated coverage-table row
    at count 0 next to the real "Syria: 2653" row, and the prompt must
    instead tell the model the table is place-only with no time dimension
    so it maps the case's place name onto the real row itself."""
    brief = _brief(
        case="Syria, 2011-2024",
        request="How did local order change over the course of the conflict?",
    )
    counts = {"Syria": 2653, "Tunisia": 41}
    prompt = compose_prompt(brief, counts)

    assert "Syria: 2653 chunks" in prompt
    assert "Syria, 2011-2024: 0 chunks" not in prompt
    assert "Syria, 2011-2024:" not in prompt
    assert "no time" in prompt.lower() or "no time/period" in prompt.lower()


# -- pass registration ------------------------------------------------------


def test_interrogate_call_uses_the_registered_pass_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The pass identifies itself with INTERROGATE_PASS_NAME so
    model_by_pass / reasoning_by_pass / votes_by_pass can route it (§7.11)."""
    _write_minimal_vault(tmp_path)
    seen_pass_names = []

    class _RecordingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            seen_pass_names.append(pass_name)
            return json.dumps({"premises_found": [], "bounds_applied": [], "refusal": None})

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "recording"

    interrogate(_brief(), client=_RecordingClient(), vault_dir=tmp_path / "vault")

    assert seen_pass_names == [INTERROGATE_PASS_NAME]


# -- malformed model JSON is a clean, named failure --------------------------


def test_interrogate_wraps_persistent_malformed_json_as_named_error(
    tmp_path: Path,
):
    _write_minimal_vault(tmp_path)

    class _AlwaysBrokenClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            return "not json, ever {{{"

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "broken"

    with pytest.raises(InterrogationFailedError):
        interrogate(_brief(), client=_AlwaysBrokenClient(), vault_dir=tmp_path / "vault")


def test_interrogate_rejects_invalid_assessment_without_silently_proceeding(
    tmp_path: Path,
):
    _write_minimal_vault(tmp_path)

    class _BadAssessmentClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            return json.dumps(
                {
                    "premises_found": [{"premise": "p", "assessment": "maybe"}],
                    "bounds_applied": [],
                    "refusal": None,
                }
            )

        def model_for_pass(self, pass_name: str | None = None) -> str:
            return "bad"

    with pytest.raises(InvalidAssessmentError):
        interrogate(_brief(), client=_BadAssessmentClient(), vault_dir=tmp_path / "vault")


# -- persistence --------------------------------------------------------------


def test_persist_interrogation_writes_keyed_on_brief_id(tmp_path: Path):
    from axial.brief.interrogate import InterrogationResult

    brief = _brief()
    result = InterrogationResult(
        premises_found=[PremiseAssessment("p", "contradicts")],
        bounds_applied=["covers X, not Y"],
        refusal=None,
        disposition="proceed_bounded",
    )
    analyses_dir = tmp_path / "analyses"
    path = persist_interrogation(brief, result, analyses_dir=analyses_dir)

    assert path == analyses_dir / f"{brief.brief_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["brief_id"] == brief.brief_id
    assert payload["interrogation"]["disposition"] == "proceed_bounded"
    assert payload["interrogation"]["premises_found"] == [
        {"premise": "p", "assessment": "contradicts"}
    ]


# -- fixture helper -----------------------------------------------------------


def _write_minimal_vault(tmp_path: Path) -> None:
    prose_dir = tmp_path / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": "bfix_001_a",
        "section": "A Section",
        "chunk_text": "Some fixture chunk text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / "bfix_001_a.md").write_text(text, encoding="utf-8")
