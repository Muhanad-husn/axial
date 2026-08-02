"""Outer acceptance test for issue #527, `axial key check`'s own logic
(`axial.llm.check_key`).

Given a configured `[openrouter]` API key (secrets.toml or the
      `OPENROUTER_API_KEY` fallback -- the existing resolution order,
      unchanged)
When  `check_key()` runs
Then  it makes exactly ONE completion call to prove the key authenticates
      -- never one call per model tier
  And on success it reports which of the named model tiers secrets.toml
      configures a model for ("reachable") and which it does not
      ("unreachable"), computed from config alone with no further call
  And a missing API key fails before any call is made at all
  And a call that raises `LLMError` (the shape a real 401 unauthorized
      response would surface as) reports `valid=False` with no tier report

The single "live" call is proven with a stub client injected via
`check_key(client=...)` -- `axial.llm`'s own test-seam convention
(mirrors `axial.pipeline_ready.evaluate_canary`'s `client=None` shape) --
never a real network call.

See GitHub issue #527 for the source of truth.
"""

from __future__ import annotations

from axial.llm import LLMError, check_key

SECRETS_PATH_ENV_VAR = "AXIAL_SECRETS_PATH"


class _CountingStubClient:
    """A minimal `LLMClient`-shaped stub: only `.complete()` is exercised
    by `check_key`, so only that method is implemented -- duck typing, no
    real network access, ever."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.call_count = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        if self.raises is not None:
            raise self.raises
        return "ok"


def _write_secrets_toml(path, **tiers: str) -> None:
    lines = ["[openrouter]", 'api_key = "sk-or-fixture-key"']
    for key, value in tiers.items():
        lines.append(f'{key} = "{value}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_check_key_makes_exactly_one_call_and_reports_valid(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets_toml(
        secrets_path,
        building_model="nvidia/nemotron-3-ultra-550b-a55b:free",
        production_high="deepseek/deepseek-v4-pro",
    )
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    stub = _CountingStubClient()
    result = check_key(config_path=tmp_path / "does_not_exist_pipeline.yaml", client=stub)

    assert stub.call_count == 1, "expected exactly one completion call, never one per tier"
    assert result.valid is True
    assert result.error is None
    assert "building" in result.reachable_tiers
    assert "production_high" in result.reachable_tiers
    assert "production_low" in result.unreachable_tiers


def test_check_key_reports_invalid_on_a_call_failure_with_no_tier_report(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    _write_secrets_toml(secrets_path)
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    stub = _CountingStubClient(raises=LLMError("401 unauthorized"))
    result = check_key(config_path=tmp_path / "does_not_exist_pipeline.yaml", client=stub)

    assert stub.call_count == 1
    assert result.valid is False
    assert result.error is not None and "401" in result.error
    assert result.reachable_tiers == []
    assert result.unreachable_tiers == {}


def test_check_key_fails_fast_on_a_missing_api_key_with_zero_calls(monkeypatch, tmp_path):
    secrets_path = tmp_path / "does_not_exist_secrets.toml"
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    stub = _CountingStubClient()
    result = check_key(config_path=tmp_path / "does_not_exist_pipeline.yaml", client=stub)

    assert stub.call_count == 0, "a bad/missing key must fail before spending a call"
    assert result.valid is False
    assert isinstance(result.error, str) and result.error
