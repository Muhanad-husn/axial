"""Outer acceptance test for issue #108 (hard wall-clock timeout per
`OpenRouterClient.complete()` attempt, so a stalled/slow-drip response
self-aborts instead of hanging indefinitely).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given  `OpenRouterClient` sends a request whose underlying transport blocks
       forever without ever raising and without ever completing the read
       (a "slow-drip" stall -- no exception, no partial byte, 0% CPU,
       observed live for 15-40 minutes on three gold-ingestion sources)
When   the client's per-attempt wall-clock ceiling elapses
Then   the attempt self-aborts and is treated as a transient failure, so
       the existing `_MAX_ATTEMPTS` retry budget (issue #60) re-issues it in
       process, exactly like a `httpx.ReadTimeout` is treated today
And    a call that keeps stalling past the ceiling on every attempt still
       gives up within a bounded time and raises a loud typed error (an
       `axial.llm.LLMError`), never hangs
And    a normal, fast completion is returned correctly with no added
       wall-clock delay

See GitHub issue #108 ("llm: hard wall-clock timeout per call so a stalled
request self-aborts and retries") for the source of truth. `_REQUEST_TIMEOUT`
(`src/axial/llm.py:564`) only bounds a single httpx *read* -- a slow-drip
stream (or provider/proxy keep-alive bytes) resets that timer forever, so the
existing per-read timeout never fires and the bounded retry never triggers.

Seam decision -- the injectable wall-clock ceiling
---------------------------------------------------
The production ceiling is on the order of ~300s; this test suite must never
wait anywhere near that long. This locked contract therefore REQUIRES
`OpenRouterClient.__init__` to accept a keyword argument named
`request_deadline_seconds` (a `float`, seconds) that overrides the
production wall-clock ceiling for that client instance, defaulting to the
existing production constant when omitted. That is the exact seam these
tests are written against -- not a module-level monkeypatch, not a private
attribute. If `request_deadline_seconds` does not exist yet on
`OpenRouterClient.__init__`, that omission is precisely what makes this
suite red: the implementer must add it.

Seam decision -- simulating the "no exception, ever" stall
------------------------------------------------------------
A real slow-drip stall never raises and never returns. This suite models it
with an `httpx.MockTransport` handler that blocks on an `threading.Event`
that is never set (`Event().wait()` with no timeout) -- the handler thread
genuinely never returns control to the caller on its own, precisely the
"0% CPU, no exception" shape from the incident report. Under today's
(unfixed) `OpenRouterClient`, driving `.complete()` against this handler
hangs the calling thread forever; every test below therefore drives
`.complete()` on a background thread and joins it with a generous
hang-guard timeout (independent of, and much larger than, the short ceiling
under test) so a genuine indefinite hang FAILS the test loudly instead of
freezing the pytest run.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx
import pytest

# The short, injected wall-clock ceiling every test below uses -- far below
# the production ~300s default, so a would-be-passing suite still runs in a
# fraction of a second per test.
SHORT_CEILING_SECONDS = 0.4

# A hang-guard for the TEST PROCESS ITSELF, not the production behavior: if
# `.complete()` is still running this long after being asked to stop
# blocking, something is genuinely, indefinitely hung (exactly the bug this
# issue fixes) and the test must fail loudly rather than freeze the suite.
HANG_GUARD_SECONDS = 6.0


def _blocking_forever_handler(request: httpx.Request) -> httpx.Response:
    """An httpx.MockTransport handler that never returns and never raises --
    the "slow-drip" stall: no partial byte ever arrives to trip httpx's
    per-read timeout, and the thread sits at 0% CPU, exactly like the live
    incident (issue #108)."""
    threading.Event().wait()
    raise AssertionError("unreachable: the handler blocks forever and is never released")


def _ok_response() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})


def _complete_with_hang_guard(
    client: Any, prompt: str, *, guard_seconds: float = HANG_GUARD_SECONDS
) -> tuple[float, tuple[str, Any]]:
    """Run `client.complete(prompt)` on a background thread and return
    `(elapsed_seconds, outcome)`, where `outcome` is `("ok", result)` or
    `("error", exception)`.

    If `.complete()` is still running after `guard_seconds`, this fails the
    test immediately with a clear message instead of letting a genuine
    indefinite hang (the exact bug issue #108 describes) freeze the whole
    pytest run."""
    captured: dict[str, Any] = {}

    def _target() -> None:
        try:
            value = client.complete(prompt)
        except BaseException as exc:  # noqa: BLE001 - captured for the caller to assert on
            captured["outcome"] = ("error", exc)
        else:
            captured["outcome"] = ("ok", value)

    thread = threading.Thread(target=_target, daemon=True)
    start = time.monotonic()
    thread.start()
    thread.join(timeout=guard_seconds)
    elapsed = time.monotonic() - start

    if thread.is_alive():
        pytest.fail(
            f"client.complete() was still running {guard_seconds}s after being asked to "
            "stop blocking -- this is a genuine indefinite hang (issue #108's bug: no "
            "wall-clock ceiling bounds a stalled attempt)."
        )

    return elapsed, captured["outcome"]


