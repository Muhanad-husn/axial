"""Inner unit tests for the holdings-completeness check (issue #284, PRD
§7.11 / §8 P0-1b).

The retired deterministic design's tests went with it: there is no
printed-TOC COVER ratio, no back-matter density, no tunable table, and no
socket-patch determinism guard (the check now makes exactly one model call
by design, so a no-network assertion would guard a design that no longer
exists). What is left to unit-test is the deterministic pre-processing, the
prompt seam, and the mapping from a model answer to the flag shape; the
model's judgment itself is measured over the real 30-source corpus, not
here.
"""

from __future__ import annotations

import json

import pytest


class _RecordingClient:
    """Stub LLM client: answers with `response` and records every call."""

    def __init__(self, response: str | dict):
        self.response = response if isinstance(response, str) else json.dumps(response)
        self.calls: list[tuple[str, str | None]] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.calls.append((prompt, pass_name))
        return self.response


COMPLETE_ANSWER = {
    "document_kind": "book",
    "claimed_extent": "412 pages",
    "claimed_extent_stated_by": "printed contents page",
    "verdict": "complete",
    "reason": "The file runs past the last page the contents states.",
}

PARTIAL_ANSWER = {
    "document_kind": "book",
    "claimed_extent": "816 pages",
    "claimed_extent_stated_by": "printed contents page",
    "verdict": "partial",
    "reason": "The contents states the volume runs to 816 pages; the file holds 85.",
}


# =============================================================================
# Deterministic pre-processing: running header/footer stripping
# =============================================================================


def test_leading_folio_is_stripped_off_a_running_head():
    """§7.11's own stated observable: `tilly`'s contents heading extracts as
    `viii Contents` -- a folio stitched to the running head -- and must
    reach the model as `Contents`."""
    from axial.holdings import strip_running_furniture

    pages = [
        "vi Preface\nMy friends will recognize this book for what it is.",
        "vii Preface\nSeveral sections first took shape as memoranda.",
        "viii Contents\n1 INTRODUCTION\n2 THEORIES OF COLLECTIVE ACTION",
    ]

    cleaned = strip_running_furniture(pages)

    assert cleaned[2].splitlines()[0] == "Contents"
    assert "viii" not in cleaned[2]


def test_a_recurring_running_head_is_removed_entirely():
    from axial.holdings import strip_running_furniture

    pages = [f"Chapter Three\nbody text on page {i}\n{i}" for i in range(6)]

    cleaned = strip_running_furniture(pages)

    assert all("Chapter Three" not in page for page in cleaned)
    assert all("body text" in page for page in cleaned)


def test_a_heading_appearing_once_is_untouched():
    from axial.holdings import strip_running_furniture

    pages = [
        "Bibliography\nBayat, A. Life as Politics.",
        "ordinary prose about the case",
        "more ordinary prose about the case",
    ]

    cleaned = strip_running_furniture(pages)

    assert cleaned[0].splitlines()[0] == "Bibliography"


def test_a_line_that_is_only_a_page_number_is_dropped():
    from axial.holdings import strip_running_furniture

    pages = ["12\nthe body of the page\nsecond line", "13\nanother page body\nmore"]

    cleaned = strip_running_furniture(pages)

    assert cleaned[0].startswith("the body of the page")


def test_a_contents_entry_keeps_its_trailing_page_reference():
    """The strip is confined to page furniture: a contents entry ending in
    its own page number is content, and losing it would cost the model the
    claimed extent it is asked to read."""
    from axial.holdings import strip_running_furniture

    pages = [
        "Contents\nIntroduction 1\nChapter One 25\nIndex 411",
        "body",
        "body",
    ]

    cleaned = strip_running_furniture(pages)

    assert "Index 411" in cleaned[0]


def test_prose_opening_with_a_year_is_not_mistaken_for_a_folio():
    """The leading-folio strip is gated on the document actually numbering
    pages at the top, so an ordinary sentence opening with a number keeps
    its number."""
    from axial.holdings import strip_running_furniture

    pages = ["1978 was a turning point for the movement.", "ordinary prose", "more prose"]

    cleaned = strip_running_furniture(pages)

    assert cleaned[0].startswith("1978 was a turning point")


# =============================================================================
# The one model call
# =============================================================================


