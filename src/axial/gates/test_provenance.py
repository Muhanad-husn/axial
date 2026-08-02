"""Inner unit tests for the provenance-integrity gate (specs/PHASE-C.md
§10.1, §7.4, §8 P0-8; issue #606). Co-located under src/axial/gates/ per the
repo's existing test layout (mirrors src/axial/gates/test_grounding.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.gates.provenance import run_provenance_gate
from axial.llm import ExplodingLLMClient

CHUNK_ID = "prov_gate_001_syria_a"
MISSING_CHUNK_ID = "prov_gate_999_missing"


def _chunk_frontmatter(*, chunk_id: str = CHUNK_ID) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A",
            "title": "T",
            "date": 2020,
            "thesis": "X",
            "scope": "Y",
        },
        "schema_version": "0.1",
        "role_in_argument": "role:claim",
        "field": {"primary": "field:political-sociology", "secondary": []},
        "claim_type": {"primary": "claim:causal", "secondary": None, "subtags": []},
        "theory_school": {
            "primary": "school:synthetic-institutionalist",
            "secondary": None,
            "status": "candidate",
        },
        "empirical_scope": {"value": "scope:country-case", "polity": "Syria"},
        "polities_touched": ["Syria"],
        "artifact_refs": [],
    }


def _write_vault(root: Path) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    text = "---\n" + yaml.safe_dump(_chunk_frontmatter(), sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{CHUNK_ID}.md").write_text(text, encoding="utf-8")
    return root / "vault"


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return _write_vault(tmp_path)


def _paper_claim(
    paper_claim_id: str,
    *,
    kind: str = "a",
    origin: dict[str, Any] | None = None,
    confidence: str = "high",
    derived_from: list[str] | None = None,
    chunk_id: str = CHUNK_ID,
) -> dict[str, Any]:
    return {
        "paper_claim_id": paper_claim_id,
        "text": f"Paper claim text for {paper_claim_id}.",
        "kind": kind,
        "origin": origin,
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id}],
        "confidence": confidence,
        "names_touched": [],
        "derived_from": derived_from or [],
    }


def _citation(paper_claim_id: str, *, section_id: str = "s1", sentence_index: int = 0):
    return {
        "section_id": section_id,
        "sentence_index": sentence_index,
        "paper_claim_id": paper_claim_id,
    }


def _paper_record(claims: list[dict[str, Any]], citations: list[dict[str, Any]]) -> dict[str, Any]:
    return {"paper_brief_id": "pb-1", "claims": claims, "citations": citations}


def _write_origin(analyses_dir: Path, brief_id: str, record: dict[str, Any]) -> None:
    analyses_dir.mkdir(parents=True, exist_ok=True)
    (analyses_dir / f"{brief_id}.json").write_text(json.dumps(record), encoding="utf-8")


# -- provenance_completeness --------------------------------------------------


def test_all_markers_resolve_scores_1_00_and_passes(vault_dir: Path, tmp_path: Path):
    claims = [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"})]
    citations = [_citation("pc-1")]
    record = _paper_record(claims, citations)
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    completeness = next(m for m in report.metrics if m.metric == "provenance_completeness")
    assert completeness.value == 1.0
    assert completeness.threshold == 1.00
    assert completeness.passed is True
    assert completeness.n == 1


def test_dangling_marker_fails_the_metric_and_names_it(tmp_path: Path):
    claims = [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"})]
    citations = [_citation("pc-1"), _citation("pc-does-not-exist")]
    record = _paper_record(claims, citations)
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=tmp_path / "no_such_vault",
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    completeness = next(m for m in report.metrics if m.metric == "provenance_completeness")
    assert completeness.value == pytest.approx(0.0), (
        "neither marker's grounds resolve without a vault"
    )
    assert completeness.passed is False
    assert "pc-does-not-exist" in completeness.detail["dangling_paper_claim_ids"]


def test_unresolvable_grounds_pointer_fails_the_metric_not_a_crash(vault_dir: Path, tmp_path: Path):
    claims = [
        _paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"}, chunk_id=MISSING_CHUNK_ID)
    ]
    citations = [_citation("pc-1")]
    record = _paper_record(claims, citations)
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    completeness = next(m for m in report.metrics if m.metric == "provenance_completeness")
    assert completeness.value == 0.0
    assert completeness.passed is False
    assert "pc-1" in completeness.detail["dangling_paper_claim_ids"]


def test_empty_citations_is_a_hard_fail_not_a_vacuous_pass(tmp_path: Path):
    record = _paper_record([], [])
    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    completeness = next(m for m in report.metrics if m.metric == "provenance_completeness")
    assert completeness.value is None
    assert completeness.passed is False


# -- confidence_upgrade_count --------------------------------------------------


def test_carried_claim_matching_clamped_origin_band_is_no_violation(
    vault_dir: Path, tmp_path: Path
):
    """The origin claim touches a name whose coverage_band is 'moderate'
    (clamps confidence to 'medium'); the carried claim discloses 'medium'
    too -- no upgrade."""
    claims = [
        _paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"}, confidence="medium")
    ]
    record = _paper_record(claims, [_citation("pc-1")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": ["Syria"]}],
            "coverage_map": {"Syria": {"coverage_band": "moderate"}},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 0.0
    assert upgrades.threshold == 0
    assert upgrades.passed is True
    assert upgrades.n == 1


def test_carried_claim_disclosing_a_higher_band_than_clamped_origin_is_a_violation(
    vault_dir: Path, tmp_path: Path
):
    """Same fixture as above, but the carried claim discloses the origin's
    UNCLAMPED 'high' band rather than the clamped 'medium' -- an upgrade,
    which is exactly what P0-4's own observable names."""
    claims = [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"}, confidence="high")]
    record = _paper_record(claims, [_citation("pc-1")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": ["Syria"]}],
            "coverage_map": {"Syria": {"coverage_band": "moderate"}},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 1.0
    assert upgrades.passed is False
    assert upgrades.detail["violating_paper_claim_ids"] == ["pc-1"]


def test_new_b_claim_exceeding_its_derived_from_minimum_is_a_violation(
    vault_dir: Path, tmp_path: Path
):
    claims = [
        _paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c-low"}, confidence="low"),
        _paper_claim("pc-2", origin={"brief_id": "b1", "claim_id": "c-high"}, confidence="high"),
        _paper_claim(
            "pc-3",
            kind="b",
            origin=None,
            confidence="high",
            derived_from=["pc-1", "pc-2"],
        ),
    ]
    record = _paper_record(claims, [_citation("pc-3")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [
                {"claim_id": "c-low", "confidence": "low", "names_touched": []},
                {"claim_id": "c-high", "confidence": "high", "names_touched": []},
            ],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 1.0
    assert upgrades.detail["violating_paper_claim_ids"] == ["pc-3"]


def test_new_b_claim_at_exactly_the_minimum_is_no_violation(vault_dir: Path, tmp_path: Path):
    claims = [
        _paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c-low"}, confidence="low"),
        _paper_claim("pc-2", origin={"brief_id": "b1", "claim_id": "c-high"}, confidence="high"),
        _paper_claim(
            "pc-3",
            kind="b",
            origin=None,
            confidence="low",
            derived_from=["pc-1", "pc-2"],
        ),
    ]
    record = _paper_record(claims, [_citation("pc-3")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [
                {"claim_id": "c-low", "confidence": "low", "names_touched": []},
                {"claim_id": "c-high", "confidence": "high", "names_touched": []},
            ],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 0.0
    assert upgrades.passed is True


def test_no_claims_is_a_vacuous_zero_never_not_scoreable(tmp_path: Path):
    record = _paper_record([], [])
    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )
    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 0.0
    assert upgrades.passed is True
    assert upgrades.n == 0


def test_missing_origin_record_is_a_violation_not_a_raise(tmp_path: Path):
    """Issue #627: a dangling origin drags `confidence_upgrade_count` down
    for that claim, never aborts the run -- `UnresolvableOriginRecordError`
    is still the class the gate raises internally, but it is caught before
    it ever reaches this caller."""
    claims = [_paper_claim("pc-1", origin={"brief_id": "no-such-brief", "claim_id": "c1"})]
    record = _paper_record(claims, [_citation("pc-1")])

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=tmp_path / "analyses",
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 1.0
    assert upgrades.passed is False
    assert "pc-1" in upgrades.detail["violating_paper_claim_ids"]


def test_missing_origin_claim_is_a_violation_not_a_raise(tmp_path: Path):
    """Issue #627: the exact real-corpus shape -- the origin analysis record
    loads fine, but no longer carries the claim id (regenerated against a
    newer corpus). This must score as a violation, not crash the run."""
    claims = [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "no-such-claim"})]
    record = _paper_record(claims, [_citation("pc-1")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(analyses_dir, "b1", {"claims": [{"claim_id": "c1"}], "coverage_map": {}})

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 1.0
    assert upgrades.passed is False
    assert "pc-1" in upgrades.detail["violating_paper_claim_ids"]


def test_one_dangling_record_does_not_stop_a_healthy_record_from_scoring(
    vault_dir: Path, tmp_path: Path
):
    """Issue #627's own batch shape: a directory of two records, one with a
    dangling origin and one clean, scored in the same `run_provenance_gate`
    call -- the dangling record fails its own metric while the healthy
    record's claim is scored normally, neither one crashing the other."""
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {"claims": [{"claim_id": "c1", "confidence": "high"}], "coverage_map": {}},
    )
    healthy = _paper_record(
        [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"}, confidence="high")],
        [_citation("pc-1")],
    )
    orphaned = {
        "paper_brief_id": "pb-2",
        "claims": [_paper_claim("pc-9", origin={"brief_id": "b1", "claim_id": "no-such-claim"})],
        "citations": [_citation("pc-9")],
    }

    report = run_provenance_gate(
        [healthy, orphaned],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    upgrades = next(m for m in report.metrics if m.metric == "confidence_upgrade_count")
    assert upgrades.value == 1.0, "only the orphaned claim violates -- the healthy one does not"
    assert upgrades.passed is False
    assert upgrades.detail["violating_paper_claim_ids"] == ["pc-9"]
    assert "pc-1" not in upgrades.detail["violating_paper_claim_ids"]

    completeness = next(m for m in report.metrics if m.metric == "provenance_completeness")
    assert completeness.n == 2, "both records' citation markers were counted -- the batch ran"


# -- zero model calls, no panel field ------------------------------------------


def test_zero_model_calls_ever(vault_dir: Path, tmp_path: Path):
    """`ExplodingLLMClient` raises the instant `.complete()` fires -- a
    clean pass here IS the proof of P0-8's "zero model calls" bullet."""
    claims = [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"})]
    record = _paper_record(claims, [_citation("pc-1")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin=None,
        trusted=False,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )
    assert report is not None


def test_report_carries_no_panel_field_and_no_reviewer_configured(vault_dir: Path, tmp_path: Path):
    claims = [_paper_claim("pc-1", origin={"brief_id": "b1", "claim_id": "c1"})]
    record = _paper_record(claims, [_citation("pc-1")])
    analyses_dir = tmp_path / "analyses"
    _write_origin(
        analyses_dir,
        "b1",
        {
            "claims": [{"claim_id": "c1", "confidence": "high", "names_touched": []}],
            "coverage_map": {},
        },
    )

    report = run_provenance_gate(
        [record],
        client=ExplodingLLMClient(),
        vault_dir=vault_dir,
        corpus_pin="baseline",
        trusted=True,
        config_path=tmp_path / "nonexistent.yaml",
        analyses_dir=analyses_dir,
    )

    payload = report.to_json()
    assert "panel" not in payload
    assert report.passed is True
    assert report.trusted is True
