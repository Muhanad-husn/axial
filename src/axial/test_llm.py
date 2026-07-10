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


def test_stub_client_returns_envelope_shaped_response_for_a_non_chunk_prompt():
    from axial.llm import StubLLMClient

    client = StubLLMClient()

    raw = client.complete("an ordinary envelope prompt")
    parsed = json.loads(raw)

    assert "thesis" in parsed
    assert "chunks" not in parsed


def test_stub_client_returns_chunk_shaped_response_for_the_chunk_pass_name():
    from axial.llm import CHUNK_PASS_NAME, StubLLMClient

    client = StubLLMClient()

    raw = client.complete("some chunking prompt", pass_name=CHUNK_PASS_NAME)
    parsed = json.loads(raw)

    assert isinstance(parsed["chunks"], list) and len(parsed["chunks"]) > 0
    for chunk in parsed["chunks"]:
        assert isinstance(chunk["text"], str) and chunk["text"].strip()


def test_stub_client_chunk_response_defaults_to_an_unset_env_var(monkeypatch):
    from axial.llm import CHUNK_PASS_NAME, STUB_CHUNK_RESPONSE_ENV_VAR, StubLLMClient

    monkeypatch.delenv(STUB_CHUNK_RESPONSE_ENV_VAR, raising=False)
    client = StubLLMClient()

    raw = client.complete("some chunking prompt", pass_name=CHUNK_PASS_NAME)
    parsed = json.loads(raw)

    assert isinstance(parsed["chunks"], list) and len(parsed["chunks"]) > 0


def test_stub_client_honors_the_forced_chunk_response_env_var(monkeypatch):
    from axial.llm import CHUNK_PASS_NAME, STUB_CHUNK_RESPONSE_ENV_VAR, StubLLMClient

    override = '{"chunks": [{"text": "overridden chunk text"}]}'
    monkeypatch.setenv(STUB_CHUNK_RESPONSE_ENV_VAR, override)
    client = StubLLMClient()

    raw = client.complete("some chunking prompt", pass_name=CHUNK_PASS_NAME)

    assert raw == override


def test_stub_client_chunk_response_override_does_not_affect_other_passes(monkeypatch):
    from axial.llm import STUB_CHUNK_RESPONSE_ENV_VAR, TAG_PASS_NAME, StubLLMClient

    monkeypatch.setenv(STUB_CHUNK_RESPONSE_ENV_VAR, '{"chunks": [{"text": "overridden"}]}')
    client = StubLLMClient()

    raw = client.complete("some tagging prompt", pass_name=TAG_PASS_NAME)
    parsed = json.loads(raw)

    assert "role_in_argument" in parsed
    assert "chunks" not in parsed


def test_record_client_honors_the_forced_chunk_response_env_var(monkeypatch, tmp_path):
    from axial.llm import CHUNK_PASS_NAME, STUB_CHUNK_RESPONSE_ENV_VAR, RecordLLMClient

    override = '{"chunks": [{"text": "overridden chunk text"}]}'
    monkeypatch.setenv(STUB_CHUNK_RESPONSE_ENV_VAR, override)
    record = RecordLLMClient(tmp_path / "prompts.jsonl")

    raw = record.complete("some chunking prompt", pass_name=CHUNK_PASS_NAME)

    assert raw == override


def test_stub_client_returns_tag_shaped_response_for_the_tag_pass_name():
    from axial.llm import TAG_PASS_NAME, StubLLMClient

    client = StubLLMClient()

    raw = client.complete("some tagging prompt", pass_name=TAG_PASS_NAME)
    parsed = json.loads(raw)

    assert isinstance(parsed["role_in_argument"], str) and parsed["role_in_argument"].strip()
    assert "chunks" not in parsed
    assert "thesis" not in parsed


def test_stub_client_returns_artifact_shaped_response_for_the_artifacts_pass_name():
    from axial.llm import ARTIFACTS_PASS_NAME, StubLLMClient

    client = StubLLMClient()

    raw = client.complete("some artifact classification prompt", pass_name=ARTIFACTS_PASS_NAME)
    parsed = json.loads(raw)

    assert isinstance(parsed["artifact_role"], str) and parsed["artifact_role"].strip()
    assert "chunks" not in parsed
    assert "thesis" not in parsed