def test_probe_makes_exactly_one_call_on_the_holdings_pass():
    from axial.holdings import probe
    from axial.llm import HOLDINGS_PASS_NAME

    client = _RecordingClient(COMPLETE_ANSWER)

    probe(["Contents\nIntroduction 1", "body"], client=client, physical_pages=2)

    assert len(client.calls) == 1
    assert client.calls[0][1] == HOLDINGS_PASS_NAME


def test_holdings_pass_runs_with_reasoning_on():
    """§7.9: reasoning is ON for this pass, carried per pass in
    `config/pipeline.yaml`, never hardcoded."""
    import yaml

    from axial.llm import HOLDINGS_PASS_NAME, _resolve_reasoning_by_pass
    from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH

    config = yaml.safe_load(DEFAULT_PIPELINE_CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["llm"]["reasoning_by_pass"][HOLDINGS_PASS_NAME] is True
    assert _resolve_reasoning_by_pass({})[HOLDINGS_PASS_NAME] is True


def test_prompt_carries_the_physical_page_count_and_the_cleaned_text():
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    probe(
        ["viii Contents\nIntroduction 1", "vii body", "ix body"],
        client=client,
        physical_pages=3,
    )

    prompt = client.calls[0][0]
    assert "3 pages" in prompt
    assert "Contents" in prompt


def test_docx_prompt_states_the_page_count_is_unobtainable():
    """§7.11: a DOCX exposes no physical page count, and its absence is
    unobtainable evidence rather than damning."""
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    probe(["Some document text"], client=client, physical_pages=None)

    assert "unknown" in client.calls[0][0]


# =============================================================================
# Verdict -> flag
# =============================================================================


def test_partial_verdict_produces_a_flag_recording_its_measurement():
    from axial.holdings import probe

    flag = probe(
        ["Contents\nIntroduction 1", "body"],
        client=_RecordingClient(PARTIAL_ANSWER),
        physical_pages=85,
        source_name="mann-v2.pdf",
    )

    assert flag == {
        "source": "mann-v2.pdf",
        "document_kind": "book",
        "claimed_extent": "816 pages",
        "claimed_extent_stated_by": "printed contents page",
        "observed_pages": 85,
        "reason": PARTIAL_ANSWER["reason"],
    }


def test_complete_verdict_produces_no_flag():
    from axial.holdings import probe

    flag = probe(
        ["Contents\nIntroduction 1", "body"],
        client=_RecordingClient(COMPLETE_ANSWER),
        physical_pages=412,
    )

    assert flag is None


def test_partial_verdict_with_no_stated_extent_still_flags():
    """A chapter offprint states no extent of its own; the flag records the
    absence rather than dropping the finding."""
    from axial.holdings import probe

    answer = dict(PARTIAL_ANSWER, claimed_extent=None, claimed_extent_stated_by=None)
    answer["document_kind"] = "chapter_offprint"

    flag = probe(["chapter one text"], client=_RecordingClient(answer), physical_pages=20)

    assert flag["claimed_extent"] is None
    assert flag["claimed_extent_stated_by"] is None
    assert flag["document_kind"] == "chapter_offprint"


def test_unrecognised_document_kind_is_recorded_as_unknown_not_raised():
    from axial.holdings import probe

    answer = dict(PARTIAL_ANSWER, document_kind="pamphlet")

    flag = probe(["text"], client=_RecordingClient(answer), physical_pages=4)

    assert flag["document_kind"] == "unknown"


@pytest.mark.parametrize("raw", ["not json at all", '{"verdict": ', json.dumps(["a", "list"])])
def test_an_unreadable_answer_degrades_to_no_flag(raw):
    """The bar is 0 false positives: an answer the check cannot read must
    not become a flag, and must not halt intake either (P0-1b)."""
    from axial.holdings import probe

    assert probe(["text"], client=_RecordingClient(raw), physical_pages=4) is None


def test_a_failing_model_call_never_raises():
    from axial.holdings import probe
    from axial.llm import LLMError

    class _Exploding:
        def complete(self, prompt, pass_name=None):
            raise LLMError("provider is down")

    assert probe(["text"], client=_Exploding(), physical_pages=4) is None


def test_empty_text_makes_no_model_call():
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    assert probe(["", "   "], client=client, physical_pages=2) is None
    assert client.calls == []
