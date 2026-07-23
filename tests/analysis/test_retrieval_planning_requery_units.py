"""Inner unit tests for issue #254 slice 02's seeded behaviours
(plans/retrieval-loop/02-planning-anchor-and-requery.md inner-loop
checklist):

- The planning prompt carries the brief `case` and the interrogation
  result's `premises_found`/`bounds_applied`.
- The thin-result predicate (`is_thin_result`): below the configured floor
  is thin, at/above is not; the floor is read from config, not hardcoded.
- A thin result is fed back to the model with its `result_count`.
- A non-thin result does not force a re-query.
- Re-query respects the step budget; a thin result near the budget halts
  cleanly.
- Evidence assembly dedupes chunk ids across calls while the trajectory
  still records every call, including ones that returned only duplicates.
- No case-scope filter strips a chunk whose `polities_touched` excludes the
  case anchor from the assembled evidence set.
- A `refuse` disposition short-circuits: zero tool calls, empty trajectory.

`tests/analysis/test_retrieval_planning_requery.py` covers the 3-scenario
outer acceptance contract; this file covers the properties underneath it,
each in isolation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult, PremiseAssessment
from axial.llm import StubLLMClient
from axial.retrieve.loop import (
    DEFAULT_THIN_RESULT_FLOOR,
    RetrievalResult,
    _resolve_thin_result_floor,
    assemble_evidence_ids,
    compose_retrieval_prompt,
    is_thin_result,
    run_planned_retrieval,
    run_retrieval_loop,
)


class _CapturingScriptedClient:
    """A minimal `LLMClient` double: plays back a fixed sequence of tool
    calls (mirroring `axial.llm.StubLLMClient`'s own per-instance-counter
    script exactly), and also records every prompt it was handed, in call
    order -- so a unit test can assert prompt CONTENT directly, without the
    record-provider/env-var seam the acceptance test uses."""

    def __init__(self, scripted_calls: list[dict[str, Any] | None]):
        self._scripted_calls = scripted_calls
        self.prompts_seen: list[str] = []
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        raise NotImplementedError("the retrieval loop only uses complete_with_tools")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "capturing-test-double"

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        self.prompts_seen.append(prompt)
        index = self.call_count
        self.call_count += 1
        return self._scripted_calls[index % len(self._scripted_calls)]


def _chunk_frontmatter(
    *, chunk_id: str, field_primary: str, polity: str, polities_touched: list[str]
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


def _write_fixture_vault(root: Path, notes: list[dict[str, Any]]) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in notes:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    return prose_dir.parent


def _brief(case: str = "Syria") -> Brief:
    return Brief(brief_id="unit-brief", case=case, request="A request.", lens=None)


def _interrogation_result(
    *, premises_found=None, bounds_applied=None, refusal=None, disposition="proceed_bounded"
) -> InterrogationResult:
    return InterrogationResult(
        premises_found=premises_found or [],
        bounds_applied=bounds_applied or [],
        refusal=refusal,
        disposition=disposition,
    )


# --- planning prompt carries case/premises_found/bounds_applied ------------


def test_compose_retrieval_prompt_carries_case_premises_and_bounds():
    brief = _brief(case="Syria")
    interrogation_result = _interrogation_result(
        premises_found=[
            PremiseAssessment(premise="A smuggled premise about Syria.", assessment="contradicts")
        ],
        bounds_applied=["Covers state-formation, not economic policy."],
    )

    prompt = compose_retrieval_prompt(brief, interrogation_result)

    assert "Syria" in prompt
    assert "A smuggled premise about Syria." in prompt
    assert "Covers state-formation, not economic policy." in prompt


# --- thin-result predicate: below floor is thin, at/above is not -----------


def test_is_thin_result_below_floor_is_thin():
    assert is_thin_result(0, 3) is True
    assert is_thin_result(2, 3) is True


def test_is_thin_result_at_or_above_floor_is_not_thin():
    assert is_thin_result(3, 3) is False
    assert is_thin_result(4, 3) is False


def test_thin_result_floor_reads_from_config(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"retrieve": {"thin_result_floor": 7}}))

    assert _resolve_thin_result_floor(config_path) == 7


def test_thin_result_floor_falls_back_to_default_when_config_absent(tmp_path: Path):
    missing_path = tmp_path / "does-not-exist.yaml"

    assert _resolve_thin_result_floor(missing_path) == DEFAULT_THIN_RESULT_FLOOR


# --- thin result fed back with its result_count; non-thin does not force ---


@pytest.fixture
def one_chunk_vault(tmp_path: Path) -> Path:
    note = _chunk_frontmatter(
        chunk_id="unitfix_001_a",
        field_primary="state-formation",
        polity="Syria",
        polities_touched=["Syria"],
    )
    return _write_fixture_vault(tmp_path / "one", [note])


def test_thin_result_is_fed_back_to_model_with_its_result_count(one_chunk_vault: Path):
    client = _CapturingScriptedClient(
        [
            {"tool": "query_by_polity", "args": {"polity": "Freedonia"}},  # matches nothing: thin
            None,
        ]
    )

    run_retrieval_loop(
        client, "seed prompt", vault_dir=one_chunk_vault, step_budget=5, thin_result_floor=3
    )

    assert len(client.prompts_seen) == 2
    assert "result_count=0" in client.prompts_seen[1]


def test_non_thin_result_does_not_force_a_requery(one_chunk_vault: Path):
    client = _CapturingScriptedClient(
        [{"tool": "query_by_polity", "args": {"polity": "Syria"}}, None]
    )

    trajectory = run_retrieval_loop(
        client, "seed prompt", vault_dir=one_chunk_vault, step_budget=5, thin_result_floor=1
    )

    # result_count (1) is at the floor (1), so it's not thin -- the loop
    # asks the model again (as always), and its own next scripted answer
    # (None) is free to stop the loop right there rather than being FORCED
    # to re-query: no thin marker appears in the feedback it was handed.
    assert len(trajectory) == 1
    assert trajectory[0]["result_count"] == 1
    assert "THIN" not in client.prompts_seen[-1]
    assert "result_count=" not in client.prompts_seen[-1]


# --- re-query respects the step budget: thin near the budget halts clean ---


def test_requery_respects_step_budget_thin_result_halts_cleanly_at_budget(one_chunk_vault: Path):
    client = _CapturingScriptedClient(
        [{"tool": "query_by_polity", "args": {"polity": "Nowhereland"}}]  # always thin, never stops
    )

    trajectory = run_retrieval_loop(
        client, "seed prompt", vault_dir=one_chunk_vault, step_budget=2, thin_result_floor=3
    )

    assert len(trajectory) == 2
    assert [entry["step"] for entry in trajectory] == [1, 2]


# --- evidence assembly dedupes while the trajectory keeps every call -------


def test_evidence_assembly_dedupes_across_calls_trajectory_keeps_every_call(tmp_path: Path):
    shared = _chunk_frontmatter(
        chunk_id="unitfix_shared",
        field_primary="state-formation",
        polity="Syria",
        polities_touched=["Syria"],
    )
    vault_dir = _write_fixture_vault(tmp_path / "dup", [shared])

    client = _CapturingScriptedClient(
        [
            {"tool": "query_by_polity", "args": {"polity": "Syria"}},
            {"tool": "query_by_polity", "args": {"polity": "Syria"}},  # same id again: a duplicate
            None,
        ]
    )

    trajectory = run_retrieval_loop(client, "seed prompt", vault_dir=vault_dir, step_budget=5)

    assert len(trajectory) == 2, (
        "both calls -- including the duplicate-only one -- get their own entry"
    )
    assert trajectory[0]["result_ids"] == ["unitfix_shared"]
    assert trajectory[1]["result_ids"] == ["unitfix_shared"]

    evidence_ids = assemble_evidence_ids(trajectory)
    assert evidence_ids == ["unitfix_shared"], "the assembled evidence set dedupes the repeated id"


# --- no case-scope filter on the assembled evidence set ---------------------


def test_no_case_scope_filter_chunk_outside_case_anchor_survives_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    egypt_chunk = _chunk_frontmatter(
        chunk_id="unitfix_egypt",
        field_primary="state-formation",
        polity="Egypt",
        polities_touched=["Egypt"],
    )
    vault_dir = _write_fixture_vault(tmp_path / "cross", [egypt_chunk])

    monkeypatch.setenv(
        "AXIAL_STUB_TOOL_CALLS",
        json.dumps([{"tool": "query_by_polity", "args": {"polity": "Egypt"}}, None]),
    )
    client = StubLLMClient()
    brief = _brief(case="Syria")
    interrogation_result = _interrogation_result()

    result: RetrievalResult = run_planned_retrieval(
        client, brief, interrogation_result, vault_dir=vault_dir, step_budget=5
    )

    assert "unitfix_egypt" in result.evidence_ids


# --- refuse short-circuits: zero tool calls, empty trajectory --------------


def test_refuse_disposition_short_circuits_zero_calls_empty_trajectory(tmp_path: Path):
    note = _chunk_frontmatter(
        chunk_id="unitfix_refused",
        field_primary="state-formation",
        polity="Syria",
        polities_touched=["Syria"],
    )
    vault_dir = _write_fixture_vault(tmp_path / "refused", [note])

    client = StubLLMClient()
    brief = _brief(case="Syria")
    interrogation_result = _interrogation_result(
        refusal={"reason": "no coverage"}, disposition="refuse"
    )

    result = run_planned_retrieval(
        client, brief, interrogation_result, vault_dir=vault_dir, step_budget=5
    )

    assert result.trajectory == []
    assert result.evidence_ids == []
    assert client.call_count == 0, "a refuse disposition must make zero model/tool calls"
