"""Inner unit tests for issue #649: `assemble_evidence_ids` gains an
optional `fork_constraint` argument -- the intake fork-check's compiled
answer (`axial.brief.fork.ForkConstraint`) biting evidence assembly at the
same site `weights` (issue #639) already does.

**The headline test here is the same shape #639's own test file uses**:
with no `fork_constraint`, every existing caller (and every existing test)
is unaffected -- see `test_round_robin_weights.py`'s own docstring for the
same trap this mirrors."""

from __future__ import annotations

from typing import Any

from axial.brief.fork import ForkConstraint
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult
from axial.retrieve.loop import assemble_evidence_ids, compose_retrieval_prompt


def _entry(tool: str, result_ids: list[str]) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": tool,
        "args": {},
        "result_ids": result_ids,
        "result_count": len(result_ids),
    }


def test_no_fork_constraint_is_unaffected():
    trajectory = [_entry("get_name", ["aaa_1_a_001", "bbb_1_a_001"])]
    assert assemble_evidence_ids(trajectory) == assemble_evidence_ids(trajectory, None, None)


def test_drop_source_ids_removes_every_id_from_that_source():
    trajectory = [
        _entry("get_name", ["aaa_1_a_001", "aaa_1_a_002", "bbb_1_a_001"]),
    ]
    constraint = ForkConstraint(drop_source_ids=frozenset({"aaa"}))

    result = assemble_evidence_ids(trajectory, fork_constraint=constraint)

    assert result == ["bbb_1_a_001"]


def test_per_source_cap_limits_how_many_ids_one_source_contributes():
    trajectory = [
        _entry("get_name", ["aaa_1_a_001", "aaa_1_a_002", "aaa_1_a_003", "bbb_1_a_001"]),
    ]
    constraint = ForkConstraint(per_source_cap=1)

    result = assemble_evidence_ids(trajectory, fork_constraint=constraint)

    assert result == ["aaa_1_a_001", "bbb_1_a_001"]


def test_drop_and_cap_compose_drop_first_then_cap():
    trajectory = [
        _entry(
            "get_name",
            ["aaa_1_a_001", "aaa_1_a_002", "bbb_1_a_001", "bbb_1_a_002", "ccc_1_a_001"],
        ),
    ]
    constraint = ForkConstraint(drop_source_ids=frozenset({"ccc"}), per_source_cap=1)

    result = assemble_evidence_ids(trajectory, fork_constraint=constraint)

    assert result == ["aaa_1_a_001", "bbb_1_a_001"]


def test_a_constraint_with_neither_drop_nor_cap_is_a_no_op():
    trajectory = [_entry("get_name", ["aaa_1_a_001", "bbb_1_a_001"])]
    constraint = ForkConstraint(guidance="just guidance, no filtering")

    assert assemble_evidence_ids(trajectory, fork_constraint=constraint) == assemble_evidence_ids(
        trajectory
    )


def test_compose_retrieval_prompt_carries_no_guidance_block_when_none_given():
    prompt = compose_retrieval_prompt(
        Brief(brief_id="x", case="Syria", request="What changed?"),
        InterrogationResult(
            premises_found=[], bounds_applied=[], refusal=None, disposition="proceed"
        ),
    )
    assert "Analyst guidance" not in prompt


def test_compose_retrieval_prompt_appends_guidance_when_given():
    prompt = compose_retrieval_prompt(
        Brief(brief_id="x", case="Syria", request="What changed?"),
        InterrogationResult(
            premises_found=[], bounds_applied=[], refusal=None, disposition="proceed"
        ),
        guidance="treat the 2021 monograph as background only",
    )
    assert "Analyst guidance" in prompt
    assert "treat the 2021 monograph as background only" in prompt