# --- criterion 1: the wall-clock cap fires even with no read exception -----


def test_wall_clock_cap_fires_on_a_stalled_no_exception_response(monkeypatch):
    """A first attempt that stalls forever (no exception, no per-read
    timeout trip) must not be allowed to consume the whole call: the
    injected `request_deadline_seconds` ceiling must abort it, and the
    existing retry budget re-issues a second attempt that succeeds fast.
    `complete()` must return well within a small multiple of the ceiling --
    not hang, and not take anywhere near the (effectively infinite) block."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _blocking_forever_handler(request)
        return _ok_response()

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
        request_deadline_seconds=SHORT_CEILING_SECONDS,
    )

    elapsed, outcome = _complete_with_hang_guard(client, "hello world")

    assert outcome == ("ok", "model reply")
    assert call_count == 2
    # Bounded by ~1 ceiling (the stalled attempt) plus a fast second
    # attempt -- nowhere near the hang-guard, and nowhere near "forever".
    assert elapsed < SHORT_CEILING_SECONDS * 2 + 2.0, (
        f"expected complete() to return within a couple ceilings, took {elapsed:.2f}s"
    )


# --- criterion 2: ceiling breach is transient -> retried --------------------


def test_ceiling_breach_is_retried_within_the_existing_retry_budget(monkeypatch):
    """Two consecutive ceiling breaches (stalled attempts) followed by a
    successful third attempt must still return the successful response --
    proving a wall-clock breach is treated as a retryable/transient failure
    within `_MAX_ATTEMPTS`, exactly like a `httpx.ReadTimeout` is today, not
    a hard abort."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, _MAX_ATTEMPTS

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < _MAX_ATTEMPTS:
            return _blocking_forever_handler(request)
        return _ok_response()

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
        request_deadline_seconds=SHORT_CEILING_SECONDS,
    )

    elapsed, outcome = _complete_with_hang_guard(client, "hello world")

    assert outcome == ("ok", "model reply")
    assert call_count == _MAX_ATTEMPTS
    assert elapsed < SHORT_CEILING_SECONDS * _MAX_ATTEMPTS + 2.0, (
        f"expected the retried call to finish within a few ceilings, took {elapsed:.2f}s"
    )


# --- criterion 3: persistent breach raises a loud typed error, bounded -----


def test_persistent_ceiling_breach_raises_a_typed_llm_error_within_a_bounded_time(monkeypatch):
    """A stall that breaches the ceiling on EVERY attempt must exhaust the
    same bounded retry budget as any other transient failure and then raise
    a loud, typed `axial.llm.LLMError` -- never hang, and never silently
    swallow the failure."""
    import axial.llm as llm_module
    from axial.llm import LLMError, OpenRouterClient, _MAX_ATTEMPTS

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _blocking_forever_handler(request)

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
        request_deadline_seconds=SHORT_CEILING_SECONDS,
    )

    elapsed, outcome = _complete_with_hang_guard(client, "hello world")

    kind, value = outcome
    assert kind == "error", f"expected complete() to raise, it returned {value!r}"
    assert isinstance(value, LLMError), (
        f"expected a typed axial.llm.LLMError on persistent ceiling breach, got "
        f"{type(value).__name__}: {value}"
    )
    assert call_count == _MAX_ATTEMPTS
    # Bounded by roughly _MAX_ATTEMPTS ceilings -- not the hang-guard, and
    # certainly not an indefinite hang.
    assert elapsed < SHORT_CEILING_SECONDS * _MAX_ATTEMPTS + 2.0, (
        f"expected the give-up to happen within a few ceilings, took {elapsed:.2f}s"
    )


# --- criterion 4: a normal, fast completion is unaffected -------------------


def test_normal_fast_completion_is_unaffected_by_the_injected_ceiling():
    """A completion that returns immediately must be returned correctly with
    no added wall-clock delay, whether or not a `request_deadline_seconds`
    ceiling is supplied -- the new wall-clock guard must add no latency and
    no behavior change to the already-working fast path."""
    from axial.llm import OpenRouterClient

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _ok_response()

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
        request_deadline_seconds=SHORT_CEILING_SECONDS,
    )

    elapsed, outcome = _complete_with_hang_guard(client, "hello world", guard_seconds=3.0)

    assert outcome == ("ok", "model reply")
    assert call_count == 1
    assert elapsed < 1.0, (
        f"a fast completion must not be slowed by the ceiling, took {elapsed:.2f}s"
    )


def test_openrouter_client_still_builds_without_the_new_kwarg():
    """Regression guard: a client built exactly the way every pre-#108 test
    builds one (no `request_deadline_seconds` at all) must keep working --
    the new parameter must default to the production ceiling, not become
    required."""
    from axial.llm import OpenRouterClient

    def handler(request: httpx.Request) -> httpx.Response:
        return _ok_response()

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    assert client.complete("hello world") == "model reply"
