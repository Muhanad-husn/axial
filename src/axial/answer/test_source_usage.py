"""Inner unit tests for the §7.13 source-usage disclosure (issues #265 and
#491). The outer acceptance test lives at tests/analysis/test_source_usage.py.

**Re-pointed at the store (DEC-75, issue #853).** The trajectory-driven
`names_queried`/denominator mechanism this file used to test (name-layer
tool calls, `where_names_meet` pairs, name pages) is retired along with the
name pages it read: the map arm makes no name-layer tool call, so
`trajectory` can never again carry a name query. `names_queried` is now the
union of each claim's own `names_touched` (§7.3), and the denominator is
read off a `notes.db` store (`axial.query.store.doors`/`concept_sources`)
built directly in these fixtures, never a name page.
"""

from __future__ import annotations

import json

import pytest
import yaml

from axial.answer.source_usage import (
    NAMES_TOUCHED_LABEL,
    compute_source_usage,
    derive_names_queried,
)
from axial.query import store as note_store

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


def _record(*, claims, disposition="proceed", brief=None):
    record = {
        "claims": claims,
        "trajectory": [],
        "interrogation": {"disposition": disposition},
    }
    if brief is not None:
        record["brief"] = brief
    return record


def _write_store(vault_dir, *, member_ids_by_name: dict, source_by_chunk: dict):
    """A minimal `notes.db` under `vault_dir`: one `names` row per key of
    `member_ids_by_name`, one `note_names` row per (chunk_id, name) pair, and
    one `notes`/`sources` row per distinct chunk_id/source_id -- exactly what
    `axial.query.store.doors`/`concept_sources` join over."""
    source_ids = sorted(set(source_by_chunk.values()))
    seen_chunks: set[str] = set()
    notes_rows = []
    note_names_rows = []
    for name, chunk_ids in member_ids_by_name.items():
        for chunk_id in chunk_ids:
            source_id = source_by_chunk[chunk_id]
            if chunk_id not in seen_chunks:
                notes_rows.append((chunk_id, source_id, "A Section", None, "A claim.", None))
                seen_chunks.add(chunk_id)
            note_names_rows.append((chunk_id, source_id, name, "person"))
    names_rows = [(name, "person", name.casefold()) for name in member_ids_by_name]
    source_rows = [(source_id, "An Author", "A Title", "1978", 1978) for source_id in source_ids]
    note_store.write_store(
        note_store.store_path(vault_dir),
        sources=source_rows,
        notes=notes_rows,
        names=names_rows,
        note_names=note_names_rows,
        note_arguing_against=[],
        note_citations=[],
    )


# -- names_queried derivation (DEC-75: read off claims, not trajectory) -------


def test_names_queried_is_the_union_of_names_touched():
    claims = [{"names_touched": [TILLY]}, {"names_touched": [BAYAT]}]
    assert derive_names_queried(claims) == [
        {"tool": NAMES_TOUCHED_LABEL, "args": {"canonical": BAYAT}},
        {"tool": NAMES_TOUCHED_LABEL, "args": {"canonical": TILLY}},
    ]


def test_names_queried_deduplicates_a_name_touched_by_two_claims():
    claims = [{"names_touched": [TILLY]}, {"names_touched": [TILLY]}]
    assert derive_names_queried(claims) == [
        {"tool": NAMES_TOUCHED_LABEL, "args": {"canonical": TILLY}}
    ]


def test_names_queried_is_deterministic_and_ascending():
    claims = [{"names_touched": [TILLY, BAYAT]}]
    first = derive_names_queried(claims)
    assert first == derive_names_queried(claims)
    assert [entry["args"]["canonical"] for entry in first] == [BAYAT, TILLY]


def test_a_claim_with_no_names_touched_contributes_nothing():
    assert derive_names_queried([{"names_touched": []}, {}]) == []


# -- source_id resolution ------------------------------------------------------


def test_evidence_fold_resolves_chunk_grounds_by_parsing_the_chunk_id(tmp_path):
    _write_chunk_note(tmp_path / "prose", "tilly_0_intro_001")
    record = _record(claims=[{"grounds": [_chunk_ground("tilly_0_intro_001")]}])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert [s["source_id"] for s in result["sources"]] == ["tilly"]


def test_evidence_fold_resolves_artifact_grounds_via_artifact_frontmatter(tmp_path):
    _write_artifact_note(tmp_path / "artifacts", "artifact-001", source_id="gellner")
    record = _record(claims=[{"grounds": [_artifact_ground("artifact-001")]}])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert [s["source_id"] for s in result["sources"]] == ["gellner"]


# -- evidence fold: dedup + shares sum to 1.0 ----------------------------------


