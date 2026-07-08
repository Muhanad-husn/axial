"""Outer acceptance test for issue #23 (secrets-driven API key & model
tiering).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given `[openrouter]` config split across `secrets/secrets.toml` (primary) and
      the `OPENROUTER_API_KEY` environment variable (fallback), plus a model
      tier selector (`llm_tier`) naming one of `building_model`,
      `production_high`, `production_low`
When   `axial.llm.get_client()` builds the `openrouter` provider
Then   the API key comes from `secrets.toml` when present there, falling
       back to the environment variable only when the file is absent or
       lacks the key, and raising `LLMConfigError` when neither source has
       one
And    the model actually sent to OpenRouter is the one named by the
       selected tier (in particular, the "building" tier resolves to
       `building_model`, e.g. `nvidia/nemotron-3-ultra-550b-a55b:free` --
       never the old hardcoded `openrouter/auto`)

See GitHub issue #23 ("feat(llm-config): secrets-driven API key & model
tiering") for the source of truth: requirement 1 (API key sourced from
secrets.toml, primary, env fallback, `LLMConfigError` if neither), and
requirement 2 (three model-name keys plus an `llm_tier` selector in
`[openrouter]`, with `get_client()` picking the model that matches the
selected tier).

Seam decision -- redirecting the secrets file path for a hermetic test
-----------------------------------------------------------------------
This test must never read the developer's real `secrets/secrets.toml` (it
may contain a real key). `get_client()`'s signature is explicitly required
to stay unchanged at the interface level (issue #23, requirement 4), so the
redirect cannot be a new keyword argument. Instead, this test drives the
existing codebase convention for hermetic seams -- an environment-variable
override, mirroring `AXIAL_LLM_PROVIDER` (provider selection) and
`AXIAL_LLM_RECORD_PATH` (record-client destination), both already read by
`src/axial/llm.py`:

    AXIAL_SECRETS_PATH   overrides the path `get_client()` reads
                         `[openrouter]` from (default: `secrets/secrets.toml`
                         relative to the repo root). Unset/"" means "use the
                         default path" -- exactly like the other seams in
                         this module.

If this env var does not exist yet in `src/axial/llm.py`, that is precisely
the seam this red test requires the implementer to build; the test does not
invent any other public entry point, and does not reach into private
attributes to inspect the resolved model or key.

Seam decision -- observing the resolved key/model without a live network call
-----------------------------------------------------------------------
`get_client()` returns a real `OpenRouterClient`, which owns an `httpx.Client`
that would otherwise make a genuine HTTP call on `.complete()`. Rather than
peek at the client's private attributes (an implementation detail, and
exactly the kind of coupling a locked outer contract must avoid), this test
patches `httpx.Client.post` for the duration of each test to capture the
outgoing request's `Authorization` header and JSON `model` field, then lets
`.complete()` return a well-formed canned response. This drives the client
through its real, documented public interface (`.complete()`) and asserts on
what it actually would have sent, with zero network access.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

SECRETS_PATH_ENV_VAR = "AXIAL_SECRETS_PATH"

BUILDING_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
PRODUCTION_HIGH_MODEL = "deepseek/deepseek-v4-pro"
PRODUCTION_LOW_MODEL = "deepseek/deepseek-v4-flash"


def _write_secrets_toml(
    path: Path,
    *,
    api_key: str | None,
    building_model: str | None = BUILDING_MODEL,
    production_high: str | None = PRODUCTION_HIGH_MODEL,
    production_low: str | None = PRODUCTION_LOW_MODEL,
    llm_tier: str | None = "building",
) -> None:
    lines = ["[openrouter]"]
    if api_key is not None:
        lines.append(f'api_key = "{api_key}"')
    if building_model is not None:
        lines.append(f'building_model = "{building_model}"')
    if production_high is not None:
        lines.append(f'production_high = "{production_high}"')
    if production_low is not None:
        lines.append(f'production_low = "{production_low}"')
    if llm_tier is not None:
        lines.append(f'llm_tier = "{llm_tier}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _CapturingTransport:
    """Patches `httpx.Client.post` so any `OpenRouterClient` built by
    `get_client()` -- which owns a real `httpx.Client` with no transport
    injected -- never makes a live network call, while still recording
    exactly what it would have sent."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls: list[dict[str, Any]] = []

        def fake_post(client_self, url, *, headers=None, json=None, **kwargs):
            self.calls.append({"url": url, "headers": headers or {}, "json": json or {}})
            # noqa placeholder retained intentionally: `json` here is the
            # keyword argument httpx.Client.post is called with in
            # production code (`src/axial/llm.py`'s `OpenRouterClient.
            # complete`), not the stdlib module -- no shadowing bug.
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "canned reply"}}]},
                request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
            )

        monkeypatch.setattr(httpx.Client, "post", fake_post)

    @property
    def last(self) -> dict[str, Any]:
        assert self.calls, "expected .complete() to have issued exactly one HTTP POST"
        return self.calls[-1]


