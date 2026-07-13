"""Inner unit tests for the axial ingest module (issue #119)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

import axial.ingest as ingest_mod
from axial.ingest import (
    RESULTS_COLUMNS,
    ResultsFileError,
    WorklistError,
    _append_result_row,
    _load_completed_source_ids,
    read_worklist,
    run_ingest,
)
from axial.vault import VaultError


# --- read_worklist -----------------------------------------------------------


def test_read_worklist_returns_one_entry_per_nonblank_stripped_line(tmp_path):
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("  /a/one.pdf  \n\n/a/two.pdf\n   \n/a/three.pdf\n", encoding="utf-8")

    assert read_worklist(worklist) == ["/a/one.pdf", "/a/two.pdf", "/a/three.pdf"]


def test_read_worklist_raises_worklist_error_for_missing_file(tmp_path):
    missing = tmp_path / "nope.txt"

    with pytest.raises(WorklistError):
        read_worklist(missing)


# --- results file helpers -----------------------------------------------------


def _write_tsv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULTS_COLUMNS, delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_load_completed_source_ids_empty_when_results_file_absent(tmp_path):
    results_path = tmp_path / "results.tsv"

    assert _load_completed_source_ids(results_path) == set()


def test_load_completed_source_ids_only_includes_ok_rows(tmp_path):
    results_path = tmp_path / "results.tsv"
    _write_tsv(
        results_path,
        [
            {
                "source_path": "a.pdf",
                "source_id": "ok-1",
                "vault_status": "OK",
                "notes_count": "1",
                "duration_sec": "0.1",
                "exit_code": "0",
                "timestamp": "t",
            },
            {
                "source_path": "b.pdf",
                "source_id": "fail-1",
                "vault_status": "FAIL",
                "notes_count": "0",
                "duration_sec": "0.1",
                "exit_code": "1",
                "timestamp": "t",
            },
        ],
    )

    assert _load_completed_source_ids(results_path) == {"ok-1"}


def test_append_result_row_writes_header_once_then_appends(tmp_path):
    results_path = tmp_path / "sub" / "results.tsv"
    row1 = {
        "source_path": "a.pdf",
        "source_id": "id-1",
        "vault_status": "OK",
        "notes_count": "1",
        "duration_sec": "0.1",
        "exit_code": "0",
        "timestamp": "t1",
    }
    row2 = {**row1, "source_id": "id-2", "timestamp": "t2"}

    _append_result_row(results_path, row1)
    _append_result_row(results_path, row2)

    with results_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        rows = list(reader)

    assert rows == [row1, row2]


# --- run_ingest: skip guard ----------------------------------------------------


def test_run_ingest_skips_source_with_existing_ok_row_and_logs_one_line(
    tmp_path, monkeypatch, capsys
):
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("/fake/source.pdf\n", encoding="utf-8")

    results_path = tmp_path / "results.tsv"
    _write_tsv(
        results_path,
        [
            {
                "source_path": "/fake/source.pdf",
                "source_id": "source-abc",
                "vault_status": "OK",
                "notes_count": "3",
                "duration_sec": "1.0",
                "exit_code": "0",
                "timestamp": "1999-01-01T00:00:00Z",
            }
        ],
    )

    monkeypatch.setattr(ingest_mod, "compute_source_id", lambda path: "source-abc")

    def _explode(*args, **kwargs):
        raise AssertionError("run_vault_write must not be called for an already-ingested source")

    monkeypatch.setattr(ingest_mod, "run_vault_write", _explode)

    exit_code = run_ingest(worklist, results_path=results_path)

    assert exit_code == 0
    captured = capsys.readouterr()
    skip_lines = [
        line
        for line in (captured.out + captured.err).splitlines()
        if "skip" in line.lower() and "already ingested" in line.lower()
    ]
    assert len(skip_lines) == 1
    assert "source.pdf" in skip_lines[0] or "source-abc" in skip_lines[0]

    # Results file untouched -- still exactly the one pre-seeded row.
    with results_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["notes_count"] == "3"


# --- run_ingest: fresh source processing --------------------------------------


def test_run_ingest_processes_fresh_source_and_appends_ok_row(tmp_path, monkeypatch):
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("/fake/fresh.pdf\n", encoding="utf-8")

    results_path = tmp_path / "results.tsv"

    monkeypatch.setattr(ingest_mod, "compute_source_id", lambda path: "fresh-id")
    monkeypatch.setattr(
        ingest_mod, "run_vault_write", lambda source_path, **kwargs: [Path("a.md"), Path("b.md")]
    )

    exit_code = run_ingest(worklist, results_path=results_path)

    assert exit_code == 0
    with results_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 1
    row = rows[0]
    assert row["source_id"] == "fresh-id"
    assert row["vault_status"] == "OK"
    assert row["notes_count"] == "2"
    assert row["exit_code"] == "0"
    assert float(row["duration_sec"]) >= 0
    assert row["timestamp"]


# --- run_ingest: per-source failure resilience --------------------------------


def test_run_ingest_records_fail_row_and_continues_to_next_source(tmp_path, monkeypatch):
    worklist = tmp_path / "worklist.txt"
    worklist.write_text("/fake/bad.pdf\n/fake/good.pdf\n", encoding="utf-8")

    results_path = tmp_path / "results.tsv"

    ids = {Path("/fake/bad.pdf"): "bad-id", Path("/fake/good.pdf"): "good-id"}
    monkeypatch.setattr(ingest_mod, "compute_source_id", lambda path: ids[Path(path)])

    def _run_vault_write(source_path, **kwargs):
        if Path(source_path) == Path("/fake/bad.pdf"):
            raise VaultError("boom")
        return [Path("a.md")]

    monkeypatch.setattr(ingest_mod, "run_vault_write", _run_vault_write)

    exit_code = run_ingest(worklist, results_path=results_path)

    assert exit_code == 0
    with results_path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert len(rows) == 2
    by_id = {row["source_id"]: row for row in rows}
    assert by_id["bad-id"]["vault_status"] == "FAIL"
    assert by_id["bad-id"]["exit_code"] == "1"
    assert by_id["good-id"]["vault_status"] == "OK"


# --- run_ingest: fatal errors --------------------------------------------------


def test_run_ingest_returns_nonzero_for_unreadable_worklist(tmp_path):
    missing = tmp_path / "nope.txt"

    assert run_ingest(missing, results_path=tmp_path / "results.tsv") == 1
