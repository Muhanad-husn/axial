"""The post-draft abstract (specs/PHASE-C.md §7.18, issue #787 slice 04).

**One model call, after all section drafts complete, over the prose that
exists rather than the plan that was written.** An abstract summarises the
paper the run actually produced; composing it from the plan would describe an
argument the drafter may not have made. So it runs as a barrier after stage 3,
reading the plan's `thesis_statement` and each section's heading and drafted
prose, and nothing else -- no `section_id`, no assigned role, and nothing
downstream of drafting.

**Unconditionally, on every paper, at 200 words.** Every venue surveyed for
issue #787 requires an abstract and the lengths converge -- IJMES asks 150
words, Nature a ~200-word summary paragraph -- so it is not venue-conditional
and there is no per-paper length option. One number, in `ABSTRACT_TARGET_WORDS`
below, stated to the model as an approximation rather than enforced: nothing
here truncates or pads a response, for the same reason slice 02's length target
is a plan target and never a cut.

**Its own pass, not one more field on the shape check.** The obvious cheaper
route -- issue #717 already added the paper's *title* to `axial.paper.shape` on
exactly the "one more field on a call already being made" argument -- was
rejected deliberately. A title is eight words; an abstract is ~200 words of
generation that would dominate the completion of a call whose response
*ordering* was measured and calibrated (issue #600 moved defect recall from
8.3% to 50% purely by requiring per-section reviews before the band, and two
of three defect classes still vary across replicates). Re-calibrating that
instrument costs a measured run. The roles differ too: the shape check grades,
and this writes.

**No self-grading guard, unlike the shape check.** `axial.paper.shape` refuses
to run when its judge resolves to the drafting model, because the model that
wrote a section's prose must never grade whether that prose did its job. This
pass has no such conflict -- summarising your own argument is the job, not a
verdict on it -- so `paper_abstract` is free to resolve to the drafting model,
and `config/pipeline.yaml` starts it there.

**The prompt forbids claim markers and citations, and that prohibition is
load-bearing.** The reader render emits the abstract verbatim rather than
through `axial.paper.reader.replace_markers`, which would otherwise turn a
stray `[pc-001]` into a parenthetical citation inside the one block of the
paper that is supposed to carry none. Emitting verbatim keeps the reader
render's standing rule -- a visible unresolved reference beats a silently
transformed one -- and puts the prevention in the prompt, where it belongs.

**It reports; it never blocks.** `parse_abstract_response` is strict, in the
same shape every other parse error in this package uses: an empty or
non-string abstract is an `AbstractParseError`, never a persisted blank. But
the failure stops there. `axial.paper.record.run_paper` catches
`AbstractError` around this pass's single call and writes `abstract: null`, so
an unusable response leaves a fully drafted paper drafted rather than turning
it into a failed run -- the same call `axial.paper.shape` already makes for a
missing title. It is not silent about it: that handler writes one
`paper_abstract_failed` line to stderr, because `abstract: null` is also what
every record written before this pass existed carries, so without the line a
pass that ran and failed reads exactly like one that never ran. A transport
failure is not caught and propagates like any other pass's, because a network
outage is not a fact about this pass.

**The quality of an abstract is not a gate.** Like the shape check, it is
written and reported. No gate in §10.1 reads it, and there is no judged band
here to invent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from axial.llm import PAPER_ABSTRACT_PASS_NAME
from axial.llm import estimate_cost as _estimate_cost
from axial.model_json import ModelJsonError, complete_json, parse_model_json

# The one length this pass has. Not configurable and not venue-conditional:
# see the module docstring on why the venues converge here.
ABSTRACT_TARGET_WORDS = 200


class AbstractError(Exception):
    """Base class for abstract-pass failures. `run_paper` catches exactly
    this, which is why every way a response can be unusable is raised as a
    subclass of it rather than left as the model layer's own type."""


