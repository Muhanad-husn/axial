"""Inner unit tests for the §7.13 source-usage disclosure (issues #265 and
#491). The outer acceptance test lives at tests/analysis/test_source_usage.py.

The `filters_observed` half of this contract is **struck** (§7.13, D1): the
two tools it drew from are deleted with the facets they filtered, so those
tests pinned a field no trajectory can carry. They are re-pointed at
`names_queried` and the denominator it now feeds -- same rule (a filter
travels with its tool), same dedupe key, real substrate.
"""

from __future__ import annotations

import json

import pytest
import yaml

from axial.answer.source_usage import compute_source_usage, derive_names_queried

TILLY = "Charles Tilly"
BAYAT = "Asef Bayat"

# -- fixture helpers ----------------------------------------------------------


def _write_chunk_note(prose_dir, chunk_id, **overrides):
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "A Section",
        "chunk_text": f"{chunk_id} text.",
        "source_meta": {"author": "A", "title": "T", "date": 2020, "thesis": "X", "scope": "Y"},
        "schema_version": "0.1",
        "frame_version": "0.1",
        "answers": {"claim": f"Claim of {chunk_id}.", "position_of": "the author"},
    }
    frontmatter.update(overrides)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


def _write_name_page(names_dir, name, member_ids):
    names_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {"name": name, "kind": "person", "aliases": [], "member_count": len(member_ids)}
    lines = ["**Member notes:**"]
    lines += [f"- [[{chunk_id}]] — An Author (1978): A claim." for chunk_id in member_ids]
    (names_dir / f"{name}.md").write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n" + "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _write_artifact_note(artifacts_dir, artifact_id, *, source_id, **overrides):
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "artifact_id": artifact_id,
        "artifact_role": "case-study",
        "source_id": source_id,
        "section": "A Section",
        "retrievable": True,
    }
    frontmatter.update(overrides)
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (artifacts_dir / f"{artifact_id}.md").write_text(text, encoding="utf-8")


def _chunk_ground(chunk_id):
    return {"ref_type": "chunk", "ref_id": chunk_id}


def _artifact_ground(artifact_id):
    return {"ref_type": "artifact", "ref_id": artifact_id}


def _name_call(step, tool, args):
    return {"step": step, "tool": tool, "args": args, "result_ids": [], "result_count": 0}


def _where_names_meet_call(step, canonical, other, *, result_count=0, result_ids=None):
    """A `where_names_meet` trajectory entry, persisted with whatever the
    real tool call would have capped `result_count`/`result_ids` to -- the
    denominator must re-query the true size rather than trust these."""
    return {
        "step": step,
        "tool": "where_names_meet",
        "args": {"canonical": canonical, "other": other},
        "result_ids": result_ids or [],
        "result_count": result_count,
    }


def _record(*, claims, trajectory, disposition="proceed", brief=None):
    record = {
        "claims": claims,
        "trajectory": trajectory,
        "interrogation": {"disposition": disposition},
    }
    if brief is not None:
        record["brief"] = brief
    return record


# -- names_queried derivation -------------------------------------------------


def test_names_queried_is_the_union_of_the_name_layer_calls():
    trajectory = [
        _name_call(1, "find_names", {"query": "Tilly"}),
        _name_call(2, "get_name", {"canonical": TILLY}),
        _name_call(3, "who_cites", {"canonical": TILLY}),
    ]
    assert derive_names_queried(trajectory) == [
        {"tool": "find_names", "args": {"query": "Tilly"}},
        {"tool": "get_name", "args": {"canonical": TILLY}},
        {"tool": "who_cites", "args": {"canonical": TILLY}},
    ]


def test_the_same_canonical_under_two_tools_stays_two_entries():
    """The #265 rule, unchanged: a filter travels with its tool. Reaching a
    name through `who_argues_against` is a different query from reading its
    page, so collapsing them would re-run the wrong tool."""
    trajectory = [
        _name_call(1, "get_name", {"canonical": TILLY}),
        _name_call(2, "who_argues_against", {"canonical": TILLY}),
    ]
    assert len(derive_names_queried(trajectory)) == 2


def test_names_queried_deduplicates_repeated_calls():
    trajectory = [
        _name_call(1, "get_name", {"canonical": TILLY}),
        _name_call(2, "get_name", {"canonical": TILLY}),
    ]
    assert derive_names_queried(trajectory) == [{"tool": "get_name", "args": {"canonical": TILLY}}]


