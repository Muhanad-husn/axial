"""The reader-facing answer render (`axial.answer.reader`, issue #783).

This is what `GET /asks/{id}/export` now serves in all three containers.
The bar is the same as the paper's: the telemetry stays in the audit render,
the evidence markers stay on the page, and an unresolved ground stays
visible.
"""

from __future__ import annotations

from typing import Any

from axial.answer.reader import render_reader_answer
from axial.answer.render import render_markdown

_CITATION = {
    "source_id": "kalyvas-2006",
    "author": "Stathis N. Kalyvas",
    "title": "The Logic of Violence in Civil War",
    "date": "2006",
    "chapter": None,
    "section": "8.3.1 Violence under full control",
}


def _record(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "brief_id": "b1",
        "brief": {"case": "Syria", "request": "Who led the uprising?"},
        "interrogation": {"disposition": "answer"},
        "claims": [
            {
                "claim_id": "c1",
                "text": "Control shapes collaboration.",
                "kind": "a",
                "confidence": "high",
                "grounds": [
                    {"ref_type": "chunk", "ref_id": "kalyvas-2006_116_x_001", "citation": _CITATION}
                ],
            },
            {
                "claim_id": "c2",
                "text": "The tool's own judgment.",
                "kind": "c",
                "confidence": "low",
                "grounds": [],
            },
        ],
        "counter_position": {
            "present": True,
            "stance": "Control follows collaboration, not the other way round.",
            "grounds": [
                {"ref_type": "chunk", "ref_id": "kalyvas-2006_117_y_001", "citation": _CITATION}
            ],
        },
        "coverage_map": {"Syria": {"corpus_note_count": 9, "evidence_note_count": 2,
                                   "coverage_band": "thin"}},
        "confidence": {"overall_band": "medium", "rationale": "because"},
        "source_usage": {
            "sources": [
                {
                    "source_id": "kalyvas-2006",
                    "evidence_share": 0.523,
                    "available_share": 0.318,
                    "usage_ratio": 22.954545454545453,
                }
            ]
        },
    }
    record.update(overrides)
    return record


def test_the_reader_answer_carries_no_telemetry():
    markdown = render_reader_answer(_record())

    assert "usage_ratio" not in markdown
    assert "kalyvas-2006_116_x_001" not in markdown
    assert "## Source usage" not in markdown
    assert "## Coverage map" not in markdown
    assert "evidence_share" not in markdown


def test_the_audit_answer_still_carries_all_of_it():
    """`render_markdown` is what the sealed packet and
    `judge_instant_dismissal` read. Unchanged by the split."""
    markdown = render_markdown(_record())

    assert "kalyvas-2006_116_x_001" in markdown
    assert "usage_ratio" in markdown
    assert "## Coverage map" in markdown


def test_the_case_titles_the_document_and_the_question_sits_under_it():
    """A real request runs to a paragraph (300 characters in
    `data/analyses/080d9e472fc56a34.json`), so it is not the `#` heading --
    and it is not truncated into one either."""
    markdown = render_reader_answer(_record())

    assert markdown.startswith("# Syria\n")
    assert "**The question:** Who led the uprising?" in markdown
    assert "**[stated]** Control shapes collaboration. (Kalyvas 2006)" in markdown


def test_a_claim_with_no_grounds_says_so():
    markdown = render_reader_answer(_record())

    assert "**[runs past the books]** The tool's own judgment. (no supporting passage)" in markdown


def test_an_unresolved_ground_renders_its_raw_pointer():
    record = _record()
    record["claims"][0]["grounds"][0].pop("citation")

    markdown = render_reader_answer(record)

    assert "(chunk:kalyvas-2006_116_x_001)" in markdown


def test_a_passage_mode_quote_renders_under_the_claim_it_grounds():
    """Issue #732's own bar, carried through the split: a record resolved in
    `passage` mode still shows the book text behind the claim."""
    record = _record()
    record["claims"][0]["grounds"][0]["citation"] = dict(_CITATION, quote="Control is prior.")

    markdown = render_reader_answer(record)

    assert "> Control is prior." in markdown


def test_every_line_of_a_multi_paragraph_quote_stays_inside_the_blockquote():
    """A real corpus passage runs to several paragraphs (measured over
    `data/analyses/`: the mean resolved passage is 767 words). Marking only
    its first line `>` renders the rest as body text -- indistinguishable
    from the tool's own prose, which is the exact confusion the evidence
    markers exist to prevent. Every line carries the marker."""
    record = _record()
    quote = "First paragraph.\n\nSecond paragraph.\nThird line."
    record["claims"][0]["grounds"][0]["citation"] = dict(_CITATION, quote=quote)

    markdown = render_reader_answer(record)

    for fragment in ("First paragraph.", "Second paragraph.", "Third line."):
        line = next(line for line in markdown.splitlines() if fragment in line)
        assert line.lstrip().startswith(">"), f"{fragment!r} escaped the blockquote: {line!r}"


def test_the_bibliography_lists_the_books_actually_cited():
    markdown = render_reader_answer(_record())

    assert "- Stathis N. Kalyvas. The Logic of Violence in Civil War. 2006." in markdown


def test_a_refusal_reads_as_a_refusal():
    record = _record(
        interrogation={"disposition": "refuse", "refusal": {"reason": "no source addresses it"}}
    )

    markdown = render_reader_answer(record)

    assert "## No answer from this corpus" in markdown
    assert "no source addresses it" in markdown
    assert "## Answer" not in markdown


def test_a_failed_counter_position_reads_as_a_failed_run():
    record = _record(
        counter_position={"present": False, "failed": True, "failure_reason": "the call raised"}
    )

    markdown = render_reader_answer(record)

    assert "**This section failed to generate.** the call raised" in markdown
    assert "says nothing about whether the corpus holds an opposing position" in markdown


def test_rendering_is_deterministic():
    assert render_reader_answer(_record()) == render_reader_answer(_record())