def test_stub_client_artifact_response_carries_a_primary_secondary_field_value():
    """Issue #32 slice 02: the artifacts-pass canned response must also
    carry a `field` value in the same `{"primary": ..., "secondary": [...]}`
    shape the tag pass already uses for its primary_plus_secondary axes, so
    the artifacts pass can classify `field` end-to-end against the stub."""
    from axial.llm import ARTIFACTS_PASS_NAME, StubLLMClient

    client = StubLLMClient()

    raw = client.complete("some artifact classification prompt", pass_name=ARTIFACTS_PASS_NAME)
    parsed = json.loads(raw)

    field = parsed["field"]
    assert isinstance(field["primary"], str) and field["primary"].strip()
    assert isinstance(field["secondary"], list)


def test_stub_client_artifact_role_defaults_to_an_unset_env_var(monkeypatch):
    from axial.llm import ARTIFACTS_PASS_NAME, STUB_ARTIFACT_ROLE_ENV_VAR, StubLLMClient

    monkeypatch.delenv(STUB_ARTIFACT_ROLE_ENV_VAR, raising=False)
    client = StubLLMClient()

    raw = client.complete("prompt", pass_name=ARTIFACTS_PASS_NAME)
    parsed = json.loads(raw)

    assert parsed["artifact_role"]


def test_stub_client_honors_the_forced_artifact_role_env_var(monkeypatch):
    from axial.llm import ARTIFACTS_PASS_NAME, STUB_ARTIFACT_ROLE_ENV_VAR, StubLLMClient

    monkeypatch.setenv(STUB_ARTIFACT_ROLE_ENV_VAR, "not-a-real-role")
    client = StubLLMClient()

    raw = client.complete("prompt", pass_name=ARTIFACTS_PASS_NAME)
    parsed = json.loads(raw)

    assert parsed["artifact_role"] == "not-a-real-role"


@pytest.fixture(autouse=True)
def _reset_artifact_call_counter():
    """The AXIAL_STUB_ARTIFACT_FAIL_AT counter is a per-process module
    global; reset it before every test so counts don't bleed across tests in
    one pytest process (mirrors `test_resume.py`'s own `_tag_pass_call_count`
    reset fixture, issue #98)."""
    import axial.llm as llm_mod

    llm_mod._artifact_pass_call_count = 0
    yield
    llm_mod._artifact_pass_call_count = 0


def test_artifact_fail_at_raises_on_the_nth_artifact_call_only(monkeypatch):
    from axial.llm import ARTIFACTS_PASS_NAME, LLMError, StubLLMClient

    monkeypatch.setenv("AXIAL_STUB_ARTIFACT_FAIL_AT", "2")
    client = StubLLMClient()

    # First artifacts call succeeds.
    client.complete("p1", pass_name=ARTIFACTS_PASS_NAME)
    # Second artifacts call raises an LLMError subclass.
    with pytest.raises(LLMError):
        client.complete("p2", pass_name=ARTIFACTS_PASS_NAME)
    # Third and later still succeed (only the Nth fails).
    assert client.complete("p3", pass_name=ARTIFACTS_PASS_NAME)


def test_artifact_fail_at_counts_only_artifacts_pass_calls(monkeypatch):
    from axial.llm import ARTIFACTS_PASS_NAME, CHUNK_PASS_NAME, LLMError, StubLLMClient

    monkeypatch.setenv("AXIAL_STUB_ARTIFACT_FAIL_AT", "2")
    client = StubLLMClient()

    # Chunk-pass calls never advance the artifacts counter.
    client.complete("c1", pass_name=CHUNK_PASS_NAME)
    client.complete("c2", pass_name=CHUNK_PASS_NAME)

    # So the first artifacts call is call #1 (succeeds), the second is #2 (fails).
    client.complete("a1", pass_name=ARTIFACTS_PASS_NAME)
    with pytest.raises(LLMError):
        client.complete("a2", pass_name=ARTIFACTS_PASS_NAME)


