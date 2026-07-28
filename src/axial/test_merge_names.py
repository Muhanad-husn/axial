"""Inner unit tests for `axial.merge_names` (issue #416, Phase A v1 slice 05
-- Reconcile, spec §7.16 artifact 3, P0-12).

The outer acceptance test (`tests/ingestion/test_merge_names.py`) drives the
real `axial names merge` CLI end to end. These cover the parts that are
cheap to pin directly: the loose prompt, the parse that never invents a
name, the fold into an alias map, the seed, and re-runnability.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.merge_names import (
    DEFAULT_MEMBER_CHAR_BUDGET,
    MergeResponseError,
    _locator_source_conflict,
    _resolve_merge_tightness,
    _seed_groups,
    build_alias_map_nodes,
    build_batches,
    compose_merge_prompt,
    render_member,
    parse_merge_response,
    write_alias_map,
    write_index,
)
from axial.names import DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES, NOISE_LABEL
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH

# ---------------------------------------------------------------------------
# The prompt (founder directive: state the judgment, then stop)
# ---------------------------------------------------------------------------


def test_prompt_states_the_judgment_and_carries_the_surface_forms():
    prompt = compose_merge_prompt(
        ["state formation through war", "bellicist state building"],
        {"state formation through war": "concept", "bellicist state building": "concept"},
    )

    assert "state formation through war" in prompt
    assert "bellicist state building" in prompt
    assert "name the same thing" in prompt
    assert "concept" in prompt


def test_prompt_carries_no_step_by_step_scaffolding():
    """Founder directive (issue #416): reasoning at `high` is the mechanism
    for thinking; restating it in the prompt is the over-restraint the
    directive exists to prevent, and a rules/criteria list is the
    prompt-engineering `docs/tag-reliability-best-of-n.md` §2.11 lesson 4
    says loses to sampling on this shape of task."""
    prompt = compose_merge_prompt(["a", "b"], {}).casefold()

    for banned in ("step by step", "step-by-step", "think carefully", "for example", "criteria"):
        assert banned not in prompt


# ---------------------------------------------------------------------------
# Batching: one call per cluster, split only to bound the request
# ---------------------------------------------------------------------------


def test_one_batch_per_cluster_and_none_for_noise_or_singletons():
    surface_forms = ["a", "b", "c", "d", "e"]
    labels = [0, 0, 1, NOISE_LABEL, NOISE_LABEL]

    batches = build_batches(labels, surface_forms)

    assert [(batch.cluster_label, batch.members) for batch in batches] == [(0, ("a", "b"))]


def test_an_outsized_cluster_is_split_across_a_few_calls():
    surface_forms = [f"surface-form-{index:03d}" for index in range(10)]
    labels = [0] * 10

    batches = build_batches(labels, surface_forms, member_char_budget=40)

    assert len(batches) > 1
    assert [member for batch in batches for member in batch.members] == surface_forms


def test_batch_key_is_content_addressed():
    """Moving the tightness dial changes which surfaces sit together, so the
    decision log has to key on membership, not on cluster label."""
    same = build_batches([0, 0], ["a", "b"])[0]
    relabelled = build_batches([7, 7], ["a", "b"])[0]
    different = build_batches([0, 0], ["a", "c"])[0]

    assert same.key == relabelled.key
    assert same.key != different.key


# ---------------------------------------------------------------------------
# Parsing: fold names, never invent them
# ---------------------------------------------------------------------------


def test_parse_keeps_only_surface_forms_the_batch_actually_carried():
    raw = json.dumps(
        {
            "nodes": [
                {
                    "canonical": "state formation through war",
                    "aliases": ["bellicist state building"],
                },
                {"canonical": "a name the corpus never said", "aliases": ["nor this one"]},
            ]
        }
    )

    nodes = parse_merge_response(
        raw, ["state formation through war", "bellicist state building", "civil society"]
    )

    assert nodes == [
        {"canonical": "state formation through war", "aliases": ["bellicist state building"]}
    ]


def test_parse_places_each_surface_form_at_most_once():
    raw = json.dumps(
        {"nodes": [{"canonical": "a", "aliases": ["b"]}, {"canonical": "b", "aliases": ["a"]}]}
    )

    nodes = parse_merge_response(raw, ["a", "b"])

    placed = [surface for node in nodes for surface in [node["canonical"], *node["aliases"]]]
    assert sorted(placed) == ["a", "b"]


def test_parse_rejects_a_shapeless_response():
    with pytest.raises(MergeResponseError):
        parse_merge_response(json.dumps({"merges": []}), ["a", "b"])


def test_parse_rejects_a_response_that_placed_nothing():
    raw = json.dumps({"nodes": [{"canonical": "unknown", "aliases": []}]})

    with pytest.raises(MergeResponseError):
        parse_merge_response(raw, ["a", "b"])


# ---------------------------------------------------------------------------
# The fold: every surface survives, the map is a pure function of its inputs
# ---------------------------------------------------------------------------


def _entries(*surface_forms: str) -> list[tuple[str, str | None, int]]:
    return [(surface_form, "concept", 1) for surface_form in surface_forms]


def test_an_unmapped_surface_survives_as_its_own_node():
    nodes = build_alias_map_nodes(
        _entries("alone", "a", "b"), [{"canonical": "a", "aliases": ["b"]}], {}
    )

    assert {node["canonical"]: node["aliases"] for node in nodes} == {"a": ["b"], "alone": []}


def test_merges_chain_across_decisions_and_the_fold_is_order_independent():
    entries = _entries("a", "b", "c")
    forward = build_alias_map_nodes(
        entries, [{"canonical": "a", "aliases": ["b"]}, {"canonical": "b", "aliases": ["c"]}], {}
    )
    backward = build_alias_map_nodes(
        entries, [{"canonical": "b", "aliases": ["c"]}, {"canonical": "a", "aliases": ["b"]}], {}
    )

    assert forward == backward
    assert len(forward) == 1
    assert sorted([forward[0]["canonical"], *forward[0]["aliases"]]) == ["a", "b", "c"]


def test_the_seed_folds_and_wins_the_canonical_spelling():
    entries = _entries("USSR", "Soviet Union")

    nodes = build_alias_map_nodes(entries, [], {"Soviet Union": ["USSR", "Soviet Union"]})

    assert nodes == [{"canonical": "Soviet Union", "kind": "concept", "aliases": ["USSR"]}]


def test_a_seed_canonical_absent_from_the_corpus_still_folds_without_minting_a_name():
    """The seed is a cleanup aid, not a source of names: it may fold two
    corpus surfaces together, but the canonical is still elected from what
    the corpus said (§7.16's inventory is the lossless record)."""
    entries = [("UK", None, 5), ("Britain", None, 1)]

    nodes = build_alias_map_nodes(entries, [], {"United Kingdom": ["UK", "Britain"]})

    assert nodes == [{"canonical": "UK", "kind": None, "aliases": ["Britain"]}]


def test_kind_falls_back_to_the_groups_own_most_mentioned_kind():
    entries = [("Gellner 1992", None, 9), ("Ernest Gellner", "person", 3)]

    nodes = build_alias_map_nodes(
        entries, [{"canonical": "Gellner 1992", "aliases": ["Ernest Gellner"]}], {}
    )

    assert nodes == [{"canonical": "Gellner 1992", "kind": "person", "aliases": ["Ernest Gellner"]}]


# ---------------------------------------------------------------------------
# The fold refuses a cross-source locator merge (issue #445)
# ---------------------------------------------------------------------------


def test_locator_source_conflict_only_fires_on_two_differently_scoped_locators():
    assert _locator_source_conflict("Table 4.1 (src1)", "Table 4.1 (src2)")
    # Same source: a legitimate same-book spelling merge, not a conflict.
    assert not _locator_source_conflict("Table 4.1 (src1)", "Tab. 4.1 (src1)")
    # A bare, single-source locator never conflicts with anything.
    assert not _locator_source_conflict("Table 4.1", "Table 4.1 (src2)")
    # Not locator-shaped at all -- a real surface that happens to end in
    # parentheses (a citation year) is never mistaken for source scoping.
    assert not _locator_source_conflict(
        "Phelps-Brown and Hopkins (1956)", "Phelps-Brown and Hopkins (1957)"
    )


def test_refuses_to_fold_source_scoped_locators_from_different_sources():
    """Issue #445: the whole point of scoping a locator's identity by source
    is undone if this fold re-fuses two different sources' instances --
    however a cluster or the model proposes it."""
    entries = _entries("Table 4.1 (src1)", "Table 4.1 (src2)")

    nodes = build_alias_map_nodes(
        entries, [{"canonical": "Table 4.1 (src1)", "aliases": ["Table 4.1 (src2)"]}], {}
    )

    assert {node["canonical"] for node in nodes} == {"Table 4.1 (src1)", "Table 4.1 (src2)"}
    assert all(node["aliases"] == [] for node in nodes)


def test_still_folds_two_spellings_of_the_same_source_scoped_locator():
    """The guard is source-specific, not locator-shape-specific -- a genuine
    same-book spelling variant still merges normally."""
    entries = _entries("Table 4.1 (src1)", "Tab. 4.1 (src1)")

    nodes = build_alias_map_nodes(
        entries, [{"canonical": "Table 4.1 (src1)", "aliases": ["Tab. 4.1 (src1)"]}], {}
    )

    assert len(nodes) == 1
    assert nodes[0] == {
        "canonical": "Table 4.1 (src1)",
        "kind": "concept",
        "aliases": ["Tab. 4.1 (src1)"],
    }


def test_seed_is_skipped_without_error_when_the_domain_file_is_absent(tmp_path):
    groups, note = _seed_groups(["anything"], tmp_path)

    assert groups == {}
    assert "seed not applied" in note


# ---------------------------------------------------------------------------
# Artifacts and the tightness dial
# ---------------------------------------------------------------------------


def test_alias_map_and_index_have_the_spec_shape(tmp_path: Path):
    nodes = [{"canonical": "a", "kind": "concept", "aliases": ["b"]}]

    write_alias_map(nodes, tmp_path / "alias_map.json")
    write_index(nodes, tmp_path / "index.json")

    alias_map = json.loads((tmp_path / "alias_map.json").read_text(encoding="utf-8"))
    assert set(alias_map) == {"version", "generated_at", "nodes"}
    assert alias_map["nodes"] == nodes
    assert json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))["names"] == ["a"]


