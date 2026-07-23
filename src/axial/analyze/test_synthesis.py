"""Inner unit tests for the stage-4 synthesis pass (issue #256,
specs/PHASE-B.md §7.4/§7.11). Co-located under src/axial/analyze/ per the
repo's existing test layout (mirrors src/axial/analyze/test_assembly.py).

Covers plans/analysis-synthesis/02-synthesis-claim-graph.md's inner-loop
checklist: kind validation, grounds non-empty for a/b, ref_type/ref_id
resolution against a fixture vault, `polities_touched` computed in code
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
    *, chunk_id: str, polities_touched: list[str], role_in_argument: str = "role:claim"
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
        "role_in_argument": role_in_argument,
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {
            "value": "scope:country-case",
            "polity": polities_touched[0] if polities_touched else None,
        },
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }


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
        _chunk_frontmatter(chunk_id="synfix_001_syria_a", polities_touched=["Syria"]),
        _chunk_frontmatter(chunk_id="synfix_002_iraq_a", polities_touched=["Iraq"]),
        _chunk_frontmatter(
            chunk_id="synfix_003_two_polities", polities_touched=["Syria", "Lebanon"]
        ),
    ]
    artifacts = [_artifact_frontmatter(artifact_id="synfix_004_artifact", source_id="synfix")]
    return _write_vault(tmp_path, chunks=chunks, artifacts=artifacts)


@pytest.fixture
def evidence_set() -> EvidenceSet:
    return EvidenceSet(
        chunk_ids=["synfix_001_syria_a", "synfix_002_iraq_a"],
        chunks=[
            EvidenceChunk(
                chunk_id="synfix_001_syria_a",
                polities_touched=["Syria"],
                role_in_argument="role:claim",
                theory_school={"primary": "school:synthetic-institutionalist"},
                claim_type={"primary": "claim:causal"},
                empirical_scope={"value": "scope:country-case"},
            ),
            EvidenceChunk(
                chunk_id="synfix_002_iraq_a",
                polities_touched=["Iraq"],
                role_in_argument="role:claim",
                theory_school={"primary": "school:synthetic-institutionalist"},
                claim_type={"primary": "claim:causal"},
                empirical_scope={"value": "scope:country-case"},
            ),
        ],
        polity_coverage={},
    )


def _valid_response(**overrides: Any) -> str:
    body = {
        "claims": [
            {
                "text": "The corpus states that displacement reshaped local authority.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
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
    assert claims[0].polities_touched == []


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
    # An artifact ground carries no polities_touched facet of its own.
    assert claims[0].polities_touched == []


# ---------------------------------------------------------------------------
# polities_touched computed in code
# ---------------------------------------------------------------------------


def test_polities_touched_computed_from_grounds_chunks_overrides_model_value(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim the model mismarks.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
                "confidence": "low",
                # A model-supplied polities_touched must be discarded, never
                # trusted -- the code recomputes it from the resolved grounds.
                "polities_touched": ["Definitely Not Syria"],
            }
        ]
    )
    claims = parse_synthesis_response(raw, vault_dir=vault_dir)
    assert claims[0].polities_touched == ["Syria"]


def test_polities_touched_dedupes_across_grounds_and_is_order_stable(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "A claim spanning multiple chunks.",
                "kind": "b",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "synfix_003_two_polities"},
                    {"ref_type": "chunk", "ref_id": "synfix_001_syria_a"},
                ],
                "confidence": "low",
            }
        ]
    )
    claims = parse_synthesis_response(raw, vault_dir=vault_dir)
    # synfix_003 touches [Syria, Lebanon], synfix_001 touches [Syria] --
    # first-seen order, deduped: Syria, Lebanon.
    assert claims[0].polities_touched == ["Syria", "Lebanon"]


# ---------------------------------------------------------------------------
# claim_id determinism and uniqueness
# ---------------------------------------------------------------------------


def test_claim_id_is_deterministic_and_unique_across_the_graph(vault_dir: Path):
    raw = _valid_response(
        claims=[
            {
                "text": "First claim.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": "synfix_001_syria_a"}],
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
    first_run = parse_synthesis_response(raw, vault_dir=vault_dir)
    second_run = parse_synthesis_response(raw, vault_dir=vault_dir)

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


def test_prompt_embeds_evidence_chunk_ids_and_text(evidence_set: EvidenceSet, vault_dir: Path):
    # evidence_set's chunk_ids (synfix_001_syria_a, synfix_002_iraq_a) are
    # also real notes under vault_dir -- assembly.py's own EvidenceChunk
    # carries no chunk_text (by design), so the prompt must re-fetch the
    # real prose via get_chunk(vault_dir=...) rather than embedding only
    # tag facets.
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    prompt = compose_prompt(brief, "political-economy", evidence_set, vault_dir=vault_dir)
    assert "synfix_001_syria_a" in prompt
    assert "synfix_002_iraq_a" in prompt
    assert "SENTINEL_synfix_001_syria_a" in prompt
    assert "SENTINEL_synfix_002_iraq_a" in prompt
    assert "political-economy" in prompt


def test_prompt_forbids_parametric_memory_and_marks_cross_source_inference():
    brief = Brief(brief_id="synfix-brief", case="Syria", request="How?", lens="political-economy")
    empty_evidence = EvidenceSet(chunk_ids=[], chunks=[], polity_coverage={})
    prompt = compose_prompt(brief, "political-economy", empty_evidence)
    lowered = prompt.lower()
    assert "parametric memory" in lowered
    assert "open web" in lowered
    assert "(b)" in prompt


# ---------------------------------------------------------------------------
# evidence-text budget cap (issue #358): an unbounded evidence set pushed a
# real synthesis prompt (plus the fixed 60k-token completion budget) past the
# model's context window on a real brief run against the real vault.
# ---------------------------------------------------------------------------


def _budget_chunk_frontmatter(*, chunk_id: str, text_len: int) -> dict[str, Any]:
    frontmatter = _chunk_frontmatter(chunk_id=chunk_id, polities_touched=["Syria"])
    frontmatter["chunk_text"] = "X" * text_len
    return frontmatter


def _budget_evidence_set(chunk_ids: list[str]) -> EvidenceSet:
    return EvidenceSet(
        chunk_ids=chunk_ids,
        chunks=[
            EvidenceChunk(
                chunk_id=chunk_id,
                polities_touched=["Syria"],
                role_in_argument="role:claim",
                theory_school={"primary": "school:synthetic-institutionalist"},
                claim_type={"primary": "claim:causal"},
                empirical_scope={"value": "scope:country-case"},
            )
            for chunk_id in chunk_ids
        ],
        polity_coverage={},
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

    prompt = compose_prompt(
        brief, "political-economy", evidence, vault_dir=vault_dir, evidence_char_budget=80
    )

    assert "synfix_budget_a" in prompt
    assert "synfix_budget_b" in prompt
    assert "synfix_budget_c" not in prompt
    # The dropped chunk's full text never leaked into the prompt either.
    assert prompt.count("X" * 40) == 2


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

    prompt = compose_prompt(
        brief, "political-economy", evidence, vault_dir=vault_dir, evidence_char_budget=1000
    )

    assert "synfix_budget_a" in prompt
    assert "synfix_budget_b" in prompt


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

    assert prompt_1 == prompt_2


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