@pytest.mark.parametrize("value", ["", "0", "-3", "notanumber"])
def test_artifact_fail_at_never_fails_for_unset_or_nonpositive(monkeypatch, value):
    from axial.llm import ARTIFACTS_PASS_NAME, StubLLMClient

    monkeypatch.setenv("AXIAL_STUB_ARTIFACT_FAIL_AT", value)
    client = StubLLMClient()
    for _ in range(5):
        assert client.complete("p", pass_name=ARTIFACTS_PASS_NAME)


def test_artifact_fail_at_is_honored_by_record_client(monkeypatch, tmp_path):
    from axial.llm import ARTIFACTS_PASS_NAME, LLMError, RecordLLMClient

    monkeypatch.setenv("AXIAL_STUB_ARTIFACT_FAIL_AT", "1")
    client = RecordLLMClient(tmp_path / "rec.jsonl")
    with pytest.raises(LLMError):
        client.complete("p", pass_name=ARTIFACTS_PASS_NAME)


def test_stub_injected_artifact_failure_error_is_an_llm_error():
    from axial.llm import LLMError, StubInjectedArtifactFailureError

    assert issubclass(StubInjectedArtifactFailureError, LLMError)


def test_record_client_response_matches_stub_for_the_artifacts_pass_name(tmp_path):
    from axial.llm import ARTIFACTS_PASS_NAME, RecordLLMClient, StubLLMClient

    stub = StubLLMClient()
    record = RecordLLMClient(tmp_path / "prompts.jsonl")

    prompt = "some artifact classification prompt"

    assert record.complete(prompt, pass_name=ARTIFACTS_PASS_NAME) == stub.complete(
        prompt, pass_name=ARTIFACTS_PASS_NAME
    )


def test_stub_client_dispatch_is_by_pass_name_not_prompt_content():
    """The chunk-vs-envelope canned-response dispatch must be driven by the
    out-of-band `pass_name` argument, never by scanning prompt text -- so an
    ordinary prompt that happens to mention "chunk" still gets the
    envelope-shaped response when no pass_name is given."""
    from axial.llm import StubLLMClient

    client = StubLLMClient()

    raw = client.complete("a prompt that happens to mention chunk boundaries")
    parsed = json.loads(raw)

    assert "thesis" in parsed
    assert "chunks" not in parsed


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


def test_get_client_selects_record_via_env_override(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, RECORD_PATH_ENV_VAR, RecordLLMClient, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "record")
    monkeypatch.setenv(RECORD_PATH_ENV_VAR, str(tmp_path / "prompts.jsonl"))

    client = get_client(config_path=tmp_path / "does_not_exist.yaml")

    assert isinstance(client, RecordLLMClient)


def test_get_client_record_without_record_path_raises_llm_config_error(monkeypatch, tmp_path):
    from axial.llm import LLMConfigError, PROVIDER_ENV_VAR, RECORD_PATH_ENV_VAR, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "record")
    monkeypatch.delenv(RECORD_PATH_ENV_VAR, raising=False)

    with pytest.raises(LLMConfigError):
        get_client(config_path=tmp_path / "does_not_exist.yaml")


def test_record_client_appends_json_encoded_prompts_creating_parent_dirs(tmp_path):
    from axial.llm import RecordLLMClient

    record_path = tmp_path / "nested" / "prompts.jsonl"
    client = RecordLLMClient(record_path)

    client.complete("prompt one")
    client.complete("prompt two")

    lines = record_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == ["prompt one", "prompt two"]


def test_record_client_response_matches_stub_for_the_same_call(tmp_path):
    from axial.llm import CHUNK_PASS_NAME, RecordLLMClient, StubLLMClient

    stub = StubLLMClient()
    record = RecordLLMClient(tmp_path / "prompts.jsonl")

    envelope_prompt = "an ordinary envelope prompt"
    chunk_prompt = "some chunking prompt"

    assert record.complete(envelope_prompt) == stub.complete(envelope_prompt)
    assert record.complete(chunk_prompt, pass_name=CHUNK_PASS_NAME) == stub.complete(
        chunk_prompt, pass_name=CHUNK_PASS_NAME
    )


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
    from axial.llm import PROVIDER_ENV_VAR, SECRETS_PATH_ENV_VAR, get_client

    monkeypatch.delenv(PROVIDER_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Redirect the secrets-file seam so this test is hermetic against the
    # developer's real secrets/secrets.toml (issue #23, requirement 4).
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(tmp_path / "does_not_exist_secrets.toml"))
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    with pytest.raises(ValueError):
        get_client(config_path=config_path)


