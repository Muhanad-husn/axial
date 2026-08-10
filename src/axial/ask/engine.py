"""The plain function underneath `axial ask` (issue #534, specs/PHASE-B.md
§7.1/§7.3): question and case in, activity events (the shared `on_event`
seam PR #622 landed, `axial.llm.EventCallback`) and a full grounded run out.
`axial ask` is this function's first caller; an API layer is its second --
that boundary is the point of this slice, not an incidental, so this module
knows nothing about a CLI or an HTTP request.

**Every turn, including a follow-up, is a full run of `axial.answer.record.
run_brief`** -- interrogation, retrieval, synthesis, validation -- never a
chat completion answering from memory of a previous turn. A follow-up's only
difference from a first question is what its own brief's `request` text
says: `_followup_request` folds the previous turn's question and the claims
its own record reached into the new turn's `request`, so interrogation
re-tests the combined premises and retrieval re-plans with that context in
view (§7.2, §7.5) -- then the identical six-stage engine runs, producing a
record exactly as complete and checkable as a first question's: same
validators, same coverage map, same corpus pin (issue #534's acceptance).

No new brief field carries this context. §7.1's brief shape (`{brief_id,
case, request, lens?}`) is FIRM, and both stages that would need to see prior
context already read `request` as plain prose
(`axial.brief.interrogate.compose_prompt`, `axial.retrieve.loop`'s own
planning prompt) -- folding the context into that text is the one seam that
reaches both without touching either module or that locked shape.

`Turn.result` is a `BriefRunResult` (`axial.answer.record`): the persisted
§7.3 record, its rendered markdown path, and the §7.15 run report -- the
answer plus its backing as data, unchanged from what a hand-authored brief's
`axial brief run` already produces. This is the seam #535 (rendering) and
#536 (session history) build over, without reaching back into the engine
themselves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from axial.answer.record import BriefRunResult, run_brief
from axial.brief.fork import ForkAnswer, ForkCheckResult
from axial.brief.intake import Brief, BriefContent, compute_brief_id
from axial.llm import EventCallback, LLMClient
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH


class AskError(Exception):
    """Base class for `axial.ask` errors -- raised only for this module's
    own precondition (a blank case or question); every error the engine
    itself raises (`InterrogationError`, `axial.brief.fork.ForkCheckError`,
    `QueryError`, `SynthesisError`, `CorpusPinError`, `AnswerError`,
    `AskError` from `axial.argmap.ask`) propagates undisguised, exactly as
    `axial brief run` already lets it."""


class BlankCaseError(AskError):
    """Raised when `case` is empty or whitespace-only -- the same rule
    `axial.brief.intake` enforces for a hand-authored brief's own `case`
    field, applied here since `ask` builds a `Brief` directly rather than
    loading one from a file."""

    def __init__(self) -> None:
        super().__init__("a case is required and cannot be blank")


class BlankQuestionError(AskError):
    """Raised when `question` is empty or whitespace-only (mirrors
    `BlankCaseError` for the brief's `request` field)."""

    def __init__(self) -> None:
        super().__init__("a question is required and cannot be blank")


@dataclass(frozen=True)
class Turn:
    """One turn of an `axial ask` session: the question asked, the case it
    was asked against, the brief `ask` built for it, and the full engine
    result behind the answer. `session_id` joins every turn of one session
    (§7.3's additive `session_id` field, issue #534); `turn_index` is this
    turn's 1-based position within it."""

    session_id: str
    turn_index: int
    question: str
    case: str
    brief: Brief
    result: BriefRunResult


def new_session_id() -> str:
    """A fresh session id -- a session's first turn gets one of these when
    its caller supplies none; every later turn threads the same id
    through."""
    return uuid.uuid4().hex


def _followup_request(question: str, previous: Turn) -> str:
    """Fold `previous`'s own question and the claims its record reached
    into this turn's `request` text (module docstring). Reads only
    `previous.question` and `previous.result.record["claims"]` -- both
    already-persisted, already-checked material, never a live model
    memory. A previous turn that reached no claims (a refusal, or a run
    whose synthesis produced none) still states that plainly rather than
    silently carrying nothing forward."""
    claim_texts = [
        claim.get("text", "")
        for claim in previous.result.record.get("claims", []) or []
        if claim.get("text")
    ]
    lines = [f'Earlier in this session, the question was: "{previous.question}"']
    if claim_texts:
        lines.append("That question's answer reached these claims:")
        lines.extend(f"- {text}" for text in claim_texts)
    else:
        lines.append("That question's answer reached no claims (see its own record for why).")
    lines.append("")
    lines.append(f"Follow-up question: {question}")
    return "\n".join(lines)


def ask(
    question: str,
    case: str,
    *,
    client: LLMClient,
    session_id: str | None = None,
    turn_index: int = 1,
    previous: Turn | None = None,
    lens: str | None = None,
    weights: dict[str, float] | None = None,
    on_event: EventCallback | None = None,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    analyses_dir: Path | None = None,
    runs_dir: Path | None = None,
    lenses_dir: Path | None = None,
    map_pin: str | None = None,
    run_brief_fn: Callable[..., BriefRunResult] = run_brief,
    on_fork: Callable[[ForkCheckResult], ForkAnswer | None] | None = None,
) -> Turn:
    """Ask one question against one case and run the full engine over it.
    `axial ask` is this function's first caller (module docstring); a
    future API layer is its second.

    `previous`, when given, makes this a follow-up: `_followup_request`
    folds its question and claims into this call's own brief `request`
    before the engine ever runs (module docstring) -- what runs after that
    is identical to a first question, `run_brief_fn` driving the full
    six-stage engine and persisting the same §7.3 shape. `run_brief_fn`
    defaults to the real `axial.answer.record.run_brief` and is a seam for
    tests to stub, never for production code to override.

    `session_id` defaults to a fresh id (`new_session_id`) when omitted --
    correct for a first question; a caller carries the same id into every
    later `ask()` call in one session so the persisted records join.

    `weights` (issue #639, `axial ask --weight <source_id>=<float>`,
    repeatable) is the analyst's own instruction for how many rotation
    slots a source gets in retrieval's evidence round-robin -- `None` (the
    default, and every call site before this parameter existed) means
    every source stays at the implicit default of 1.0, byte-identical to
    before. It is folded straight into this turn's own `Brief`, never
    inferred and never asked for (DEC-61): a follow-up does not inherit a
    prior turn's weights automatically, since a follow-up is its own full
    brief and the analyst supplies weights with the question they go with.

    `map_pin` (issue #684) names the built argument map `positions_on`
    reads, skipping `resolve_pinned_map_dir`'s own derivation of it --
    which hashes every raw source file. `None` (the default, and every call
    site before this parameter existed) leaves that derivation exactly as it
    was. A worker bound to a published snapshot passes the pin its manifest
    recorded at publish time, because a hosted worker holds no source bytes
    to hash and would otherwise silently lose the map tool.

    `on_fork` (issue #649, specs/PHASE-B.md §7, DEC-62) is forwarded
    verbatim to `run_brief_fn`: the interactive hook a genuine intake fork
    is offered to, so `axial ask` can ask it live of the analyst
    (`axial.cli._fork_prompt`). `None` (the default) means no interactive
    answer is available -- a fork found on this turn is recorded unanswered
    and the turn proceeds unconstrained, exactly as a batch brief run does.

    Raises `BlankCaseError`/`BlankQuestionError` for its own precondition;
    every engine error `run_brief_fn` raises propagates unchanged."""
    if not case or not case.strip():
        raise BlankCaseError()
    if not question or not question.strip():
        raise BlankQuestionError()

    if session_id is None:
        session_id = new_session_id()

    request_text = _followup_request(question, previous) if previous is not None else question
    weights = dict(weights) if weights else {}
    content = BriefContent(case=case, request=request_text, lens=lens, weights=weights)
    brief = Brief(
        brief_id=compute_brief_id(content),
        case=case,
        request=request_text,
        lens=lens,
        weights=weights,
    )

    result = run_brief_fn(
        brief,
        client=client,
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        config_path=config_path,
        analyses_dir=analyses_dir,
        runs_dir=runs_dir,
        lenses_dir=lenses_dir,
        map_pin=map_pin,
        on_event=on_event,
        session_id=session_id,
        on_fork=on_fork,
    )

    return Turn(
        session_id=session_id,
        turn_index=turn_index,
        question=question,
        case=case,
        brief=brief,
        result=result,
    )
