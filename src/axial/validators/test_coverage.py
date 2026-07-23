"""Inner unit tests for the stage-5 coverage/confidence validator (issue
#260, specs/PHASE-B.md §7.7, §7.9). Co-located under src/axial/validators/
per the repo's existing test layout (mirrors
src/axial/validators/test_attribution.py).

Covers plans/analysis-validators/03-coverage-and-confidence.md's inner-loop
checklist: the polity fold, `corpus_chunk_count` sourced from
`coverage_count` (never a recount), `evidence_chunk_count`'s distinct-chunk
dedup, band-boundary derivation, config-driven overriding, determinism,
zero model calls, the three release-gate checks, and the vacuous
refuse-disposition pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from axial.validators.coverage import (
    REASON_CONFIDENCE_EXCEEDS_COVERAGE,
    REASON_MISSING_CONFIDENCE_DISCLOSURE,
    REASON_MISSING_COVERAGE_ENTRY,
    compute_coverage_map,
    coverage_band_for,
    format_coverage_map,
    validate_coverage_and_confidence,
)

SYRIA_CHUNK_1 = "syr_001_intro_001"
SYRIA_CHUNK_2 = "syr_002_intro_001"
YEMEN_CHUNK = "yem_001_intro_001"
BOTH_CHUNK = "both_001_intro_001"  # touches both Syria and Yemen


def _write_chunk(root: Path, chunk_id: str, polities_touched: list[str]) -> None:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": "SENTINEL: synthetic prose.",
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
        "empirical_scope": {"value": "scope:country-case", "polity": polities_touched[0]},
        "polities_touched": polities_touched,
        "artifact_refs": [],
    }
    text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
    (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    _write_chunk(tmp_path, SYRIA_CHUNK_1, ["Syria"])
    _write_chunk(tmp_path, SYRIA_CHUNK_2, ["Syria"])
    _write_chunk(tmp_path, YEMEN_CHUNK, ["Yemen"])
    _write_chunk(tmp_path, BOTH_CHUNK, ["Syria", "Yemen"])
    return tmp_path / "vault"


def _claim(
    claim_id: str, *, polities_touched: list[str], grounds: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": f"Text for {claim_id}.",
        "kind": "a",
        "grounds": grounds,
        "confidence": "medium",
        "polities_touched": polities_touched,
    }


# -- compute_coverage_map: polity fold ---------------------------------------


def test_polity_appearing_in_five_claims_yields_one_map_entry(vault_dir: Path):
    grounds = [{"ref_type": "chunk", "ref_id": SYRIA_CHUNK_1}]
    claims = [_claim(f"c-{i}", polities_touched=["Syria"], grounds=grounds) for i in range(5)]
    coverage_map = compute_coverage_map(claims, vault_dir=vault_dir)
    assert list(coverage_map.keys()) == ["Syria"]


def test_no_claims_yields_empty_map(vault_dir: Path):
    assert compute_coverage_map([], vault_dir=vault_dir) == {}


# -- corpus_chunk_count: from coverage_count, never a recount ----------------


def test_corpus_chunk_count_comes_from_coverage_count_not_a_recount(
    vault_dir: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[Path | None] = []
    import axial.validators.coverage as coverage_module

    real_coverage_count = coverage_module.coverage_count

    def spy_coverage_count(*, vault_dir=None):
        calls.append(vault_dir)
        return real_coverage_count(vault_dir=vault_dir)

    monkeypatch.setattr(coverage_module, "coverage_count", spy_coverage_count)

    claims = [
        _claim(
            "c-1",
            polities_touched=["Syria"],
            grounds=[{"ref_type": "chunk", "ref_id": SYRIA_CHUNK_1}],
        )
    ]
    coverage_map = compute_coverage_map(claims, vault_dir=vault_dir)

    assert calls == [vault_dir], "corpus_chunk_count must call coverage_count, not recount"
    # 3 chunks touch Syria in the fixture vault: SYRIA_CHUNK_1, SYRIA_CHUNK_2, BOTH_CHUNK.
    assert coverage_map["Syria"]["corpus_chunk_count"] == 3


# -- evidence_chunk_count: distinct grounds chunks, deduped ------------------


def test_evidence_chunk_count_dedupes_the_same_chunk_cited_by_two_claims(vault_dir: Path):
    grounds = [{"ref_type": "chunk", "ref_id": SYRIA_CHUNK_1}]
    claims = [
        _claim("c-1", polities_touched=["Syria"], grounds=grounds),
        _claim("c-2", polities_touched=["Syria"], grounds=grounds),
    ]
    coverage_map = compute_coverage_map(claims, vault_dir=vault_dir)
    assert coverage_map["Syria"]["evidence_chunk_count"] == 1


def test_evidence_chunk_count_counts_distinct_grounds_chunks(vault_dir: Path):
    claims = [
        _claim(
            "c-1",
            polities_touched=["Syria"],
            grounds=[{"ref_type": "chunk", "ref_id": SYRIA_CHUNK_1}],
        ),
        _claim(
            "c-2",
            polities_touched=["Syria"],
            grounds=[{"ref_type": "chunk", "ref_id": SYRIA_CHUNK_2}],
        ),
    ]
    coverage_map = compute_coverage_map(claims, vault_dir=vault_dir)
    assert coverage_map["Syria"]["evidence_chunk_count"] == 2


def test_artifact_grounds_never_contribute_to_evidence_count(vault_dir: Path):
    claims = [
        _claim(
            "c-1",
            polities_touched=["Syria"],
            grounds=[{"ref_type": "artifact", "ref_id": "some-artifact"}],
        )
    ]
    coverage_map = compute_coverage_map(claims, vault_dir=vault_dir)
    assert coverage_map["Syria"]["evidence_chunk_count"] == 0


# -- band derivation at the boundaries ---------------------------------------


@pytest.mark.parametrize(
    "count,expected",
    [
        (0, "thin"),
        (19, "thin"),
        (20, "moderate"),
        (99, "moderate"),
        (100, "dense"),
        (1000, "dense"),
    ],
)
def test_band_boundaries(count: int, expected: str):
    assert coverage_band_for(count, moderate_floor=20, dense_floor=100) == expected


def test_overriding_coverage_bands_config_changes_the_band(vault_dir: Path, tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        yaml.safe_dump({"coverage_bands": {"moderate_floor": 1, "dense_floor": 2}}),
        encoding="utf-8",
    )
    claims = [
        _claim(
            "c-1",
            polities_touched=["Syria"],
            grounds=[{"ref_type": "chunk", "ref_id": SYRIA_CHUNK_1}],
        )
    ]
    # 3 corpus chunks touch Syria -- "dense" under the tiny overridden
    # thresholds (dense_floor=2), "thin" under the module defaults.
    coverage_map = compute_coverage_map(claims, vault_dir=vault_dir, config_path=config_path)
    assert coverage_map["Syria"]["coverage_band"] == "dense"

    default_map = compute_coverage_map(claims, vault_dir=vault_dir)
    assert default_map["Syria"]["coverage_band"] == "thin"


# -- determinism --------------------------------------------------------------


def test_same_record_over_same_vault_yields_byte_identical_map(vault_dir: Path):
    claims = [
        _claim(
            "c-1",
            polities_touched=["Syria", "Yemen"],
            grounds=[{"ref_type": "chunk", "ref_id": BOTH_CHUNK}],
        )
    ]
    first = compute_coverage_map(claims, vault_dir=vault_dir)
    second = compute_coverage_map(claims, vault_dir=vault_dir)
    assert first == second
    assert list(first.keys()) == sorted(first.keys())


# -- inspection affordance formatting ----------------------------------------


def test_format_coverage_map_prints_every_polity():
    rendered = format_coverage_map(
        {
            "Syria": {
                "corpus_chunk_count": 240,
                "evidence_chunk_count": 5,
                "coverage_band": "dense",
            },
            "Yemen": {"corpus_chunk_count": 6, "evidence_chunk_count": 1, "coverage_band": "thin"},
        }
    )
    assert "Syria" in rendered
    assert "Yemen" in rendered
    assert "240" in rendered
    assert "thin" in rendered


def test_format_coverage_map_empty_is_not_blank():
    assert format_coverage_map({}) != ""


# -- validate_coverage_and_confidence: presence checks -----------------------


def _record(
    *, claims: list[dict[str, Any]], coverage_map: dict[str, Any], confidence: Any
) -> dict[str, Any]:
    return {"claims": claims, "coverage_map": coverage_map, "confidence": confidence}


def test_polity_touched_but_absent_from_map_fails():
    claims = [_claim("c-1", polities_touched=["Yemen"], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={},
        confidence={"overall_band": "medium", "rationale": "x"},
    )
    report = validate_coverage_and_confidence(record)
    assert not report.passed
    assert report.failures[0].reason == REASON_MISSING_COVERAGE_ENTRY
    assert "Yemen" in report.failures[0].detail


def test_complete_map_and_valid_confidence_passes():
    claims = [_claim("c-1", polities_touched=["Syria"], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            "Syria": {
                "corpus_chunk_count": 240,
                "evidence_chunk_count": 5,
                "coverage_band": "dense",
            }
        },
        confidence={"overall_band": "medium", "rationale": "240 corpus chunks, 5 evidence chunks"},
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


@pytest.mark.parametrize(
    "confidence",
    [
        {"overall_band": None, "rationale": ""},
        {"overall_band": "", "rationale": "x"},
        {"overall_band": "medium", "rationale": ""},
        {"overall_band": "medium", "rationale": "   "},
        {},
        None,
    ],
)
def test_absent_null_or_empty_confidence_fails(confidence: Any):
    record = _record(claims=[], coverage_map={}, confidence=confidence)
    report = validate_coverage_and_confidence(record)
    assert not report.passed
    assert report.failures[0].reason == REASON_MISSING_CONFIDENCE_DISCLOSURE


# -- validate_coverage_and_confidence: confidence-vs-coverage check ----------


def test_top_band_confidence_with_thin_polity_fails():
    claims = [_claim("c-1", polities_touched=["Yemen"], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            "Yemen": {"corpus_chunk_count": 6, "evidence_chunk_count": 1, "coverage_band": "thin"}
        },
        confidence={"overall_band": "high", "rationale": "6 corpus chunks"},
    )
    report = validate_coverage_and_confidence(record)
    assert not report.passed
    assert report.failures[0].reason == REASON_CONFIDENCE_EXCEEDS_COVERAGE
    assert "Yemen" in report.failures[0].detail


def test_top_band_confidence_with_no_thin_polity_passes():
    claims = [_claim("c-1", polities_touched=["Syria"], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            "Syria": {
                "corpus_chunk_count": 240,
                "evidence_chunk_count": 5,
                "coverage_band": "dense",
            }
        },
        confidence={"overall_band": "high", "rationale": "240 corpus chunks"},
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


def test_lower_band_confidence_with_thin_polity_passes():
    claims = [_claim("c-1", polities_touched=["Yemen"], grounds=[])]
    record = _record(
        claims=claims,
        coverage_map={
            "Yemen": {"corpus_chunk_count": 6, "evidence_chunk_count": 1, "coverage_band": "thin"}
        },
        confidence={"overall_band": "low", "rationale": "6 corpus chunks"},
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed, report.failures


# -- refuse disposition: vacuous pass -----------------------------------------


def test_refuse_disposition_empty_claims_yields_empty_map_and_passes_vacuously():
    record = _record(
        claims=[],
        coverage_map={},
        confidence={"overall_band": "low", "rationale": "refused; no synthesis was attempted"},
    )
    report = validate_coverage_and_confidence(record)
    assert report.passed
    assert report.failures == []


def test_claims_key_absent_passes_vacuously_for_the_coverage_check():
    # Only the coverage-entry check is vacuous on absent claims; confidence
    # is still required (§7.3 marks it non-nullable even on refusal).
    report = validate_coverage_and_confidence(
        {"confidence": {"overall_band": "low", "rationale": "x"}}
    )
    assert report.passed


# -- model-free by construction -----------------------------------------------


def test_validate_and_compute_take_no_llm_client_at_all():
    """`validate_coverage_and_confidence` and `compute_coverage_map` accept
    no client parameter -- nothing here can make a model call, so the
    `explode` provider installed at the CLI layer never fires by
    construction, not by a check that happens not to trip it."""
    import inspect

    assert "client" not in inspect.signature(validate_coverage_and_confidence).parameters
    assert "client" not in inspect.signature(compute_coverage_map).parameters
