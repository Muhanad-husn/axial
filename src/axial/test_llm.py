"""Inner unit tests for the axial llm module (issue #16 slice 04 --
structural envelope; the LLM client seam every LLM-backed pass reuses)."""

from __future__ import annotations

import json

import httpx
import pytest


def test_stub_client_returns_a_non_empty_envelope_shaped_response():
    from axial.llm import StubLLMClient

    client = StubLLMClient()

    raw = client.complete("some prompt")
    parsed = json.loads(raw)

    assert isinstance(parsed["thesis"], str) and parsed["thesis"].strip()
    assert isinstance(parsed["toc"], list) and len(parsed["toc"]) > 0
    assert isinstance(parsed["scope"], str) and parsed["scope"].strip()
    assert isinstance(parsed["stated_argument"], str) and parsed["stated_argument"].strip()


def test_stub_client_records_call_count():
    from axial.llm import StubLLMClient

    client = StubLLMClient()
    assert client.call_count == 0

    client.complete("prompt one")
    client.complete("prompt two")

    assert client.call_count == 2


def test_exploding_client_construction_does_not_raise():
    from axial.llm import ExplodingLLMClient

    # Selecting/constructing the poison client must never itself be an error.
    client = ExplodingLLMClient()
    assert client is not None


def test_exploding_client_raises_when_complete_is_invoked():
    from axial.llm import ExplodingLLMClient

    client = ExplodingLLMClient()

    with pytest.raises(Exception):
        client.complete("anything")


def test_get_client_selects_stub_via_env_override(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, StubLLMClient, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "stub")

    client = get_client(config_path=tmp_path / "does_not_exist.yaml")

    assert isinstance(client, StubLLMClient)


def test_get_client_selects_explode_via_env_override(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, ExplodingLLMClient, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "explode")

    client = get_client(config_path=tmp_path / "does_not_exist.yaml")

    assert isinstance(client, ExplodingLLMClient)


def test_get_client_env_override_takes_precedence_over_config_file(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, StubLLMClient, get_client

    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")
    monkeypatch.setenv(PROVIDER_ENV_VAR, "stub")

    client = get_client(config_path=config_path)

    assert isinstance(client, StubLLMClient)


def test_get_client_reads_provider_from_config_file_when_no_env_override(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, StubLLMClient, get_client

    monkeypatch.delenv(PROVIDER_ENV_VAR, raising=False)
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: stub\n", encoding="utf-8")

    client = get_client(config_path=config_path)

    assert isinstance(client, StubLLMClient)


def test_get_client_openrouter_requires_an_api_key_env_var(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, get_client

    monkeypatch.delenv(PROVIDER_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    with pytest.raises(ValueError):
        get_client(config_path=config_path)


def test_get_client_unknown_provider_raises(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "not-a-real-provider")

    with pytest.raises(ValueError):
        get_client(config_path=tmp_path / "does_not_exist.yaml")


# --- OpenRouter client: mocked transport, never a live network call --------


def test_openrouter_client_builds_the_expected_request_and_parses_the_response():
    from axial.llm import OpenRouterClient

    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "model reply"}}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(
        api_key="test-key",
        model="test-model",
        transport=transport,
    )

    result = client.complete("hello world")

    assert result == "model reply"
    assert len(captured_requests) == 1
    request = captured_requests[0]
    assert request.url.path == "/api/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "test-model"
    assert body["messages"] == [{"role": "user", "content": "hello world"}]


def test_openrouter_client_raises_a_typed_error_on_malformed_response():
    from axial.llm import OpenRouterClient, OpenRouterError

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(OpenRouterError):
        client.complete("hello world")


def test_openrouter_client_raises_on_http_error_status():
    from axial.llm import OpenRouterClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        client.complete("hello world")
