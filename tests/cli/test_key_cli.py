"""Outer acceptance test for issue #527, the `axial key set` / `axial key
check` CLI surface.

Given a fresh install with no secrets file
When  `axial key set` runs
Then  it never reads the key from `sys.argv` (only from a prompt) and never
      echoes or logs the key value anywhere in stdout/stderr
  And the resolved secrets file carries the entered key afterward

Given a configured, working key
When  `axial key check` runs
Then  it exits 0, spends exactly one completion call (proven via a patched
      HTTP transport, never real network), and never prints the key value
  And a bad/missing key exits nonzero with a named error, no traceback

See GitHub issue #527 for the source of truth. In-process (`axial.cli.main`)
rather than subprocess, so `getpass.getpass` and the HTTP transport can be
patched directly -- the fast, hermetic seam this module's own handlers are
built for.
"""

from __future__ import annotations

import httpx
import pytest

from axial.cli import main

SECRETS_PATH_ENV_VAR = "AXIAL_SECRETS_PATH"
FIXTURE_KEY = "sk-or-v1-do-not-echo-me-1234567890"


def test_key_set_reads_from_a_prompt_and_never_echoes_or_logs_the_key(
    monkeypatch, tmp_path, capsys
):
    secrets_path = tmp_path / "secrets.toml"
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))
    monkeypatch.setattr("axial.cli.getpass.getpass", lambda prompt="": FIXTURE_KEY)

    exit_code = main(["key", "set"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert FIXTURE_KEY not in captured.out
    assert FIXTURE_KEY not in captured.err
    assert secrets_path.is_file()
    assert f'api_key = "{FIXTURE_KEY}"' in secrets_path.read_text(encoding="utf-8")


def test_key_set_never_declares_a_command_line_argument_for_the_key():
    """The key must be unreachable via argv -- `axial key set <key>` is not
    a valid invocation shape at all (positional args would land in shell
    history, exactly what issue #527 rules out)."""
    with pytest.raises(SystemExit):
        main(["key", "set", "sk-or-passed-on-argv"])


def test_key_check_exits_zero_and_makes_exactly_one_http_call(monkeypatch, tmp_path, capsys):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        '[openrouter]\napi_key = "sk-or-fixture-key"\n'
        'building_model = "nvidia/nemotron-3-ultra-550b-a55b:free"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    calls: list[dict] = []

    def fake_post(client_self, url, *, headers=None, json=None, **kwargs):
        calls.append({"url": url, "headers": headers or {}, "json": json or {}})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}]},
            request=httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"),
        )

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    exit_code = main(["key", "check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert len(calls) == 1, f"expected exactly one HTTP call, got {len(calls)}"
    assert "sk-or-fixture-key" not in captured.out
    assert "sk-or-fixture-key" not in captured.err
    assert "valid" in captured.out.lower()


def test_key_check_exits_nonzero_with_a_named_error_on_a_missing_key(monkeypatch, tmp_path, capsys):
    secrets_path = tmp_path / "does_not_exist_secrets.toml"
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    exit_code = main(["key", "check"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "error" in captured.err.lower()
