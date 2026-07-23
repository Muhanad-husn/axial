"""Inner unit tests for issue #253 slice 01's remaining seeded behaviours
(plans/retrieval-loop/01-tool-loop-skeleton.md inner-loop checklist):

- Step budget: the loop halts at exactly the configured count; the budget is
  read from config, not hardcoded.
- The loop registers its `pass_name` so `model_by_pass`/`reasoning_by_pass`
  can route it (§7.11).
- The tool-use seam: the loop drives the scripted client through the new
  tool-capable entry point, and existing `complete()` callers are
  unaffected.

`tests/analysis/test_retrieval_loop_skeleton.py` covers the 4-scenario
outer acceptance contract (including the budget-halts-cleanly behaviour
itself); this file covers the config-wiring and seam-additivity properties
underneath it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from axial.llm import RETRIEVE_PASS_NAME, OpenRouterClient, OpenRouterError
from axial.retrieve.loop import DEFAULT_STEP_BUDGET, _resolve_step_budget


# --- step budget: read from config, not hardcoded --------------------------


def test_step_budget_reads_from_config_pipeline_yaml(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"retrieve": {"step_budget": 3}}), encoding="utf-8")

    assert _resolve_step_budget(config_path) == 3


def test_step_budget_falls_back_to_default_when_config_absent(tmp_path: Path):
    missing_path = tmp_path / "does-not-exist.yaml"

    assert _resolve_step_budget(missing_path) == DEFAULT_STEP_BUDGET


def test_step_budget_falls_back_to_default_when_retrieve_block_absent(tmp_path: Path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(yaml.safe_dump({"llm": {"provider": "openrouter"}}), encoding="utf-8")

    assert _resolve_step_budget(config_path) == DEFAULT_STEP_BUDGET


# --- pass_name routing (§7.11) ----------------------------------------------


def test_retrieve_pass_name_routes_through_model_by_pass():
    """Naming `RETRIEVE_PASS_NAME` in `model_by_pass` (the same generic,
    pre-existing per-pass config seam every other pass uses) is enough to
    route the retrieval loop's calls to a different model -- no code change
    beyond using the constant as `pass_name` is required."""
    client = OpenRouterClient(
        api_key="test-key",
        model="default-model",
        model_by_pass={RETRIEVE_PASS_NAME: "tool-use-tier-model"},
    )

    assert client.model_for_pass(RETRIEVE_PASS_NAME) == "tool-use-tier-model"
    # A pass not named in model_by_pass still falls back to the client's own
    # default -- proving this is additive, not a special-cased branch.
    assert client.model_for_pass("some_other_pass") == "default-model"


# --- the tool-use seam: complete() is unaffected ----------------------------


def _stop_response(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
    )


def test_complete_payload_carries_no_tools_field_when_tools_not_requested():
    """`complete()` (used by every existing Phase-A pass) must send the
    exact same payload shape it always has -- no `tools` key at all -- even
    after `complete_with_tools`/`_post_with_deadline`'s `tools` parameter
    exists."""
    seen_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_bodies.append(json.loads(request.content))
        return _stop_response("an answer")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="some-model", transport=transport)

    result = client.complete("prompt text")

    assert result == "an answer"
    assert len(seen_bodies) == 1
    assert "tools" not in seen_bodies[0], (
        f"complete() must never add a 'tools' key to its payload, got {seen_bodies[0]!r}"
    )


def test_complete_with_tools_sends_tools_and_parses_first_tool_call():
    """`complete_with_tools` sends `tools` in the payload and reads the
    first `tool_calls` entry off the response, returning
    `{"tool": <name>, "args": <dict>}`."""
    seen_bodies: list[dict[str, Any]] = []
    tool_schema = [
        {
            "type": "function",
            "function": {
                "name": "query_by_polity",
                "description": "d",
                "parameters": {
                    "type": "object",
                    "properties": {"polity": {"type": "string"}},
                    "required": ["polity"],
                },
            },
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_bodies.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "query_by_polity",
                                        "arguments": json.dumps({"polity": "Syria"}),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="some-model", transport=transport)

    result = client.complete_with_tools("prompt text", tool_schema, pass_name=RETRIEVE_PASS_NAME)

    assert result == {"tool": "query_by_polity", "args": {"polity": "Syria"}}
    assert seen_bodies[0]["tools"] == tool_schema


def test_complete_with_tools_returns_none_when_no_tool_call_issued_and_finish_reason_is_stop():
    """A turn whose message carries no `tool_calls` at all, ending with a
    genuine clean stop (`finish_reason: "stop"`), is a clean end, not an
    error -- v0's "no retry on a tool-less turn" rule. The positive case
    for the review finding below: a LEGITIMATE end-of-loop must still
    return the clean-stop sentinel, not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _stop_response("just a plain text answer, no tool call")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="some-model", transport=transport)

    result = client.complete_with_tools("prompt text", [], pass_name=RETRIEVE_PASS_NAME)

    assert result is None


# --- review finding: a non-tool-call turn is not always a CLEAN end ---------


def _no_tool_call_response(finish_reason: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": None}, "finish_reason": finish_reason}]},
    )


def test_complete_with_tools_raises_content_refused_on_content_filter_with_no_tool_call():
    """A `content_filter` refusal with an empty `tool_calls` list must NOT
    be treated as a clean end-of-loop -- it must raise the same
    `ContentRefusedError` `complete()` raises for this finish_reason, so a
    refused turn can never masquerade as a clean short §7.6 trajectory."""
    from axial.llm import ContentRefusedError

    def handler(request: httpx.Request) -> httpx.Response:
        return _no_tool_call_response("content_filter")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="some-model", transport=transport)

    with pytest.raises(ContentRefusedError, match="content_filter"):
        client.complete_with_tools("prompt text", [], pass_name=RETRIEVE_PASS_NAME)


def test_complete_with_tools_raises_openrouter_error_on_length_with_no_tool_call():
    """A truncated (`length`) turn with an empty `tool_calls` list must NOT
    be treated as a clean end-of-loop -- it must raise `OpenRouterError`
    naming the finish_reason, so a truncated turn can never masquerade as a
    clean short §7.6 trajectory."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _no_tool_call_response("length")

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="some-model", transport=transport)

    with pytest.raises(OpenRouterError, match="length"):
        client.complete_with_tools("prompt text", [], pass_name=RETRIEVE_PASS_NAME)
