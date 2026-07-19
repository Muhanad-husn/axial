"""Inner unit tests for the axial drive connector (issue #237 slice 01;
issue #238 slice 02: incremental fetch-state).

Seeds the behaviours the outer acceptance tests
(`tests/test_drive_ingest.py`, `tests/test_drive_incremental.py`) compose:
the `[drive]` secrets loader, pagination, the `.pdf`/`.docx` candidate
filter, the download-to-cache path (extension preserved), lazy
`DriveClient` construction (google libs mocked), `ingest_fn` dispatch, and
the fetch-state manifest (round-trip, skip predicate, write-after-success).

Every call to the real `run_drive_ingest` in this file passes an explicit,
per-test `fetch_state_path` (a `tmp_path`-scoped file) -- never the module
default `data/drive/fetch_state.json`. That default is a real, cwd-relative,
persisted path (P0-11b's whole point is that it survives across runs), so
leaving it un-isolated would let one test's manifest entry leak into
another test that happens to reuse the same fixture Drive file id -- the
same class of shared on-disk state problem `tests/conftest.py` already
guards for `data/trees/`, `data/envelopes/`, and `data/chunks/`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from axial.drive import (
    DriveClient,
    DriveSecretsError,
    FetchStateError,
    _build_drive_client,
    _cache_path,
    _fetch_state_entry,
    _is_candidate,
    _is_unchanged,
    _list_all_candidates,
    _load_drive_secrets,
    _load_fetch_state,
    _write_fetch_state,
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
        self.download_calls: list[str] = []

    def list_files(self, folder_id, page_token=None):
        self.list_calls.append((folder_id, page_token))
        return self._pages[page_token]

    def download(self, file_id):  # pragma: no cover - not exercised here
        raise NotImplementedError


def _tracking_download(client: "_FakeClient", blob: bytes = b"pdf-bytes"):
    """A `download` override for `_FakeClient` that both returns `blob` and
    records the call into `client.download_calls`, for tests that need to
    assert exactly which candidates were (or were not) downloaded."""

    def _download(file_id: str) -> bytes:
        client.download_calls.append(file_id)
        return blob

    return _download


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
        fetch_state_path=tmp_path / "fetch_state.json",
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
        fetch_state_path=tmp_path / "fetch_state.json",
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
        "BOOKS",
        client=client,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=tmp_path / "fetch_state.json",
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
        "BOOKS",
        client=client,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=tmp_path / "fetch_state.json",
    )

    assert exit_code == 0, "one bad candidate must not fail the overall run"
    # Both candidates were attempted (cache path is keyed by Drive file id,
    # `_cache_path`) -- the failure did not abort the loop.
    processed_paths = {path.name for _, path in order}
    assert processed_paths == {"f-bad.pdf", "f-good.pdf"}

    captured = capsys.readouterr()
    assert "bad.pdf" in (captured.out + captured.err)


# --- fetch-state manifest (issue #238, P0-11b) --------------------------------


def test_load_fetch_state_absent_file_reads_as_empty(tmp_path):
    assert _load_fetch_state(tmp_path / "absent.json") == {}


def test_load_fetch_state_blank_file_reads_as_empty(tmp_path):
    path = tmp_path / "fetch_state.json"
    path.write_text("   \n", encoding="utf-8")

    assert _load_fetch_state(path) == {}


def test_fetch_state_round_trips_write_then_read(tmp_path):
    path = tmp_path / "nested" / "fetch_state.json"
    manifest = {
        "f-alpha": {
            "modifiedTime": "2026-07-01T00:00:00.000Z",
            "md5Checksum": "checksum-v1",
            "fetched_at": "2026-07-19T00:00:00+00:00",
        }
    }

    _write_fetch_state(path, manifest)

    assert path.is_file(), "expected _write_fetch_state to create parent dirs and the file"
    assert _load_fetch_state(path) == manifest


def test_load_fetch_state_raises_fetch_state_error_for_malformed_json(tmp_path):
    path = tmp_path / "fetch_state.json"
    path.write_text("not valid json {{{", encoding="utf-8")

    with pytest.raises(FetchStateError):
        _load_fetch_state(path)


def test_load_fetch_state_raises_fetch_state_error_when_not_a_json_object(tmp_path):
    path = tmp_path / "fetch_state.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(FetchStateError):
        _load_fetch_state(path)


def test_is_unchanged_true_only_when_both_tokens_match():
    record = {"id": "f-alpha", "modifiedTime": "2026-07-01T00:00:00.000Z", "md5Checksum": "v1"}
    manifest = {
        "f-alpha": {"modifiedTime": "2026-07-01T00:00:00.000Z", "md5Checksum": "v1"},
    }

    assert _is_unchanged(record, manifest) is True


def test_is_unchanged_false_when_id_absent_from_manifest():
    record = {"id": "f-new", "modifiedTime": "2026-07-01T00:00:00.000Z", "md5Checksum": "v1"}

    assert _is_unchanged(record, manifest={}) is False


@pytest.mark.parametrize(
    ("manifest_modified_time", "manifest_md5"),
    [
        ("2026-07-02T00:00:00.000Z", "v1"),  # modifiedTime differs
        ("2026-07-01T00:00:00.000Z", "v2"),  # md5Checksum differs
        ("2026-07-02T00:00:00.000Z", "v2"),  # both differ
    ],
)
def test_is_unchanged_false_when_either_token_differs(manifest_modified_time, manifest_md5):
    record = {"id": "f-alpha", "modifiedTime": "2026-07-01T00:00:00.000Z", "md5Checksum": "v1"}
    manifest = {"f-alpha": {"modifiedTime": manifest_modified_time, "md5Checksum": manifest_md5}}

    assert _is_unchanged(record, manifest) is False


def test_fetch_state_entry_carries_current_tokens_and_a_nonempty_fetched_at():
    record = {
        "id": "f-alpha",
        "modifiedTime": "2026-07-01T00:00:00.000Z",
        "md5Checksum": "v1",
    }

    entry = _fetch_state_entry(record)

    assert entry["modifiedTime"] == "2026-07-01T00:00:00.000Z"
    assert entry["md5Checksum"] == "v1"
    assert entry["fetched_at"]


def test_run_drive_ingest_skips_unchanged_candidate_before_download_and_ingest(tmp_path):
    """Pre-download skip: a candidate already recorded in the manifest with
    matching tokens is never downloaded and never reaches ingest_fn."""
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"
    fetch_state_path = tmp_path / "fetch_state.json"
    _write_fetch_state(
        fetch_state_path,
        {
            "f-alpha": {
                "modifiedTime": "2026-07-01T00:00:00.000Z",
                "md5Checksum": "v1",
                "fetched_at": "2026-07-18T00:00:00+00:00",
            }
        },
    )

    client = _FakeClient(
        {
            None: (
                [
                    {
                        "id": "f-alpha",
                        "name": "alpha.pdf",
                        "mimeType": "application/pdf",
                        "modifiedTime": "2026-07-01T00:00:00.000Z",
                        "md5Checksum": "v1",
                    }
                ],
                None,
            )
        }
    )
    calls = []

    exit_code = run_drive_ingest(
        "BOOKS",
        client=client,
        ingest_fn=calls.append,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code == 0
    assert client.download_calls == []
    assert calls == []


def test_run_drive_ingest_writes_manifest_entry_only_after_ingest_succeeds(tmp_path):
    """Write-after-success: a candidate whose ingest_fn raises gets NO
    manifest entry (re-fetched next run); one that succeeds does."""
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"
    fetch_state_path = tmp_path / "fetch_state.json"

    from axial.extract import ExtractError

    def _raising_ingest(local_path):
        raise ExtractError("simulated pipeline failure")

    client = _FakeClient(
        {
            None: (
                [
                    {
                        "id": "f-bad",
                        "name": "bad.pdf",
                        "mimeType": "application/pdf",
                        "modifiedTime": "2026-07-01T00:00:00.000Z",
                        "md5Checksum": "v1",
                    }
                ],
                None,
            )
        }
    )
    client.download = _tracking_download(client)

    exit_code = run_drive_ingest(
        "BOOKS",
        client=client,
        ingest_fn=_raising_ingest,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code == 0, "a per-candidate ingest failure must not fail the overall run"
    assert _load_fetch_state(fetch_state_path) == {}, (
        "expected NO manifest entry for a candidate whose ingest raised"
    )

    # A second, successful run over the same record must now succeed and
    # write the manifest entry.
    client2 = _FakeClient(
        {
            None: (
                [
                    {
                        "id": "f-bad",
                        "name": "bad.pdf",
                        "mimeType": "application/pdf",
                        "modifiedTime": "2026-07-01T00:00:00.000Z",
                        "md5Checksum": "v1",
                    }
                ],
                None,
            )
        }
    )
    client2.download = _tracking_download(client2)
    calls = []

    exit_code_2 = run_drive_ingest(
        "BOOKS",
        client=client2,
        ingest_fn=calls.append,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code_2 == 0
    assert client2.download_calls == ["f-bad"], (
        "expected the previously-failed candidate to be re-fetched"
    )
    assert len(calls) == 1
    manifest = _load_fetch_state(fetch_state_path)
    assert "f-bad" in manifest, "expected a manifest entry once the retry succeeds"


def test_pre_download_manifest_skip_composes_with_ingest_level_vault_status_skip(tmp_path):
    """Plan scenario 4: the pre-download manifest skip is independent of
    the ingest-level `vault_status=OK` skip (`axial.ingest.run_ingest`) --
    neither masks the other. Modeled as a unit: an `ingest_fn` stand-in
    that itself implements a vault_status=OK-style skip (its own
    already-done set) alongside the manifest's own pre-download skip, and
    both skip mechanisms fire independently across three candidates: one
    skipped by the manifest before it ever reaches ingest_fn, one skipped
    BY ingest_fn's own already-done set, and one that reaches neither skip
    and is actually processed."""
    key_path = _key_file(tmp_path)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        f'[drive]\nservice_account_json = "{_toml_path(key_path)}"\nbooks_folder_id = "BOOKS"\n',
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache"
    fetch_state_path = tmp_path / "fetch_state.json"
    _write_fetch_state(
        fetch_state_path,
        {
            "f-manifest-skip": {
                "modifiedTime": "2026-07-01T00:00:00.000Z",
                "md5Checksum": "v1",
                "fetched_at": "2026-07-18T00:00:00+00:00",
            }
        },
    )

    already_done_source_ids = {"f-vault-skip"}
    processed = []

    def _ingest_with_vault_status_skip(local_path):
        # Stand-in for axial.ingest.run_ingest's own vault_status=OK skip,
        # independent of the manifest's pre-download skip.
        if local_path.stem in already_done_source_ids:
            return
        processed.append(local_path)

    client = _FakeClient(
        {
            None: (
                [
                    {
                        "id": "f-manifest-skip",
                        "name": "manifest-skip.pdf",
                        "mimeType": "application/pdf",
                        "modifiedTime": "2026-07-01T00:00:00.000Z",
                        "md5Checksum": "v1",
                    },
                    {
                        "id": "f-vault-skip",
                        "name": "vault-skip.pdf",
                        "mimeType": "application/pdf",
                        "modifiedTime": "2026-07-05T00:00:00.000Z",
                        "md5Checksum": "v2",
                    },
                    {
                        "id": "f-both-run",
                        "name": "both-run.pdf",
                        "mimeType": "application/pdf",
                        "modifiedTime": "2026-07-05T00:00:00.000Z",
                        "md5Checksum": "v3",
                    },
                ],
                None,
            )
        }
    )
    client.download = _tracking_download(client)

    exit_code = run_drive_ingest(
        "BOOKS",
        client=client,
        ingest_fn=_ingest_with_vault_status_skip,
        secrets_path=secrets_path,
        cache_dir=cache_dir,
        fetch_state_path=fetch_state_path,
    )

    assert exit_code == 0
    # The manifest-level skip fired BEFORE download for f-manifest-skip.
    assert "f-manifest-skip" not in client.download_calls
    # The vault-status skip fired INSIDE ingest_fn for f-vault-skip -- it
    # WAS downloaded (the manifest skip didn't know about it), but never
    # landed in `processed`.
    assert "f-vault-skip" in client.download_calls
    assert all(path.stem != "f-vault-skip" for path in processed)
    # The third candidate hit neither skip and was actually processed.
    assert "f-both-run" in client.download_calls
    assert any(path.stem == "f-both-run" for path in processed)


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
