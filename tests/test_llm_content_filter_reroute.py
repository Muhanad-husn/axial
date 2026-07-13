"""Outer acceptance test for issue #116 (split the `finish_reason` taxonomy
in `OpenRouterClient.complete()`: `length` retries same model, `content_filter`
reroutes to a fallback model -- else raises `ContentRefusedError` -- and
`error` is a transient, backoff-retried fault).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given `OpenRouterClient.complete()` receives a provider response whose
      `finish_reason` is one of `"length"`, `"content_filter"`, or `"error"`
When  the client decides how to react to that finish reason
Then  `length` is retried against the SAME prompt and the SAME model
      (today's behavior, unchanged) -- and raises the existing truncation
      `OpenRouterError` if every attempt in the retry budget stays truncated
And   `content_filter` is NEVER retried same-model: the single completion is
      rerouted to a designated fallback model instead, and if the fallback
      also refuses with `content_filter`, a new typed `ContentRefusedError`
      (an `axial.llm.LLMError` subclass) is raised so callers can quarantine
      the chunk instead of failing the whole source
And   `error` is treated as a transient provider fault -- backoff-retried
      within the existing `_MAX_ATTEMPTS` budget, exactly like a transport
      error or a 5xx, same model each attempt, and succeeds if a later
      attempt returns `"stop"`

See GitHub issue #116 and
`docs/postmortem/gold-run-2026-07/model-tier-decision.md` (ratified,
PR #122) for the source of truth. Before this fix, `src/axial/llm.py`
buckets every non-"stop" `finish_reason` as truncation and blind-retries the
same prompt against the same model up to 3x -- the right remedy for
`length`, the wrong one for a moderation refusal (2 fatal `content_filter`
events in the 2026-07 gold run, one costing a 5.5h attempt and killing a
source for good) or a transient `error`.

Seam decision -- the fallback model is a constructor kwarg
------------------------------------------------------------
This locked contract requires `OpenRouterClient.__init__` to accept a
keyword argument named `content_fallback_model` (a `str | None`, defaulting
to `None` -- no fallback configured) naming the model `complete()` reroutes
a `content_filter` completion to. This mirrors the existing
`request_deadline_seconds` seam (issue #108): a constructed, testable
argument on the class itself, never a module-level monkeypatch or a private
attribute the test reaches into. Where `content_fallback_model` itself comes
from in production (e.g. a `secrets.toml` key) is the implementer's call --
this outer contract only pins down the client-level seam and the resulting
`.complete()` behavior.

Seam decision -- observing which model each POST targeted
------------------------------------------------------------
Every test drives `OpenRouterClient` via `httpx.MockTransport`, exactly like
`tests/test_llm_wallclock_timeout.py`. Each handler below decodes the
outgoing JSON body's `"model"` field and appends it to a `models_seen` list,
in call order, so a test can assert precisely which model each attempt
targeted -- reroute-vs-retry -- without ever touching a live network call.
`axial.llm._sleep` is monkeypatched to a no-op wherever a retry path is
exercised, so backoff delays never slow the suite (mirrors every other outer
test in this module already).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

PRIMARY_MODEL = "deepseek/deepseek-v4-flash"
FALLBACK_MODEL = "some/unmoderated-fallback-model"


def _response(*, content: str | None, finish_reason: str | None) -> httpx.Response:
    """Build a well-formed OpenRouter-shaped chat-completion response body."""
    choice: dict[str, Any] = {"message": {"content": content}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return httpx.Response(200, json={"choices": [choice]})


def _model_of(request: httpx.Request) -> str:
    """Decode the `"model"` field of the outgoing chat-completion request
    body -- the seam every test below uses to tell a same-model retry apart
    from a reroute to the fallback model."""
    return json.loads(request.content)["model"]


# --- criterion 1: "length" retries the SAME prompt against the SAME model --


def test_length_finish_reason_retries_same_prompt_against_same_model_and_succeeds(monkeypatch):
    """A `length` (truncated) completion must be retried against the exact
    same model -- never rerouted to the fallback -- and a later attempt that
    returns `stop` must succeed with that attempt's content."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    models_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models_seen.append(_model_of(request))
        if len(models_seen) == 1:
            return _response(content="partial answer", finish_reason="length")
        return _response(content="full answer", finish_reason="stop")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model=PRIMARY_MODEL,
        transport=transport,
        content_fallback_model=FALLBACK_MODEL,
    )

    result = client.complete("prompt text")

    assert result == "full answer"
    assert models_seen == [PRIMARY_MODEL, PRIMARY_MODEL], (
        "a 'length' finish_reason must retry the SAME prompt against the SAME "
        f"model, never reroute to the fallback -- saw models {models_seen!r}"
    )