def test_names_queried_is_deterministic_and_sorts_arg_keys():
    trajectory = [
        _name_call(1, "get_name", {"limit": 5, "canonical": TILLY}),
        _name_call(2, "find_names", {"query": "Bayat"}),
    ]
    first = derive_names_queried(trajectory)
    assert first == derive_names_queried(trajectory)
    assert list(first[0]["args"]) == ["canonical", "limit"]


def test_non_name_tools_contribute_nothing_to_names_queried():
    trajectory = [
        _name_call(1, "get_chunk", {"chunk_id": "x_0_a_001"}),
        _name_call(2, "query_by_source", {"source_id": "x"}),
        _name_call(3, "get_envelope", {"source_id": "x"}),
    ]
    assert derive_names_queried(trajectory) == []


# -- source_id resolution ------------------------------------------------------


def test_evidence_fold_resolves_chunk_grounds_by_parsing_the_chunk_id(tmp_path):
    _write_chunk_note(tmp_path / "prose", "tilly_0_intro_001")
    record = _record(claims=[{"grounds": [_chunk_ground("tilly_0_intro_001")]}], trajectory=[])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert [s["source_id"] for s in result["sources"]] == ["tilly"]


def test_evidence_fold_resolves_artifact_grounds_via_artifact_frontmatter(tmp_path):
    _write_artifact_note(tmp_path / "artifacts", "artifact-001", source_id="gellner")
    record = _record(claims=[{"grounds": [_artifact_ground("artifact-001")]}], trajectory=[])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert [s["source_id"] for s in result["sources"]] == ["gellner"]


# -- evidence fold: dedup + shares sum to 1.0 ----------------------------------


def test_evidence_fold_counts_a_chunk_cited_by_two_claims_once():
    claims = [
        {"grounds": [_chunk_ground("tilly_0_a_001")]},
        {"grounds": [_chunk_ground("tilly_0_a_001"), _chunk_ground("tilly_0_a_002")]},
    ]
    result = compute_source_usage(_record(claims=claims, trajectory=[]), vault_dir=None)
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
    result = compute_source_usage(_record(claims=claims, trajectory=[]), vault_dir=None)
    assert sum(s["evidence_share"] for s in result["sources"]) == pytest.approx(1.0)


# -- the denominator, re-based onto the names queried (#491) -------------------