def test_merge_tightness_comes_from_config_and_falls_back_to_the_loosest(tmp_path: Path):
    configured = tmp_path / "pipeline.yaml"
    configured.write_text("names:\n  merge_min_cluster_size: 7\n  merge_min_samples: 3\n", "utf-8")

    assert _resolve_merge_tightness(configured) == (7, 3)
    assert _resolve_merge_tightness(tmp_path / "absent.yaml") == (
        DEFAULT_MIN_CLUSTER_SIZE,
        DEFAULT_MIN_SAMPLES,
    )


def test_the_shipped_config_seeds_the_loosest_tightness():
    """D10: start loose. The dial is the founder's; the shipped value is
    HDBSCAN's loosest, matching `axial names build`'s own default."""
    assert _resolve_merge_tightness() == (DEFAULT_MIN_CLUSTER_SIZE, DEFAULT_MIN_SAMPLES)


def test_member_char_budget_bounds_a_batch_not_the_prompts_wording():
    """The budget is a construction limit on request size (P0-13's own rule),
    so it never appears in the prompt as an instruction."""
    assert str(DEFAULT_MEMBER_CHAR_BUDGET) not in compose_merge_prompt(["a"], {})


def test_the_shipped_config_pins_the_merge_tier_deliberately():
    """§7.9's table says "tier per config" for `reconcile`. Naming it is what
    keeps the pass off whatever `llm_tier` happens to be -- the 2026-07-28
    30-cluster probe chose flash on judgment quality, not on cost."""
    from axial.llm import RECONCILE_PASS_NAME, _load_pipeline_llm_config

    llm_config = _load_pipeline_llm_config(DEFAULT_PIPELINE_CONFIG_PATH)
    assert llm_config["model_by_pass"][RECONCILE_PASS_NAME] == "production_low"


