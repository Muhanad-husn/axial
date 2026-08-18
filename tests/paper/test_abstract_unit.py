"""Unit tests for `axial.paper.abstract`, the post-draft abstract pass
(specs/PHASE-C.md §7.18, issue #787 slice 04).

The pass's own contract, at the function level: what the prompt carries and
what it forbids, what the parser accepts and rejects, and that `run_abstract`
makes exactly one call on its own pass name. That the abstract reaches the
record and both renders is pinned in `test_abstract.py`, where `run_paper`
actually drives it.
"""

from __future__ import annotations

import json

import pytest

from axial.llm import PAPER_ABSTRACT_PASS_NAME, StubLLMClient
from axial.model_json import ModelJsonError
from axial.paper.abstract import (
    ABSTRACT_TARGET_WORDS,
    AbstractError,
    AbstractParseError,
    compose_abstract_prompt,
    parse_abstract_response,
    run_abstract,
)

THESIS = "Control over the material foundations of rule explains the outcome."


def _sections():
    return [
        {
            "section_id": "s1",
            "heading": "The mechanism",
            "role": "claim",
            "prose": "Rent dependence loosened the bargain [pc-001].",
        },
        {
            "section_id": "s2",
            "heading": "The case against",
            "role": "counter-position",
            "prose": "The institutionalist account reads the same record otherwise.",
        },
    ]


class _StubClient(StubLLMClient):
    """The same stub shape the shape-check and pipeline tests use --
    `model_for_pass`, `usage_for_pass`, `complete` -- without depending on
    either file."""

    def __init__(self, response, model_by_pass=None):
        super().__init__()
        self.model_by_pass = model_by_pass or {
            "paper_draft": "stub/draft",
            PAPER_ABSTRACT_PASS_NAME: "stub/abstract",
        }
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def usage_for_pass(self, pass_name=None):
        return {"prompt_tokens": 900, "completion_tokens": 260}

    def complete(self, prompt, pass_name=None, **_):
        self.calls.append((pass_name, prompt))
        return self._response


# ---------------------------------------------------------------------------
# The prompt: the thesis, the prose that delivered it, one paragraph of about
# 200 words, and two explicit prohibitions.
# ---------------------------------------------------------------------------


def test_the_prompt_carries_the_thesis_statement_and_every_sections_prose():
    prompt = compose_abstract_prompt(THESIS, _sections())
    assert THESIS in prompt
    for section in _sections():
        assert section["heading"] in prompt
        assert section["prose"] in prompt


def test_the_prompt_asks_for_one_paragraph_of_about_two_hundred_words():
    prompt = compose_abstract_prompt(THESIS, _sections())
    assert ABSTRACT_TARGET_WORDS == 200
    assert str(ABSTRACT_TARGET_WORDS) in prompt
    assert "one paragraph" in prompt.lower()


def test_the_prompt_forbids_claim_markers_and_citations():
    """The reader render emits the abstract verbatim rather than through
    `replace_markers`, so a stray `[pc-001]` would stand on the page. The
    prompt is where that is prevented."""
    prompt = compose_abstract_prompt(THESIS, _sections())
    lowered = prompt.lower()
    assert "[pc-" in prompt
    assert "citation" in lowered
    assert "marker" in lowered


def test_the_prompt_asks_for_the_papers_own_argument_not_a_summary_of_the_sources():
    prompt = compose_abstract_prompt(THESIS, _sections()).lower()
    assert "concluded" in prompt
    assert "sources" in prompt


def test_different_prose_produces_a_different_prompt():
    other = [dict(section, prose="entirely different prose") for section in _sections()]
    assert compose_abstract_prompt(THESIS, _sections()) != compose_abstract_prompt(THESIS, other)


# ---------------------------------------------------------------------------
# The parser: strict and typed, in the shape `parse_shape_response` uses.
# ---------------------------------------------------------------------------


def test_a_well_formed_abstract_parses_and_is_stripped():
    assert parse_abstract_response(json.dumps({"abstract": "  The paper argues X.  "})) == (
        "The paper argues X."
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"abstract": ""},
        {"abstract": "   "},
        {"abstract": None},
        {"abstract": 200},
        {"abstract": ["The paper argues X."]},
        {},
        {"summary": "wrong key"},
    ],
)
def test_an_empty_or_non_string_abstract_is_a_typed_parse_error(payload):
    with pytest.raises(AbstractParseError):
        parse_abstract_response(json.dumps(payload))


def test_a_non_object_response_is_a_typed_parse_error():
    with pytest.raises(AbstractParseError):
        parse_abstract_response(json.dumps(["The paper argues X."]))


def test_the_parse_error_is_an_abstract_error():
    """One base class for the orchestrator to catch, so `run_paper` never
    needs a bare `except Exception` to keep the pass non-blocking."""
    assert issubclass(AbstractParseError, AbstractError)


# ---------------------------------------------------------------------------
# `run_abstract`: one call, on its own pass, over arguments rather than a
# pipeline object -- so it runs over a record already on disk.
# ---------------------------------------------------------------------------


def test_run_abstract_makes_exactly_one_call_on_its_own_pass_name():
    client = _StubClient(json.dumps({"abstract": "The paper argues X."}))
    result = run_abstract(client, THESIS, _sections())
    assert [name for name, _ in client.calls] == [PAPER_ABSTRACT_PASS_NAME]
    assert result.text == "The paper argues X."
    assert result.model == "stub/abstract"


def test_run_abstract_prices_the_call_it_made():
    """A model the price table knows prices; an unpriced one yields `None`
    rather than a fabricated zero, exactly as `estimate_cost` requires."""
    priced = _StubClient(
        json.dumps({"abstract": "The paper argues X."}),
        model_by_pass={PAPER_ABSTRACT_PASS_NAME: "deepseek/deepseek-v4-pro"},
    )
    assert run_abstract(priced, THESIS, _sections()).cost > 0

    unpriced = _StubClient(json.dumps({"abstract": "The paper argues X."}))
    assert run_abstract(unpriced, THESIS, _sections()).cost is None


def test_run_abstract_costs_none_when_the_client_reports_no_usage():
    class _NoUsage(_StubClient):
        def usage_for_pass(self, pass_name=None):
            return None

    client = _NoUsage(json.dumps({"abstract": "The paper argues X."}))
    assert run_abstract(client, THESIS, _sections()).cost is None


def test_run_abstract_raises_a_typed_error_when_the_response_never_parses():
    """`complete_json` gives up with `ModelJsonError`; the pass hands the
    orchestrator its own type instead, so one `except AbstractError` covers
    every way a response can be unusable."""
    client = _StubClient("not json at all")
    with pytest.raises(AbstractParseError):
        run_abstract(client, THESIS, _sections())
    assert not isinstance(AbstractParseError("x"), ModelJsonError)


def test_the_abstract_pass_may_resolve_to_the_same_model_as_the_drafter():
    """Deliberately unlike the shape check: that pass GRADES the drafter's
    prose and carries a self-grading guard. This one writes, and a writer
    summarising its own argument is not a conflict of interest."""
    client = _StubClient(
        json.dumps({"abstract": "The paper argues X."}),
        model_by_pass={"paper_draft": "stub/same", PAPER_ABSTRACT_PASS_NAME: "stub/same"},
    )
    assert run_abstract(client, THESIS, _sections()).model == "stub/same"
