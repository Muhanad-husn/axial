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


# --- default ingest_fn runs the full source-to-vault chain --------------------
#
# `run_vault_write` alone is only the pipeline TAIL (it reads a pre-existing
# stored envelope and pre-built chunks, never recomputing either -- see
# axial.vault.run_vault_write's docstring); a freshly-downloaded Drive source
# has never been through extract/envelope/chunk, so the default `ingest_fn`
# must drive the whole chain. These tests mock every stage (extract,
# run_envelope, run_chunk_recursive, run_vault_write) where `axial.drive`
# imports them -- never touching real docling/LLM calls.


def _patch_chain(monkeypatch, *, order: list[str] | None = None, fail_at: str | None = None):
    """Patch the four chain stages, where `axial.drive` imports them, to
    record call order (and each call's `source_path` argument) into
    `order` when given, optionally raising that stage's own typed error
    when `fail_at` names it -- so callers can assert both the happy-path
    sequencing and the per-candidate isolation behaviour."""
    import axial.drive as drive_mod
    from axial.chunk import ChunkError
    from axial.envelope import EnvelopeError
    from axial.extract import ExtractError
    from axial.vault import VaultError

    if order is None:
        order = []

    def _make(name, error_cls, return_value):
        def _stage(source_path, *args, **kwargs):
            order.append((name, source_path))
            if fail_at == name:
                raise error_cls(f"synthetic {name} failure")
            return return_value

        return _stage

    monkeypatch.setattr(drive_mod, "extract", _make("extract", ExtractError, {}))
    monkeypatch.setattr(drive_mod, "run_envelope", _make("run_envelope", EnvelopeError, {}))
    monkeypatch.setattr(
        drive_mod, "run_chunk_recursive", _make("run_chunk_recursive", ChunkError, [])
    )
    monkeypatch.setattr(
        drive_mod,
        "run_vault_write",
        _make("run_vault_write", VaultError, [Path("data/vault/prose/x.md")]),
    )
    return order


def test_default_ingest_fn_runs_the_full_chain_in_order_for_one_source(monkeypatch, tmp_path):
    from axial.drive import _default_ingest_fn

    order = _patch_chain(monkeypatch)
    ingest_fn = _default_ingest_fn(
        client=None,
        config_path=Path("config/pipeline.yaml"),
        domain_dir="config/domains/syria",
        envelopes_dir=None,
        chunks_dir=None,
        tags_dir=None,
        artifacts_dir=None,
        xref_dir=None,
        vault_dir=None,
    )
    source_path = tmp_path / "alpha.pdf"

    result = ingest_fn(source_path)

    assert [name for name, _ in order] == [
        "extract",
        "run_envelope",
        "run_chunk_recursive",
        "run_vault_write",
    ]
    assert all(path == source_path for _, path in order)
    assert result == [Path("data/vault/prose/x.md")]


def test_run_drive_ingest_default_path_runs_the_full_chain_per_candidate(monkeypatch, tmp_path):
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"

    order = _patch_chain(monkeypatch)

    client = _FakeClient(
        {None: ([{"id": "f-1", "name": "alpha.pdf", "mimeType": "application/pdf"}], None)}
    )
    client.download = lambda file_id: b"pdf-bytes"

    exit_code = run_drive_ingest(
        "BOOKS", client=client, secrets_path=secrets_path, cache_dir=cache_dir
    )

    assert exit_code == 0
    assert [name for name, _ in order] == [
        "extract",
        "run_envelope",
        "run_chunk_recursive",
        "run_vault_write",
    ]
    assert all(path == cache_dir / "f-1.pdf" for _, path in order)


@pytest.mark.parametrize(
    "fail_at", ["extract", "run_envelope", "run_chunk_recursive", "run_vault_write"]
)
def test_run_drive_ingest_isolates_a_per_candidate_chain_failure_and_continues(
    monkeypatch, tmp_path, capsys, fail_at
):
    """A failure at any stage of one candidate's chain is caught, logged to
    stderr, and the loop continues to the next candidate -- one bad source
    never aborts the whole folder (mirrors axial.ingest.run_ingest's
    per-source FAIL isolation)."""
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"

    order = _patch_chain(monkeypatch, fail_at=fail_at)

    client = _FakeClient(
        {
            None: (
                [
                    {"id": "f-bad", "name": "bad.pdf", "mimeType": "application/pdf"},
                    {"id": "f-good", "name": "good.pdf", "mimeType": "application/pdf"},
                ],
                None,
            )
        }
    )
    client.download = lambda file_id: b"pdf-bytes"

    exit_code = run_drive_ingest(
        "BOOKS", client=client, secrets_path=secrets_path, cache_dir=cache_dir
    )

    assert exit_code == 0, "one bad candidate must not fail the overall run"
    # Both candidates were attempted (cache path is keyed by Drive file id,
    # `_cache_path`) -- the failure did not abort the loop.
    processed_paths = {path.name for _, path in order}
    assert processed_paths == {"f-bad.pdf", "f-good.pdf"}

    captured = capsys.readouterr()
    assert "bad.pdf" in (captured.out + captured.err)


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
