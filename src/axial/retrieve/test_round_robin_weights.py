"""Inner unit tests for issue #639: `_round_robin_by_source`/
`assemble_evidence_ids` (`axial.retrieve.loop`) gain an optional
`weights` argument -- how many rotation slots a source earns per pass,
relative to the implicit default of 1.0.

**The headline test here is not "weights work" -- it is "with no weights,
the composed prefix is exactly what it is today"** (issue #639's own
trap): `_pre_639_round_robin` below is a verbatim copy of the function
this issue replaced, kept only as an independent oracle, and every
existing caller of `assemble_evidence_ids`/`_round_robin_by_source` calls
it with no `weights` argument at all, so this file proves the new
implementation reduces to the old one byte for byte before any weight is
ever supplied. The outer, scripted-scenario round-robin acceptance tests
(issue #517 slice 2) live in
`tests/analysis/test_retrieval_planning_requery_units.py` and are
untouched by this change -- they call `assemble_evidence_ids(trajectory)`
with the same one argument they always did, and the assertions in this
file are why they still pass unmodified."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult
from axial.llm import STUB_TOOL_CALLS_ENV_VAR, StubLLMClient
from axial.retrieve.loop import (
    _round_robin_by_source,
    assemble_evidence_ids,
    run_planned_retrieval,
)


def _pre_639_round_robin(ids: list[str]) -> list[str]:
    """A verbatim copy of `_round_robin_by_source` as it stood immediately
    before issue #639 -- one id per source per pass, no weights concept at
    all. Kept only as this file's own independent oracle."""
    from axial.retrieve.loop import _source_id_or_empty

    groups: dict[str, list[str]] = {}
    for chunk_id in ids:
        groups.setdefault(_source_id_or_empty(chunk_id), []).append(chunk_id)

    group_keys = sorted(groups)
    rotated: list[str] = []
    round_index = 0
    while len(rotated) < len(ids):
        for key in group_keys:
            bucket = groups[key]
            if round_index < len(bucket):
                rotated.append(bucket[round_index])
        round_index += 1
    return rotated


def _entry(tool: str, result_ids: list[str]) -> dict[str, Any]:
    return {
        "step": 1,
        "tool": tool,
        "args": {},
        "result_ids": result_ids,
        "result_count": len(result_ids),
    }


_FIXTURES: list[list[str]] = [
    [],
    ["aaa_1_a_001"],
    ["aaa_1_a_001", "bbb_1_a_001"],
    ["aaa_1_a_001", "aaa_1_a_002", "aaa_1_a_003", "bbb_1_a_001", "ccc_1_a_001", "bbb_1_a_002"],
    ["ccc_1_a_001", "aaa_1_a_001", "aaa_1_a_002", "bbb_1_a_001", "bbb_1_a_002", "bbb_1_a_003"],
]


def test_no_weights_argument_matches_the_pre_639_implementation_exactly():
    for ids in _FIXTURES:
        assert _round_robin_by_source(ids) == _pre_639_round_robin(ids), ids


def test_none_and_empty_dict_weights_are_the_same_as_omitting_the_argument():
    for ids in _FIXTURES:
        expected = _pre_639_round_robin(ids)
        assert _round_robin_by_source(ids, None) == expected, ids
        assert _round_robin_by_source(ids, {}) == expected, ids


def test_a_weight_of_one_for_every_source_is_the_same_as_the_implicit_default():
    ids = _FIXTURES[3]
    explicit = _round_robin_by_source(ids, {"aaa": 1.0, "bbb": 1.0, "ccc": 1.0})
    assert explicit == _pre_639_round_robin(ids)


def test_assemble_evidence_ids_default_call_is_unaffected_by_the_weights_parameter_existing():
    trajectory = [
        _entry("get_name", ["aaa_1_a_001", "aaa_1_a_002"]),
        _entry("get_name", ["bbb_1_a_001", "bbb_1_a_002"]),
        _entry("where_names_meet", ["ccc_1_a_001"]),
    ]
    assert assemble_evidence_ids(trajectory) == [
        "aaa_1_a_001",
        "bbb_1_a_001",
        "ccc_1_a_001",
        "aaa_1_a_002",
        "bbb_1_a_002",
    ]


# --- a weight changes composition order, never the surviving set -----------


def test_a_higher_weight_source_surfaces_denser_and_sooner():
    ids = ["aaa_1_a_001", "aaa_1_a_002", "aaa_1_a_003", "bbb_1_a_001"]
    weighted = _round_robin_by_source(ids, {"aaa": 3.0})
    # aaa earns 3 slots in its first pass, so all of it lands ahead of bbb's
    # one id -- unlike the unweighted case, where they interleave.
    assert weighted == ["aaa_1_a_001", "aaa_1_a_002", "aaa_1_a_003", "bbb_1_a_001"]
    unweighted = _round_robin_by_source(ids)
    assert unweighted == ["aaa_1_a_001", "bbb_1_a_001", "aaa_1_a_002", "aaa_1_a_003"]
    assert weighted != unweighted


def test_a_zero_weight_source_is_pushed_to_the_tail_but_never_dropped():
    ids = ["aaa_1_a_001", "aaa_1_a_002", "bbb_1_a_001", "ccc_1_a_001"]
    result = _round_robin_by_source(ids, {"aaa": 0.0})
    assert set(result) == set(ids), "a weight of 0 is not a filter -- nothing is dropped"
    assert result.index("bbb_1_a_001") < result.index("aaa_1_a_001")
    assert result.index("ccc_1_a_001") < result.index("aaa_1_a_001")
    # aaa's own two ids keep their relative order even pushed to the tail.
    assert result.index("aaa_1_a_001") < result.index("aaa_1_a_002")