def test_evidence_fold_counts_a_chunk_cited_by_two_claims_once():
    claims = [
        {"grounds": [_chunk_ground("tilly_0_a_001")]},
        {"grounds": [_chunk_ground("tilly_0_a_001"), _chunk_ground("tilly_0_a_002")]},
    ]
    result = compute_source_usage(_record(claims=claims), vault_dir=None)
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
    result = compute_source_usage(_record(claims=claims), vault_dir=None)
    assert sum(s["evidence_share"] for s in result["sources"]) == pytest.approx(1.0)


# -- the denominator, read off the store (DEC-75) ------------------------------


def test_available_count_is_the_sum_across_the_names_touched(tmp_path):
    """§7.13's stated analogue: a source the run under-drew on still gets an
    honest, non-zero denominator when the corpus held it."""
    _write_store(
        tmp_path,
        member_ids_by_name={
            TILLY: ["tilly_0_a_001", "tilly_0_a_002"],
            BAYAT: ["bayat_0_a_001"],
        },
        source_by_chunk={
            "tilly_0_a_001": "tilly",
            "tilly_0_a_002": "tilly",
            "bayat_0_a_001": "bayat",
        },
    )
    claims = [{"names_touched": [TILLY, BAYAT], "grounds": [_chunk_ground("tilly_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {TILLY: 2, BAYAT: 1}
    tilly = result["sources"][0]
    assert tilly["evidence_share"] == 1.0
    assert tilly["available_chunk_count"] == 2
    assert tilly["available_share"] == pytest.approx(2 / 3)
    # Drawn on harder than its availability explains -- the §7.13 signal.
    assert tilly["usage_ratio"] == pytest.approx(1.5)


def test_a_note_that_is_a_member_of_two_touched_names_is_summed_once_per_name(tmp_path):
    """DEC-75's own disclosed change from the retired chunk-level union
    (module docstring, `axial.answer.source_usage`): a note naming two
    touched names is counted once per name, not once overall."""
    _write_store(
        tmp_path,
        member_ids_by_name={TILLY: ["tilly_0_a_001"], BAYAT: ["tilly_0_a_001"]},
        source_by_chunk={"tilly_0_a_001": "tilly"},
    )
    claims = [{"names_touched": [TILLY, BAYAT], "grounds": [_chunk_ground("tilly_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {TILLY: 1, BAYAT: 1}
    # Summed across both touched names, not de-duplicated to 1.
    assert result["sources"][0]["available_chunk_count"] == 2
    assert result["sources"][0]["available_share"] == 1.0


def test_the_per_name_contribution_is_disclosed_so_a_hub_name_is_visible(tmp_path):
    """One hub name can be most of the corpus (`Syria`: 962 of 6,148 live
    prose notes). The per-name contribution is recorded so a denominator
    inflated by one name is legible as data, not only in the ratios it
    flattens."""
    hub_members = [f"hub_0_a_{i:03d}" for i in range(20)]
    source_by_chunk = {chunk_id: "hub" for chunk_id in hub_members}
    source_by_chunk["tilly_0_a_001"] = "tilly"
    _write_store(
        tmp_path,
        member_ids_by_name={"Syria": hub_members, TILLY: ["tilly_0_a_001"]},
        source_by_chunk=source_by_chunk,
    )
    claims = [{"names_touched": ["Syria", TILLY], "grounds": [_chunk_ground("tilly_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {"Syria": 20, TILLY: 1}


def test_a_touched_name_with_no_door_contributes_nothing(tmp_path):
    """A canonical the store carries no door for is simply absent from the
    denominator, never a fabricated 0 or a raised error."""
    _write_store(
        tmp_path,
        member_ids_by_name={TILLY: ["tilly_0_a_001"]},
        source_by_chunk={"tilly_0_a_001": "tilly"},
    )
    claims = [
        {"names_touched": [TILLY, "Nobody"], "grounds": [_chunk_ground("tilly_0_a_001")]}
    ]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    assert result["denominator_by_name"] == {TILLY: 1}


# -- usage_ratio ----------------------------------------------------------------


def test_usage_ratio_and_available_are_null_not_zero_when_the_run_touched_no_name(tmp_path):
    """A run whose claims touch no name at all (issue #584: the map arm's
    own claims may carry an empty `names_touched`) has no denominator at
    all -- `available_chunk_count` and `available_share` are `None`, an
    unknown, not a measured `0`, and `usage_ratio` is `None` for the same
    reason it always was."""
    _write_chunk_note(tmp_path / "prose", "other_0_a_001")
    claims = [{"grounds": [_chunk_ground("zaum_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    zaum = result["sources"][0]
    assert zaum["available_chunk_count"] is None
    assert zaum["available_share"] is None
    assert zaum["usage_ratio"] is None


def test_source_drawn_on_but_absent_from_every_touched_name_has_zero_available(tmp_path):
    _write_store(
        tmp_path,
        member_ids_by_name={TILLY: ["known_0_a_001"]},
        source_by_chunk={"known_0_a_001": "known"},
    )
    claims = [
        {
            "names_touched": [TILLY],
            "grounds": [_chunk_ground("known_0_a_001"), _chunk_ground("unmatched_0_a_001")],
        }
    ]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    by_source = {s["source_id"]: s for s in result["sources"]}
    assert by_source["unmatched"]["available_chunk_count"] == 0
    assert by_source["unmatched"]["usage_ratio"] is None


def test_source_in_the_denominator_but_absent_from_evidence_gets_no_entry(tmp_path):
    _write_store(
        tmp_path,
        member_ids_by_name={TILLY: ["cited_0_a_001", "uncited_0_a_001"]},
        source_by_chunk={"cited_0_a_001": "cited", "uncited_0_a_001": "uncited"},
    )
    claims = [{"names_touched": [TILLY], "grounds": [_chunk_ground("cited_0_a_001")]}]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)

    assert {s["source_id"] for s in result["sources"]} == {"cited"}


# -- empty sources on refuse / no grounds --------------------------------------


def test_sources_is_empty_on_refuse_but_names_queried_still_populated():
    record = _record(claims=[{"names_touched": [TILLY]}], disposition="refuse")

    result = compute_source_usage(record, vault_dir=None)
    assert result["sources"] == []
    assert result["names_queried"] == [{"tool": NAMES_TOUCHED_LABEL, "args": {"canonical": TILLY}}]


def test_sources_is_empty_when_claims_carry_no_grounds():
    record = _record(claims=[{"grounds": []}], disposition="proceed")
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
    record = _record(claims=[{"grounds": [_chunk_ground("gellner_0_a_001")]}])

    result = compute_source_usage(record, vault_dir=tmp_path)
    assert result["sources"][0]["source_id"] == "gellner"


# -- determinism ----------------------------------------------------------------


def test_source_usage_is_byte_identical_across_repeat_runs(tmp_path):
    members = [f"tilly_0_a_{i:03d}" for i in range(22)]
    _write_store(
        tmp_path,
        member_ids_by_name={TILLY: members},
        source_by_chunk={chunk_id: "tilly" for chunk_id in members},
    )
    claims = [
        {
            "names_touched": [TILLY],
            "grounds": [_chunk_ground("tilly_0_a_000"), _chunk_ground("other_0_a_000")],
        }
    ]
    record = _record(claims=claims)

    first = compute_source_usage(record, vault_dir=tmp_path)
    second = compute_source_usage(record, vault_dir=tmp_path)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# -- gates nothing ---------------------------------------------------------------


def test_full_concentration_on_one_source_produces_no_failure(tmp_path):
    _write_store(
        tmp_path,
        member_ids_by_name={TILLY: ["gellner_0_a_001", "gellner_0_a_002"]},
        source_by_chunk={"gellner_0_a_001": "gellner", "gellner_0_a_002": "gellner"},
    )
    claims = [
        {"names_touched": [TILLY], "grounds": [_chunk_ground("gellner_0_a_001")]},
        {"names_touched": [TILLY], "grounds": [_chunk_ground("gellner_0_a_002")]},
    ]
    result = compute_source_usage(_record(claims=claims), vault_dir=tmp_path)
    assert result["sources"][0]["evidence_share"] == 1.0
    assert result["sources"][0]["usage_ratio"] == pytest.approx(1.0)


# -- issue #639: weights disclosure ----------------------------------------------


def test_weights_defaults_to_empty_when_the_record_carries_no_brief():
    record = _record(claims=[])
    assert compute_source_usage(record, vault_dir=None)["weights"] == {}


def test_weights_defaults_to_empty_when_the_brief_supplied_none():
    record = _record(claims=[], brief={"case": "Syria", "weights": {}})
    assert compute_source_usage(record, vault_dir=None)["weights"] == {}


def test_weights_are_disclosed_verbatim_from_the_brief():
    record = _record(claims=[], brief={"case": "Syria", "weights": {"beshara-2011": 0.1}})
    assert compute_source_usage(record, vault_dir=None)["weights"] == {"beshara-2011": 0.1}


def test_weights_are_disclosed_even_on_refuse():
    record = _record(
        claims=[{"names_touched": [TILLY]}],
        disposition="refuse",
        brief={"weights": {"beshara-2011": 0.1}},
    )
    result = compute_source_usage(record, vault_dir=None)
    assert result["sources"] == []
    assert result["weights"] == {"beshara-2011": 0.1}
