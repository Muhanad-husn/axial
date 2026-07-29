"""Outer acceptance test for issue #254, slice 02 of the retrieval-loop
subproject (Phase B, sub:analysis-v0): planning from the interrogation
result + case anchor, and re-query on thin.

Locked behavioral contract -- do not edit once committed red/green without a
one-line justification in the PR body.

> **The scripted tool names moved** (issue #487, D1/D5): `query_by_tag` and
> `query_by_polity` are deleted with the facets they filtered, so the
> scenarios below script surviving tools instead. What they pin -- broaden on
> thin, the thin signal reaching the model, and no case-scope fence on
> assembly -- is unchanged. Scenario 2's cross-case material is identified by
> the source it comes from rather than by a `polities_touched` filter, which
> no longer exists.

Given a fixture vault where query_by_source{source_id: <an absent source>}
      returns 0 chunk ids
  And a brief with case "Syria" and an interrogation result whose
      bounds_applied names the thin coverage
  And a scripted model that broadens to a real query_by_source when it is
      handed a result with result_count 0
When  the retrieval loop runs with a thin-result floor of 3
Then  the trajectory log has at least 2 entries
  And entry 1 is the narrow call with result_count 0
  And entry 2 is the broadened query, and its result_ids are non-empty
  And the recorded prompt for step 2 carries the step-1 result_count, so the
      model re-queried on the thin signal rather than by luck

Given a brief whose case is "Syria"
  And a fixture vault whose chunks include material about "Egypt" that bears
      on the request
When  the retrieval loop runs and retrieves that material
Then  the assembled evidence set contains that cross-case chunk id
  And it is not filtered out by any case-scope rule

Given the same brief and the interrogation result from brief-interrogation
When  the retrieval loop runs
Then  the recorded prompt for step 1 contains the brief's `case` and the
      interrogation result's premises_found and bounds_applied -- retrieval
      is planned from them, not from the raw request alone

See specs/PHASE-B.md §4 (the agentic loop re-queries on thin, [FIRM]), §7.2
(the interrogation result), §7.5/§7.6 (the vault query API / trajectory
log), and charter §3 (case-as-anchor, not case-as-fence) for the source of
truth, and plans/retrieval-loop/02-planning-anchor-and-requery.md for this
slice's own acceptance criterion (identical Gherkin).

Seam decisions
--------------
Library calls, not a CLI subprocess -- same seam as
tests/analysis/test_retrieval_loop_skeleton.py (slice 01): a `Brief` and an
`InterrogationResult` are constructed directly in-process (no brief file, no
real interrogation model call -- those are already covered by their own
slices' acceptance tests), and `axial.llm.RecordLLMClient` observes the
assembled prompt exactly like tests/analysis/test_brief_interrogation.py's
subprocess `record` provider does, but constructed directly since this test
never shells out. The scripted tool-call channel (`AXIAL_STUB_TOOL_CALLS`)
is the same mechanism slice 01 already established; `RecordLLMClient`
delegates to the identical scripted dispatch `StubLLMClient` uses (see
`axial.llm._scripted_tool_call_for`'s own docstring), so the model is
deterministic while its assembled prompt stays observable.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, PremiseAssessment, disposition_for
from axial.llm import STUB_TOOL_CALLS_ENV_VAR, RecordLLMClient
from axial.retrieve.loop import run_planned_retrieval

SYRIA_SOURCE_ID = "rpfix-syria"
EGYPT_SOURCE_ID = "rpfix-egypt"
FREEDONIA_SOURCE_ID = "rpfix-freedonia"
ABSENT_SOURCE_ID = "rpfix-nowhere"

SYRIA_CHUNK_ID = f"{SYRIA_SOURCE_ID}_1_syria_001"
EGYPT_CHUNK_ID = f"{EGYPT_SOURCE_ID}_1_egypt_001"
FREEDONIA_CHUNK_ID = f"{FREEDONIA_SOURCE_ID}_1_state-formation_001"


def _chunk_frontmatter(
    *,
    chunk_id: str,
    field_primary: str,
    polity: str,
    polities_touched: list[str],
) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": field_primary, "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": polity},
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


def _write_fixture_vault(root: Path) -> Path:
    """Three synthetic prose notes, one per source: a Freedonia source, a
    Syria source (what the broadened `query_by_source` finds), and an Egypt
    source -- cross-case material bearing on a state-formation request that a
    case-scope fence would wrongly exclude. `ABSENT_SOURCE_ID` matches no note
    at all, which is the narrow query that comes back thin."""
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    notes = [
        _chunk_frontmatter(
            chunk_id=FREEDONIA_CHUNK_ID,
            field_primary="state-formation",
            polity="Freedonia",
            polities_touched=["Freedonia"],
        ),
        _chunk_frontmatter(
            chunk_id=SYRIA_CHUNK_ID,
            field_primary="ideology",
            polity="Syria",
            polities_touched=["Syria"],
        ),
        _chunk_frontmatter(
            chunk_id=EGYPT_CHUNK_ID,
            field_primary="state-formation",
            polity="Egypt",
            polities_touched=["Egypt"],
        ),
    ]
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")

    return prose_dir.parent


@pytest.fixture
def fixture_vault_dir(tmp_path: Path) -> Path:
    return _write_fixture_vault(tmp_path / "fixture")


def _brief() -> Brief:
    return Brief(
        brief_id="test-brief-id",
        case="Syria",
        request="What explains state-formation outcomes across comparable cases?",
        lens=None,
    )


def _bounded_interrogation_result() -> InterrogationResult:
    """A `proceed_bounded` result whose `bounds_applied` names the corpus's
    thin coverage -- the §7.2 signal the retrieval plan carries forward."""
    premises_found = [
        PremiseAssessment(
            premise="The brief assumes dense Syria-specific coverage.",
            assessment="contradicts",
        )
    ]
    bounds_applied = ["Corpus coverage of Syria under this filter is thin."]
    disposition = disposition_for(premises_found, bounds_applied, refusal=None)
    return InterrogationResult(
        premises_found=premises_found,
        bounds_applied=bounds_applied,
        refusal=None,
        disposition=disposition,
    )


def _set_scripted_tool_calls(
    monkeypatch: pytest.MonkeyPatch, calls: list[dict[str, Any] | None]
) -> None:
    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, json.dumps(calls))


def _record_client(tmp_path: Path) -> tuple[RecordLLMClient, Path]:
    record_path = tmp_path / "record.jsonl"
    return RecordLLMClient(record_path), record_path


def _read_recorded_prompts(record_path: Path) -> list[str]:
    lines = record_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_thin_first_result_triggers_broadened_requery_recorded_on_the_signal(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 1: a narrow query returning 0 ids is followed by a broadened
    one, both entries land in the trajectory, and the step-2 recorded prompt
    carries the step-1 result_count."""
    _set_scripted_tool_calls(
        monkeypatch,
        [
            {"tool": "query_by_source", "args": {"source_id": ABSENT_SOURCE_ID}},
            {"tool": "query_by_source", "args": {"source_id": SYRIA_SOURCE_ID}},
            None,
        ],
    )
    client, record_path = _record_client(tmp_path)
    brief = _brief()
    interrogation_result = _bounded_interrogation_result()

    result = run_planned_retrieval(
        client,
        brief,
        interrogation_result,
        vault_dir=fixture_vault_dir,
        step_budget=10,
        thin_result_floor=3,
    )

    assert len(result.trajectory) >= 2, (
        f"expected >=2 trajectory entries, got {result.trajectory!r}"
    )

    entry_1 = result.trajectory[0]
    assert entry_1["tool"] == "query_by_source"
    assert entry_1["result_count"] == 0
    assert entry_1["result_ids"] == []

    entry_2 = result.trajectory[1]
    assert entry_2["tool"] == "query_by_source"
    assert entry_2["result_ids"] != []
    assert entry_2["result_count"] == len(entry_2["result_ids"])

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) >= 2
    step_2_prompt = prompts[1]
    assert "result_count=0" in step_2_prompt or "result_count': 0" in step_2_prompt, (
        f"step 2's recorded prompt must carry step 1's result_count so the "
        f"model re-queried on the thin signal, got {step_2_prompt!r}"
    )


