"""Inner unit tests for issue #153 (`axial chunk examine`), slice 03 of the
chunk-redesign subproject. Complements tests/test_chunk_examine.py (the
LOCKED outer acceptance test) with unit-level coverage of the two pieces it
exercises only end-to-end: the garbage-skip sidecar `run_chunk_embedding`
now persists (founder-approved Option A), and the pure `examine_chunks` /
`format_examine_report` functions `axial chunk examine` is built on.
"""

from __future__ import annotations

import json

import pytest

from axial.chunk import (
    ChunkArtifactCorruptError,
    HashingEmbedder,
    ExamineStats,
    chunks_skips_sidecar_path,
    examine_chunks,
    format_examine_report,
    run_chunk_embedding,
)

from .test_chunk_embedding import _patch_tree, _tree_with_sections

# --- run_chunk_embedding: the skips sidecar ---------------------------------


def test_run_chunk_embedding_writes_skips_sidecar_for_garbage_section(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    garbage = "; ".join(f"{n}, {n + 1}-{n + 2}" for n in range(1, 400))
    tree = _tree_with_sections(
        {
            "Overview": ["Ordinary prose about the survey and its findings."],
            "Numeric Annex": [garbage],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    from axial.envelope import compute_source_id

    source_id = compute_source_id(source)
    sidecar_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    assert sidecar_path.is_file()

    lines = sidecar_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["section"] == "Numeric Annex"
    assert record["section_order"] == "2"
    assert "non-alpha" in record["reason"]


def test_run_chunk_embedding_no_skips_writes_no_sidecar(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    tree = _tree_with_sections({"Overview": ["Ordinary prose about the survey and its findings."]})
    _patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    from axial.envelope import compute_source_id

    source_id = compute_source_id(source)
    sidecar_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    assert not sidecar_path.exists()


def test_run_chunk_embedding_rerun_removes_stale_sidecar(monkeypatch, tmp_path):
    """A source that had a garbage skip on one run must not carry a stale
    sidecar forward if a later rerun (e.g. after the guard changes, or the
    section itself changes) has zero skips -- the sidecar mirrors the main
    JSONL's own overwrite-cleanly/idempotent contract."""
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    garbage = "; ".join(f"{n}, {n + 1}-{n + 2}" for n in range(1, 400))
    tree_with_garbage = _tree_with_sections(
        {
            "Overview": ["Ordinary prose about the survey and its findings."],
            "Numeric Annex": [garbage],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree_with_garbage)
    chunks_dir = tmp_path / "chunks"

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    from axial.envelope import compute_source_id

    source_id = compute_source_id(source)
    sidecar_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    assert sidecar_path.is_file()

    clean_tree = _tree_with_sections(
        {"Overview": ["Ordinary prose about the survey and its findings."]}
    )
    _patch_tree(monkeypatch, tmp_path, clean_tree)

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    assert not sidecar_path.exists()


def test_run_chunk_embedding_rerun_with_skips_overwrites_sidecar_cleanly(monkeypatch, tmp_path):
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    garbage = "; ".join(f"{n}, {n + 1}-{n + 2}" for n in range(1, 400))
    tree = _tree_with_sections(
        {
            "Overview": ["Ordinary prose about the survey and its findings."],
            "Numeric Annex": [garbage],
        }
    )
    _patch_tree(monkeypatch, tmp_path, tree)
    chunks_dir = tmp_path / "chunks"

    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)
    run_chunk_embedding(source, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    from axial.envelope import compute_source_id

    source_id = compute_source_id(source)
    sidecar_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    lines = sidecar_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1  # not doubled by the rerun


# --- examine_chunks: pure aggregation ---------------------------------------


def _write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def _record(chunk_id, section, section_order, text):
    return {"chunk_id": chunk_id, "section": section, "section_order": section_order, "text": text}


def test_examine_chunks_missing_dir_returns_zero_stats(tmp_path):
    stats = examine_chunks(tmp_path / "does_not_exist")
    assert stats.total == 0
    assert stats.per_source == {}
    assert stats.above_max == 0
    assert stats.below_min == 0
    assert stats.split_sections == 0
    assert stats.skips == []
    assert stats.samples == []


def test_examine_chunks_counts_total_and_per_source(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(
        chunks_dir / "src-a.jsonl",
        [_record("a1", "Intro", "1", "x" * 1200), _record("a2", "Body", "2", "y" * 1500)],
    )
    _write_jsonl(chunks_dir / "src-b.jsonl", [_record("b1", "Overview", "1", "z" * 1300)])

    stats = examine_chunks(chunks_dir)

    assert stats.total == 3
    assert stats.per_source == {"src-a": 2, "src-b": 1}


def test_examine_chunks_excludes_skips_sidecar_from_counts(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(chunks_dir / "src-a.jsonl", [_record("a1", "Intro", "1", "x" * 1200)])
    with (chunks_dir / "src-a.skips.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"section": "Junk", "section_order": "2", "reason": "bad"}) + "\n")

    stats = examine_chunks(chunks_dir)

    assert stats.total == 1
    assert stats.per_source == {"src-a": 1}


def test_examine_chunks_malformed_main_jsonl_line_raises_named_error(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    path = chunks_dir / "src-a.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(_record("a1", "Intro", "1", "x" * 1200)) + "\n")
        handle.write("{not valid json\n")

    with pytest.raises(ChunkArtifactCorruptError) as excinfo:
        examine_chunks(chunks_dir)

    assert excinfo.value.path == path
    assert excinfo.value.line_no == 2
    assert str(path) in str(excinfo.value)
    assert "line 2" in str(excinfo.value)


def test_examine_chunks_malformed_skips_sidecar_line_raises_named_error(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(chunks_dir / "src-a.jsonl", [_record("a1", "Intro", "1", "x" * 1200)])
    sidecar_path = chunks_dir / "src-a.skips.jsonl"
    with sidecar_path.open("w", encoding="utf-8") as handle:
        handle.write("not json at all\n")

    with pytest.raises(ChunkArtifactCorruptError) as excinfo:
        examine_chunks(chunks_dir)

    assert excinfo.value.path == sidecar_path
    assert excinfo.value.line_no == 1
    assert str(sidecar_path) in str(excinfo.value)


def test_chunk_examine_cli_reports_clean_error_on_corrupt_artifact(capsys):
    """Mirrors `_chunk`/`_envelope`'s own convention: a domain `ChunkError`
    is caught at the CLI boundary and rendered as a clean `error: ...`
    line, never a raw traceback. Writes into `axial.chunk.CHUNKS_DIR`
    itself (already redirected to a fresh per-test temp dir by this
    package's autouse `_isolate_checkpoint_dirs` fixture, see conftest.py)
    -- the same seam `_default_chunks_dir`/`_chunk_examine` resolve
    through, so no cwd juggling is needed here."""
    import axial.chunk as chunk_mod

    chunks_dir = chunk_mod.CHUNKS_DIR
    chunks_dir.mkdir(parents=True, exist_ok=True)
    with (chunks_dir / "src-a.jsonl").open("w", encoding="utf-8") as handle:
        handle.write("{broken\n")

    from axial.cli import main

    exit_code = main(["chunk", "examine"])

    assert exit_code != 0
    err = capsys.readouterr().err
    assert err.startswith("error: ")
    assert "src-a.jsonl" in err
    assert "line 1" in err


def test_examine_chunks_size_distribution(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    sizes = [1000, 2000, 3000, 4000]
    _write_jsonl(
        chunks_dir / "src-a.jsonl",
        [_record(f"a{i}", "Sec", str(i), "x" * size) for i, size in enumerate(sizes)],
    )

    stats = examine_chunks(chunks_dir, chunk_min=1000, chunk_max=3000)

    assert stats.min_size == 1000
    assert stats.max_size == 4000
    assert stats.mean_size == 2500.0
    assert stats.median_size == 2500.0


def test_examine_chunks_boundary_sanity_above_and_below(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(
        chunks_dir / "src-a.jsonl",
        [
            _record("a1", "Sec", "1", "x" * 500),  # below CHUNK_MIN
            _record("a2", "Sec", "1", "y" * 1500),  # in band
            _record("a3", "Sec2", "2", "z" * 5000),  # above CHUNK_MAX
        ],
    )

    stats = examine_chunks(chunks_dir, chunk_min=1000, chunk_max=3000)

    assert stats.below_min == 1
    assert stats.above_max == 1


def test_examine_chunks_split_sections_grouped_by_section_order(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(
        chunks_dir / "src-a.jsonl",
        [
            _record("a1", "Findings", "2", "x" * 1200),
            _record("a2", "Findings", "2", "y" * 1200),
            _record("a3", "Intro", "1", "z" * 1200),
        ],
    )

    stats = examine_chunks(chunks_dir)

    assert stats.split_sections == 1


def test_examine_chunks_split_sections_distinct_across_sources(tmp_path):
    """Two different sources each with ONE record sharing section_order '1'
    must NOT count as a split -- grouping is per (source_id, section_order),
    never section_order alone."""
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(chunks_dir / "src-a.jsonl", [_record("a1", "Intro", "1", "x" * 1200)])
    _write_jsonl(chunks_dir / "src-b.jsonl", [_record("b1", "Intro", "1", "y" * 1200)])

    stats = examine_chunks(chunks_dir)

    assert stats.split_sections == 0


def test_examine_chunks_reads_skip_reasons_from_sidecar(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(chunks_dir / "src-a.jsonl", [_record("a1", "Intro", "1", "x" * 1200)])
    with (chunks_dir / "src-a.skips.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "section": "Appendix Tables",
                    "section_order": "3",
                    "reason": "high non-alpha ratio (73.4%)",
                }
            )
            + "\n"
        )

    stats = examine_chunks(chunks_dir)

    assert len(stats.skips) == 1
    skip = stats.skips[0]
    assert skip.source_id == "src-a"
    assert skip.section == "Appendix Tables"
    assert skip.section_order == "3"
    assert skip.reason == "high non-alpha ratio (73.4%)"


def test_examine_chunks_samples_include_text_and_identifiers(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(
        chunks_dir / "src-a.jsonl", [_record("a1", "Intro", "1", "MARKER hello world " * 60)]
    )

    stats = examine_chunks(chunks_dir, sample_size=5)

    assert len(stats.samples) == 1
    sample = stats.samples[0]
    assert sample.chunk_id == "a1"
    assert sample.section == "Intro"
    assert "MARKER" in sample.text


def test_examine_chunks_sample_size_caps_number_of_samples(tmp_path):
    chunks_dir = tmp_path / "data" / "chunks"
    _write_jsonl(
        chunks_dir / "src-a.jsonl",
        [_record(f"a{i}", "Sec", str(i), "x" * 1200) for i in range(10)],
    )

    stats = examine_chunks(chunks_dir, sample_size=3)

    assert len(stats.samples) == 3


# --- format_examine_report: pure formatting ---------------------------------


def test_format_examine_report_zero_stats_does_not_crash():
    stats = ExamineStats(total=0)
    report = format_examine_report(stats)
    assert "0" in report


def test_format_examine_report_includes_counts_and_distribution():
    stats = ExamineStats(
        total=3,
        per_source={"src-a": 2, "src-b": 1},
        min_size=900,
        max_size=2000,
        mean_size=1400.0,
        median_size=1300.0,
        above_max=0,
        below_min=1,
        split_sections=1,
    )
    report = format_examine_report(stats, chunk_min=1000, chunk_max=3000)

    assert "3" in report
    assert "src-a" in report
    assert "src-b" in report
    assert "900" in report
    assert "2000" in report
    assert "1400" in report
    assert "1300" in report


def test_format_examine_report_includes_skip_heading_and_reason():
    from axial.chunk import ExamineSkip

    stats = ExamineStats(
        total=1,
        skips=[
            ExamineSkip(
                source_id="src-a",
                section="Appendix Tables",
                section_order="3",
                reason="high non-alpha ratio (73.4%)",
            )
        ],
    )
    report = format_examine_report(stats)

    assert "Appendix Tables" in report
    assert "high non-alpha ratio (73.4%)" in report


def test_format_examine_report_includes_sample_text():
    from axial.chunk import ExamineSample

    stats = ExamineStats(
        total=1,
        samples=[
            ExamineSample(
                source_id="src-a", chunk_id="a1", section="Intro", text="MARKER-XYZ hello"
            )
        ],
    )
    report = format_examine_report(stats)

    assert "MARKER-XYZ" in report
