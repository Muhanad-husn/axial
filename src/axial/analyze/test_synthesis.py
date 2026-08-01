"""Inner unit tests for the stage-4 synthesis pass (issue #256,
specs/PHASE-B.md §7.4/§7.11). Co-located under src/axial/analyze/ per the
repo's existing test layout (mirrors src/axial/analyze/test_assembly.py).

Covers plans/analysis-synthesis/02-synthesis-claim-graph.md's inner-loop
checklist: kind validation, grounds non-empty for a/b, ref_type/ref_id
resolution against a fixture vault, `names_touched` computed in code
(never trusted from the model), `claim_id` determinism/uniqueness, lens
resolution (named/unknown/absent), the prompt embedding evidence chunks, the
pass's own `pass_name` for `model_by_pass`/`reasoning_by_pass` routing, and
an unparseable response failing loudly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.analyze.assembly import EvidenceChunk, EvidenceSet
from axial.analyze.synthesis import (
    Ground,
    InvalidClaimConfidenceError,
    InvalidClaimKindError,
    InvalidGroundRefTypeError,
    SynthesisParseError,
    UngroundedClaimError,
    UnknownLensError,
    UnresolvableGroundError,
    compose_prompt,
    parse_synthesis_response,
    resolve_lens,
)
from axial.brief.intake import Brief
from axial.llm import SYNTHESIZE_PASS_NAME
from axial.model_json import ModelJsonError


def _chunk_frontmatter(
    *, chunk_id: str, names: list[str] | None = None, answers: dict[str, Any] | None = None
) -> dict[str, Any]:
    """A prose note in the shape `axial.materialize` writes today: source
    metadata plus the nested interrogation `answers` block (§7.15, Appendix H).
    `names` is the shorthand every test here needs -- the surface forms this
    note named, which is what `names_touched` resolves through the alias
    map."""
    note_answers: dict[str, Any] = {
        "claim": f"Claim of {chunk_id}.",
        "move": "stating a mechanism",
        "position_of": "the author",
        "names": [{"name": surface, "kind": "person"} for surface in (names or [])],
    }
    if answers is not None:
        note_answers.update(answers)
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
        "frame_version": "0.1",
        "answers": note_answers,
    }


def _write_name_layer(root: Path) -> Path:
    """Reconcile's alias map and index (§7.16) -- what `names_touched`
    resolves a surface form through, and the only tier it is allowed to use.
    "Tilly" is an ALIAS of "Charles Tilly", so a real alias-map hop is
    exercised rather than string equality."""
    names_dir = root / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    (names_dir / "alias_map.json").write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "canonical": "Charles Tilly",
                        "kind": "person",
                        "aliases": ["Tilly", "C. Tilly 1975"],
                    },
                    {"canonical": "Ibn Khaldun", "kind": "person", "aliases": []},
                ]
            }
        ),
        encoding="utf-8",
    )
    (names_dir / "index.json").write_text(
        json.dumps({"names": ["Charles Tilly", "Ibn Khaldun"]}), encoding="utf-8"
    )
    return names_dir


def _artifact_frontmatter(*, artifact_id: str, source_id: str) -> dict[str, Any]:
    return {
        "artifact_id": artifact_id,
        "artifact_role": "case-study",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "source_id": source_id,
        "section": "Synthetic Section",
        "retrievable": True,
        "cited_by": [],
    }


def _write_vault(
    root: Path, *, chunks: list[dict[str, Any]], artifacts: list[dict[str, Any]]
) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in chunks:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{frontmatter['chunk_id']}.md").write_text(text, encoding="utf-8")
    artifacts_dir = root / "vault" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    for frontmatter in artifacts:
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (artifacts_dir / f"{frontmatter['artifact_id']}.md").write_text(text, encoding="utf-8")
    return root / "vault"


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    chunks = [
        _chunk_frontmatter(chunk_id="synfix_001_syria_a", names=["Tilly"]),
        _chunk_frontmatter(chunk_id="synfix_002_iraq_a", names=["Ibn Khaldun"]),
        _chunk_frontmatter(
            chunk_id="synfix_003_two_names", names=["Tilly", "Ibn Khaldun", "Absurdistan"]
        ),
    ]
    artifacts = [_artifact_frontmatter(artifact_id="synfix_004_artifact", source_id="synfix")]
    return _write_vault(tmp_path, chunks=chunks, artifacts=artifacts)


@pytest.fixture
def names_dir(tmp_path: Path) -> Path:
    return _write_name_layer(tmp_path)


def _evidence_chunk(chunk_id: str, **answers: Any) -> EvidenceChunk:
    """An `EvidenceChunk` as `assemble_evidence` would have built it: source
    metadata plus the substantive answers only (an abstention never gets this
    far -- assembly dropped it)."""
    return EvidenceChunk(
        chunk_id=chunk_id,
        source_meta={"author": "A. Synthetic Author", "title": "A Synthetic Fixture Source"},
        answers=answers,
    )


@pytest.fixture
def evidence_set() -> EvidenceSet:
    return EvidenceSet(
        chunk_ids=["synfix_001_syria_a", "synfix_002_iraq_a"],
        chunks=[
            _evidence_chunk("synfix_001_syria_a", claim="Claim of synfix_001_syria_a."),
            _evidence_chunk("synfix_002_iraq_a", claim="Claim of synfix_002_iraq_a."),
        ],
        name_counts={},
    )


# The handle map a real `compose_prompt` call over `vault_dir`'s three
# chunks would hand out (issue #410) -- assigned in the same first-seen
# order `compose_prompt` itself walks. Most grounds-resolution tests below
# don't compose a real prompt (they only exercise `parse_synthesis_response`
# in isolation), so this fixed map stands in for whatever a real call would
# have produced, exactly the same way the old tests hardcoded the real
# `chunk_id` string directly.
_HANDLE_MAP = {
    "[c1]": "synfix_001_syria_a",
    "[c2]": "synfix_002_iraq_a",
    "[c3]": "synfix_003_two_names",
}


def _valid_response(**overrides: Any) -> str:
    body = {
        "claims": [
            {
                "text": "The corpus states that displacement reshaped local authority.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                "confidence": "medium",
            }
        ]
    }
    body.update(overrides)
    return json.dumps(body)


# ---------------------------------------------------------------------------
# kind validation
# ---------------------------------------------------------------------------


def test_rejects_a_claim_whose_kind_is_absent(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "Some claim.",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(InvalidClaimKindError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "Some claim." in str(exc_info.value) or "#1" in str(exc_info.value)


def test_rejects_a_claim_whose_kind_is_outside_a_b_c(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "Some claim.",
                "kind": "z",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(InvalidClaimKindError):
        parse_synthesis_response(raw, vault_dir=vault_dir)


# ---------------------------------------------------------------------------
# confidence validation -- exactly the §7.4 three-band vocabulary (#402)
# ---------------------------------------------------------------------------


def test_rejects_a_claim_whose_confidence_is_outside_the_three_bands(vault_dir: Path):
    """Issue #402: a real run emitted "medium-high", a fourth band §7.4
    never defines. The calibration gate correctly refused to score/impute
    it, but only at scoring time, after the record was already persisted --
    caught here instead, at generation."""
    raw = _valid_response(
        claims=[
            {
                "text": "Some claim.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
                "confidence": "medium-high",
            }
        ]
    )
    with pytest.raises(InvalidClaimConfidenceError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "medium-high" in str(exc_info.value)


def test_rejects_a_claim_whose_confidence_is_absent(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "Some claim.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
            }
        ]
    )
    with pytest.raises(InvalidClaimConfidenceError):
        parse_synthesis_response(raw, vault_dir=vault_dir)


def test_accepts_each_of_the_three_confidence_bands(vault_dir: Path):
    for band in ("high", "medium", "low"):
        raw = _valid_response(
            claims=[
                {
                    "text": "Some claim.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                    "confidence": band,
                }
            ]
        )
        claims = parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP)
        assert claims[0].confidence == band


# ---------------------------------------------------------------------------
# grounds non-empty for a/b, permitted empty for c
# ---------------------------------------------------------------------------


def test_rejects_an_a_claim_with_empty_grounds(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "An ungrounded source-says claim.",
                "kind": "a",
                "grounds": [],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(UngroundedClaimError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "An ungrounded source-says claim." in str(exc_info.value)


def test_rejects_a_b_claim_with_absent_grounds(vault_dir: Path):
    raw = _valid_response(
        claims=[{"text": "A cross-source inference.", "kind": "b", "confidence": "low"}]
    )
    with pytest.raises(UngroundedClaimError):
        parse_synthesis_response(raw, vault_dir=vault_dir)


def test_accepts_a_c_claim_with_empty_grounds(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A speculative extrapolation.",
                "kind": "c",
                "grounds": [],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(raw, vault_dir=vault_dir)
    assert len(claims) == 1
    assert claims[0].kind == "c"
    assert claims[0].grounds == []
    assert claims[0].names_touched == []


# ---------------------------------------------------------------------------
# grounds resolution against the vault
# ---------------------------------------------------------------------------


def test_a_grounds_entry_whose_ref_id_does_not_resolve_is_rejected(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing a hallucinated chunk.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "no_such_chunk"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "no_such_chunk" in str(exc_info.value)


def test_ref_type_outside_chunk_or_artifact_is_rejected(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim with a bogus ref_type.",
                "kind": "a",
                "grounds": [{"ref_type": "book", "ref_id": "synfix_001_syria_a"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(InvalidGroundRefTypeError):
        parse_synthesis_response(raw, vault_dir=vault_dir)


def test_an_artifact_ground_resolves(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim grounded in an artifact.",
                "kind": "a",
                "grounds": [{"ref_type": "artifact", "ref_id": "synfix_004_artifact"}],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(raw, vault_dir=vault_dir)
    assert claims[0].grounds == [Ground(ref_type="artifact", ref_id="synfix_004_artifact")]
    # An artifact ground names nothing of its own, so it contributes nothing.
    assert claims[0].names_touched == []


# ---------------------------------------------------------------------------
# opaque-handle resolution for CHUNK grounds (issue #410): the model is never
# shown a real chunk_id, only a short per-call handle (`compose_prompt`), so
# a `chunk` ref_id resolves ONLY by exact lookup in `handle_map` -- no fuzzy
# match, no suffix repair, nothing left to fuzz. Artifact grounds are
# unaffected (artifacts are never listed under a handle) and keep the DEC-42
# truncated-citation repair (`_resolve_truncated_ref_id`) unchanged: a real
# id runs to ~200 chars and the model sometimes echoes only the tail.
# ---------------------------------------------------------------------------


def test_a_cited_handle_that_maps_cleanly_resolves_to_the_real_chunk(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing a clean handle.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                "confidence": "medium",
            }
        ]
    )
    claims = parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP)
    # The stored ground carries the REAL chunk_id the handle stood for,
    # never the handle token itself.
    assert claims[0].grounds == [Ground(ref_type="chunk", ref_id="synfix_001_syria_a")]


def test_a_cited_handle_absent_from_the_handle_map_still_raises(vault_dir: Path):
    # "[c99]" was never assigned by compose_prompt -- an invented handle is
    # exactly as unresolvable as an invented id always was.
    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing an invented handle.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c99]"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP)
    assert "[c99]" in str(exc_info.value)


def test_a_real_full_chunk_id_no_longer_resolves_only_its_handle_does(vault_dir: Path):
    # Pins the mitigation directly: even the CORRECT, real chunk_id is
    # rejected once handles are in play, because it was never offered as a
    # citable id in the first place -- only its handle was. There is
    # nothing left for a model to transcribe, truncate, or blend.
    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing the real id instead of its handle.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP)
    assert "synfix_001_syria_a" in str(exc_info.value)


def test_a_unique_suffix_match_repairs_a_truncated_artifact_ref_id_to_the_full_id(tmp_path: Path):
    full_id = "Some Long Human Title - libgen.li-abc123def456_artifact_003"
    truncated_tail = "libgen.li-abc123def456_artifact_003"
    artifacts_fm = [_artifact_frontmatter(artifact_id=full_id, source_id="synfix")]
    vault_dir = _write_vault(tmp_path, chunks=[], artifacts=artifacts_fm)

    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing a truncated tail of a real long artifact id.",
                "kind": "a",
                "grounds": [{"ref_type": "artifact", "ref_id": truncated_tail}],
                "confidence": "medium",
            }
        ]
    )

    claims = parse_synthesis_response(raw, vault_dir=vault_dir)

    assert claims[0].grounds == [Ground(ref_type="artifact", ref_id=full_id)]


def test_an_artifact_ref_id_matching_two_or_more_real_ids_by_suffix_still_raises(tmp_path: Path):
    artifacts_fm = [
        _artifact_frontmatter(artifact_id="source-one_25_case_001", source_id="synfix"),
        _artifact_frontmatter(artifact_id="source-two_25_case_001", source_id="synfix"),
    ]
    vault_dir = _write_vault(tmp_path, chunks=[], artifacts=artifacts_fm)

    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing an ambiguous truncated artifact tail.",
                "kind": "a",
                "grounds": [{"ref_type": "artifact", "ref_id": "25_case_001"}],
                "confidence": "low",
            }
        ]
    )

    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "25_case_001" in str(exc_info.value)


def test_an_artifact_ref_id_matching_no_real_id_by_suffix_still_raises(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing a wholly invented, unmatched artifact tail.",
                "kind": "a",
                "grounds": [{"ref_type": "artifact", "ref_id": "zzz_totally_invented_999"}],
                "confidence": "low",
            }
        ]
    )
    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "zzz_totally_invented_999" in str(exc_info.value)


def test_a_unique_prefix_match_repairs_a_head_truncated_artifact_ref_id(tmp_path: Path):
    """The mirror image of the tail case (issue #524): the model emitted the
    head of a long id and dropped the order segment."""
    full_id = "Some Long Human Title - libgen.li-abc123def456_art_3"
    truncated_head = "Some Long Human Title - libgen.li-abc123def456"
    artifacts_fm = [_artifact_frontmatter(artifact_id=full_id, source_id="synfix")]
    vault_dir = _write_vault(tmp_path, chunks=[], artifacts=artifacts_fm)

    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing the head of a real long artifact id.",
                "kind": "a",
                "grounds": [{"ref_type": "artifact", "ref_id": truncated_head}],
                "confidence": "medium",
            }
        ]
    )

    claims = parse_synthesis_response(raw, vault_dir=vault_dir)

    assert claims[0].grounds == [Ground(ref_type="artifact", ref_id=full_id)]


def test_an_artifact_ref_id_matching_two_or_more_real_ids_by_prefix_still_raises(tmp_path: Path):
    artifacts_fm = [
        _artifact_frontmatter(artifact_id="src-digest_art_3", source_id="synfix"),
        _artifact_frontmatter(artifact_id="src-digest_art_4", source_id="synfix"),
    ]
    vault_dir = _write_vault(tmp_path, chunks=[], artifacts=artifacts_fm)

    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing an ambiguous truncated artifact head.",
                "kind": "a",
                "grounds": [{"ref_type": "artifact", "ref_id": "src-digest"}],
                "confidence": "low",
            }
        ]
    )

    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir)
    assert "src-digest" in str(exc_info.value)


# ---------------------------------------------------------------------------
# names_touched computed in code, through the alias map alone (issue #489)
# ---------------------------------------------------------------------------


def test_names_touched_resolves_a_surface_form_through_the_alias_map(
    vault_dir: Path, names_dir: Path
):
    """synfix_001's own `names` answer says "Tilly", which the index carries
    only as an ALIAS of "Charles Tilly". The claim touches the canonical."""
    raw = _valid_response(
        claims=[
            {
                "text": "A claim grounded in a note naming Tilly.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(
        raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP, names_dir=names_dir
    )
    assert claims[0].names_touched == ["Charles Tilly"]


def test_names_touched_computed_from_grounds_overrides_a_model_supplied_value(
    vault_dir: Path, names_dir: Path
):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim the model mismarks.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                "confidence": "low",
                # A model-supplied names_touched must be discarded, never
                # trusted -- the code recomputes it from the resolved grounds.
                "names_touched": ["Definitely Not Tilly"],
            }
        ]
    )
    claims = parse_synthesis_response(
        raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP, names_dir=names_dir
    )
    assert claims[0].names_touched == ["Charles Tilly"]


def test_names_touched_drops_a_surface_the_index_does_not_carry(vault_dir: Path, names_dir: Path):
    """§7.4: a surface the index does not carry is DROPPED rather than
    invented. synfix_003 names "Absurdistan", which no node carries -- and
    nothing here falls back to the embedding tier, which would land the claim
    on a plausible neighbour and fabricate coverage."""
    raw = _valid_response(
        claims=[
            {
                "text": "A claim grounded in a note naming an unknown surface.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c3]"}],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(
        raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP, names_dir=names_dir
    )
    assert claims[0].names_touched == ["Charles Tilly", "Ibn Khaldun"]


def test_names_touched_dedupes_across_grounds_and_is_order_stable(vault_dir: Path, names_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim spanning multiple chunks.",
                "kind": "b",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "[c3]"},
                    {"ref_type": "chunk", "ref_id": "[c1]"},
                ],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(
        raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP, names_dir=names_dir
    )
    # [c3] names Tilly + Ibn Khaldun (+ one unknown, dropped), [c1] names
    # Tilly -- first-seen order, deduped.
    assert claims[0].names_touched == ["Charles Tilly", "Ibn Khaldun"]


def test_names_touched_is_empty_when_the_vault_has_no_name_layer(vault_dir: Path, tmp_path: Path):
    """An empty/absent alias map resolves nothing, so every surface drops.
    Honest: the index carries no such name, so the claim touches none."""
    raw = _valid_response(
        claims=[
            {
                "text": "A claim over a vault with no name layer.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(
        raw,
        vault_dir=vault_dir,
        handle_map=_HANDLE_MAP,
        names_dir=tmp_path / "no-name-layer",
    )
    assert claims[0].names_touched == []


# ---------------------------------------------------------------------------
# claim_id determinism and uniqueness
# ---------------------------------------------------------------------------


def test_claim_id_is_deterministic_and_unique_across_the_graph(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "First claim.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                "confidence": "low",
            },
            {
                "text": "Second claim.",
                "kind": "c",
                "grounds": [],
                "confidence": "low",
            },
        ]
    )
    first_run = parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP)
    second_run = parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=_HANDLE_MAP)

    assert [c.claim_id for c in first_run] == [c.claim_id for c in second_run]
    assert len({c.claim_id for c in first_run}) == len(first_run)


# ---------------------------------------------------------------------------
# lens resolution
# ---------------------------------------------------------------------------


def test_resolve_lens_loads_a_named_lens():
    assert resolve_lens("political-economy") == "political-economy"


def test_resolve_lens_rejects_an_unknown_name():
    with pytest.raises(UnknownLensError) as exc_info:
        resolve_lens("not-a-real-lens")
    assert "not-a-real-lens" in str(exc_info.value)


def test_resolve_lens_selects_and_returns_a_lens_when_absent():
    selected = resolve_lens(None)
    assert selected
    assert isinstance(selected, str)


# ---------------------------------------------------------------------------
# prompt composition
# ---------------------------------------------------------------------------


def test_prompt_embeds_evidence_handles_and_text_never_the_real_chunk_id(
    evidence_set: EvidenceSet, vault_dir: Path
):
    # evidence_set's chunk_ids (synfix_001_syria_a, synfix_002_iraq_a) are
    # also real notes under vault_dir -- assembly.py's own EvidenceChunk
    # carries no chunk_text (by design), so the prompt must re-fetch the
    # real prose via get_chunk(vault_dir=...) rather than embedding only
    # tag facets. Issue #410: the id LABEL the model is shown is the short
    # opaque handle, never the real chunk_id -- there is nothing long to
    # transcribe, truncate, or blend across two similar sources.
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    composed = compose_prompt(brief, "political-economy", evidence_set, vault_dir=vault_dir)
    assert "chunk=[c1]" in composed.text
    assert "chunk=[c2]" in composed.text
    # The id LABEL is the handle; the real id is never offered as a citable
    # one. (That no real id appears ANYWHERE is the stronger property, pinned
    # by test_prompt_never_contains_the_real_long_chunk_id_anywhere below,
    # whose fixture prose does not embed its own id the way SENTINEL does.)
    assert "chunk=synfix_001_syria_a" not in composed.text
    assert "chunk=synfix_002_iraq_a" not in composed.text
    assert "SENTINEL_synfix_001_syria_a" in composed.text
    assert "SENTINEL_synfix_002_iraq_a" in composed.text
    assert "political-economy" in composed.text
    assert composed.handle_map == {
        "[c1]": "synfix_001_syria_a",
        "[c2]": "synfix_002_iraq_a",
    }


def test_prompt_never_contains_the_real_long_chunk_id_anywhere(tmp_path: Path):
    # Pins the specific #410 failure shape: two similar sources' long ids
    # (mirroring the real ayubi-1995/batatu-1999 pair) never appear ANYWHERE
    # in the prompt -- not as a label, not embedded in prose -- so the model
    # has nothing left to blend across them, and a response that "blends"
    # the two the way the real failure did can no longer even be expressed
    # as a valid citation.
    long_id_a = "ayubi-1995-16fd6a2e503f_105_the-conflict-with-israel_002"
    long_id_b = "batatu-1999-598624067df3_105_the-conflict-with-israel_002"
    chunks_fm = []
    for chunk_id in (long_id_a, long_id_b):
        frontmatter = _chunk_frontmatter(chunk_id=chunk_id, names=["Tilly"])
        # Deliberately does NOT embed the id in the prose (unlike the
        # SENTINEL fixture text above) -- a real chunk's prose never
        # contains its own id, so this is what a real "the id is nowhere in
        # the prompt" check needs.
        frontmatter["chunk_text"] = "Generic prose about the 1948 conflict."
        chunks_fm.append(frontmatter)
    vault_dir = _write_vault(tmp_path, chunks=chunks_fm, artifacts=[])
    evidence = EvidenceSet(
        chunk_ids=[long_id_a, long_id_b],
        chunks=[_evidence_chunk(chunk_id) for chunk_id in (long_id_a, long_id_b)],
        name_counts={},
    )
    brief = Brief(
        brief_id="synfix-brief-blend", case="Syria", request="How?", lens="political-economy"
    )
    composed = compose_prompt(brief, "political-economy", evidence, vault_dir=vault_dir)

    assert long_id_a not in composed.text
    assert long_id_b not in composed.text
    assert composed.handle_map == {"[c1]": long_id_a, "[c2]": long_id_b}

    # A "blended" id -- Ayubi's head, Batatu's tail, the real P2-04 shape --
    # is simply not a handle at all, so it fails to resolve rather than
    # silently landing on either scholar's real chunk.
    blended_id = "ayubi-1995-598624067df3_105_the-conflict-with-israel_002"
    raw = _valid_response(
        claims=[
            {
                "text": "A claim citing a blended cross-source id.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": blended_id}],
                "confidence": "medium",
            }
        ]
    )
    with pytest.raises(UnresolvableGroundError) as exc_info:
        parse_synthesis_response(raw, vault_dir=vault_dir, handle_map=composed.handle_map)
    assert blended_id in str(exc_info.value)


def test_prompt_forbids_parametric_memory_and_marks_cross_source_inference():
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    empty_evidence = EvidenceSet(chunk_ids=[], chunks=[], name_counts={})
    composed = compose_prompt(brief, "political-economy", empty_evidence)
    lowered = composed.text.lower()
    assert "parametric memory" in lowered
    assert "open web" in lowered
    assert "(b)" in composed.text


# ---------------------------------------------------------------------------
# the prompt answers the question (measured: 1 claim of kind "c" in 653
# across 34 persisted brief runs, 0.15% -- the prompt asked for axial coding
# over evidence and never asked the model to answer the brief's own request)
# ---------------------------------------------------------------------------


def _empty_evidence_prompt(request: str = "Did the state collapse or adapt?") -> str:
    brief = Brief(brief_id="synfix-brief", case="Syria", request=request, lens="political-economy")
    empty_evidence = EvidenceSet(chunk_ids=[], chunks=[], name_counts={})
    return compose_prompt(brief, "political-economy", empty_evidence).text


def test_prompt_carries_the_request_as_the_operative_task_not_a_bare_field():
    """The request must read as the job the model is doing, not a labelled
    field sitting beside Case/Lens the way `Request: "..."` used to."""
    text = _empty_evidence_prompt("Did the state collapse or adapt?")
    assert 'Request: "Did the state collapse or adapt?"' not in text
    assert "your task" in text.lower()
    assert '"Did the state collapse or adapt?"' in text
    assert "answer this question" in text.lower()


def test_prompt_instructs_commitment_and_stating_the_chosen_accounts_limits():
    """Two rubric lines a sealed peer reviewer failed in both arms: commits
    to one account and defends it throughout, and names the limits of the
    chosen account explicitly."""
    text = _empty_evidence_prompt().lower()
    assert "commit" in text
    assert "defend" in text
    assert "weak or fails" in text or "limits" in text


def test_prompt_describes_kind_c_as_the_analysts_own_judgment_not_speculation():
    """The persisted vocabulary value stays exactly "c" (parsing/validation
    is untouched, see test_rejects_a_claim_whose_kind_is_outside_a_b_c
    elsewhere in this file) -- only how the PROMPT describes that kind
    changes: it is the analyst's own judgment, never voiced as a source's
    assertion, and never called "speculation" to the model."""
    text = _empty_evidence_prompt()
    assert '"c"' in text
    assert "speculation" not in text.lower()
    assert "your own" in text.lower()
    assert "judgment" in text.lower() or "judgement" in text.lower()


def test_prompt_scopes_the_traceability_ban_to_a_and_b_only():
    """The regression this test locks: the prompt used to state a blanket
    "any assertion not traceable to a supplied grounds pointer is not a claim
    this pass may emit" up front, then offer (c) as a kind that "may carry
    partial or empty grounds" four paragraphs later -- two rules that cannot
    both be obeyed. The ban must attach to (a) and (b) specifically, and (c)
    must be explicitly exempted from it."""
    text = _empty_evidence_prompt()
    assert "any assertion not traceable to a supplied grounds pointer is not a claim" not in (
        text.lower()
    )
    assert "traceability rule above binds (a) and (b) only" in text
    assert "may carry partial or empty grounds" in text


# ---------------------------------------------------------------------------
# question_scope: the period/setting the QUESTION ITSELF states (soft
# favouring only -- never a filter, a threshold, or a numeric weight)
# ---------------------------------------------------------------------------


def test_compose_prompt_with_no_question_scope_is_the_plain_no_scope_form():
    """Omitting `question_scope` (the default, and every call site before
    this parameter existed) must render byte-identical to explicitly passing
    `None` -- there is no separate code path to drift out of sync."""
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    empty_evidence = EvidenceSet(chunk_ids=[], chunks=[], name_counts={})
    without_kwarg = compose_prompt(brief, "political-economy", empty_evidence).text
    with_none = compose_prompt(brief, "political-economy", empty_evidence, question_scope=None).text
    with_empty_subfields = compose_prompt(
        brief,
        "political-economy",
        empty_evidence,
        question_scope={"period": None, "setting": None},
    ).text
    assert without_kwarg == with_none == with_empty_subfields
    assert "states its own scope" not in without_kwarg


def test_compose_prompt_with_a_stated_scope_states_it_as_a_soft_preference():
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    empty_evidence = EvidenceSet(chunk_ids=[], chunks=[], name_counts={})
    text = compose_prompt(
        brief,
        "political-economy",
        empty_evidence,
        question_scope={"period": "2011-2021", "setting": "Syria"},
    ).text

    assert "states its own scope" in text
    assert "2011-2021" in text
    assert "Syria" in text
    # Soft favouring, never a filter -- off-scope evidence stays usable, and
    # a claim resting on it must say so rather than being excluded.
    assert "stays fully usable" in text
    assert "disclosure" in text.lower()
    # No filtering/exclusion/weighting language anywhere in the prompt.
    lowered = text.lower()
    for banned in ("exclude", "filter", "down-rank", "downrank", "threshold", "discard"):
        assert banned not in lowered, f"unexpected filtering language: {banned!r}"


def test_compose_prompt_scope_with_only_one_subfield_states_only_that_one():
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    empty_evidence = EvidenceSet(chunk_ids=[], chunks=[], name_counts={})
    text = compose_prompt(
        brief,
        "political-economy",
        empty_evidence,
        question_scope={"period": "2011-2021", "setting": None},
    ).text
    assert "period: 2011-2021" in text
    assert "setting:" not in text


# ---------------------------------------------------------------------------
# evidence-text budget cap (issue #358): an unbounded evidence set pushed a
# real synthesis prompt (plus the fixed 60k-token completion budget) past the
# model's context window on a real brief run against the real vault.
# ---------------------------------------------------------------------------


def _budget_chunk_frontmatter(*, chunk_id: str, text_len: int) -> dict[str, Any]:
    frontmatter = _chunk_frontmatter(chunk_id=chunk_id, names=["Tilly"])
    frontmatter["chunk_text"] = "X" * text_len
    return frontmatter


def _budget_evidence_set(chunk_ids: list[str]) -> EvidenceSet:
    return EvidenceSet(
        chunk_ids=chunk_ids,
        chunks=[_evidence_chunk(chunk_id) for chunk_id in chunk_ids],
        name_counts={},
    )


def test_compose_prompt_drops_chunks_once_the_evidence_char_budget_is_exceeded(tmp_path: Path):
    """Three 40-char chunks and a budget of 80 chars must include exactly
    the first two (in retrieval order) and drop the third -- never
    mid-text-truncate a chunk, never include the third out of order."""
    chunk_ids = ["synfix_budget_a", "synfix_budget_b", "synfix_budget_c"]
    chunks_fm = [_budget_chunk_frontmatter(chunk_id=cid, text_len=40) for cid in chunk_ids]
    vault_dir = _write_vault(tmp_path, chunks=chunks_fm, artifacts=[])
    evidence = _budget_evidence_set(chunk_ids)
    brief = Brief(
        brief_id="synfix-brief-budget", case="Syria", request="How?", lens="political-economy"
    )

    composed = compose_prompt(
        brief, "political-economy", evidence, vault_dir=vault_dir, evidence_char_budget=80
    )

    assert composed.handle_map == {"[c1]": "synfix_budget_a", "[c2]": "synfix_budget_b"}
    assert "[c1]" in composed.text
    assert "[c2]" in composed.text
    # The dropped chunk gets no handle at all -- nothing to cite it with.
    assert "[c3]" not in composed.text
    assert "synfix_budget_c" not in composed.text
    # The dropped chunk's full text never leaked into the prompt either.
    assert composed.text.count("X" * 40) == 2


def test_compose_prompt_within_budget_keeps_every_chunk(tmp_path: Path):
    """A generous budget that easily covers every chunk's text must include
    all of them -- the cap only ever removes what does not fit."""
    chunk_ids = ["synfix_budget_a", "synfix_budget_b"]
    chunks_fm = [_budget_chunk_frontmatter(chunk_id=cid, text_len=40) for cid in chunk_ids]
    vault_dir = _write_vault(tmp_path, chunks=chunks_fm, artifacts=[])
    evidence = _budget_evidence_set(chunk_ids)
    brief = Brief(
        brief_id="synfix-brief-budget-ok", case="Syria", request="How?", lens="political-economy"
    )

    composed = compose_prompt(
        brief, "political-economy", evidence, vault_dir=vault_dir, evidence_char_budget=1000
    )

    assert composed.handle_map == {"[c1]": "synfix_budget_a", "[c2]": "synfix_budget_b"}
    assert "[c1]" in composed.text
    assert "[c2]" in composed.text


def test_compose_prompt_evidence_budget_truncation_is_deterministic(tmp_path: Path):
    """The same over-budget evidence set composed twice must drop exactly
    the same chunks both times."""
    chunk_ids = ["synfix_budget_a", "synfix_budget_b", "synfix_budget_c"]
    chunks_fm = [_budget_chunk_frontmatter(chunk_id=cid, text_len=40) for cid in chunk_ids]
    vault_dir = _write_vault(tmp_path, chunks=chunks_fm, artifacts=[])
    evidence = _budget_evidence_set(chunk_ids)
    brief = Brief(
        brief_id="synfix-brief-budget-det", case="Syria", request="How?", lens="political-economy"
    )

    prompt_1 = compose_prompt(
        brief, "political-economy", evidence, vault_dir=vault_dir, evidence_char_budget=80
    )
    prompt_2 = compose_prompt(
        brief, "political-economy", evidence, vault_dir=vault_dir, evidence_char_budget=80
    )

    assert prompt_1.text == prompt_2.text
    assert prompt_1.handle_map == prompt_2.handle_map


def test_resolve_evidence_char_budget_reads_from_config_pipeline_yaml(tmp_path: Path):
    from axial.analyze.synthesis import _resolve_evidence_char_budget

    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        yaml.safe_dump({"synthesis": {"evidence_char_budget": 12345}}), encoding="utf-8"
    )

    assert _resolve_evidence_char_budget(config_path) == 12345


def test_resolve_evidence_char_budget_falls_back_to_default_when_config_absent(tmp_path: Path):
    from axial.analyze.synthesis import DEFAULT_EVIDENCE_CHAR_BUDGET, _resolve_evidence_char_budget

    missing_path = tmp_path / "does_not_exist.yaml"
    assert _resolve_evidence_char_budget(missing_path) == DEFAULT_EVIDENCE_CHAR_BUDGET


def test_resolve_evidence_char_budget_falls_back_when_synthesis_block_absent(tmp_path: Path):
    from axial.analyze.synthesis import DEFAULT_EVIDENCE_CHAR_BUDGET, _resolve_evidence_char_budget

    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"llm": {"provider": "openrouter"}}), encoding="utf-8")

    assert _resolve_evidence_char_budget(config_path) == DEFAULT_EVIDENCE_CHAR_BUDGET


# ---------------------------------------------------------------------------
# unparseable response fails loudly
# ---------------------------------------------------------------------------


def test_unparseable_response_raises_rather_than_returning_empty(vault_dir: Path):
    # Not-JSON-at-all propagates `ModelJsonError` unchanged (the same
    # convention `axial.brief.interrogate.parse_interrogation_response`
    # already follows) -- a shape violation on otherwise-valid JSON is what
    # raises the domain-specific `SynthesisParseError` subclasses instead.
    with pytest.raises(ModelJsonError):
        parse_synthesis_response("not json at all", vault_dir=vault_dir)


def test_missing_claims_key_raises(vault_dir: Path):
    with pytest.raises(SynthesisParseError):
        parse_synthesis_response(json.dumps({"not_claims": []}), vault_dir=vault_dir)


def test_empty_claims_list_is_accepted(vault_dir: Path):
    claims = parse_synthesis_response(json.dumps({"claims": []}), vault_dir=vault_dir)
    assert claims == []


def test_synthesize_pass_name_is_the_stable_dispatch_key():
    # Pins the pass_name literal itself -- model_by_pass/reasoning_by_pass
    # config routing depends on this string never drifting silently.
    assert SYNTHESIZE_PASS_NAME == "synthesize"
