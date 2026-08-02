"""Inner unit tests for `axial.sources` (issue #528): the local folder
backend's scan/sync and the shared report renderer/backend resolver both
backends share with the Drive side (`axial.drive.run_drive_sources`,
covered in `test_drive.py`).

Every test builds its own `sources_dir`/`ledger_path` under `tmp_path` --
`data/` does not exist in a worktree, and even in the main checkout this
module must never read or write the real corpus/ledger by accident.
"""

from __future__ import annotations

from pathlib import Path

from axial.envelope import compute_source_id
from axial.run import FAIL_STATUS, OK_STATUS, RunSummary, _append_ledger_row
from axial.sources import (
    CHANGED,
    DEFAULT_INGEST_PASSES,
    DONE,
    NEW,
    REJECTED,
    SourceRecord,
    render_report,
    resolve_backend,
    scan_local,
    sync_local,
)


def _write_source(sources_dir: Path, name: str, content: bytes = b"hello world") -> Path:
    sources_dir.mkdir(parents=True, exist_ok=True)
    path = sources_dir / name
    path.write_bytes(content)
    return path


def _ledger_row(pass_name: str, source_path: Path, source_id: str, status: str, reason: str = ""):
    return {
        "pass": pass_name,
        "source_path": str(source_path),
        "source_id": source_id,
        "status": status,
        "reason": reason,
        "timestamp": "2026-08-02T00:00:00+00:00",
    }


# --- scan_local --------------------------------------------------------------


def test_scan_local_returns_empty_list_for_absent_sources_dir(tmp_path):
    assert scan_local(tmp_path / "nowhere", tmp_path / "ledger.tsv") == []


def test_scan_local_flags_unsupported_extension_as_rejected(tmp_path):
    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "notes.txt")

    records = scan_local(sources_dir, tmp_path / "ledger.tsv")

    assert len(records) == 1
    assert records[0].status == REJECTED
    assert "unsupported file type" in records[0].reason
    assert ".txt" in records[0].reason


def test_scan_local_never_seen_before_is_new(tmp_path):
    sources_dir = tmp_path / "sources"
    _write_source(sources_dir, "alpha.pdf")

    records = scan_local(sources_dir, tmp_path / "ledger.tsv")

    assert records == [SourceRecord("alpha.pdf", NEW)]


def test_scan_local_ok_ledger_row_for_current_bytes_is_done(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row("interrogate", path, source_id, OK_STATUS))

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", DONE)]


def test_scan_local_edited_file_with_stale_ledger_row_is_changed(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf", content=b"original bytes")
    stale_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row("interrogate", path, stale_id, OK_STATUS))

    # Re-save with different content -- source_id changes, the ledger row
    # for this path now names a different source_id.
    path.write_bytes(b"a completely different revision")

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", CHANGED)]


def test_scan_local_prior_fail_under_current_bytes_stays_new_not_rejected(tmp_path):
    """A pipeline failure (not a gate rejection) leaves the source retryable
    -- mirrors Drive's own chain-error handling, which writes no manifest
    entry either (module docstring)."""
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(
        ledger_path, _ledger_row("interrogate", path, source_id, FAIL_STATUS, "boom")
    )

    records = scan_local(sources_dir, ledger_path)

    assert records == [SourceRecord("alpha.pdf", NEW)]


def test_scan_local_re_running_immediately_reports_all_done(tmp_path):
    sources_dir = tmp_path / "sources"
    path = _write_source(sources_dir, "alpha.pdf")
    source_id = compute_source_id(path)
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(ledger_path, _ledger_row("interrogate", path, source_id, OK_STATUS))

    first = scan_local(sources_dir, ledger_path)
    second = scan_local(sources_dir, ledger_path)

    assert first == second == [SourceRecord("alpha.pdf", DONE)]


def test_scan_local_reports_new_changed_done_and_rejected_together(tmp_path):
    sources_dir = tmp_path / "sources"
    done_path = _write_source(sources_dir, "done.pdf", content=b"done bytes")
    new_path = _write_source(sources_dir, "new.pdf")
    _write_source(sources_dir, "stray.txt")
    ledger_path = tmp_path / "ledger.tsv"
    _append_ledger_row(
        ledger_path,
        _ledger_row("interrogate", done_path, compute_source_id(done_path), OK_STATUS),
    )

    records = {record.name: record for record in scan_local(sources_dir, ledger_path)}

    assert records["done.pdf"].status == DONE
    assert records["new.pdf"].status == NEW
    assert records["stray.txt"].status == REJECTED
    assert new_path.exists()  # sanity: file really is there, not consumed


# --- render_report -------------------------------------------------------------


def test_render_report_header_plus_one_row_per_record():
    records = [SourceRecord("alpha.pdf", NEW), SourceRecord("bad.txt", REJECTED, "wrong type")]

    text = render_report(records)

    lines = text.splitlines()
    assert lines[0] == "name\tstatus\treason"
    assert lines[1] == "alpha.pdf\tnew\t"
    assert lines[2] == "bad.txt\trejected\twrong type"


