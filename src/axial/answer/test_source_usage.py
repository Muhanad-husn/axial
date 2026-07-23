"""Inner unit tests for the §7.13 source-usage disclosure (issue #265,
plans/source-usage/01-per-run-source-usage.md's inner-loop list). The outer
acceptance test lives at tests/analysis/test_source_usage.py.
"""

from __future__ import annotations

import json

import pytest
import yaml

from axial.answer.source_usage import compute_source_usage, derive_filters_observed
from axial.query import reader

# -- fixture helpers ----------------------------------------------------------


def _write_chunk_note(prose_dir, chunk_id, *, polities_touched=None, **overrides):
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "A Section",
        "chunk_text": f"{chunk_id} text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-science", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Freedonia"},
        "polities_touched": polities_touched if polities_touched is not None else ["Freedonia"],
        "artifact_refs": [],
    }
    frontmatter.update(overrides)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_artifact_note(artifacts_dir, artifact_id, *, source_id, **overrides):
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "artifact_id": artifact_id,
        "artifact_role": "case-study",
        "field": {"primary": "field:political-science", "secondary": []},
        "source_id": source_id,
        "section": "A Section",
        "retrievable": True,
        "cited_by": [],
    }
    frontmatter.update(overrides)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (artifacts_dir / f"{artifact_id}.md").write_text(text, encoding="utf-8")


def _chunk_ground(chunk_id):
    return {"ref_type": "chunk", "ref_id": chunk_id}


def _artifact_ground(artifact_id):
    return {"ref_type": "artifact", "ref_id": artifact_id}


def _record(*, claims, trajectory, disposition="proceed"):
    return {
        "claims": claims,
        "trajectory": trajectory,
        "interrogation": {"disposition": disposition},
    }


# -- filters_observed derivation ----------------------------------------------


def test_filters_observed_is_the_union_of_query_by_tag_and_query_by_polity_args():
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        },
        {
            "step": 2,
            "tool": "query_by_polity",
            "args": {"polity": "Freedonia"},
            "result_ids": [],
            "result_count": 0,
        },
    ]
    filters_observed = derive_filters_observed(trajectory)
    assert filters_observed == [
        {"tool": "query_by_tag", "args": {"field": "field:political-science"}},
        {"tool": "query_by_polity", "args": {"polity": "Freedonia"}},
    ]


def test_filters_observed_deduplicates_repeated_calls():
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "f1"},
            "result_ids": [],
            "result_count": 0,
        },
        {
            "step": 2,
            "tool": "query_by_tag",
            "args": {"field": "f1"},
            "result_ids": [],
            "result_count": 0,
        },
    ]
    assert derive_filters_observed(trajectory) == [
        {"tool": "query_by_tag", "args": {"field": "f1"}}
    ]


def test_filters_observed_is_deterministic_across_repeat_calls():
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"claim_type": "c", "field": "f"},
            "result_ids": [],
            "result_count": 0,
        },
        {
            "step": 2,
            "tool": "query_by_polity",
            "args": {"polity": "Ruritania"},
            "result_ids": [],
            "result_count": 0,
        },
    ]
    first = derive_filters_observed(trajectory)
    second = derive_filters_observed(trajectory)
    assert first == second
    # arg keys within one filter are also sorted, so the same filter with
    # its keys supplied in a different order still dedupes/renders identically.
    assert first[0]["args"] == {"claim_type": "c", "field": "f"}


def test_non_filter_tools_contribute_nothing_to_filters_observed():
    trajectory = [
        {
            "step": 1,
            "tool": "get_chunk",
            "args": {"chunk_id": "x_0_a_001"},
            "result_ids": ["x_0_a_001"],
            "result_count": 1,
        },
        {
            "step": 2,
            "tool": "follow_backlinks",
            "args": {"id": "x_0_a_001"},
            "result_ids": [],
            "result_count": 0,
        },
        {
            "step": 3,
            "tool": "query_by_source",
            "args": {"source_id": "x"},
            "result_ids": [],
            "result_count": 0,
        },
        {
            "step": 4,
            "tool": "get_envelope",
            "args": {"source_id": "x"},
            "result_ids": ["x"],
            "result_count": 1,
        },
        {"step": 5, "tool": "coverage_count", "args": {}, "result_ids": [], "result_count": 0},
    ]
    assert derive_filters_observed(trajectory) == []


# -- source_id resolution ------------------------------------------------------