def test_available_count_is_the_union_of_member_notes_across_the_names_queried(tmp_path):
    """§7.13's stated analogue: a source the run under-drew on still gets an
    honest, non-zero denominator when the corpus held it."""
    prose = tmp_path / "prose"
    for chunk_id in ("tilly_0_a_001", "tilly_0_a_002", "bayat_0_a_001"):
        _write_chunk_note(prose, chunk_id)
    names = tmp_path / "names"
    _write_name_page(names, TILLY, ["tilly_0_a_001", "tilly_0_a_002"])
    _write_name_page(names, BAYAT, ["bayat_0_a_001"])

    trajectory = [
        _name_call(1, "get_name", {"canonical": TILLY}),
        _name_call(2, "get_name", {"canonical": BAYAT}),
    ]
    claims = [{"grounds": [_chunk_ground("tilly_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {TILLY: 2, BAYAT: 1}
    tilly = result["sources"][0]
    assert tilly["evidence_share"] == 1.0
    assert tilly["available_chunk_count"] == 2
    assert tilly["available_share"] == pytest.approx(2 / 3)
    # Drawn on harder than its availability explains -- the §7.13 signal.
    assert tilly["usage_ratio"] == pytest.approx(1.5)


def test_a_note_that_is_a_member_of_two_queried_names_counts_once(tmp_path):
    prose = tmp_path / "prose"
    _write_chunk_note(prose, "tilly_0_a_001")
    names = tmp_path / "names"
    _write_name_page(names, TILLY, ["tilly_0_a_001"])
    _write_name_page(names, BAYAT, ["tilly_0_a_001"])

    trajectory = [
        _name_call(1, "get_name", {"canonical": TILLY}),
        _name_call(2, "who_cites", {"canonical": BAYAT}),
    ]
    claims = [{"grounds": [_chunk_ground("tilly_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)

    # Both pages contribute the same note; the union holds it once, so the
    # source's available share is 1.0 rather than a double-counted 0.5.
    assert result["denominator_by_name"] == {TILLY: 1, BAYAT: 1}
    assert result["sources"][0]["available_chunk_count"] == 1
    assert result["sources"][0]["available_share"] == 1.0


def test_the_per_name_contribution_is_disclosed_so_a_hub_name_is_visible(tmp_path):
    """One hub name can be most of the corpus (`Syria`: 962 of 6,148 live
    prose notes). The per-name contribution is recorded so a denominator
    inflated by one name is legible as data, not only in the ratios it
    flattens."""
    prose = tmp_path / "prose"
    hub_members = [f"hub_0_a_{i:03d}" for i in range(20)]
    for chunk_id in [*hub_members, "tilly_0_a_001"]:
        _write_chunk_note(prose, chunk_id)
    names = tmp_path / "names"
    _write_name_page(names, "Syria", hub_members)
    _write_name_page(names, TILLY, ["tilly_0_a_001"])

    trajectory = [
        _name_call(1, "get_name", {"canonical": "Syria"}),
        _name_call(2, "get_name", {"canonical": TILLY}),
    ]
    claims = [{"grounds": [_chunk_ground("tilly_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {"Syria": 20, TILLY: 1}


def test_a_page_over_the_default_limit_is_counted_in_full(tmp_path):
    """`get_name`'s members are capped at `DEFAULT_LIMIT` (10, issue #505),
    which a denominator cannot accept: a member past the cap would silently
    shrink the corpus."""
    prose = tmp_path / "prose"
    members = [f"tilly_0_a_{i:03d}" for i in range(25)]
    for chunk_id in members:
        _write_chunk_note(prose, chunk_id)
    _write_name_page(tmp_path / "names", TILLY, members)

    trajectory = [_name_call(1, "get_name", {"canonical": TILLY})]
    claims = [{"grounds": [_chunk_ground("tilly_0_a_000")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {TILLY: 25}
    assert result["sources"][0]["available_chunk_count"] == 25


# -- where_names_meet: pair-keyed, re-queried, additive (issue #550) ---------


def test_an_intersection_alone_credits_only_the_pair_with_its_true_size(tmp_path):
    """Issue #550's own first acceptance scenario: a trajectory with one
    `where_names_meet` and no other name query puts the pair's TRUE size in
    the denominator -- and nothing under either name alone, since neither
    page was read as a whole here."""
    prose = tmp_path / "prose"
    shared = [f"shared_0_a_{i:03d}" for i in range(3)]
    for chunk_id in shared:
        _write_chunk_note(prose, chunk_id)
    names = tmp_path / "names"
    _write_name_page(names, TILLY, shared)
    _write_name_page(names, BAYAT, shared)

    trajectory = [_where_names_meet_call(1, TILLY, BAYAT, result_count=3, result_ids=shared)]
    result = compute_source_usage(_record(claims=[], trajectory=trajectory), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {f"{BAYAT} & {TILLY}": 3}


def test_a_directly_queried_name_keeps_its_full_page_and_the_pair_is_added_alongside(tmp_path):
    """Issue #550's own second acceptance scenario: `get_name('Syria')` plus
    `where_names_meet('Syria', 'paramilitarism')` keeps Syria's full page
    count unchanged and adds the pair as an ADDITIONAL entry, never a
    replacement."""
    prose = tmp_path / "prose"
    syria_only = [f"syria_0_a_{i:03d}" for i in range(5)]
    shared = [f"shared_0_a_{i:03d}" for i in range(2)]
    for chunk_id in [*syria_only, *shared]:
        _write_chunk_note(prose, chunk_id)
    names = tmp_path / "names"
    _write_name_page(names, "Syria", [*syria_only, *shared])
    _write_name_page(names, "paramilitarism", shared)

    trajectory = [
        _name_call(1, "get_name", {"canonical": "Syria"}),
        _where_names_meet_call(2, "Syria", "paramilitarism", result_count=2, result_ids=shared),
    ]
    result = compute_source_usage(_record(claims=[], trajectory=trajectory), vault_dir=tmp_path)

    assert result["denominator_by_name"]["Syria"] == 7
    assert result["denominator_by_name"]["Syria & paramilitarism"] == 2
    assert "paramilitarism" not in result["denominator_by_name"], (
        "the name reached ONLY as the intersection's other half must not get its own "
        "whole-page entry"
    )


def test_the_pairs_true_size_is_re_queried_not_the_capped_persisted_result_count(tmp_path):
    """`result_count` on the persisted step is the capped `limit` (the tool
    caps at `DEFAULT_LIMIT`, 10), never the true intersection size -- the
    denominator must re-query it fresh rather than trust the trajectory."""
    prose = tmp_path / "prose"
    shared = [f"shared_0_a_{i:03d}" for i in range(12)]  # exceeds DEFAULT_LIMIT (10)
    for chunk_id in shared:
        _write_chunk_note(prose, chunk_id)
    names = tmp_path / "names"
    _write_name_page(names, TILLY, shared)
    _write_name_page(names, BAYAT, shared)

    # Mirrors what the real tool call would have persisted: capped at 10.
    trajectory = [_where_names_meet_call(1, TILLY, BAYAT, result_count=10, result_ids=shared[:10])]
    result = compute_source_usage(_record(claims=[], trajectory=trajectory), vault_dir=tmp_path)

    key = f"{BAYAT} & {TILLY}"
    assert result["denominator_by_name"][key] == 12, "must re-query the TRUE size, not result_count"


def test_the_same_pair_with_swapped_arguments_is_one_entry(tmp_path):
    prose = tmp_path / "prose"
    shared = ["shared_0_a_000"]
    _write_chunk_note(prose, shared[0])
    names = tmp_path / "names"
    _write_name_page(names, TILLY, shared)
    _write_name_page(names, BAYAT, shared)

    trajectory = [
        _where_names_meet_call(1, TILLY, BAYAT, result_count=1, result_ids=shared),
        _where_names_meet_call(2, BAYAT, TILLY, result_count=1, result_ids=shared),
    ]
    result = compute_source_usage(_record(claims=[], trajectory=trajectory), vault_dir=tmp_path)

    assert len([k for k in result["denominator_by_name"] if "&" in k]) == 1


def test_an_intersection_naming_an_absent_page_is_skipped_not_raised(tmp_path):
    _write_name_page(tmp_path / "names", TILLY, [])
    trajectory = [
        _where_names_meet_call(1, TILLY, "Some Absent Name", result_count=0, result_ids=[])
    ]

    result = compute_source_usage(_record(claims=[], trajectory=trajectory), vault_dir=tmp_path)

    assert not any("&" in k for k in result["denominator_by_name"])


# -- usage_ratio ----------------------------------------------------------------


def test_usage_ratio_and_available_are_null_not_zero_when_the_run_queried_no_name(tmp_path):
    """A run that never queried a name (issue #584: the argument-map path
    queries none, but any empty trajectory hits the same branch) has no
    denominator at all -- `available_chunk_count` and `available_share` are
    `None`, an unknown, not a measured `0`, and `usage_ratio` is `None` for
    the same reason it always was."""
    _write_chunk_note(tmp_path / "prose", "other_0_a_001")
    claims = [{"grounds": [_chunk_ground("zaum_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=[]), vault_dir=tmp_path)

    zaum = result["sources"][0]
    assert zaum["available_chunk_count"] is None
    assert zaum["available_share"] is None
    assert zaum["usage_ratio"] is None


def test_source_drawn_on_but_absent_from_every_queried_name_has_zero_available(tmp_path):
    prose = tmp_path / "prose"
    _write_chunk_note(prose, "known_0_a_001")
    _write_name_page(tmp_path / "names", TILLY, ["known_0_a_001"])

    trajectory = [_name_call(1, "get_name", {"canonical": TILLY})]
    claims = [{"grounds": [_chunk_ground("known_0_a_001"), _chunk_ground("unmatched_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)

    by_source = {s["source_id"]: s for s in result["sources"]}
    assert by_source["unmatched"]["available_chunk_count"] == 0
    assert by_source["unmatched"]["usage_ratio"] is None


def test_source_in_the_denominator_but_absent_from_evidence_gets_no_entry(tmp_path):
    prose = tmp_path / "prose"
    _write_chunk_note(prose, "cited_0_a_001")
    _write_chunk_note(prose, "uncited_0_a_001")
    _write_name_page(tmp_path / "names", TILLY, ["cited_0_a_001", "uncited_0_a_001"])

    trajectory = [_name_call(1, "get_name", {"canonical": TILLY})]
    claims = [{"grounds": [_chunk_ground("cited_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)

    assert {s["source_id"] for s in result["sources"]} == {"cited"}


# -- empty sources on refuse / no grounds --------------------------------------


def test_sources_is_empty_on_refuse_but_names_queried_still_populated():
    trajectory = [_name_call(1, "find_names", {"query": "Tilly"})]
    record = _record(claims=[], trajectory=trajectory, disposition="refuse")

    result = compute_source_usage(record, vault_dir=None)
    assert result["sources"] == []
    assert result["names_queried"] == [{"tool": "find_names", "args": {"query": "Tilly"}}]


def test_sources_is_empty_when_claims_carry_no_grounds():
    record = _record(claims=[{"grounds": []}], trajectory=[], disposition="proceed")
    assert compute_source_usage(record, vault_dir=None)["sources"] == []


# -- model-free by construction -------------------------------------------------


def test_compute_source_usage_makes_zero_llm_calls(tmp_path, monkeypatch):
    """`explode`'s own poison-client contract (axial.llm.ExplodingLLMClient):
    constructing/selecting it never raises, only `.complete()`/
    `.complete_with_tools()` do."""
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "explode")
    from axial.llm import ExplodingLLMClient, get_client

    assert isinstance(get_client(), ExplodingLLMClient)

    _write_chunk_note(tmp_path / "prose", "gellner_0_a_001")
    record = _record(claims=[{"grounds": [_chunk_ground("gellner_0_a_001")]}], trajectory=[])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert result["sources"][0]["source_id"] == "gellner"


# -- determinism ----------------------------------------------------------------


def test_source_usage_is_byte_identical_across_repeat_runs(tmp_path):
    prose = tmp_path / "prose"
    members = [f"tilly_0_a_{i:03d}" for i in range(22)]
    for chunk_id in [*members, "other_0_a_000"]:
        _write_chunk_note(prose, chunk_id)
    _write_name_page(tmp_path / "names", TILLY, members)

    trajectory = [_name_call(1, "get_name", {"canonical": TILLY})]
    claims = [{"grounds": [_chunk_ground("tilly_0_a_000"), _chunk_ground("other_0_a_000")]}]
    record = _record(claims=claims, trajectory=trajectory)

    first = compute_source_usage(record, vault_dir=tmp_path)
    second = compute_source_usage(record, vault_dir=tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# -- gates nothing ---------------------------------------------------------------


def test_full_concentration_on_one_source_produces_no_failure(tmp_path):
    prose = tmp_path / "prose"
    _write_chunk_note(prose, "gellner_0_a_001")
    _write_chunk_note(prose, "gellner_0_a_002")
    _write_name_page(tmp_path / "names", TILLY, ["gellner_0_a_001", "gellner_0_a_002"])

    trajectory = [_name_call(1, "get_name", {"canonical": TILLY})]
    claims = [
        {"grounds": [_chunk_ground("gellner_0_a_001")]},
        {"grounds": [_chunk_ground("gellner_0_a_002")]},
    ]
    result = compute_source_usage(_record(claims=claims, trajectory=trajectory), vault_dir=tmp_path)
    assert result["sources"][0]["evidence_share"] == 1.0
    assert result["sources"][0]["usage_ratio"] == pytest.approx(1.0)


# -- issue #639: weights disclosure ----------------------------------------------


def test_weights_defaults_to_empty_when_the_record_carries_no_brief():
    record = _record(claims=[], trajectory=[])
    assert compute_source_usage(record, vault_dir=None)["weights"] == {}


def test_weights_defaults_to_empty_when_the_brief_supplied_none():
    record = _record(claims=[], trajectory=[], brief={"case": "Syria", "weights": {}})
    assert compute_source_usage(record, vault_dir=None)["weights"] == {}


def test_weights_are_disclosed_verbatim_from_the_brief():
    record = _record(
        claims=[], trajectory=[], brief={"case": "Syria", "weights": {"beshara-2011": 0.1}}
    )
    assert compute_source_usage(record, vault_dir=None)["weights"] == {"beshara-2011": 0.1}


def test_weights_are_disclosed_even_on_refuse():
    trajectory = [_name_call(1, "find_names", {"query": "Tilly"})]
    record = _record(
        claims=[],
        trajectory=trajectory,
        disposition="refuse",
        brief={"weights": {"beshara-2011": 0.1}},
    )
    result = compute_source_usage(record, vault_dir=None)
    assert result["sources"] == []
    assert result["weights"] == {"beshara-2011": 0.1}
