"""Outer acceptance test for issue #527, `axial key set`'s own write
(`axial.llm.write_api_key`).

Given a resolved secrets path (`AXIAL_SECRETS_PATH`, the same env override
      every other reader in `axial.llm` already honors -- issue #527 says
      "do not add a second one")
When  `write_api_key(key)` is called
Then  the file is created (with its parent directory) if absent, carrying
      `[openrouter].api_key = "<key>"`
  And a re-run with a different key overwrites only that one line, leaving
      every other `[openrouter]` key, every other table, and every comment
      in the file untouched
  And a blank/whitespace-only key raises `LLMConfigError` and writes nothing
  And the file is narrowed to owner-only permissions where the platform
      supports it (POSIX; best-effort no-op on Windows)

See GitHub issue #527 for the source of truth.
"""

from __future__ import annotations

import stat
import sys

import pytest

from axial.llm import LLMConfigError, write_api_key

SECRETS_PATH_ENV_VAR = "AXIAL_SECRETS_PATH"


def test_write_api_key_creates_a_fresh_secrets_file(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets" / "secrets.toml"
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    returned_path = write_api_key("sk-or-fixture-key")

    assert returned_path == secrets_path
    assert secrets_path.is_file()
    text = secrets_path.read_text(encoding="utf-8")
    assert "[openrouter]" in text
    assert 'api_key = "sk-or-fixture-key"' in text


def test_write_api_key_replaces_only_the_api_key_line_in_an_existing_file(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        "# a real operator comment nobody wants lost\n"
        "[openrouter]\n"
        'api_key = "sk-or-old-key"\n'
        'llm_tier = "building"\n'
        'building_model = "nvidia/nemotron-3-ultra-550b-a55b:free"\n'
        "\n"
        "[drive]\n"
        'books_folder_id = "some-folder-id"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    write_api_key("sk-or-new-key")

    text = secrets_path.read_text(encoding="utf-8")
    assert 'api_key = "sk-or-new-key"' in text
    assert "sk-or-old-key" not in text
    # Everything else survives byte-for-byte.
    assert "# a real operator comment nobody wants lost" in text
    assert 'llm_tier = "building"' in text
    assert 'building_model = "nvidia/nemotron-3-ultra-550b-a55b:free"' in text
    assert "[drive]" in text
    assert 'books_folder_id = "some-folder-id"' in text


def test_write_api_key_inserts_into_an_openrouter_table_with_no_api_key_yet(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        '[openrouter]\nllm_tier = "building"\n\n[drive]\nbooks_folder_id = "x"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    write_api_key("sk-or-added-key")

    text = secrets_path.read_text(encoding="utf-8")
    assert 'api_key = "sk-or-added-key"' in text
    assert 'llm_tier = "building"' in text
    assert "[drive]" in text
    assert 'books_folder_id = "x"' in text


def test_write_api_key_appends_a_table_when_none_exists_yet(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('[drive]\nbooks_folder_id = "x"\n', encoding="utf-8")
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    write_api_key("sk-or-fresh-key")

    text = secrets_path.read_text(encoding="utf-8")
    assert "[drive]" in text
    assert 'books_folder_id = "x"' in text
    assert "[openrouter]" in text
    assert 'api_key = "sk-or-fresh-key"' in text


def test_write_api_key_refuses_a_blank_key_and_writes_nothing(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    with pytest.raises(LLMConfigError):
        write_api_key("   ")

    assert not secrets_path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_write_api_key_narrows_permissions_to_owner_only(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    monkeypatch.setenv(SECRETS_PATH_ENV_VAR, str(secrets_path))

    write_api_key("sk-or-fixture-key")

    mode = stat.S_IMODE(secrets_path.stat().st_mode)
    assert mode & 0o077 == 0, f"expected no group/other permission bits, got {oct(mode)}"
