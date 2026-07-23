"""Inner unit tests for the stage-6 markdown-answer renderer (issue #261,
specs/PHASE-B.md §7.10). Co-located under src/axial/answer/ per the repo's
existing test layout (mirrors src/axial/answer/test_source_usage.py).

Covers plans/analysis-record/02-markdown-answer-rendering.md's inner-loop
checklist: claim-kind markers, claim order preservation, grounds-id
tracing, empty-grounds safety, the counter-position present/one-sided/none
paths, deterministic coverage-map ordering, the confidence section,
refusal-path claims omission, byte-identical determinism, and "none" lines
for empty sections rather than silent gaps.
"""

from __future__ import annotations

import copy
from typing import Any

from axial.answer.render import render_markdown


def _claim(
    claim_id: str, kind: str, text: str, grounds: list[dict[str, str]], confidence: str = "medium"
) -> dict[str, Any]:
    return {
        "claim_id": claim_id,
        "text": text,
        "kind": kind,
        "grounds": grounds,
        "confidence": confidence,
        "polities_touched": [],
    }


def _base_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "brief_id": "brf_test_001",
        "brief": {
            "brief_id": "brf_test_001",
            "case": "Syria",
            "request": "How did displacement reshape local authority?",
            "lens": None,
        },
        "corpus_pin": "baseline",
        "schema_version": "0.1",
        "lens": "lens:default",
        "interrogation": {
            "premises_found": [],
            "bounds_applied": [],
            "refusal": None,
            "disposition": "proceed",
        },
        "claims": [
            _claim(
                "clm_a",
                "a",
                "The corpus states displacement reshaped local authority.",
                [{"ref_type": "chunk", "ref_id": "syr_001_intro_001"}],
            ),
            _claim(
                "clm_b",
                "b",
                "A cross-source inference linking Syrian and Iraqi dynamics.",
                [
                    {"ref_type": "chunk", "ref_id": "syr_001_intro_001"},
                    {"ref_type": "chunk", "ref_id": "irq_001_intro_001"},
                ],
            ),
            _claim("clm_c", "c", "A speculative extension beyond the corpus.", []),
        ],
        "counter_position": {
            "present": True,
            "stance": "Displacement entrenched, rather than reshaped, existing authority.",
            "grounds": [{"ref_type": "chunk", "ref_id": "irq_002_counter_001"}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": {
            "Syria": {
                "corpus_chunk_count": 150,
                "evidence_chunk_count": 1,
                "coverage_band": "dense",
            },
            "Iraq": {
                "corpus_chunk_count": 5,
                "evidence_chunk_count": 1,
                "coverage_band": "thin",
            },
        },
        "confidence": {
            "overall_band": "medium",
            "rationale": "medium confidence, grounded in 2 evidence chunks against 155 corpus chunks",
        },
        "source_usage": {
            "filters_observed": [],
            "sources": [
                {
                    "source_id": "syr_001",
                    "evidence_chunk_count": 1,
                    "evidence_share": 0.5,
                    "available_chunk_count": 10,
                    "available_share": 0.8,
                    "usage_ratio": 0.625,
                },
            ],
        },
        "trajectory": [],
        "model_by_pass": {"interrogate": "stub"},
    }
    record.update(overrides)
    return record


def test_claim_kinds_render_distinctly():
    markdown = render_markdown(_base_record())
    assert "(a)" in markdown
    assert "(b)" in markdown
    assert "(c)" in markdown


def test_claim_order_follows_record_order_not_resorted():
    record = _base_record()
    markdown = render_markdown(record)
    idx_a = markdown.index("The corpus states")
    idx_b = markdown.index("A cross-source inference")
    idx_c = markdown.index("A speculative extension")
    assert idx_a < idx_b < idx_c


def test_grounds_ids_appear_against_their_claims():
    markdown = render_markdown(_base_record())
    assert "chunk:syr_001_intro_001" in markdown
    assert "chunk:irq_001_intro_001" in markdown


def test_c_claim_with_empty_grounds_renders_without_raising_or_a_grounds_list():
    record = _base_record()
    markdown = render_markdown(record)
    lines = markdown.splitlines()
    c_line_idx = next(i for i, line in enumerate(lines) if "A speculative extension" in line)
    # The next line is either blank/a new section header, never a
    # "grounds:" line, since the (c) claim's own grounds are empty.
    assert not lines[c_line_idx + 1].strip().startswith("grounds:")


def test_counter_position_present_renders_stance_and_grounds():
    markdown = render_markdown(_base_record())
    assert "Displacement entrenched" in markdown
    assert "chunk:irq_002_counter_001" in markdown


def test_counter_position_corpus_one_sided_renders_disclosure_and_reason():
    record = _base_record(
        counter_position={
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": True,
            "one_sided_reason": "the corpus holds no opposing theory_school material here",
        }
    )
    markdown = render_markdown(record)
    assert "the corpus holds no opposing theory_school material here" in markdown
    assert "Displacement entrenched" not in markdown


def test_absent_counter_position_renders_a_stated_none_line():
    record = _base_record(
        counter_position={
            "present": False,
            "stance": None,
            "grounds": [],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        }
    )
    markdown = render_markdown(record)
    assert "(none disclosed)" in markdown


def test_coverage_map_rows_are_emitted_in_deterministic_polity_order():
    record = _base_record()
    # Rebuild coverage_map with keys inserted in the OPPOSITE order to what
    # a correct alphabetical render would need, proving the renderer sorts
    # rather than trusting dict insertion order.
    record["coverage_map"] = {
        "Zanzibar": {"corpus_chunk_count": 3, "evidence_chunk_count": 1, "coverage_band": "thin"},
        "Iraq": {"corpus_chunk_count": 5, "evidence_chunk_count": 1, "coverage_band": "thin"},
    }
    markdown = render_markdown(record)
    idx_iraq = markdown.index("Iraq:")
    idx_zanzibar = markdown.index("Zanzibar:")
    assert idx_iraq < idx_zanzibar


def test_coverage_map_entries_carry_both_counts_and_the_band():
    markdown = render_markdown(_base_record())
    assert "corpus=150" in markdown
    assert "evidence=1" in markdown
    assert "band=dense" in markdown
    assert "band=thin" in markdown


def test_empty_coverage_map_renders_a_stated_none_line():
    record = _base_record(coverage_map={})
    markdown = render_markdown(record)
    assert "(none -- no polity touched by any claim)" in markdown


def test_confidence_section_renders_band_and_rationale():
    markdown = render_markdown(_base_record())
    assert "medium" in markdown
    assert "medium confidence, grounded in 2 evidence chunks" in markdown


def test_refusal_path_renders_reason_and_omits_claims_section():
    record = _base_record(
        interrogation={
            "premises_found": [],
            "bounds_applied": [],
            "refusal": {"reason": "the corpus holds no coverage for this polity"},
            "disposition": "refuse",
        },
        claims=[],
    )
    markdown = render_markdown(record)
    assert "the corpus holds no coverage for this polity" in markdown
    assert "## Claims" not in markdown


def test_determinism_two_renders_are_byte_identical():
    record = _base_record()
    first = render_markdown(copy.deepcopy(record))
    second = render_markdown(copy.deepcopy(record))
    assert first == second
    assert first.endswith("\n") and not first.endswith("\n\n")


def test_source_usage_renders_when_present():
    markdown = render_markdown(_base_record())
    assert "syr_001" in markdown
    assert "0.500" in markdown  # evidence_share
