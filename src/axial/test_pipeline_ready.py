"""Inner unit tests for `axial.pipeline_ready` (issue #121). These are NOT
the locked outer acceptance test (`tests/test_pipeline_ready.py`) -- they
cover the module's own building blocks (manifest loading, table rendering,
verdict math) in isolation, fast and dependency-free."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.cli import main
from axial.envelope import compute_source_id
from axial.pipeline_ready import (
    Canary,
    CanaryResult,
    ManifestError,
    evaluate_canary,
    load_manifest,
    render_table,
    run_pipeline_ready,
)
from axial.tag import _default_tags_dir, tags_checkpoint_path


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


# ---------------------------------------------------------------------------
# Reviewer finding 1: a corrupt/unreadable tag checkpoint must fail that one
# canary's row, never crash the whole gate run with a bare traceback.
# ---------------------------------------------------------------------------


def _write_corrupt_checkpoint(tags_dir: Path, source_id: str) -> None:
    """Write a tag checkpoint whose first (non-final) line is not valid
    JSON -- genuine corruption (mirrors `axial.tag.TagCheckpointCorruptError`'s
    own docstring: a torn FINAL line is tolerated as a hard-kill artifact, but
    a torn line anywhere else raises loudly)."""
    checkpoint_path = tags_checkpoint_path(source_id, tags_dir)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        "this is not json at all {\n"
        + json.dumps({"chunk_id": "chunk-2", "quarantine_reason": None})
        + "\n",
        encoding="utf-8",
    )


def test_evaluate_canary_corrupt_checkpoint_fails_with_reason(tmp_path, monkeypatch):
    monkeypatch.setattr("axial.pipeline_ready.run_vault_write", lambda *args, **kwargs: [])

    source_path = tmp_path / "source.docx"
    source_path.write_bytes(b"synthetic source bytes")
    source_id = compute_source_id(source_path)

    # `_default_tags_dir()` picks up src/axial/conftest.py's autouse
    # `_isolate_checkpoint_dirs` fixture (issue #81), which redirects
    # `axial.tag.TAGS_DIR` to a fresh per-test tmp dir regardless of cwd --
    # so the corrupt checkpoint must be written to the SAME resolved
    # location `evaluate_canary` will read from, not a hand-picked path.
    tags_dir = _default_tags_dir()
    _write_corrupt_checkpoint(tags_dir, source_id)

    canary = Canary(
        source_id=source_id,
        source_path=source_path,
        time_envelope_sec=600,
        quarantine_budget=0.02,
    )

    result = evaluate_canary(canary)

    assert result.verdict == "FAIL"
    assert any("corrupt" in reason.lower() for reason in result.reasons)


def test_run_pipeline_ready_isolates_one_canarys_crash_from_the_rest(tmp_path, monkeypatch):
    """One canary whose evaluation raises an exception `evaluate_canary`'s own
    try/except doesn't cover must still yield a FAIL row for it AND leave
    every other canary in the manifest evaluated and reported -- never a bare
    traceback that drops the whole run's table (reviewer finding 1)."""
    monkeypatch.chdir(tmp_path)

    good_source = tmp_path / "good.docx"
    good_source.write_bytes(b"a perfectly fine synthetic source")
    good_source_id = compute_source_id(good_source)

    bad_source = tmp_path / "bad.docx"
    bad_source.write_bytes(b"a source whose evaluation blows up")
    bad_source_id = compute_source_id(bad_source)

    def _fake_run_vault_write(source_path, **kwargs):
        if Path(source_path) == bad_source:
            raise RuntimeError("boom: unexpected crash evaluating this canary")
        return []

    monkeypatch.setattr("axial.pipeline_ready.run_vault_write", _fake_run_vault_write)

    manifest_path = tmp_path / "manifest.toml"
    _write_manifest(
        manifest_path,
        f"""
        [[canary]]
        source_id = "{good_source_id}"
        source_path = "{good_source.as_posix()}"
        time_envelope_sec = 600
        quarantine_budget = 0.02

        [[canary]]
        source_id = "{bad_source_id}"
        source_path = "{bad_source.as_posix()}"
        time_envelope_sec = 600
        quarantine_budget = 0.02
        """,
    )

    table_text, exit_code = run_pipeline_ready(manifest_path)

    assert exit_code != 0
    lines = table_text.splitlines()
    header = [col.strip() for col in lines[0].split("\t")]
    rows = {
        dict(zip(header, [col.strip() for col in line.split("\t")]))["source_id"]: dict(
            zip(header, [col.strip() for col in line.split("\t")])
        )
        for line in lines[1:]
    }

    assert rows[good_source_id]["verdict"] == "PASS"
    assert rows[bad_source_id]["verdict"] == "FAIL"


# ---------------------------------------------------------------------------
# Reviewer finding 2: wrong-typed manifest fields and a single `[canary]`
# table (instead of `[[canary]]`) must raise `ManifestError`, never a bare
# traceback -- and the CLI must surface it as a clean `error: ...` line.
# ---------------------------------------------------------------------------


def test_load_manifest_wrong_typed_field_raises_manifest_error(tmp_path):
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        """
        [[canary]]
        source_id = "abc123"
        source_path = "/tmp/foo.docx"
        time_envelope_sec = "not-a-number"
        quarantine_budget = 0.02
        """,
    )

    with pytest.raises(ManifestError):
        load_manifest(manifest_path)


def test_load_manifest_single_table_instead_of_array_raises_manifest_error(tmp_path):
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        """
        [canary]
        source_id = "abc123"
        source_path = "/tmp/foo.docx"
        time_envelope_sec = 600
        quarantine_budget = 0.02
        """,
    )

    with pytest.raises(ManifestError):
        load_manifest(manifest_path)


def test_cli_pipeline_ready_malformed_manifest_prints_clean_error_not_traceback(tmp_path, capsys):
    manifest_path = _write_manifest(
        tmp_path / "manifest.toml",
        """
        [canary]
        source_id = "abc123"
        source_path = "/tmp/foo.docx"
        time_envelope_sec = 600
        quarantine_budget = 0.02
        """,
    )

    exit_code = main(["pipeline-ready", "--manifest", str(manifest_path)])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err