def _build_and_complete(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    from axial.llm import get_client

    capture = _CapturingTransport(monkeypatch)
    client = get_client(config_path=tmp_path / "does_not_exist_pipeline.yaml")
    result = client.complete("does the request use the right key and model?")
    assert result == "canned reply"
    return capture.last


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the real `openrouter` provider regardless of `config/
    pipeline.yaml`'s current default, mirroring the existing
    `test_get_client_env_override_takes_precedence_over_config_file`
    convention in `src/axial/test_llm.py`."""
    from axial.llm import PROVIDER_ENV_VAR

    monkeypatch.setenv(PROVIDER_ENV_VAR, "openrouter")


def test_get_client_sources_api_key_and_building_model_from_secrets_toml_primary(
    monkeypatch, tmp_path
):
    """Requirement 1 (secrets.toml is PRIMARY) + requirement 2/3 (building
    tier resolves to building_model, not `openrouter/auto`), together in one
    scenario: a secrets.toml with a key present, and NO env var key at all,
    must still produce a working client using the secrets.toml key and the
    building_model named there."""
    _base_env(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets_toml(secrets_path, api_key="sk-fixture-primary-key")
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    sent = _build_and_complete(monkeypatch, tmp_path)

    assert sent["headers"].get("Authorization") == "Bearer sk-fixture-primary-key", (
        f"expected the request to authenticate with the secrets.toml api_key "
        f"(secrets.toml is the PRIMARY source per issue #23), got headers: "
        f"{sent['headers']!r}"
    )
    assert sent["json"].get("model") == BUILDING_MODEL, (
        f"expected the 'building' tier to resolve to building_model "
        f"({BUILDING_MODEL!r}), not the old hardcoded 'openrouter/auto' or "
        f"anything else, got: {sent['json'].get('model')!r}"
    )


def test_get_client_falls_back_to_env_var_when_secrets_toml_file_is_absent(monkeypatch, tmp_path):
    """Requirement 1, fallback branch: no secrets.toml at all -> the
    OPENROUTER_API_KEY env var must still work."""
    _base_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env-fallback-key")
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(tmp_path / "does_not_exist_secrets.toml"))

    sent = _build_and_complete(monkeypatch, tmp_path)

    assert sent["headers"].get("Authorization") == "Bearer sk-env-fallback-key", (
        f"expected a fallback to OPENROUTER_API_KEY when secrets.toml is "
        f"absent, got headers: {sent['headers']!r}"
    )


def test_get_client_falls_back_to_env_var_when_secrets_toml_lacks_the_api_key(
    monkeypatch, tmp_path
):
    """Requirement 1, fallback branch: secrets.toml exists (and even names a
    building_model) but has no api_key -> the env var must still work."""
    _base_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-env-fallback-key-2")

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets_toml(secrets_path, api_key=None)
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    sent = _build_and_complete(monkeypatch, tmp_path)

    assert sent["headers"].get("Authorization") == "Bearer sk-env-fallback-key-2", (
        f"expected a fallback to OPENROUTER_API_KEY when secrets.toml is "
        f"present but missing api_key, got headers: {sent['headers']!r}"
    )


def test_get_client_raises_llm_config_error_when_neither_source_has_a_key(monkeypatch, tmp_path):
    """Requirement 1, hard-failure branch: neither secrets.toml nor the env
    var supplies a key -> LLMConfigError, not a bare exception or a silent
    None key reaching the HTTP layer."""
    from axial.llm import LLMConfigError, get_client

    _base_env(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(tmp_path / "does_not_exist_secrets.toml"))

    with pytest.raises(LLMConfigError):
        get_client(config_path=tmp_path / "does_not_exist_pipeline.yaml")


@pytest.mark.parametrize(
    ("tier", "expected_model"),
    [
        ("building", BUILDING_MODEL),
        ("production_high", PRODUCTION_HIGH_MODEL),
        ("production_low", PRODUCTION_LOW_MODEL),
    ],
)
def test_get_client_selects_model_by_llm_tier_key(monkeypatch, tmp_path, tier, expected_model):
    """Requirement 2: `llm_tier` is a real selector across all three tiers,
    not a hardcoded building-only special case -- selecting each tier must
    route to its correspondingly named model key in secrets.toml."""
    _base_env(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    secrets_path = tmp_path / "secrets.toml"
    _write_secrets_toml(secrets_path, api_key="sk-fixture-primary-key", llm_tier=tier)
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    sent = _build_and_complete(monkeypatch, tmp_path)

    assert sent["json"].get("model") == expected_model, (
        f"expected llm_tier={tier!r} to select model {expected_model!r}, "
        f"got: {sent['json'].get('model')!r}"
    )