def test_get_client_unknown_provider_raises(monkeypatch, tmp_path):
    from axial.llm import PROVIDER_ENV_VAR, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "not-a-real-provider")

    with pytest.raises(ValueError):
        get_client(config_path=tmp_path / "does_not_exist.yaml")


# --- typed LLM error hierarchy (so callers can catch one type and wrap it,
# instead of a bare ValueError/traceback reaching the CLI) -------------------


def test_missing_api_key_raises_llm_config_error(monkeypatch, tmp_path):
    from axial.llm import LLMConfigError, PROVIDER_ENV_VAR, SECRETS_PATH_ENV_VAR, get_client

    monkeypatch.delenv(PROVIDER_ENV_VAR, raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # Redirect the secrets-file seam so this test is hermetic against the
    # developer's real secrets/secrets.toml (issue #23, requirement 4).
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(tmp_path / "does_not_exist_secrets.toml"))
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    with pytest.raises(LLMConfigError):
        get_client(config_path=config_path)


def test_unknown_provider_raises_llm_config_error(monkeypatch, tmp_path):
    from axial.llm import LLMConfigError, PROVIDER_ENV_VAR, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "not-a-real-provider")

    with pytest.raises(LLMConfigError):
        get_client(config_path=tmp_path / "does_not_exist.yaml")


def test_llm_config_error_is_an_llm_error():
    from axial.llm import LLMConfigError, LLMError

    assert issubclass(LLMConfigError, LLMError)


def test_openrouter_error_is_an_llm_error():
    from axial.llm import LLMError, OpenRouterError

    assert issubclass(OpenRouterError, LLMError)


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


def test_openrouter_client_ignores_pass_name_and_never_forwards_it():
    """`pass_name` is a stub/record-only dispatch seam; a real provider must
    accept it (so callers can pass it uniformly) but never let it leak into
    the actual request sent to the model."""
    from axial.llm import OpenRouterClient

    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world", pass_name="chunk")

    assert result == "model reply"
    body = json.loads(captured_requests[0].content)
    assert body["messages"] == [{"role": "user", "content": "hello world"}]
    assert "chunk" not in json.dumps(body)


