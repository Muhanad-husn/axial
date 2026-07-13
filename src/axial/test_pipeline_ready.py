"""Inner unit tests for `axial.pipeline_ready` (issue #121). These are NOT
the locked outer acceptance test (`tests/test_pipeline_ready.py`) -- they
cover the module's own building blocks (manifest loading, table rendering,
verdict math) in isolation, fast and dependency-free."""

from __future__ import annotations

from pathlib import Path

import pytest

from axial.pipeline_ready import (
    Canary,
    CanaryResult,
    ManifestError,
    load_manifest,
    render_table,
)


def _write_manifest(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_manifest_parses_canary_entries(tmp_path):
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        """
        [[canary]]
        source_id = "abc123"
        source_path = "/tmp/foo.docx"
        time_envelope_sec = 600
        quarantine_budget = 0.02
        """,
    )

    canaries = load_manifest(manifest_path)

    assert len(canaries) == 1
    canary = canaries[0]
    assert canary.source_id == "abc123"
    assert canary.source_path == Path("/tmp/foo.docx")
    assert canary.time_envelope_sec == 600
    assert canary.quarantine_budget == 0.02


def test_load_manifest_missing_file_raises_manifest_error(tmp_path):
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "does-not-exist.toml")


def test_load_manifest_missing_field_raises_manifest_error(tmp_path):
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        """
        [[canary]]
        source_id = "abc123"
        source_path = "/tmp/foo.docx"
        time_envelope_sec = 600
        """,
    )

    with pytest.raises(ManifestError):
        load_manifest(manifest_path)


def test_load_manifest_malformed_toml_raises_manifest_error(tmp_path):
    manifest_path = _write_manifest(tmp_path / "manifest.toml", "not [ valid toml")

    with pytest.raises(ManifestError):
        load_manifest(manifest_path)


def _make_result(
    *,
    source_id: str = "src-1",
    verdict: str = "PASS",
    completed: bool = True,
    quarantine_count: int = 0,
    total_chunks: int = 2,
    duration_sec: float = 1.0,
    time_envelope_sec: float = 600,
    quarantine_budget: float = 0.02,
    reasons: list[str] | None = None,
) -> CanaryResult:
    canary = Canary(
        source_id=source_id,
        source_path=Path("/tmp/x.docx"),
        time_envelope_sec=time_envelope_sec,
        quarantine_budget=quarantine_budget,
    )
    return CanaryResult(
        canary=canary,
        source_id=source_id,
        verdict=verdict,
        completed=completed,
        quarantine_count=quarantine_count,
        total_chunks=total_chunks,
        duration_sec=duration_sec,
        reasons=reasons or [],
    )


def test_render_table_header_includes_source_id_and_verdict():
    table = render_table([_make_result()])
    header = table.splitlines()[0]
    columns = [col.strip() for col in header.split("\t")]

    assert "source_id" in columns
    assert "verdict" in columns


def test_render_table_one_row_per_result_looked_up_by_source_id():
    results = [
        _make_result(source_id="src-1", verdict="PASS"),
        _make_result(source_id="src-2", verdict="FAIL", reasons=["boom"]),
    ]
    table = render_table(results)
    lines = table.splitlines()
    header = [col.strip() for col in lines[0].split("\t")]

    rows = {}
    for line in lines[1:]:
        cols = [col.strip() for col in line.split("\t")]
        rows[dict(zip(header, cols))["source_id"]] = dict(zip(header, cols))

    assert rows["src-1"]["verdict"] == "PASS"
    assert rows["src-2"]["verdict"] == "FAIL"


def test_canary_result_quarantine_fraction_computed_from_counts():
    result = _make_result(quarantine_count=1, total_chunks=2)
    assert result.quarantine_fraction == pytest.approx(0.5)


def test_canary_result_quarantine_fraction_zero_chunks_is_zero():
    result = _make_result(quarantine_count=0, total_chunks=0)
    assert result.quarantine_fraction == 0.0