def test_parse_accepts_a_surface_echoed_in_the_form_the_prompt_showed():
    """The 2.89% failure of the first full corpus pass. The prompt renders
    `- 'Sociology' (institution/group)` and says "write every surface form
    exactly as it appears above", so the model writes exactly that -- and the
    parse threw the whole cluster away because it wanted bare `Sociology`.
    The judgment was correct; only the formatting was not."""
    members = ["Sociology", "sociology"]
    kinds = {"Sociology": "institution/group", "sociology": "concept"}
    raw = json.dumps(
        {
            "nodes": [
                {"canonical": "'Sociology' (institution/group)", "aliases": []},
                {"canonical": "'sociology' (concept)", "aliases": []},
            ]
        }
    )

    with pytest.raises(MergeResponseError):
        parse_merge_response(raw, members)

    nodes = parse_merge_response(raw, members, kinds)
    assert {n["canonical"] for n in nodes} == {"Sociology", "sociology"}


def test_parse_accepts_the_rendered_form_for_a_real_merge():
    members = ["Fifty-Three Years in Syria", "Fifty-three years in Syria"]
    kinds = dict.fromkeys(members, "work")
    raw = json.dumps(
        {
            "nodes": [
                {
                    "canonical": "'Fifty-Three Years in Syria' (work)",
                    "aliases": ["'Fifty-three years in Syria' (work)"],
                }
            ]
        }
    )

    nodes = parse_merge_response(raw, members, kinds)
    assert nodes == [
        {"canonical": "Fifty-Three Years in Syria", "aliases": ["Fifty-three years in Syria"]}
    ]


