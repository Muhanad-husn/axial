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
    DEFAULT_EVIDENCE_TIER,
    DEFAULT_MEMBER_CHAR_BUDGET,
    EVIDENCE_TIER_SECTION,
    EVIDENCE_TIER_SOURCE,
    EVIDENCE_TIER_WINDOW,
    EVIDENCE_WINDOW_CHARS,
    EVIDENCE_WINDOW_MAX_MENTIONS,
    MergeBatch,
    MergeResponseError,
    _resolve_merge_tightness,
    _seed_groups,
    _stale_evidence_tier_reasks,
    build_alias_map_nodes,
    build_batches,
    build_evidence_index,
    compose_merge_prompt,
    render_member,
    parse_merge_response,
    purge_decisions,
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


# ---------------------------------------------------------------------------
# Issue #449: evidence tiers -- source, section, window
# ---------------------------------------------------------------------------


def _write_chunk_fixture(chunks_dir: Path, source_id: str, records: list[dict]) -> None:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    with (chunks_dir / f"{source_id}.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def test_the_shipped_default_evidence_tier_is_the_cheapest():
    """D10-style "start loose" applies here too: ship the tier that costs
    zero file I/O, and let the founder's own measurement run pick further."""
    assert DEFAULT_EVIDENCE_TIER == EVIDENCE_TIER_SOURCE


def test_tier_1_source_provenance_costs_zero_file_io(tmp_path: Path):
    """Tier 1 needs nothing from `data/chunks/`: source_id lives inside
    chunk_id itself. Pointing at a chunks_dir that doesn't even exist must
    not raise, and the source book(s) must still show up."""
    chunk_ids_by_surface = {
        "Table 4.1": ("mann-v2-1993-ec759675dcbd_56_2-pre-1792-militarism_002",)
    }

    evidence = build_evidence_index(
        chunk_ids_by_surface, tier=EVIDENCE_TIER_SOURCE, chunks_dir=tmp_path / "no-such-dir"
    )

    assert evidence["Table 4.1"] == "(in mann-v2-1993-ec759675dcbd)"


def test_tier_2_adds_section_titles_from_the_chunk_file(tmp_path: Path):
    _write_chunk_fixture(
        tmp_path,
        "src1-aaaaaaaaaaaa",
        [
            {
                "chunk_id": "src1-aaaaaaaaaaaa_1_intro_001",
                "section": "Introduction",
                "section_order": "1",
                "text": "Adam Smith argued for free trade.",
            }
        ],
    )
    chunk_ids_by_surface = {"Adam Smith": ("src1-aaaaaaaaaaaa_1_intro_001",)}

    evidence = build_evidence_index(
        chunk_ids_by_surface, tier=EVIDENCE_TIER_SECTION, chunks_dir=tmp_path
    )

    assert evidence["Adam Smith"] == "(in src1-aaaaaaaaaaaa; under Introduction)"


def test_tier_3_adds_a_capped_window_around_the_mention(tmp_path: Path):
    long_text = ("padding " * 100) + "Anthony D. Smith wrote about nationalism." + (" more" * 100)
    _write_chunk_fixture(
        tmp_path,
        "src2-bbbbbbbbbbbb",
        [
            {
                "chunk_id": "src2-bbbbbbbbbbbb_1_nations_001",
                "section": "Nations",
                "section_order": "1",
                "text": long_text,
            }
        ],
    )
    chunk_ids_by_surface = {"Anthony D. Smith": ("src2-bbbbbbbbbbbb_1_nations_001",)}

    evidence = build_evidence_index(
        chunk_ids_by_surface, tier=EVIDENCE_TIER_WINDOW, chunks_dir=tmp_path
    )

    rendered = evidence["Anthony D. Smith"]
    assert "in src2-bbbbbbbbbbbb" in rendered
    assert "under Nations" in rendered
    assert "e.g." in rendered
    assert "Anthony D. Smith wrote about nationalism" in rendered
    # The window itself, quoted, never exceeds the char cap plus its own
    # ellipsis markers.
    window = rendered.split("e.g. ")[1].strip(")")
    for snippet in window.split(" / "):
        assert len(snippet.strip('"').replace("...", "")) <= EVIDENCE_WINDOW_CHARS


def test_tier_3_never_carries_more_than_two_windows(tmp_path: Path):
    """CIP's own rule (`CIP_Curation_Operations_Manual.md` §2.4.2): at most
    two short snippets per entity, however many mentions the corpus has."""
    records = [
        {
            "chunk_id": f"src3-cccccccccccc_{index}_section_001",
            "section": f"Section {index}",
            "section_order": str(index),
            "text": f"Robin Cohen appears here, mention number {index}.",
        }
        for index in range(1, 6)
    ]
    _write_chunk_fixture(tmp_path, "src3-cccccccccccc", records)
    chunk_ids_by_surface = {
        "Robin Cohen": tuple(record["chunk_id"] for record in records),
    }

    evidence = build_evidence_index(
        chunk_ids_by_surface, tier=EVIDENCE_TIER_WINDOW, chunks_dir=tmp_path
    )

    windows = evidence["Robin Cohen"].split("e.g. ")[1].strip(")").split(" / ")
    assert len(windows) == EVIDENCE_WINDOW_MAX_MENTIONS


def test_a_missing_chunk_artifact_degrades_to_the_tiers_it_can_still_answer(tmp_path: Path):
    """A source whose chunk file never made it to this chunks_dir (or was
    cleaned up) must not crash tier 2/3 -- it just contributes no section or
    window evidence, same as #446's own "no cluster to decide" tolerance."""
    chunk_ids_by_surface = {"Ghost Source": ("ghost-source-000000000000_1_intro_001",)}

    evidence = build_evidence_index(
        chunk_ids_by_surface, tier=EVIDENCE_TIER_WINDOW, chunks_dir=tmp_path / "empty"
    )

    assert evidence["Ghost Source"] == "(in ghost-source-000000000000)"


def test_evidence_is_folded_into_the_one_rendered_member_line():
    """Trap 1: evidence rides inside `render_member`'s own output, so the
    parse's round-trip acceptance (`render_member` reused verbatim) covers
    it for free -- no second echo format for the model to get right."""
    evidence = {"Table 4.1": "(in doe-2001-aaaaaaaaaaaa, smith-1998-bbbbbbbbbbbb)"}
    kinds = {"Table 4.1": "concept"}

    rendered = render_member("Table 4.1", kinds, evidence)

    assert rendered == "'Table 4.1' (concept) (in doe-2001-aaaaaaaaaaaa, smith-1998-bbbbbbbbbbbb)"
    assert f"- {rendered}" in compose_merge_prompt(["Table 4.1"], kinds, evidence)


def test_render_parse_round_trip_survives_evidence_attached():
    """The 2.89% failure mode (issue #416) generalizes: whatever
    `render_member` puts in front of the model with evidence attached, the
    parse must accept back verbatim."""
    members = ["Table 4.1", "Fig. 4.1"]
    kinds = {"Table 4.1": "concept", "Fig. 4.1": "concept"}
    evidence = {
        "Table 4.1": "(in doe-2001-aaaaaaaaaaaa, smith-1998-bbbbbbbbbbbb)",
        "Fig. 4.1": "(in doe-2001-aaaaaaaaaaaa)",
    }
    echoed_a = render_member("Table 4.1", kinds, evidence)
    echoed_b = render_member("Fig. 4.1", kinds, evidence)
    raw = json.dumps({"nodes": [{"canonical": echoed_a, "aliases": [echoed_b]}]})

    with pytest.raises(MergeResponseError):
        parse_merge_response(raw, members, kinds)  # no evidence -> doesn't match

    nodes = parse_merge_response(raw, members, kinds, evidence)
    assert nodes == [{"canonical": "Table 4.1", "aliases": ["Fig. 4.1"]}]


def test_char_budget_counts_the_rendered_length_not_the_bare_surface_form():
    """Trap 2: a bare-length count (`len("a")`, `len("b")`, ...) would let
    all four members fit comfortably under a 150-char budget -- they are
    single letters. Once evidence is attached, each RENDERED line is ~57
    chars, and only two fit together, so the same four members must split
    into two batches once the budget counts what was actually sent."""
    kinds = dict.fromkeys("abcd", None)
    evidence = {surface: f"({surface * 50})" for surface in "abcd"}
    labels = [0, 0, 0, 0]
    surface_forms = list("abcd")

    with_evidence = build_batches(labels, surface_forms, kinds, evidence, member_char_budget=150)
    assert len(with_evidence) == 2, "the rendered length must be what is bounded, not len('a')"
    assert sorted(m for batch in with_evidence for m in batch.members) == surface_forms

    bare_only = build_batches(labels, surface_forms, kinds, member_char_budget=150)
    assert len(bare_only) == 1, "without evidence the same budget holds all four bare forms"


def test_batch_key_changes_when_evidence_changes():
    """Trap 3: a different prompt must be a different decision, so a
    re-decide is forced when evidence is added -- an unchanged member list
    with evidence attached must NOT silently reuse the bare-name decision."""
    labels = [0, 0]
    surface_forms = ["a", "b"]
    kinds = {"a": None, "b": None}

    bare = build_batches(labels, surface_forms)[0]
    with_evidence = build_batches(
        labels, surface_forms, kinds, {"a": "(in src1)", "b": "(in src2)"}
    )[0]
    different_evidence = build_batches(
        labels, surface_forms, kinds, {"a": "(in src1)", "b": "(in src3)"}
    )[0]

    assert bare.key != with_evidence.key
    assert with_evidence.key != different_evidence.key


# ---------------------------------------------------------------------------
# Issue #449's rollout hazard: a bare-name decision log, an evidence-tier
# change, and the gate that keeps the re-ask from being silent
# ---------------------------------------------------------------------------


def test_stale_evidence_tier_reasks_finds_a_batch_by_bare_membership_not_key():
    """The whole point: a batch whose CURRENT key is pending (never decided
    under this exact kind/evidence rendering) is still recognizable as
    "already decided, just at a different tier" by its bare member list,
    which every decision record carries regardless of tier."""
    pending = [MergeBatch(0, ("a", "b"), ("'a' (in src1)", "'b' (in src1)"))]
    decisions = {
        "old-bare-key": {
            "batch_key": "old-bare-key",
            "members": ["a", "b"],
            "nodes": [{"canonical": "a", "aliases": ["b"]}],
            # No "evidence_tier" at all -- every real pre-#449 record.
        }
    }

    stale_batches, stale_keys = _stale_evidence_tier_reasks(pending, decisions, evidence_tier=1)

    assert stale_batches == pending
    assert stale_keys == {"old-bare-key"}


def test_stale_evidence_tier_reasks_ignores_a_genuinely_new_cluster():
    """A pending batch with no bare-membership match anywhere in the
    decision log is a genuinely new cluster (tightness dial moved, or the
    corpus grew) -- ordinary churn, not this hazard, and must not be
    flagged."""
    pending = [MergeBatch(0, ("x", "y"), ("'x'", "'y'"))]
    decisions = {
        "old-bare-key": {
            "batch_key": "old-bare-key",
            "members": ["a", "b"],
            "nodes": [],
        }
    }

    stale_batches, stale_keys = _stale_evidence_tier_reasks(pending, decisions, evidence_tier=1)

    assert stale_batches == []
    assert stale_keys == set()


def test_stale_evidence_tier_reasks_ignores_a_batch_already_decided_at_the_same_tier():
    """A record stamped with the SAME evidence_tier this run wants is not
    stale -- but note it would also already be `reused` by key in the
    normal case; this only matters for the rare case where the rendered
    kind/evidence differ even at the same nominal tier."""
    pending = [MergeBatch(0, ("a", "b"), ("'a' (in src1)", "'b' (in src1)"))]
    decisions = {
        "some-key": {
            "batch_key": "some-key",
            "members": ["a", "b"],
            "nodes": [],
            "evidence_tier": 1,
        }
    }

    stale_batches, stale_keys = _stale_evidence_tier_reasks(pending, decisions, evidence_tier=1)

    assert stale_batches == []
    assert stale_keys == set()


def test_purge_decisions_removes_only_the_named_keys(tmp_path: Path):
    path = tmp_path / "merge_decisions.jsonl"
    records = [
        {"batch_key": "keep-1", "members": ["a"], "nodes": []},
        {"batch_key": "purge-me", "members": ["b"], "nodes": []},
        {"batch_key": "keep-2", "members": ["c"], "nodes": []},
    ]
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    removed = purge_decisions(path, {"purge-me"})

    assert removed == 1
    remaining = [json.loads(line)["batch_key"] for line in path.read_text("utf-8").splitlines()]
    assert remaining == ["keep-1", "keep-2"]


def test_purge_decisions_is_a_no_op_on_a_path_that_does_not_exist_yet(tmp_path: Path):
    assert purge_decisions(tmp_path / "no-such-file.jsonl", {"anything"}) == 0
