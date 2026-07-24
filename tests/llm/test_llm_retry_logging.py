"""Outer acceptance test for issue #117 (structured retry logging: every
NON-FINAL retry attempt inside `OpenRouterClient.complete()`'s `_MAX_ATTEMPTS`
loop must emit exactly one structured log line, so a gold run's moderation-
exposure numbers become measurable instead of a lower bound).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Update (real-time per-API-call logging, #368/#369): a later feature adds
its own `llm_call_request`/`llm_call_response` stderr line pair around
EVERY request/response in `_post_with_deadline` -- the single choke point
`complete()` routes through -- independent of retry status. That is a
different, additive log stream, not a change to `_log_retry`'s own
contract. The line-filtering helpers below were narrowed from "every
stderr line" to "lines starting `llm_retry`" so this suite keeps asserting
exactly the same `_log_retry` behavior it always has (tests are contracts
owned by the product, not locked artifacts -- CLAUDE.local.md).

Given  `OpenRouterClient.complete()` retries a transient failure (a 429/5xx,
       a truncated/empty/error `finish_reason`, or a `content_filter`
       moderation refusal rerouted to the fallback model) silently today --
       only the final failure of the `_MAX_ATTEMPTS` budget ever surfaces to
       a caller; a chunk that failed twice then succeeded leaves no trace
When   any attempt fails and is NOT the final attempt in the budget (i.e. it
       will be retried, or -- for `content_filter` -- rerouted)
Then   exactly one structured log line is emitted to stderr for that event,
       carrying at minimum: the `pass_name` argument already threaded into
       `.complete()`, the attempt number and the total attempt budget (e.g.
       attempt 2 of 3), and a machine-readable trigger token (a
       `finish_reason` value, an HTTP status, or similar)
And    a clean FIRST-attempt success logs NOTHING new (no retry line at all)
And    a `content_filter` reroute additionally records a STABLE IDENTIFIER
       of the refused prompt (a hash plus a prefix of the prompt text) in
       its log line, so a fallback model can later be validated against real
       refused chunks
And    the FINAL attempt of an exhausted budget -- the one that raises --
       is not itself logged as a retry (only non-final, retried-or-rerouted
       attempts are)

See GitHub issue #117 for the source of truth.

Seam decision -- log destination is stderr, no logging framework
------------------------------------------------------------------
This repo has no logging framework; the established convention for an
operational log line is a bare `print(..., file=sys.stderr)` (see
`src/axial/xref.py:334`). This suite captures stderr with pytest's `capsys`
and asserts on it directly. The retry loop runs on the calling thread (no
background thread involved, unlike the wall-clock-deadline suite), so
`capsys` sees every line synchronously. This locked contract does NOT pin
down how the implementer produces that stderr line -- no assumption is made
about any internal logger function/attribute name -- only that the line
appears, on stderr, containing the tokens asserted below.

Seam decision -- driving the client and picking retry triggers
------------------------------------------------------------------
Every test drives `OpenRouterClient` via `httpx.MockTransport`, exactly like
`tests/test_llm_content_filter_reroute.py` and
`tests/test_llm_wallclock_timeout.py`. `axial.llm._sleep` is monkeypatched to
a no-op so backoff never slows the suite. The fails-twice-then-succeeds
primary criterion deliberately exercises TWO DIFFERENT non-final-retry code
paths in `complete()` -- an HTTP 503 on attempt 1 (the status-code retry
branch) and a `finish_reason="error"` on attempt 2 (the transient-fault
branch) -- so the trigger token asserted per line is a real, distinguishing
signal and not an artifact of a single code path.

Seam decision -- what is (and is not) pinned down about line format
------------------------------------------------------------------
Per the issue's own guidance, this suite asserts strictly on OBSERVABLE
substrings/regex tokens (the pass_name string, the attempt number, the
attempt budget, the trigger token, a hash-shaped token, a prompt prefix) and
never on exact whole-line punctuation/spacing/field order. The implementer
is free to choose the log line's exact shape, the hash algorithm, and the
prefix length N, as long as the assertions below are satisfied.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
import pytest

PRIMARY_MODEL = "primary/test-model"
FALLBACK_MODEL = "fallback/test-model"

# A hash-shaped token: a contiguous run of 8-64 hex characters. Used to prove
# the content_filter log line carries something hash-like, not merely the
# raw prompt text repeated back.
_HASH_TOKEN_RE = re.compile(r"\b[0-9a-fA-F]{8,64}\b")

# A short, distinctive marker placed at the very start of the "refused"
# prompt in the content_filter test below. Kept deliberately short (8 chars)
# so this test never over-specifies the implementer's choice of N (the
# number of prompt characters the log line records) -- any reasonable N
# includes at least this much of the prompt's prefix.
_REFUSED_PROMPT_MARKER = "REFUSAL1"


def _response(*, content: str | None, finish_reason: str | None) -> httpx.Response:
    """Build a well-formed OpenRouter-shaped chat-completion response body."""
    choice: dict[str, Any] = {"message": {"content": content}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return httpx.Response(200, json={"choices": [choice]})


def _nonempty_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _retry_lines(text: str) -> list[str]:
    """Lines emitted by `_log_retry` specifically (prefix `llm_retry`), not
    stderr as a whole. A later feature (real-time per-API-call logging,
    #368/#369) adds its own `llm_call_request`/`llm_call_response` line
    pair around EVERY request/response, retried or not -- this suite is
    about `_log_retry`'s own contract (issue #117: does a retried/rerouted
    attempt get exactly one structured line), which is unaffected and
    still asserted here, just filtered to the lines that are actually
    `_log_retry`'s."""
    return [line for line in _nonempty_lines(text) if line.startswith("llm_retry")]