# --- resolve_backend -----------------------------------------------------------


def test_resolve_backend_defaults_to_local_for_absent_config(tmp_path):
    assert resolve_backend(tmp_path / "absent.yaml") == "local"


def test_resolve_backend_reads_configured_backend(tmp_path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("sources:\n  backend: drive\n", encoding="utf-8")

    assert resolve_backend(config_path) == "drive"


def test_resolve_backend_defaults_to_local_when_sources_block_absent(tmp_path):
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text("llm:\n  provider: openrouter\n", encoding="utf-8")

    assert resolve_backend(config_path) == "local"


# --- sync_local ----------------------------------------------------------------


def test_sync_local_calls_run_pass_once_per_ingest_pass_in_order(tmp_path, monkeypatch):
    calls = []

    def fake_run_pass(pass_name, **kwargs):
        calls.append((pass_name, kwargs))
        return RunSummary(pass_name, [], 0, 0, 0, 0), 0

    monkeypatch.setattr("axial.sources.run_pass", fake_run_pass)

    sources_dir = tmp_path / "sources"
    ledger_path = tmp_path / "ledger.tsv"

    summaries = sync_local(sources_dir, ledger_path)

    assert [name for name, _ in calls] == list(DEFAULT_INGEST_PASSES)
    for _name, kwargs in calls:
        assert kwargs["corpus"] is True
        assert kwargs["sources_dir"] == sources_dir
        assert kwargs["ledger_path"] == ledger_path
    assert len(summaries) == len(DEFAULT_INGEST_PASSES)


def test_sync_local_threads_one_shared_client_into_every_pass(tmp_path, monkeypatch):
    calls = []
    sentinel_client = object()

    def fake_run_pass(pass_name, **kwargs):
        calls.append(kwargs["client"])
        return RunSummary(pass_name, [], 0, 0, 0, 0), 0

    monkeypatch.setattr("axial.sources.run_pass", fake_run_pass)

    sync_local(tmp_path / "sources", tmp_path / "ledger.tsv", client=sentinel_client)

    assert calls == [sentinel_client] * len(DEFAULT_INGEST_PASSES)


# --- CLI wiring (axial sources) -------------------------------------------


def test_build_parser_recognises_sources_subcommand_with_optional_backend():
    from axial.cli import build_parser

    parser = build_parser()

    args = parser.parse_args(["sources"])
    assert args.command == "sources"
    assert args.backend is None

    args_override = parser.parse_args(["sources", "--backend", "drive"])
    assert args_override.backend == "drive"


def test_main_sources_local_backend_reports_then_ingests_when_something_is_pending(monkeypatch):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(cli_mod, "scan_local", lambda: [SourceRecord("alpha.pdf", NEW)])
    sync_calls = []
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: sync_calls.append(kwargs) or [])
    monkeypatch.setattr(cli_mod, "get_client", lambda: "client-sentinel")

    exit_code = cli_mod.main(["sources"])

    assert exit_code == 0
    assert len(sync_calls) == 1
    assert sync_calls[0]["client"] == "client-sentinel"


def test_main_sources_local_backend_does_nothing_and_says_so_when_all_done(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    monkeypatch.setattr(cli_mod, "scan_local", lambda: [SourceRecord("alpha.pdf", DONE)])
    sync_calls = []
    monkeypatch.setattr(cli_mod, "sync_local", lambda **kwargs: sync_calls.append(kwargs) or [])

    exit_code = cli_mod.main(["sources"])

    assert exit_code == 0
    assert sync_calls == [], "nothing new/changed must run zero pipeline work"
    captured = capsys.readouterr()
    assert "nothing new" in captured.out.lower()


def test_main_sources_backend_flag_overrides_config(monkeypatch):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "local")
    drive_calls = []

    def fake_run_drive_sources(folder_id):
        drive_calls.append(folder_id)
        return [], 0

    monkeypatch.setattr(cli_mod, "run_drive_sources", fake_run_drive_sources)
    monkeypatch.setattr(
        cli_mod, "_load_drive_secrets", lambda path: {"books_folder_id": "BOOKS-ID"}
    )

    exit_code = cli_mod.main(["sources", "--backend", "drive"])

    assert exit_code == 0
    assert drive_calls == ["BOOKS-ID"]


def test_main_sources_drive_backend_halts_on_missing_secrets(monkeypatch, capsys):
    import axial.cli as cli_mod

    def _raise(_path):
        from axial.drive import DriveSecretsError

        raise DriveSecretsError("no [drive] secrets")

    monkeypatch.setattr(cli_mod, "resolve_backend", lambda: "drive")
    monkeypatch.setattr(cli_mod, "_load_drive_secrets", _raise)
    drive_calls = []

    def fake_run_drive_sources(folder_id):
        drive_calls.append(folder_id)
        return [], 0

    monkeypatch.setattr(cli_mod, "run_drive_sources", fake_run_drive_sources)

    exit_code = cli_mod.main(["sources"])

    assert exit_code != 0
    assert drive_calls == []
    captured = capsys.readouterr()
    assert "drive" in (captured.out + captured.err).lower()