def test_evidence_fold_resolves_chunk_grounds_by_parsing_the_chunk_id(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "tilly_0_intro_001")
    claims = [{"grounds": [_chunk_ground("tilly_0_intro_001")]}]
    record = _record(claims=claims, trajectory=[])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert [s["source_id"] for s in result["sources"]] == ["tilly"]


def test_evidence_fold_resolves_artifact_grounds_via_artifact_frontmatter(tmp_path):
    artifacts_dir = tmp_path / "artifacts"
    _write_artifact_note(artifacts_dir, "artifact-001", source_id="gellner")
    claims = [{"grounds": [_artifact_ground("artifact-001")]}]
    record = _record(claims=claims, trajectory=[])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert [s["source_id"] for s in result["sources"]] == ["gellner"]


# -- evidence fold: dedup + shares sum to 1.0 ----------------------------------


def test_evidence_fold_counts_a_chunk_cited_by_two_claims_once():
    claims = [
        {"grounds": [_chunk_ground("tilly_0_a_001")]},
        {"grounds": [_chunk_ground("tilly_0_a_001"), _chunk_ground("tilly_0_a_002")]},
    ]
    record = _record(claims=claims, trajectory=[])

    result = compute_source_usage(record, vault_dir=None)
    tilly = result["sources"][0]
    assert tilly["evidence_chunk_count"] == 2
    assert tilly["evidence_share"] == 1.0


def test_evidence_share_sums_to_one_across_sources():
    claims = [
        {
            "grounds": [
                _chunk_ground("tilly_0_a_001"),
                _chunk_ground("tilly_0_a_002"),
                _chunk_ground("other_0_a_001"),
            ]
        }
    ]
    record = _record(claims=claims, trajectory=[])

    result = compute_source_usage(record, vault_dir=None)
    assert sum(s["evidence_share"] for s in result["sources"]) == pytest.approx(1.0)


# -- denominator: real query API, asserted by call+args ------------------------


def test_available_chunk_count_comes_from_the_query_api_not_the_runs_evidence(
    tmp_path, monkeypatch
):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "tilly_0_a_001")

    recorded_calls = []
    real_query_by_tag = reader.query_by_tag

    def _spy_query_by_tag(*, vault_dir=None, **filters):
        recorded_calls.append(("query_by_tag", filters))
        return real_query_by_tag(vault_dir=vault_dir, **filters)

    monkeypatch.setattr("axial.answer.source_usage.query_by_tag", _spy_query_by_tag)

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    # The run's OWN evidence names a chunk that does not even exist in the
    # vault -- proving the denominator is never derived from it.
    claims = [{"grounds": [_chunk_ground("tilly_0_a_001")]}]
    record = _record(claims=claims, trajectory=trajectory)

    compute_source_usage(record, vault_dir=tmp_path)

    assert recorded_calls == [("query_by_tag", {"field": "field:political-science"})]


def test_available_share_is_this_sources_count_over_the_corpus_wide_matching_count(tmp_path):
    prose_dir = tmp_path / "prose"
    for i in range(22):
        _write_chunk_note(prose_dir, f"tilly_0_a_{i:03d}")
    for i in range(78):
        _write_chunk_note(prose_dir, f"other_0_a_{i:03d}")

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science", "claim_type": "claim:causal"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    claims = [{"grounds": [_chunk_ground("tilly_0_a_000")]}]
    record = _record(claims=claims, trajectory=trajectory)

    result = compute_source_usage(record, vault_dir=tmp_path)
    tilly = result["sources"][0]
    assert tilly["available_chunk_count"] == 22
    assert tilly["available_share"] == pytest.approx(22 / 100)


# -- usage_ratio ----------------------------------------------------------------