def test_length_finish_reason_exhausts_retry_budget_and_raises_truncation_error(monkeypatch):
    """A completion that stays truncated on every attempt must exhaust the
    existing `_MAX_ATTEMPTS` budget -- always against the same primary model
    -- and then raise the existing typed truncation `OpenRouterError`."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, OpenRouterError, _MAX_ATTEMPTS

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    models_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models_seen.append(_model_of(request))
        return _response(content="partial answer", finish_reason="length")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model=PRIMARY_MODEL,
        transport=transport,
        content_fallback_model=FALLBACK_MODEL,
    )

    with pytest.raises(OpenRouterError, match="truncat"):
        client.complete("prompt text")

    assert models_seen == [PRIMARY_MODEL] * _MAX_ATTEMPTS


# --- criterion 2: "content_filter" reroutes to the fallback, never retries -


def test_content_filter_reroutes_single_completion_to_fallback_model(monkeypatch):
    """A `content_filter` refusal from the primary model must NOT be blind-
    retried against that same model. Instead, the single completion is
    rerouted to the configured `content_fallback_model`; if that fallback
    returns `stop`, its content is the result."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    models_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = _model_of(request)
        models_seen.append(model)
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

    result = client.complete("prompt text")

    assert result == "fallback answer"
    assert models_seen == [PRIMARY_MODEL, FALLBACK_MODEL], (
        "a 'content_filter' refusal must reroute the single completion to "
        f"the fallback model, never blind-retry the primary -- saw {models_seen!r}"
    )


def test_content_filter_from_fallback_raises_content_refused_error(monkeypatch):
    """If the fallback model ALSO refuses with `content_filter`, `complete()`
    must raise a distinct, typed `ContentRefusedError` (an `LLMError`
    subclass) so a caller can catch it specifically and quarantine the chunk
    -- never a bare `OpenRouterError`, and never a further blind retry
    against either model."""
    import axial.llm as llm_module
    from axial.llm import ContentRefusedError, LLMError, OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    models_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models_seen.append(_model_of(request))
        return _response(content="", finish_reason="content_filter")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model=PRIMARY_MODEL,
        transport=transport,
        content_fallback_model=FALLBACK_MODEL,
    )

    with pytest.raises(ContentRefusedError) as excinfo:
        client.complete("prompt text")

    assert isinstance(excinfo.value, LLMError), (
        "ContentRefusedError must subclass axial.llm.LLMError so existing "
        "callers that catch LLMError still quarantine the chunk correctly"
    )
    assert models_seen == [PRIMARY_MODEL, FALLBACK_MODEL], (
        "a refusal on the fallback model must not trigger further blind "
        f"retries against either model -- saw {models_seen!r}"
    )


# --- criterion 3: "error" is a transient fault -> backoff-retried ----------


def test_error_finish_reason_is_backoff_retried_like_a_transient_fault(monkeypatch):
    """An `error` finish_reason is a transient provider fault, exactly like
    a transport error or a 5xx: it must be backoff-retried against the SAME
    model (never rerouted to the fallback), and a later attempt returning
    `stop` must succeed."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    sleep_calls: list[float] = []
    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: sleep_calls.append(seconds))
    models_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models_seen.append(_model_of(request))
        if len(models_seen) == 1:
            return _response(content=None, finish_reason="error")
        return _response(content="recovered answer", finish_reason="stop")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model=PRIMARY_MODEL,
        transport=transport,
        content_fallback_model=FALLBACK_MODEL,
    )

    result = client.complete("prompt text")

    assert result == "recovered answer"
    assert models_seen == [PRIMARY_MODEL, PRIMARY_MODEL], (
        "an 'error' finish_reason is a transient provider fault: it must be "
        f"backoff-retried against the SAME model, never rerouted -- saw {models_seen!r}"
    )
    assert sleep_calls, "an 'error' finish_reason must go through the existing backoff path"


def test_error_finish_reason_exhausts_retry_budget_and_raises_transient_error(monkeypatch):
    """An `error` finish_reason that persists on every attempt must exhaust
    the existing `_MAX_ATTEMPTS` budget -- always against the same primary
    model, never the fallback -- and raise a typed error that is NOT
    `ContentRefusedError` (that type is reserved for moderation refusals)."""
    import axial.llm as llm_module
    from axial.llm import ContentRefusedError, OpenRouterClient, OpenRouterError, _MAX_ATTEMPTS

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    models_seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        models_seen.append(_model_of(request))
        return _response(content=None, finish_reason="error")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model=PRIMARY_MODEL,
        transport=transport,
        content_fallback_model=FALLBACK_MODEL,
    )

    with pytest.raises(OpenRouterError) as excinfo:
        client.complete("prompt text")

    assert not isinstance(excinfo.value, ContentRefusedError), (
        "a transient 'error' finish_reason must never surface as a content "
        "refusal -- ContentRefusedError is reserved for content_filter"
    )
    assert models_seen == [PRIMARY_MODEL] * _MAX_ATTEMPTS, (
        f"an 'error' finish_reason must never reroute to the fallback -- saw {models_seen!r}"
    )


# --- regression guard: the new kwarg must stay optional ---------------------


def test_openrouter_client_still_builds_without_content_fallback_model_kwarg():
    """Every pre-#116 caller (and test) builds `OpenRouterClient` without
    `content_fallback_model` at all -- that must keep working for the normal
    `stop` path, so the new kwarg must default, never become required."""
    from axial.llm import OpenRouterClient

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(content="model reply", finish_reason="stop")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model=PRIMARY_MODEL, transport=transport)

    assert client.complete("hello world") == "model reply"