def test_cross_polity_evidence_survives_assembly_uncensored_by_case_scope(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 2: the agent retrieves the Egypt source (not the case anchor
    "Syria"), and the assembled evidence set keeps that cross-case chunk --
    no case-scope filter strips it."""
    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "query_by_source", "args": {"source_id": EGYPT_SOURCE_ID}}, None],
    )
    client, _record_path = _record_client(tmp_path)
    brief = _brief()
    interrogation_result = _bounded_interrogation_result()

    result = run_planned_retrieval(
        client,
        brief,
        interrogation_result,
        vault_dir=fixture_vault_dir,
        step_budget=10,
        thin_result_floor=3,
    )

    cross_case_calls = [
        entry
        for entry in result.trajectory
        if EGYPT_CHUNK_ID in entry["result_ids"] and brief.case not in str(entry["args"])
    ]
    assert cross_case_calls, (
        f"expected a call reaching material outside the case anchor "
        f"{brief.case!r}, got {result.trajectory!r}"
    )

    assert EGYPT_CHUNK_ID in result.evidence_ids, (
        f"expected the cross-case chunk {EGYPT_CHUNK_ID!r} in the assembled "
        f"evidence set, got {result.evidence_ids!r}"
    )


def test_planning_prompt_for_step_1_carries_case_premises_and_bounds(
    fixture_vault_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Scenario 3: the recorded prompt for step 1 contains the brief's
    `case` and the interrogation result's `premises_found`/`bounds_applied`
    -- retrieval is planned from them, not the raw request alone."""
    _set_scripted_tool_calls(
        monkeypatch,
        [{"tool": "query_by_source", "args": {"source_id": SYRIA_SOURCE_ID}}, None],
    )
    client, record_path = _record_client(tmp_path)
    brief = _brief()
    interrogation_result = _bounded_interrogation_result()

    run_planned_retrieval(
        client,
        brief,
        interrogation_result,
        vault_dir=fixture_vault_dir,
        step_budget=10,
        thin_result_floor=3,
    )

    prompts = _read_recorded_prompts(record_path)
    assert len(prompts) >= 1
    step_1_prompt = prompts[0]

    assert brief.case in step_1_prompt
    for premise in interrogation_result.premises_found:
        assert premise.premise in step_1_prompt
    for bound in interrogation_result.bounds_applied:
        assert bound in step_1_prompt