def test_usage_ratio_is_null_not_zero_when_available_share_is_zero(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(
        prose_dir, "other_0_a_001", field={"primary": "field:economics", "secondary": []}
    )

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    # "zaum"'s grounds chunk does not even exist in the vault, so it
    # certainly cannot match the observed filter -- available_share is 0.
    claims = [{"grounds": [_chunk_ground("zaum_0_a_001")]}]
    record = _record(claims=claims, trajectory=trajectory)

    result = compute_source_usage(record, vault_dir=tmp_path)
    zaum = result["sources"][0]
    assert zaum["available_chunk_count"] == 0
    assert zaum["available_share"] == 0
    assert zaum["usage_ratio"] is None


# -- sources present in one side but not the other, no KeyError ---------------


def test_source_in_evidence_but_absent_from_filter_results_has_zero_available(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "known_0_a_001")

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    claims = [{"grounds": [_chunk_ground("known_0_a_001"), _chunk_ground("unmatched_0_a_001")]}]
    record = _record(claims=claims, trajectory=trajectory)

    result = compute_source_usage(record, vault_dir=tmp_path)
    by_source = {s["source_id"]: s for s in result["sources"]}
    assert by_source["unmatched"]["available_chunk_count"] == 0
    assert by_source["unmatched"]["usage_ratio"] is None


def test_source_in_filter_results_but_absent_from_evidence_gets_no_entry(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "cited_0_a_001")
    _write_chunk_note(prose_dir, "uncited_0_a_001")

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    claims = [{"grounds": [_chunk_ground("cited_0_a_001")]}]
    record = _record(claims=claims, trajectory=trajectory)

    result = compute_source_usage(record, vault_dir=tmp_path)
    source_ids = {s["source_id"] for s in result["sources"]}
    assert source_ids == {"cited"}


# -- empty sources on refuse / no grounds --------------------------------------


def test_sources_is_empty_on_refuse_disposition_but_filters_observed_still_populated():
    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    record = _record(claims=[], trajectory=trajectory, disposition="refuse")

    result = compute_source_usage(record, vault_dir=None)
    assert result["sources"] == []
    assert result["filters_observed"] == [
        {"tool": "query_by_tag", "args": {"field": "field:political-science"}}
    ]


def test_sources_is_empty_when_claims_carry_no_grounds():
    record = _record(claims=[{"grounds": []}], trajectory=[], disposition="proceed")

    result = compute_source_usage(record, vault_dir=None)
    assert result["sources"] == []


# -- model-free by construction -------------------------------------------------


def test_compute_source_usage_makes_zero_llm_calls(tmp_path, monkeypatch):
    """`explode`'s own poison-client contract (axial.llm.ExplodingLLMClient):
    constructing/selecting it never raises, only `.complete()`/
    `.complete_with_tools()` do. Configuring it and never touching those
    methods proves this computation never reaches for the LLM at all."""
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    from axial.llm import ExplodingLLMClient, get_client

    client = get_client()
    assert isinstance(client, ExplodingLLMClient)

    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "gellner_0_a_001")
    claims = [{"grounds": [_chunk_ground("gellner_0_a_001")]}]
    record = _record(claims=claims, trajectory=[])

    # Would raise RuntimeError immediately if this function ever called
    # `client.complete()`/`client.complete_with_tools()` -- it never does,
    # because it never even receives a client.
    result = compute_source_usage(record, vault_dir=tmp_path)
    assert result["sources"][0]["source_id"] == "gellner"


# -- determinism ----------------------------------------------------------------


def test_source_usage_is_byte_identical_across_repeat_runs(tmp_path):
    prose_dir = tmp_path / "prose"
    for i in range(22):
        _write_chunk_note(prose_dir, f"tilly_0_a_{i:03d}")
    for i in range(5):
        _write_chunk_note(prose_dir, f"other_0_a_{i:03d}")

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    claims = [
        {"grounds": [_chunk_ground("tilly_0_a_000"), _chunk_ground("other_0_a_000")]},
    ]
    record = _record(claims=claims, trajectory=trajectory)

    first = compute_source_usage(record, vault_dir=tmp_path)
    second = compute_source_usage(record, vault_dir=tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert [s["source_id"] for s in first["sources"]] == [s["source_id"] for s in second["sources"]]


# -- gates nothing ---------------------------------------------------------------


def test_full_concentration_on_one_source_produces_no_failure(tmp_path):
    prose_dir = tmp_path / "prose"
    _write_chunk_note(prose_dir, "gellner_0_a_001")
    _write_chunk_note(prose_dir, "gellner_0_a_002")

    trajectory = [
        {
            "step": 1,
            "tool": "query_by_tag",
            "args": {"field": "field:political-science"},
            "result_ids": [],
            "result_count": 0,
        }
    ]
    claims = [
        {"grounds": [_chunk_ground("gellner_0_a_001")]},
        {"grounds": [_chunk_ground("gellner_0_a_002")]},
    ]
    record = _record(claims=claims, trajectory=trajectory)

    # No exception, no sentinel failure value -- just the honest disclosure.
    result = compute_source_usage(record, vault_dir=tmp_path)
    assert result["sources"][0]["evidence_share"] == 1.0