def _assert_line_names_attempt(
    line: str, *, pass_name: str, attempt: int, budget: int, trigger_token: str
) -> None:
    """Assert `line` carries the pass name, the attempt number, the total
    attempt budget, and a recognizable trigger token -- as loose substring/
    regex checks, never a whole-line format assertion (see module
    docstring)."""
    assert re.search(rf"\b{re.escape(pass_name)}\b", line), (
        f"expected pass_name {pass_name!r} to appear in retry log line: {line!r}"
    )
    assert re.search(rf"\b{attempt}\b", line), (
        f"expected attempt number {attempt} to appear in retry log line: {line!r}"
    )
    assert re.search(rf"\b{budget}\b", line), (
        f"expected attempt budget {budget} to appear in retry log line: {line!r}"
    )
    assert trigger_token in line, (
        f"expected trigger token {trigger_token!r} to appear in retry log line: {line!r}"
    )


# --- primary acceptance criterion: fails twice, succeeds, two retry lines --


def test_two_non_final_retries_each_log_exactly_one_line_with_pass_attempt_and_trigger(
    monkeypatch, capsys
):
    """An attempt that fails with an HTTP 503 (attempt 1) followed by an
    attempt that fails with `finish_reason="error"` (attempt 2), followed by
    a clean `stop` (attempt 3), must emit EXACTLY TWO structured retry log
    lines on stderr -- one per non-final failed attempt -- each naming the
    pass_name, its own attempt number, the total attempt budget, and a
    trigger token distinguishing "503" from "error". The final, successful
    attempt must not itself be logged as a retry."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, _MAX_ATTEMPTS

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(503)
        if call_count == 2:
            return _response(content=None, finish_reason="error")
        return _response(content="clean success", finish_reason="stop")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model=PRIMARY_MODEL, transport=transport)

    result = client.complete("prompt text for retry logging", pass_name="tag")

    assert result == "clean success"
    assert call_count == 3

    stderr = capsys.readouterr().err
    lines = _retry_lines(stderr)
    assert len(lines) == 2, (
        f"expected exactly 2 non-final-retry log lines (attempts 1 and 2 of "
        f"{_MAX_ATTEMPTS}), got {len(lines)}: {lines!r}"
    )

    line_for_attempt_1, line_for_attempt_2 = lines
    _assert_line_names_attempt(
        line_for_attempt_1,
        pass_name="tag",
        attempt=1,
        budget=_MAX_ATTEMPTS,
        trigger_token="503",
    )
    _assert_line_names_attempt(
        line_for_attempt_2,
        pass_name="tag",
        attempt=2,
        budget=_MAX_ATTEMPTS,
        trigger_token="error",
    )


def test_clean_first_attempt_success_logs_nothing_new(capsys):
    """A completion that succeeds on the very first attempt logs no
    `llm_retry` line -- no retry line is ever warranted when there is
    nothing to retry. (A clean call DOES now emit its own
    `llm_call_request`/`llm_call_response` pair -- real-time per-API-call
    logging, #368/#369 -- but that is a distinct feature from `_log_retry`'s
    own "nothing to retry" contract, which this test still pins down.)"""
    from axial.llm import OpenRouterClient

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(content="clean success", finish_reason="stop")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model=PRIMARY_MODEL, transport=transport)

    result = client.complete("prompt text", pass_name="tag")

    assert result == "clean success"
    stderr = capsys.readouterr().err
    assert _retry_lines(stderr) == [], (
        f"a clean first-attempt success must log no llm_retry line, got: {stderr!r}"
    )


# --- the final, raising attempt of an exhausted budget is not itself logged


def test_final_exhausted_attempt_is_not_logged_only_the_two_non_final_ones_are(monkeypatch, capsys):
    """A persistent `finish_reason="error"` on every attempt exhausts the
    retry budget and raises on the final attempt. Only the two NON-FINAL
    attempts (1 and 2 of 3) are retries and must be logged; the final,
    raising attempt (3 of 3) must not add a third log line."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, OpenRouterError, _MAX_ATTEMPTS

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(content=None, finish_reason="error")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model=PRIMARY_MODEL, transport=transport)

    with pytest.raises(OpenRouterError):
        client.complete("prompt text", pass_name="chunk")

    stderr = capsys.readouterr().err
    lines = _retry_lines(stderr)
    assert len(lines) == _MAX_ATTEMPTS - 1, (
        f"expected exactly {_MAX_ATTEMPTS - 1} retry log lines (every attempt "
        f"except the final, raising one), got {len(lines)}: {lines!r}"
    )
    _assert_line_names_attempt(
        lines[0], pass_name="chunk", attempt=1, budget=_MAX_ATTEMPTS, trigger_token="error"
    )
    _assert_line_names_attempt(
        lines[1], pass_name="chunk", attempt=2, budget=_MAX_ATTEMPTS, trigger_token="error"
    )