def test_a_real_surface_form_always_beats_another_surfaces_rendering():
    """No stripped-parenthetical heuristic: real surfaces end in parentheses
    too. A bare surface form must never lose to a rendered one."""
    members = ["Phelps-Brown and Hopkins (1956)", "Phelps-Brown"]
    kinds = {"Phelps-Brown": "person"}
    raw = json.dumps(
        {"nodes": [{"canonical": "Phelps-Brown and Hopkins (1956)", "aliases": ["Phelps-Brown"]}]}
    )

    nodes = parse_merge_response(raw, members, kinds)
    assert nodes == [{"canonical": "Phelps-Brown and Hopkins (1956)", "aliases": ["Phelps-Brown"]}]


def test_the_prompt_and_the_parse_share_one_renderer():
    """They cannot be allowed to drift: the parse only works because it knows
    exactly what the prompt put in front of the model."""
    kinds = {"Mao": "person"}
    assert f"- {render_member('Mao', kinds)}" in compose_merge_prompt(["Mao"], kinds)


def test_case_only_variants_can_both_be_placed():
    """`_normalize` casefolds, so `Slavery`/`slavery` shared one lookup key and
    the model's merge was silently dropped -- both surviving as separate
    canonical names, and later as separate wiki pages. The first corpus map
    carried 1,514 such pairs."""
    members = ["Slavery", "slavery"]
    raw = json.dumps({"nodes": [{"canonical": "Slavery", "aliases": ["slavery"]}]})

    assert parse_merge_response(raw, members) == [{"canonical": "Slavery", "aliases": ["slavery"]}]


def test_normalized_matching_still_absorbs_stray_whitespace_and_case():
    """The lenient path stays wherever it is unambiguous -- it is only refused
    when two members share the normalized key."""
    raw = json.dumps({"nodes": [{"canonical": "  mao   zedong ", "aliases": ["MAO"]}]})

    nodes = parse_merge_response(raw, ["Mao Zedong", "Mao"])
    assert nodes == [{"canonical": "Mao Zedong", "aliases": ["Mao"]}]