class AbstractParseError(AbstractError):
    """Raised when the abstract response is not the expected shape, or
    carries an empty or non-string abstract."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"abstract response is malformed: {reason}")


@dataclass(frozen=True)
class AbstractResult:
    """What the pass produces: the abstract itself, which model wrote it,
    and what the call cost. `cost` is `None` when the client cannot report
    per-pass usage, mirroring `axial.llm.estimate_cost`'s own
    null-for-unpriced convention -- never a fabricated zero."""

    text: str
    model: str
    cost: float | None


def _section_block(heading: str, prose: str) -> str:
    return f"### {heading}\n{prose}\n"


def compose_abstract_prompt(thesis_statement: str, sections: list[dict[str, str]]) -> str:
    """The §7.18 prompt: the paper's thesis, then the prose that argued it.

    `sections` is `[{heading, prose}, ...]` in plan order; extra keys
    (`section_id`, `role`) are ignored, so the same list `run_shape_check`
    takes works here unchanged and this composes directly over a persisted
    paper record."""
    sections_text = "\n".join(
        _section_block(str(s.get("heading") or ""), str(s.get("prose") or "")) for s in sections
    )
    return f"""You are writing the abstract for a finished scholarly paper. The paper is below, in full, exactly as it was drafted.

The thesis it set out to argue: "{thesis_statement}"

{sections_text}

Write ONE paragraph of about {ABSTRACT_TARGET_WORDS} words that states what THIS PAPER argues and what it concluded.

- State the paper's own position and the verdict it reached, in the paper's own voice. An abstract that describes what the sources say, or lists which scholars are discussed, has failed: the reader wants the argument, not a tour of the literature.
- Say what the argument rests on and where it commits itself, including where the paper concedes the opposing account has force.
- Summarise the paper that is actually above. Do not restate the thesis verbatim, and do not promise anything the drafted prose did not deliver.
- Write NO citations of any kind: no author names in parentheses, no years, no page or chapter references.
- Write NO claim markers. The prose above carries bracketed markers such as [pc-001]; those are internal identifiers and must never appear in the abstract.
- One paragraph. No heading, no bullet list, no sub-sections.

Return JSON only:
{{"abstract": "..."}}"""


def parse_abstract_response(raw: str) -> str:
    """Parse and validate one abstract response, returning the stripped
    abstract. An empty, blank or non-string `abstract` is an
    `AbstractParseError`, never a persisted blank -- the same strictness
    `parse_shape_response` applies to its own required fields."""
    parsed = parse_model_json(raw)
    if not isinstance(parsed, dict):
        raise AbstractParseError(f"expected an object, got {type(parsed).__name__}")

    text = parsed.get("abstract")
    if not isinstance(text, str) or not text.strip():
        raise AbstractParseError(f"'abstract' is {text!r}, not a non-empty string")
    return text.strip()


def run_abstract(
    client: Any, thesis_statement: str, sections: list[dict[str, str]]
) -> AbstractResult:
    """One call, over the whole paper regardless of section count.

    Takes its inputs as arguments rather than reading a pipeline object, so
    it runs over a paper record already on disk -- `plan.thesis_statement`
    plus `[{heading, prose}]` built from `plan.sections` and `drafts` -- as
    well as from inside `run_paper`.

    Raises `AbstractParseError` when the response never parses or carries no
    usable abstract; both are subclasses of `AbstractError`, so one `except`
    in the caller keeps this pass non-blocking."""
    model = client.model_for_pass(PAPER_ABSTRACT_PASS_NAME)
    prompt = compose_abstract_prompt(thesis_statement, sections)
    try:
        raw = complete_json(client, prompt, pass_name=PAPER_ABSTRACT_PASS_NAME)
    except ModelJsonError as exc:
        raise AbstractParseError(str(exc)) from exc
    text = parse_abstract_response(raw)

    usage_for_pass = getattr(client, "usage_for_pass", None)
    usage = usage_for_pass(PAPER_ABSTRACT_PASS_NAME) if usage_for_pass is not None else None
    cost = (
        _estimate_cost(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        if usage
        else None
    )
    return AbstractResult(text=text, model=model, cost=cost)