def test_openrouter_client_raises_on_http_error_status(monkeypatch):
    """A persistent 5xx is retried (issue #60) but still fails in the end,
    exactly with the same `httpx.HTTPStatusError` type as before."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        client.complete("hello world")

    assert call_count == 3


# --- timeout and bounded retry (issue #60) ----------------------------------


def test_openrouter_client_carries_the_explicit_request_timeout():
    """httpx's 5s default read timeout kills a real completion before a
    slow model finishes; the client must be built with an explicit,
    generous timeout instead (issue #60)."""
    from axial.llm import OpenRouterClient, _REQUEST_TIMEOUT

    client = OpenRouterClient(api_key="test-key", model="test-model", transport=None)

    assert client._client.timeout == _REQUEST_TIMEOUT
    assert client._client.timeout.read == 180.0
    assert client._client.timeout.connect == 15.0
    assert client._client.timeout.write == 30.0
    assert client._client.timeout.pool == 15.0


def test_openrouter_client_retries_a_read_timeout_then_succeeds(monkeypatch):
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 3


def test_openrouter_client_retries_a_read_error_then_succeeds(monkeypatch):
    """A raw TCP reset surfaces as httpx.ReadError -- a TransportError
    subclass but not a TimeoutException -- and must be retried exactly like
    a timeout (issue #82)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadError("connection forcibly closed", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


def test_openrouter_client_gives_up_after_max_attempts_on_a_persistent_read_error(monkeypatch):
    """A persistent ReadError exhausts the retry budget and propagates,
    exactly like a persistent timeout (issue #82)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadError("connection forcibly closed", request=request)

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(httpx.ReadError):
        client.complete("hello world")

    assert call_count == 3


def test_openrouter_client_retries_a_429_then_succeeds(monkeypatch):
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


def test_openrouter_client_gives_up_after_max_attempts_on_a_persistent_timeout(monkeypatch):
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ReadTimeout("timed out", request=request)

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(httpx.ReadTimeout):
        client.complete("hello world")

    assert call_count == 3


def test_openrouter_client_does_not_retry_a_non_retryable_4xx(monkeypatch):
    """A 400 (or any non-429 4xx) is not transient and must fail on the
    first attempt, exactly as before this issue."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(400, json={"error": "bad request"})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        client.complete("hello world")

    assert call_count == 1


def test_openrouter_client_does_not_retry_a_malformed_response_shape(monkeypatch):
    """A malformed response body is a parsing bug, not a transient
    transport failure -- it must still fail immediately with
    `OpenRouterError`, never retried."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, OpenRouterError

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(OpenRouterError):
        client.complete("hello world")

    assert call_count == 1


# --- empty-completion retry (issue #66) ------------------------------------


def test_openrouter_client_retries_an_empty_completion_then_succeeds(monkeypatch):
    """A provider occasionally returns HTTP 200 with an empty `content` --
    that must be treated as transient (retried), not passed through to a
    downstream JSON parser (issue #66)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


def test_openrouter_client_gives_up_after_max_attempts_on_persistent_empty_completion(monkeypatch):
    """If every attempt yields an empty completion, the client must give up
    after the same bounded budget as any other transient failure and raise
    a typed `OpenRouterError` naming the condition (issue #66)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, OpenRouterError

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(OpenRouterError, match="empty completion"):
        client.complete("hello world")

    assert call_count == 3


def test_openrouter_client_treats_whitespace_only_content_as_empty(monkeypatch):
    """A whitespace-only `content` (e.g. a stray newline) is functionally
    empty and must be retried exactly like a fully empty string (issue #66)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "  \n"}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


def test_openrouter_client_treats_null_content_as_empty_not_malformed(monkeypatch):
    """`content: null` is a shape the API can legitimately return for an
    empty completion -- it must be retried like any other empty completion,
    not raise the immediate malformed-shape error (issue #66)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


# --- truncated-completion retry (issue #69) --------------------------------


def test_openrouter_client_retries_a_truncated_completion_then_succeeds(monkeypatch):
    """A `finish_reason` other than `"stop"` (e.g. `"length"`) means the
    provider cut the completion short -- that must be retried like any other
    transient failure, not passed through to a downstream JSON parser
    (issue #69)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": '{"partial": "cut off'}, "finish_reason": "length"}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "model reply"}, "finish_reason": "stop"}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


def test_openrouter_client_gives_up_after_max_attempts_on_persistent_truncation(monkeypatch):
    """If every attempt is truncated, the client must give up after the same
    bounded budget as any other transient failure and raise a typed
    `OpenRouterError` naming the finish_reason (issue #69)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, OpenRouterError

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "still cut off"}, "finish_reason": "length"}]
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(OpenRouterError, match="length"):
        client.complete("hello world")

    assert call_count == 3


def test_openrouter_client_accepts_null_finish_reason(monkeypatch):
    """A `finish_reason: null` is a provider that legitimately omits the
    field -- it must be accepted as success, not retried (issue #69)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "model reply"}, "finish_reason": None}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 1


def test_openrouter_client_accepts_absent_finish_reason(monkeypatch):
    """A response with no `finish_reason` key at all (a provider that omits
    it entirely) must be accepted as success, not retried (issue #69)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 1


def test_openrouter_client_request_body_carries_max_tokens():
    """The request body must include an explicit `max_tokens` so
    legitimately long completions (chunking responses echo section text)
    aren't cut by a conservative provider default (issue #69)."""
    from axial.llm import OpenRouterClient, _MAX_COMPLETION_TOKENS

    captured_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    client.complete("hello world")

    body = json.loads(captured_requests[0].content)
    assert body["max_tokens"] == _MAX_COMPLETION_TOKENS


def test_openrouter_client_does_not_double_retry_empty_and_truncated_in_one_attempt(monkeypatch):
    """A response that is BOTH empty and non-`"stop"` must only consume one
    retry per attempt (share the same transient-this-attempt path), so the
    3-attempt budget still yields exactly 3 requests, not more (issue #69)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient, OpenRouterError

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        )

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(OpenRouterError):
        client.complete("hello world")

    assert call_count == 3


# --- malformed API response body retry (issue #86) -------------------------


def test_openrouter_client_retries_a_malformed_response_body_then_succeeds(monkeypatch):
    """An HTTP 200 whose body is not valid JSON (e.g. a proxy error page)
    must be retried within the same bounded budget as any other transient
    failure, not let a raw `json.JSONDecodeError` escape (issue #86)."""
    import axial.llm as llm_module
    from axial.llm import OpenRouterClient

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, content=b"<html>proxy error</html>")
        return httpx.Response(200, json={"choices": [{"message": {"content": "model reply"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    result = client.complete("hello world")

    assert result == "model reply"
    assert call_count == 2


def test_openrouter_client_gives_up_after_max_attempts_on_persistent_malformed_body(monkeypatch):
    """If every attempt returns a non-JSON body, the client must give up
    after the same bounded budget as any other transient failure and raise a
    typed `OpenRouterError` (an `LLMError` -- the CLI error surface) naming
    the condition with a body snippet for diagnosability (issue #86)."""
    import axial.llm as llm_module
    from axial.llm import LLMError, OpenRouterClient, OpenRouterError

    monkeypatch.setattr(llm_module, "_sleep", lambda seconds: None)
    call_count = 0
    garbage = b"<html>proxy error</html>" + b"\n" * 5

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=garbage)

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    with pytest.raises(OpenRouterError, match="malformed") as exc_info:
        client.complete("hello world")

    assert call_count == 3
    assert isinstance(exc_info.value, LLMError)
    assert "proxy error" in str(exc_info.value)


# --- secrets.toml error handling (issue #23 review findings) --------------


def test_malformed_secrets_toml_raises_llm_config_error(monkeypatch, tmp_path):
    """A syntactically invalid secrets.toml must not let a raw
    `tomllib.TOMLDecodeError` escape -- every error this module raises must
    be an `LLMError` (module docstring)."""
    from axial.llm import LLMConfigError, PROVIDER_ENV_VAR, SECRETS_PATH_ENV_VAR, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "openrouter")
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text("[openrouter\napi_key = broken", encoding="utf-8")
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    with pytest.raises(LLMConfigError) as exc_info:
        get_client(config_path=config_path)

    assert str(secrets_path) in str(exc_info.value)


def test_malformed_secrets_toml_error_names_the_offending_path(tmp_path):
    from axial.llm import LLMConfigError, _load_openrouter_secrets

    secrets_path = tmp_path / "bad_secrets.toml"
    secrets_path.write_text("not = valid = toml", encoding="utf-8")

    with pytest.raises(LLMConfigError) as exc_info:
        _load_openrouter_secrets(secrets_path)

    assert str(secrets_path) in str(exc_info.value)


def test_missing_production_tier_model_key_raises_llm_config_error(monkeypatch, tmp_path):
    """A non-building tier with no matching model key in secrets.toml must
    fail loudly rather than silently falling back to DEFAULT_BUILDING_MODEL
    (issue #23 review finding 2)."""
    from axial.llm import LLMConfigError, PROVIDER_ENV_VAR, SECRETS_PATH_ENV_VAR, get_client

    monkeypatch.setenv(PROVIDER_ENV_VAR, "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        '[openrouter]\napi_key = "sk-fixture"\nllm_tier = "production_high"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    with pytest.raises(LLMConfigError):
        get_client(config_path=config_path)


def test_missing_building_tier_model_key_still_falls_back_to_default(monkeypatch, tmp_path):
    """The `building` tier must keep its default fallback so today's
    no-secrets-file behavior is unchanged (issue #23 review finding 2)."""
    from axial.llm import DEFAULT_BUILDING_MODEL, _resolve_model

    model = _resolve_model(secrets={}, llm_config={})

    assert model == DEFAULT_BUILDING_MODEL


def test_missing_production_tier_model_key_raises_directly_from_resolve_model():
    from axial.llm import LLMConfigError, _resolve_model

    with pytest.raises(LLMConfigError):
        _resolve_model(secrets={"llm_tier": "production_low"}, llm_config={})