# --- content_filter reroute: log line also records the refused-prompt id ---


def test_content_filter_reroute_log_line_records_refused_prompt_hash_and_prefix(
    monkeypatch, capsys
):
    """When the primary model refuses with `finish_reason="content_filter"`
    and `complete()` reroutes to the fallback model, the emitted log line
    for that event must additionally carry a STABLE IDENTIFIER of the
    refused prompt: something hash-shaped, AND a recognizable prefix of the
    prompt's own text -- so a fallback model can later be validated against
    real refused chunks. A prefix alone (without anything hash-shaped) must
    not satisfy this contract; neither would a hash alone."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)

    def _model_of(request: httpx.Request) -> str:
        import json as _json

        return _json.loads(request.content)["model"]

    def handler(request: httpx.Request) -> httpx.Response:
        model = _model_of(request)
        if model == PRIMARY_MODEL:
            return _response(content="", finish_reason="content_filter")
        return _response(content="fallback answer", finish_reason="stop")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model=PRIMARY_MODEL,
        transport=transport,
        content_fallback_model=FALLBACK_MODEL,
    )

    refused_prompt = _REFUSED_PROMPT_MARKER + ": " + ("moderately sensitive filler text " * 20)

    result = client.complete(refused_prompt, pass_name="chunk")

    assert result == "fallback answer"

    stderr = capsys.readouterr().err
    lines = _retry_lines(stderr)
    content_filter_lines = [line for line in lines if "content_filter" in line]
    assert content_filter_lines, (
        f"expected at least one log line naming the 'content_filter' trigger "
        f"for the reroute event, got lines: {lines!r}"
    )
    reroute_line = content_filter_lines[0]

    assert re.search(r"\bchunk\b", reroute_line), (
        f"expected pass_name 'chunk' to appear in the content_filter reroute "
        f"log line: {reroute_line!r}"
    )
    assert _REFUSED_PROMPT_MARKER in reroute_line, (
        "expected a recognizable prefix of the refused prompt's own text "
        f"(starting {_REFUSED_PROMPT_MARKER!r}) in the reroute log line: {reroute_line!r}"
    )
    assert _HASH_TOKEN_RE.search(reroute_line), (
        "expected a stable, hash-shaped identifier (8-64 contiguous hex "
        f"characters) of the refused prompt in the reroute log line: {reroute_line!r}"
    )
