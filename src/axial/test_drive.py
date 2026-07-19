"""Inner unit tests for the axial drive connector (issue #237, slice 01).

Seeds the behaviours the outer acceptance test (`tests/test_drive_ingest.py`)
composes: the `[drive]` secrets loader, pagination, the `.pdf`/`.docx`
candidate filter, the download-to-cache path (extension preserved), lazy
`DriveClient` construction (google libs mocked), and `ingest_fn` dispatch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from axial.drive import (
    DriveClient,
    DriveSecretsError,
    _build_drive_client,
    _cache_path,
    _is_candidate,
    _list_all_candidates,
    _load_drive_secrets,
    run_drive_ingest,
)

# --- _load_drive_secrets -----------------------------------------------------


def _key_file(tmp_path: Path) -> Path:
    key_path = tmp_path / "key.json"
    key_path.write_text('{"type": "service_account"}', encoding="utf-8")
    return key_path


def _toml_path(path: Path) -> str:
    """Render `path` for embedding in a double-quoted TOML string. TOML
    basic strings treat backslash as an escape character, so a raw
    Windows path (`C:\\Users\\...`) is not valid TOML content -- forward
    slashes are valid in both TOML and Windows paths."""
    return path.as_posix()


def test_load_drive_secrets_happy_path_returns_key_path_and_folder_id(tmp_path):
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )

    secrets = _load_drive_secrets(secrets_path)

    assert secrets == {"service_account_json": str(key_path), "books_folder_id": "BOOKS"}


def test_load_drive_secrets_raises_for_missing_secrets_file(tmp_path):
    with pytest.raises(DriveSecretsError, match="drive"):
        _load_drive_secrets(tmp_path / "absent.toml")


def test_load_drive_secrets_raises_for_absent_drive_section(tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('[openrouter]\napi_key = "x"\n', encoding="utf-8")

    with pytest.raises(DriveSecretsError, match="drive"):
        _load_drive_secrets(secrets_path)


def test_load_drive_secrets_raises_for_missing_service_account_json(tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('[drive]\nbooks_folder_id = "BOOKS"\n', encoding="utf-8")

    with pytest.raises(DriveSecretsError, match="service_account_json"):
        _load_drive_secrets(secrets_path)


def test_load_drive_secrets_raises_for_unreadable_service_account_json_path(tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    missing_key = tmp_path / "does-not-exist.json"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(missing_key)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )

    with pytest.raises(DriveSecretsError, match="service_account_json"):
        _load_drive_secrets(secrets_path)


def test_load_drive_secrets_raises_for_missing_books_folder_id(tmp_path):
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\n', encoding="utf-8"
    )

    with pytest.raises(DriveSecretsError, match="books_folder_id"):
        _load_drive_secrets(secrets_path)


# --- _is_candidate -------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "mime_type", "expected"),
    [
        ("alpha.pdf", "application/pdf", True),
        ("ALPHA.PDF", "application/pdf", True),
        (
            "beta.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            True,
        ),
        ("notes.txt", "text/plain", False),
        ("no-extension", "application/octet-stream", False),
        # mime type alone (no matching suffix) still counts as a candidate.
        ("mystery", "application/pdf", True),
    ],
)
def test_is_candidate_filters_by_name_suffix_or_mime_type(name, mime_type, expected):
    record = {"id": "f-1", "name": name, "mimeType": mime_type}

    assert _is_candidate(record) is expected


# --- pagination ------------------------------------------------------------


class _FakeClient:
    def __init__(self, pages):
        self._pages = pages
        self.list_calls: list[tuple[str, str | None]] = []

    def list_files(self, folder_id, page_token=None):
        self.list_calls.append((folder_id, page_token))
        return self._pages[page_token]

    def download(self, file_id):  # pragma: no cover - not exercised here
        raise NotImplementedError


def test_list_all_candidates_paginates_to_exhaustion_and_filters():
    client = _FakeClient(
        {
            None: (
                [
                    {"id": "f-1", "name": "alpha.pdf", "mimeType": "application/pdf"},
                    {"id": "f-2", "name": "notes.txt", "mimeType": "text/plain"},
                ],
                "tok-2",
            ),
            "tok-2": (
                [
                    {
                        "id": "f-3",
                        "name": "beta.docx",
                        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    }
                ],
                None,
            ),
        }
    )

    candidates = _list_all_candidates(client, "BOOKS")

    assert [record["id"] for record in candidates] == ["f-1", "f-3"]
    assert client.list_calls == [("BOOKS", None), ("BOOKS", "tok-2")]


# --- _cache_path -------------------------------------------------------------


def test_cache_path_preserves_extension_and_is_keyed_by_file_id(tmp_path):
    record = {"id": "f-alpha", "name": "alpha.pdf"}

    path = _cache_path(tmp_path, record)

    assert path == tmp_path / "f-alpha.pdf"


def test_cache_path_is_deterministic_across_calls(tmp_path):
    record = {"id": "f-beta", "name": "beta.docx"}

    assert _cache_path(tmp_path, record) == _cache_path(tmp_path, record)


# --- download-to-cache + ingest_fn dispatch (via run_drive_ingest) -----------


def test_run_drive_ingest_writes_downloaded_bytes_and_calls_ingest_fn_once_per_candidate(
    tmp_path,
):
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"

    client = _FakeClient(
        {
            None: (
                [
                    {"id": "f-1", "name": "alpha.pdf", "mimeType": "application/pdf"},
                    {"id": "f-2", "name": "notes.txt", "mimeType": "text/plain"},
                ],
                None,
            )
        }
    )
    client.download = lambda file_id: b"bytes-for-" + file_id.encode("utf-8")

    calls = []
    exit_code = run_drive_ingest(
        "BOOKS",
        client=client,
        ingest_fn=calls.append,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
    )

    assert exit_code == 0
    assert len(calls) == 1
    local_path = calls[0]
    assert local_path == cache_dir / "f-1.pdf"
    assert local_path.read_bytes() == b"bytes-for-f-1"


# --- secrets halt before any client call (run_drive_ingest) ------------------


def test_run_drive_ingest_halts_on_missing_secrets_before_any_client_call(tmp_path, capsys):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text("", encoding="utf-8")
    client = _FakeClient({})
    calls = []

    exit_code = run_drive_ingest(
        "BOOKS",
        client=client,
        ingest_fn=calls.append,
        secrets_path=secrets_path,
        cache_dir=tmp_path / "cache",
    )

    assert exit_code != 0
    assert client.list_calls == []
    assert calls == []
    captured = capsys.readouterr()
    assert "drive" in (captured.out + captured.err).lower()


# --- DriveClient (real impl), google libs mocked ------------------------------


def test_drive_client_constructs_from_service_account_key_with_mocked_google_libs(
    tmp_path, monkeypatch
):
    key_path = _key_file(tmp_path)

    fake_credentials = MagicMock()
    fake_service_account_module = MagicMock()
    fake_service_account_module.Credentials.from_service_account_file.return_value = (
        fake_credentials
    )
    fake_google_oauth2_module = MagicMock(service_account=fake_service_account_module)
    fake_google_module = MagicMock(oauth2=fake_google_oauth2_module)

    fake_service = MagicMock()
    fake_discovery_module = MagicMock()
    fake_discovery_module.build.return_value = fake_service
    fake_googleapiclient_module = MagicMock(discovery=fake_discovery_module)

    monkeypatch.setitem(sys.modules, "google", fake_google_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_google_oauth2_module)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_service_account_module)
    monkeypatch.setitem(sys.modules, "googleapiclient", fake_googleapiclient_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", fake_discovery_module)

    client = DriveClient(str(key_path))

    fake_service_account_module.Credentials.from_service_account_file.assert_called_once()
    called_path = fake_service_account_module.Credentials.from_service_account_file.call_args[0][0]
    assert called_path == str(key_path)
    fake_discovery_module.build.assert_called_once_with(
        "drive", "v3", credentials=fake_credentials, cache_discovery=False
    )
    assert client._service is fake_service


def test_build_drive_client_returns_a_drive_client_instance(tmp_path, monkeypatch):
    key_path = _key_file(tmp_path)

    fake_service_account_module = MagicMock()
    fake_google_oauth2_module = MagicMock(service_account=fake_service_account_module)
    fake_google_module = MagicMock(oauth2=fake_google_oauth2_module)
    fake_discovery_module = MagicMock()
    fake_googleapiclient_module = MagicMock(discovery=fake_discovery_module)

    monkeypatch.setitem(sys.modules, "google", fake_google_module)
    monkeypatch.setitem(sys.modules, "google.oauth2", fake_google_oauth2_module)
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_service_account_module)
    monkeypatch.setitem(sys.modules, "googleapiclient", fake_googleapiclient_module)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", fake_discovery_module)

    client = _build_drive_client(str(key_path))

    assert isinstance(client, DriveClient)


# --- default ingest_fn binds the real ingestion path --------------------------


def test_run_drive_ingest_default_ingest_fn_is_run_vault_write(monkeypatch, tmp_path):
    import axial.drive as drive_mod

    calls = []
    monkeypatch.setattr(drive_mod, "run_vault_write", lambda path: calls.append(path))

    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"

    client = _FakeClient(
        {None: ([{"id": "f-1", "name": "alpha.pdf", "mimeType": "application/pdf"}], None)}
    )
    client.download = lambda file_id: b"pdf-bytes"

    exit_code = run_drive_ingest(
        "BOOKS", client=client, secrets_path=secrets_path, cache_dir=cache_dir
    )

    assert exit_code == 0
    assert calls == [cache_dir / "f-1.pdf"]


# --- CLI wiring (axial drive ingest) ------------------------------------------


def test_build_parser_recognises_drive_ingest_subcommand_with_optional_folder_id():
    from axial.cli import build_parser

    parser = build_parser()

    args = parser.parse_args(["drive", "ingest", "BOOKS"])
    assert args.command == "drive"
    assert args.drive_command == "ingest"
    assert args.folder_id == "BOOKS"

    args_default = parser.parse_args(["drive", "ingest"])
    assert args_default.folder_id is None


def test_main_drive_ingest_dispatches_explicit_folder_id_to_run_drive_ingest(monkeypatch):
    import axial.cli as cli_mod

    calls = []
    monkeypatch.setattr(cli_mod, "run_drive_ingest", lambda folder_id: calls.append(folder_id) or 0)

    exit_code = cli_mod.main(["drive", "ingest", "BOOKS"])

    assert exit_code == 0
    assert calls == ["BOOKS"]


def test_main_drive_ingest_without_folder_id_resolves_books_folder_id_from_secrets(
    monkeypatch, tmp_path
):
    import axial.cli as cli_mod

    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "RESOLVED"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_mod, "DRIVE_SECRETS_PATH", secrets_path)

    calls = []
    monkeypatch.setattr(cli_mod, "run_drive_ingest", lambda folder_id: calls.append(folder_id) or 0)

    exit_code = cli_mod.main(["drive", "ingest"])

    assert exit_code == 0
    assert calls == ["RESOLVED"]


def test_main_drive_ingest_without_folder_id_and_missing_secrets_returns_nonzero_without_calling_run(
    monkeypatch, tmp_path, capsys
):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "DRIVE_SECRETS_PATH", tmp_path / "absent.toml")

    calls = []
    monkeypatch.setattr(cli_mod, "run_drive_ingest", lambda folder_id: calls.append(folder_id) or 0)

    exit_code = cli_mod.main(["drive", "ingest"])

    assert exit_code != 0
    assert calls == []
    captured = capsys.readouterr()
    assert "drive" in (captured.out + captured.err).lower()