def test_a_deemphasised_source_still_changes_the_composed_prefix():
    """The bar this issue is actually built to clear: a weight that
    de-emphasises a dominant source changes what appears EARLY in the
    ordering, which is exactly what `compose_prompt`'s char-budget walk
    reads (synthesis.py's own prefix rule) -- so a weighted run's evidence
    differs from a plain run's, not just its wording."""
    ids = [
        "dominant_1_a_001",
        "dominant_1_a_002",
        "dominant_1_a_003",
        "middle_1_a_001",
        "middle_1_a_002",
        "minor_1_a_001",
    ]
    plain = _round_robin_by_source(ids)
    deemphasised = _round_robin_by_source(ids, {"dominant": 0.1})

    plain_prefix = plain[:2]
    deemphasised_prefix = deemphasised[:2]
    assert plain_prefix != deemphasised_prefix
    assert "minor_1_a_001" in deemphasised_prefix
    assert "minor_1_a_001" not in plain_prefix, (
        "the fixture is chosen so the unweighted prefix does NOT already "
        "include the minor source, otherwise this would not prove the "
        "weight moved anything"
    )


def test_weights_never_change_which_ids_survive_only_their_order():
    ids = _FIXTURES[4]
    weighted = _round_robin_by_source(ids, {"aaa": 2.5, "bbb": 0.4, "ccc": 1.0})
    assert sorted(weighted) == sorted(ids)
    assert len(weighted) == len(ids)


def test_an_unweighted_source_named_in_the_dict_falls_back_to_one():
    """A weights dict that names some but not all sources leaves the
    unnamed ones at the implicit default of 1.0, never 0."""
    ids = ["aaa_1_a_001", "bbb_1_a_001", "bbb_1_a_002"]
    result = _round_robin_by_source(ids, {"aaa": 5.0})
    assert set(result) == set(ids)
    assert result[0] == "aaa_1_a_001"


# --- issue #639: run_planned_retrieval forwards brief.weights end to end ---


def _write_two_source_vault(vault_dir: Path) -> None:
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)

    def _note(chunk_id: str, source_id: str) -> None:
        frontmatter = {
            "chunk_id": chunk_id,
            "section": "Synthetic Section",
            "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
            "source_meta": {"author": source_id, "title": "T", "date": 2020},
            "answers": {"claim": f"Claim of {chunk_id}.", "position_of": "the author"},
        }
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")

    _note("dominant_1_a_001", "dominant")
    _note("dominant_1_a_002", "dominant")
    _note("dominant_1_a_003", "dominant")
    _note("minor_1_a_001", "minor")


def _brief(weights: dict[str, float] | None = None) -> Brief:
    return Brief(
        brief_id="unit-brief",
        case="Syria",
        request="A request.",
        weights=weights or {},
    )


def _interrogation_result() -> InterrogationResult:
    return InterrogationResult(
        premises_found=[], bounds_applied=[], refusal=None, disposition="proceed_bounded"
    )


def test_run_planned_retrieval_with_no_weights_matches_the_unweighted_default(
    tmp_path: Path, monkeypatch
):
    vault_dir = tmp_path / "vault"
    _write_two_source_vault(vault_dir)
    monkeypatch.setenv(
        STUB_TOOL_CALLS_ENV_VAR,
        json.dumps(
            [
                {"tool": "query_by_source", "args": {"source_id": "dominant"}},
                {"tool": "query_by_source", "args": {"source_id": "minor"}},
                None,
            ]
        ),
    )
    client = StubLLMClient()

    result = run_planned_retrieval(
        client, _brief(), _interrogation_result(), vault_dir=vault_dir, step_budget=5
    )

    assert assemble_evidence_ids(result.trajectory) == result.evidence_ids


def test_run_planned_retrieval_applies_the_briefs_own_weights(tmp_path: Path, monkeypatch):
    """The end-to-end wire (issue #639): `brief.weights` reaches
    `assemble_evidence_ids` through `run_planned_retrieval` with no
    separate parameter needed -- it is the brief's own field."""
    vault_dir = tmp_path / "vault"
    _write_two_source_vault(vault_dir)
    scripted_calls = json.dumps(
        [
            {"tool": "query_by_source", "args": {"source_id": "dominant"}},
            {"tool": "query_by_source", "args": {"source_id": "minor"}},
            None,
        ]
    )

    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, scripted_calls)
    plain = run_planned_retrieval(
        StubLLMClient(), _brief(), _interrogation_result(), vault_dir=vault_dir, step_budget=5
    )

    monkeypatch.setenv(STUB_TOOL_CALLS_ENV_VAR, scripted_calls)
    weighted = run_planned_retrieval(
        StubLLMClient(),
        _brief({"dominant": 0.1}),
        _interrogation_result(),
        vault_dir=vault_dir,
        step_budget=5,
    )

    assert set(plain.evidence_ids) == set(weighted.evidence_ids)
    assert plain.evidence_ids != weighted.evidence_ids
    assert weighted.evidence_ids.index("minor_1_a_001") < plain.evidence_ids.index("minor_1_a_001")
