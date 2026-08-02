"""Inner unit tests for the analyst-facing answer view (issue #535,
specs/PHASE-B.md §7.10/§7.15). `render_analyst_answer` is `axial ask`'s own
rendering: the answer printed where it was asked, plus what stands behind
it in plain language, for a reader who has never opened a JSON record and
does not know what a `source_id` is.

Every number here is read straight off a hand-built `report` (the same
shape `axial.answer.run_report.build_run_report` returns) or `record` --
never recomputed, so a test that changes a report figure and re-asserts on
the render is proof there is one set of numbers, not two.
"""

from __future__ import annotations

from typing import Any

import axial.intake as intake_mod
from axial.answer.render import render_analyst_answer


def _claim(kind: str, text: str) -> dict[str, Any]:
    return {
        "claim_id": f"clm-{kind}",
        "text": text,
        "kind": kind,
        "grounds": [],
        "confidence": "medium",
        "names_touched": [],
    }


def _base_record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "brief_id": "brf_test_001",
        "brief": {
            "case": "Syria",
            "request": "How did displacement reshape local authority?",
            "lens": None,
        },
        "interrogation": {"disposition": "proceed", "refusal": None},
        "claims": [
            _claim("a", "The corpus states displacement reshaped local authority."),
            _claim("b", "A cross-source inference linking Syrian and Iraqi dynamics."),
        ],
        "coverage_map": {
            "Syria": {
                "corpus_note_count": 150,
                "evidence_note_count": 12,
                "coverage_band": "dense",
            },
            "Iraq": {"corpus_note_count": 5, "evidence_note_count": 1, "coverage_band": "thin"},
        },
        "confidence": {
            "overall_band": "medium",
            "rationale": "medium confidence, grounded in 13 evidence chunks against 155 corpus chunks",
        },
    }
    record.update(overrides)
    return record


def _base_report(**overrides: Any) -> dict[str, Any]:
    report: dict[str, Any] = {
        "operational": {
            "cost": {"total_usd": 4.21, "total_tokens": 91000},
            "evidence": {"assembled_count": 60, "composed_count": 24, "composed_share": 0.4},
        },
        "response_quality": {
            "per_source_share": {"syr-2001": 0.65, "irq-1999": 0.35},
            "retrieval_precision": {
                "value": 0.5,
                "cited_note_count": 12,
                "composed_note_count": 24,
            },
            "cross_source_rate": {"value": 1.0, "numerator": 1, "denominator": 1},
        },
    }
    report.update(overrides)
    return report


def _write_source_meta(source_id: str, *, title: str) -> None:
    meta_dir = intake_mod.SOURCE_META_DIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / f"{source_id}.json").write_text(
        f'{{"author": {{"value": "A. Author", "provenance": "embedded"}}, '
        f'"title": {{"value": "{title}", "provenance": "embedded"}}}}',
        encoding="utf-8",
    )


# -- header / disposition ------------------------------------------------------


def test_case_and_question_are_printed_plainly():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "Syria" in text
    assert "How did displacement reshape local authority?" in text


def test_refusal_states_the_reason_and_never_crashes_on_missing_sections():
    record = _base_record(
        interrogation={
            "disposition": "refuse",
            "refusal": {"reason": "the corpus holds no coverage for this polity"},
        },
        claims=[],
        coverage_map={},
        confidence={"overall_band": "not_measured", "rationale": "nothing was measured"},
    )
    text = render_analyst_answer(record, _base_report(response_quality={}, operational={}))
    assert "the corpus holds no coverage for this polity" in text


# -- claims, in plain language --------------------------------------------------


def test_claim_kinds_render_as_plain_words_not_letter_codes():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "source-says" in text
    assert "cross-source" in text
    assert "The corpus states displacement reshaped local authority." in text
    assert "A cross-source inference linking Syrian and Iraqi dynamics." in text


# -- which books it drew on, by title -------------------------------------------


def test_books_drawn_on_resolve_to_titles_with_their_share():
    _write_source_meta("syr-2001", title="Syria Under Siege")
    _write_source_meta("irq-1999", title="Iraq After Empire")
    text = render_analyst_answer(_base_record(), _base_report())
    assert "Syria Under Siege" in text
    assert "Iraq After Empire" in text
    assert "65%" in text
    assert "35%" in text
    # The raw ids never appear once titles are known.
    assert "syr-2001" not in text
    assert "irq-1999" not in text


def test_a_source_with_no_metadata_record_is_named_untitled_not_by_its_id_alone():
    # No source-metadata record written for either id.
    text = render_analyst_answer(_base_record(), _base_report())
    assert "untitled" in text
    assert "syr-2001" in text  # named honestly alongside "untitled", not hidden
    assert "irq-1999" in text


def test_a_metadata_record_whose_title_was_never_resolved_is_also_untitled():
    meta_dir = intake_mod.SOURCE_META_DIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    (meta_dir / "syr-2001.json").write_text('{"title": "not_attempted"}', encoding="utf-8")
    text = render_analyst_answer(
        _base_record(),
        _base_report(response_quality={"per_source_share": {"syr-2001": 1.0}}),
    )
    assert "untitled" in text


# -- how many passages it read vs. used ------------------------------------------


def test_passages_read_and_used_are_read_off_the_report_not_recomputed():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "60" in text  # assembled_count
    assert "12" in text  # cited_note_count


# -- corpus coverage per name, in plain language ---------------------------------


def test_coverage_bands_render_in_plain_language_with_their_counts():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "Syria" in text
    assert "dense" in text
    assert "12" in text
    assert "150" in text
    assert "Iraq" in text
    assert "thin" in text


# -- confidence -------------------------------------------------------------------


def test_confidence_band_and_rationale_are_both_present():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "medium" in text
    assert "medium confidence, grounded in 13 evidence chunks" in text


# -- the cross-book headline --------------------------------------------------------


def test_cross_book_rate_is_rendered_as_the_headline_number():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "100%" in text


def test_cross_book_rate_states_its_reason_when_not_measured():
    report = _base_report(
        response_quality={
            "per_source_share": {},
            "retrieval_precision": {"cited_note_count": 0},
            "cross_source_rate": {
                "value": None,
                "reason": "not scored: this run produced no (b) claim to take a share of",
            },
        }
    )
    text = render_analyst_answer(
        _base_record(claims=[_claim("a", "A single-source claim.")]), report
    )
    assert "not scored: this run produced no (b) claim to take a share of" in text


# -- cost stays off the analyst view -----------------------------------------------


def test_no_dollar_figure_ever_appears_in_the_analyst_view():
    text = render_analyst_answer(_base_record(), _base_report())
    assert "usd" not in text.lower()
    assert "$" not in text
    assert "4.21" not in text
