"""Inner unit tests for the holdings-completeness check and title-page
bibliographic read (issue #284, issue #285, PRD §7.11/§7.13, §8 P0-1b/P0-1d).

The retired deterministic design's tests went with it: there is no
printed-TOC COVER ratio, no back-matter density, no tunable table, and no
socket-patch determinism guard (the check now makes exactly one model call
by design, so a no-network assertion would guard a design that no longer
exists). What is left to unit-test is the deterministic pre-processing, the
prompt seam, and the mapping from a model answer to the flag/title-page
shape; the model's judgment itself is measured over the real 30-source
corpus, not here.

`probe()` now always returns a dict with two keys, `"holdings_flag"` and
`"title_page"` (issue #285: one combined call replaces the deterministic
title-page fallback #268 measured out of `axial.intake`, and lets the model
cross-check embedded metadata against what the title page actually says).
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


def test_prompt_states_the_embedded_metadata_claim_when_given():
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    probe(
        ["Some document text"],
        client=client,
        physical_pages=10,
        embedded_author="Michael Hanby",
        embedded_title="Augustine and Modernity",
    )

    prompt = client.calls[0][0]
    assert "Michael Hanby" in prompt
    assert "Augustine and Modernity" in prompt


def test_the_title_page_reaches_the_model_as_printed_when_its_title_also_runs_as_a_header():
    """Issue #316's root cause. A book whose main title runs as its own
    header makes that title recur often enough to count as running
    furniture, and the strip then deletes it from the title page itself --
    so the read could only ever return the subtitle. Measured on 7 of the 30
    corpus sources. The opening pages are therefore shown as printed as
    well, and the cleaned windows are unchanged (the holdings judgment keeps
    exactly the text it was measured on)."""
    from axial.holdings import probe, strip_running_furniture

    pages = [
        "Paramilitarism",
        "Paramilitarism\nMass Violence in the Shadow\nof the State\nUgur Umit Ungor",
    ] + [f"Paramilitarism\nbody prose on page {i} about pro-government militias" for i in range(4)]
    client = _RecordingClient(COMPLETE_ANSWER)

    probe(pages, client=client, physical_pages=len(pages))

    # The strip removes the main title from the title page -- this is why the
    # defect existed, and it still happens to the cleaned window.
    assert "Paramilitarism" not in strip_running_furniture(pages)[1]
    # The model nonetheless sees the title page as the book prints it.
    assert "Paramilitarism\nMass Violence in the Shadow" in client.calls[0][0]


def test_prompt_tells_the_model_a_main_title_and_its_subtitle_are_one_title():
    """Issue #316: on two real sources the read returned only the subtitle
    line (`Mass Violence in the Shadow of the State` for a book titled
    `Paramilitarism: Mass Violence in the Shadow of the State`). A title page
    prints one title across two lines; the prompt has to say so. The rule
    against inventing a value the front matter does not carry must survive
    beside it -- a confabulated title is a worse failure than a partial one."""
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    probe(
        ["Paramilitarism\nMass Violence in the Shadow of the State\nUgur Ungor"],
        client=client,
        physical_pages=300,
    )

    prompt = client.calls[0][0]
    assert "subtitle" in prompt.lower()
    assert "Never invent a value the front matter does not carry" in prompt


def test_prompt_states_no_embedded_metadata_when_none_given():
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    probe(["Some document text"], client=client, physical_pages=10)

    assert "states no author and no title" in client.calls[0][0]


# =============================================================================
# Verdict -> holdings_flag
# =============================================================================


def test_partial_verdict_produces_a_flag_recording_its_measurement():
    from axial.holdings import probe

    result = probe(
        ["Contents\nIntroduction 1", "body"],
        client=_RecordingClient(PARTIAL_ANSWER),
        physical_pages=85,
        source_name="mann-v2.pdf",
    )

    assert result["holdings_flag"] == {
        "source": "mann-v2.pdf",
        "document_kind": "book",
        "claimed_extent": "816 pages",
        "claimed_extent_stated_by": "printed contents page",
        "observed_pages": 85,
        "reason": PARTIAL_ANSWER["reason"],
    }


def test_complete_verdict_produces_no_flag():
    from axial.holdings import probe

    result = probe(
        ["Contents\nIntroduction 1", "body"],
        client=_RecordingClient(COMPLETE_ANSWER),
        physical_pages=412,
    )

    assert result["holdings_flag"] is None


def test_partial_verdict_with_no_stated_extent_still_flags():
    """A chapter offprint states no extent of its own; the flag records the
    absence rather than dropping the finding."""
    from axial.holdings import probe

    answer = dict(PARTIAL_ANSWER, claimed_extent=None, claimed_extent_stated_by=None)
    answer["document_kind"] = "chapter_offprint"

    result = probe(["chapter one text"], client=_RecordingClient(answer), physical_pages=20)

    flag = result["holdings_flag"]
    assert flag["claimed_extent"] is None
    assert flag["claimed_extent_stated_by"] is None
    assert flag["document_kind"] == "chapter_offprint"


def test_unrecognised_document_kind_is_recorded_as_unknown_not_raised():
    from axial.holdings import probe

    answer = dict(PARTIAL_ANSWER, document_kind="pamphlet")

    result = probe(["text"], client=_RecordingClient(answer), physical_pages=4)

    assert result["holdings_flag"]["document_kind"] == "unknown"


@pytest.mark.parametrize("raw", ["not json at all", '{"verdict": ', json.dumps(["a", "list"])])
def test_an_unreadable_answer_degrades_to_no_flag_and_nothing_read(raw):
    """The bar is 0 false positives: an answer the check cannot read must
    not become a flag (or a bibliographic reading), and must not halt
    intake either (P0-1b)."""
    from axial.holdings import probe

    result = probe(["text"], client=_RecordingClient(raw), physical_pages=4)

    assert result["holdings_flag"] is None
    assert result["title_page"]["author"] is None
    assert result["title_page"]["title"] is None


def test_a_failing_model_call_never_raises():
    from axial.holdings import probe
    from axial.llm import LLMError

    class _Exploding:
        def complete(self, prompt, pass_name=None):
            raise LLMError("provider is down")

    result = probe(["text"], client=_Exploding(), physical_pages=4)

    assert result["holdings_flag"] is None
    assert result["title_page"]["author"] is None


def test_empty_text_makes_no_model_call():
    from axial.holdings import probe

    client = _RecordingClient(COMPLETE_ANSWER)

    result = probe(["", "   "], client=client, physical_pages=2)

    assert result["holdings_flag"] is None
    assert result["title_page"]["author"] is None
    assert client.calls == []


# =============================================================================
# Verdict -> title_page (issue #285, §7.13)
# =============================================================================


def test_probe_reads_the_title_pages_own_stated_bibliographic_fields():
    from axial.holdings import probe

    answer = dict(
        COMPLETE_ANSWER,
        title_page_title="The Long Road to Damascus",
        title_page_author="Jane Q. Historian",
        title_page_date="1971",
    )

    result = probe(["front matter text"], client=_RecordingClient(answer), physical_pages=200)

    assert result["title_page"]["title"] == "The Long Road to Damascus"
    assert result["title_page"]["author"] == "Jane Q. Historian"
    assert result["title_page"]["date"] == "1971"


def test_a_title_composed_of_a_main_title_and_a_subtitle_is_read_whole():
    """Issue #316's acceptance shape at this seam: whatever the model
    composes off the two printed lines reaches the reading intact -- nothing
    here splits a title at its colon or keeps only one clause."""
    from axial.holdings import probe

    answer = dict(
        COMPLETE_ANSWER,
        title_page_title="Paramilitarism: Mass Violence in the Shadow of the State",
    )

    result = probe(["front matter text"], client=_RecordingClient(answer), physical_pages=300)

    assert (
        result["title_page"]["title"] == "Paramilitarism: Mass Violence in the Shadow of the State"
    )


def test_title_page_fields_default_to_none_when_the_document_states_none():
    from axial.holdings import probe

    result = probe(
        ["front matter text"], client=_RecordingClient(COMPLETE_ANSWER), physical_pages=1
    )

    title_page = result["title_page"]
    assert title_page["title"] is None
    assert title_page["author"] is None
    assert title_page["date"] is None


def test_a_true_matches_verdict_is_read_as_a_bool():
    from axial.holdings import probe

    answer = dict(COMPLETE_ANSWER, author_metadata_matches=True, title_metadata_matches=True)

    result = probe(["text"], client=_RecordingClient(answer), physical_pages=1)

    assert result["title_page"]["author_matches_embedded"] is True
    assert result["title_page"]["title_matches_embedded"] is True


def test_a_false_matches_verdict_is_read_as_a_bool():
    """The cross-check's whole point (#285 finding 2): a model that reads
    the title page and judges the embedded metadata does NOT name this
    document must be able to say so plainly."""
    from axial.holdings import probe

    answer = dict(COMPLETE_ANSWER, author_metadata_matches=False, title_metadata_matches=False)

    result = probe(["text"], client=_RecordingClient(answer), physical_pages=1)

    assert result["title_page"]["author_matches_embedded"] is False
    assert result["title_page"]["title_matches_embedded"] is False


def test_a_missing_or_null_matches_verdict_is_none_not_false():
    """No embedded claim was given to compare (or the answer omitted the
    key): `None`, never coerced to `False` -- `axial.intake` treats `None`
    as "no evidence of a mismatch", not as a mismatch."""
    from axial.holdings import probe

    result = probe(["text"], client=_RecordingClient(COMPLETE_ANSWER), physical_pages=1)

    assert result["title_page"]["author_matches_embedded"] is None
    assert result["title_page"]["title_matches_embedded"] is None


# =============================================================================
# `answered`: did a usable answer come back? (issue #303) -- the caller that
# persists the judgment (§7.12) must not cache a failed call as a judgment.
# =============================================================================


def test_a_usable_answer_reports_answered():
    from axial.holdings import probe

    result = probe(
        ["Contents\nIntroduction 1", "body"],
        client=_RecordingClient(COMPLETE_ANSWER),
        physical_pages=412,
    )

    assert result["answered"] is True


def test_a_failed_call_reports_not_answered():
    from axial.holdings import probe
    from axial.llm import LLMError

    class _FailingClient:
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            raise LLMError("provider unavailable")

    result = probe(["Contents\nIntroduction 1"], client=_FailingClient(), physical_pages=412)

    assert result["answered"] is False
    assert result["holdings_flag"] is None


def test_an_empty_text_layer_reports_not_answered():
    from axial.holdings import probe

    result = probe(["   ", ""], client=_RecordingClient(COMPLETE_ANSWER), physical_pages=2)

    assert result["answered"] is False
