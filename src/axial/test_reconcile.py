"""Inner unit tests for issue #291, reconcile slice 01 (`axial reconcile
gc`). Complements tests/test_reconcile.py (the outer CLI/subprocess
acceptance test) with unit-level coverage of `axial.reconcile`'s own
functions: the live keep-set, the flat-dir orphan diff (including the
`.skips` sidecar attribution and non-source-scoped exclusion), the vault-
note attribution wrinkle (frontmatter/fallback/unreadable), the dry-run /
apply / confirm-injection consent gate, and the removal log's shape.

Every test builds its own `data/`-shaped tree under `tmp_path` and passes an
explicit `DerivedDirs`/`sources_dir` -- never relying on
`default_derived_dirs()`'s config-file/cwd-relative resolution (that seam
is exercised instead by the outer CLI test, which runs from a genuinely
isolated cwd)."""

from __future__ import annotations

import json
from pathlib import Path

from axial.reconcile import (
    DerivedDirs,
    attribute_vault_note,
    live_source_ids,
    remove_orphans,
    run_gc,
    scan_orphans,
    write_removal_log,
)

LIVE_ID = "paper-aaaaaaaaaaaa"
STALE_ID = "paper-bbbbbbbbbbbb"


def _make_dirs(tmp_path: Path) -> DerivedDirs:
    return DerivedDirs(
        trees=tmp_path / "data" / "trees",
        envelopes=tmp_path / "data" / "envelopes",
        chunks=tmp_path / "data" / "chunks",
        tags=tmp_path / "data" / "tags",
        artifacts=tmp_path / "data" / "artifacts",
        xref=tmp_path / "data" / "xref",
        vault=tmp_path / "data" / "vault",
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_flat_set(dirs: DerivedDirs, source_id: str) -> list[Path]:
    """Place one file per flat (directly source_id-named) surface for
    `source_id`, plus its chunk `.skips` sidecar, and return every path
    written."""
    paths = [
        dirs.trees / f"{source_id}.json",
        dirs.envelopes / f"{source_id}.json",
        dirs.chunks / f"{source_id}.jsonl",
        dirs.chunks / f"{source_id}.skips.jsonl",
        dirs.tags / f"{source_id}.jsonl",
        dirs.artifacts / f"{source_id}.jsonl",
        dirs.xref / f"{source_id}.jsonl",
    ]
    for path in paths:
        _write(path, json.dumps({"source_id": source_id}) + "\n")
    return paths


def _prose_note(dirs: DerivedDirs, source_id: str, *, with_source_id: bool = True) -> Path:
    chunk_id = f"{source_id}_1_intro_000"
    path = dirs.vault / "prose" / f"{chunk_id}.md"
    source_id_line = f'source_id: "{source_id}"\n' if with_source_id else ""
    _write(path, f'---\nchunk_id: "{chunk_id}"\n{source_id_line}---\nbody text\n')
    return path


# --- live_source_ids ---------------------------------------------------------


def test_live_source_ids_empty_when_sources_dir_absent(tmp_path):
    assert live_source_ids(tmp_path / "data" / "sources") == set()


def test_live_source_ids_empty_when_sources_dir_has_no_files(tmp_path):
    sources_dir = tmp_path / "data" / "sources"
    sources_dir.mkdir(parents=True)
    assert live_source_ids(sources_dir) == set()


def test_live_source_ids_computes_id_for_every_source_file(tmp_path):
    from axial.envelope import compute_source_id

    sources_dir = tmp_path / "data" / "sources"
    sources_dir.mkdir(parents=True)
    paper = sources_dir / "paper.pdf"
    paper.write_bytes(b"real source bytes")

    ids = live_source_ids(sources_dir)

    assert ids == {compute_source_id(paper)}


# --- flat-dir orphan diff, incl. the .skips sidecar and non-source-scoped ---


def test_flat_artifact_in_live_set_is_not_an_orphan(tmp_path):
    from axial.envelope import compute_source_id

    dirs = _make_dirs(tmp_path)
    sources_dir = tmp_path / "data" / "sources"
    sources_dir.mkdir(parents=True)
    paper = sources_dir / "paper.pdf"
    paper.write_bytes(b"live paper bytes")
    live_id = compute_source_id(paper)
    _write_flat_set(dirs, live_id)

    result = scan_orphans(sources_dir=sources_dir, dirs=dirs)

    assert live_id not in result.orphans


def test_flat_artifact_not_in_live_set_is_an_orphan(tmp_path):
    dirs = _make_dirs(tmp_path)
    _write_flat_set(dirs, STALE_ID)

    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    assert STALE_ID in result.orphans
    assert dirs.trees / f"{STALE_ID}.json" in result.orphans[STALE_ID]


def test_skips_sidecar_attributed_to_same_source_id_as_main_artifact(tmp_path):
    dirs = _make_dirs(tmp_path)
    _write_flat_set(dirs, STALE_ID)

    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    sidecar = dirs.chunks / f"{STALE_ID}.skips.jsonl"
    assert sidecar in result.orphans[STALE_ID]
    # Never a distinct id of its own.
    assert f"{STALE_ID}.skips" not in result.orphans


def test_non_source_scoped_file_never_attributed_or_orphaned(tmp_path):
    dirs = _make_dirs(tmp_path)
    candidates_path = dirs.tags / "theory_school_candidates.jsonl"
    _write(candidates_path, "{}\n")

    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    assert result.orphans == {}
    assert candidates_path not in result.unattributed
    assert candidates_path.exists()


# --- vault-note attribution: the load-bearing decision -----------------------


def test_vault_note_attributed_by_frontmatter_source_id(tmp_path):
    dirs = _make_dirs(tmp_path)
    note = _prose_note(dirs, STALE_ID, with_source_id=True)

    attributed = attribute_vault_note(note, known_ids=set())

    assert attributed == STALE_ID


def test_vault_note_falls_back_to_filename_prefix_when_source_id_absent(tmp_path):
    dirs = _make_dirs(tmp_path)
    note = _prose_note(dirs, STALE_ID, with_source_id=False)

    attributed = attribute_vault_note(note, known_ids={STALE_ID, LIVE_ID})

    assert attributed == STALE_ID


def test_unreadable_vault_note_is_unattributed_never_guessed(tmp_path):
    dirs = _make_dirs(tmp_path)
    note = dirs.vault / "prose" / "garbage.md"
    _write(note, "not a frontmatter note at all -- no delimiters here")

    attributed = attribute_vault_note(note, known_ids={STALE_ID, LIVE_ID})

    assert attributed is None


def test_scan_reports_unreadable_note_unattributed_and_leaves_it_in_place(tmp_path):
    dirs = _make_dirs(tmp_path)
    note = dirs.vault / "prose" / "garbage.md"
    _write(note, "not a frontmatter note at all -- no delimiters here")

    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    assert note in result.unattributed
    for paths in result.orphans.values():
        assert note not in paths
    assert note.exists()


def test_vault_note_with_no_matching_known_id_is_unattributed(tmp_path):
    dirs = _make_dirs(tmp_path)
    note = _prose_note(dirs, "unrelated-cccccccccccc", with_source_id=False)

    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    assert note in result.unattributed


# --- dry run vs. apply/yes/confirm consent gate ------------------------------


def test_dry_run_lists_orphans_and_deletes_nothing(tmp_path):
    dirs = _make_dirs(tmp_path)
    stale_paths = _write_flat_set(dirs, STALE_ID)
    log_dir = tmp_path / "data" / "logs" / "reconcile"

    result = run_gc(
        apply=False, sources_dir=tmp_path / "data" / "sources", dirs=dirs, log_dir=log_dir
    )

    assert result.applied is False
    assert result.removed == []
    assert result.log_path is None
    for path in stale_paths:
        assert path.exists()
    assert not log_dir.exists()


def test_apply_without_yes_declining_confirm_removes_nothing(tmp_path):
    dirs = _make_dirs(tmp_path)
    stale_paths = _write_flat_set(dirs, STALE_ID)
    log_dir = tmp_path / "data" / "logs" / "reconcile"

    result = run_gc(
        apply=True,
        yes=False,
        confirm=lambda _prompt: False,
        sources_dir=tmp_path / "data" / "sources",
        dirs=dirs,
        log_dir=log_dir,
    )

    assert result.applied is False
    assert result.aborted is True
    for path in stale_paths:
        assert path.exists()
    assert not log_dir.exists()


def test_apply_without_yes_accepting_confirm_removes_exactly_the_listed_orphans(tmp_path):
    from axial.envelope import compute_source_id

    dirs = _make_dirs(tmp_path)
    sources_dir = tmp_path / "data" / "sources"
    sources_dir.mkdir(parents=True)
    paper = sources_dir / "paper.pdf"
    paper.write_bytes(b"live paper bytes")
    live_id = compute_source_id(paper)

    live_paths = _write_flat_set(dirs, live_id)
    stale_paths = _write_flat_set(dirs, STALE_ID)
    log_dir = tmp_path / "data" / "logs" / "reconcile"

    result = run_gc(
        apply=True,
        yes=False,
        confirm=lambda _prompt: True,
        sources_dir=sources_dir,
        dirs=dirs,
        log_dir=log_dir,
    )

    assert result.applied is True
    assert set(result.removed) == set(stale_paths)
    for path in live_paths:
        assert path.exists()
    assert paper.exists()


def test_apply_and_yes_removes_every_orphan_keeps_live_and_sources(tmp_path):
    dirs = _make_dirs(tmp_path)
    sources_dir = tmp_path / "data" / "sources"
    sources_dir.mkdir(parents=True)
    paper = sources_dir / "paper.pdf"
    paper.write_bytes(b"live paper bytes")

    from axial.envelope import compute_source_id

    live_id = compute_source_id(paper)
    live_paths = _write_flat_set(dirs, live_id)
    stale_paths = _write_flat_set(dirs, STALE_ID)
    log_dir = tmp_path / "data" / "logs" / "reconcile"

    result = run_gc(apply=True, yes=True, sources_dir=sources_dir, dirs=dirs, log_dir=log_dir)

    assert result.applied is True
    for path in stale_paths:
        assert not path.exists()
    for path in live_paths:
        assert path.exists()
    assert paper.read_bytes() == b"live paper bytes"


# --- empty / absent dirs, no-orphan case -------------------------------------


def test_empty_and_absent_derived_dirs_exit_clean_with_no_orphans_and_no_log(tmp_path):
    dirs = _make_dirs(tmp_path)  # nothing created under any of these dirs
    log_dir = tmp_path / "data" / "logs" / "reconcile"

    result = run_gc(
        apply=True, yes=True, sources_dir=tmp_path / "data" / "sources", dirs=dirs, log_dir=log_dir
    )

    assert result.scan.orphans == {}
    assert result.scan.unattributed == []
    assert result.applied is False
    assert result.log_path is None
    assert not log_dir.exists()


def test_no_orphans_at_all_when_every_flat_artifact_is_live(tmp_path):
    dirs = _make_dirs(tmp_path)
    sources_dir = tmp_path / "data" / "sources"
    sources_dir.mkdir(parents=True)
    paper = sources_dir / "paper.pdf"
    paper.write_bytes(b"live paper bytes")

    from axial.envelope import compute_source_id

    live_id = compute_source_id(paper)
    _write_flat_set(dirs, live_id)

    result = scan_orphans(sources_dir=sources_dir, dirs=dirs)

    assert result.orphans == {}


# --- removal log shape: paths + source_ids only, no source text (DEC-23) ----


def test_removal_log_has_run_header_with_keep_set_and_one_record_per_removed_path(tmp_path):
    dirs = _make_dirs(tmp_path)
    stale_paths = _write_flat_set(dirs, STALE_ID)
    log_dir = tmp_path / "data" / "logs" / "reconcile"
    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    _removed, log_path = remove_orphans(result, log_dir=log_dir)

    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line]
    header = lines[0]
    assert header["type"] == "run"
    assert header["keep_set"] == sorted(result.keep_set)

    removed_records = lines[1:]
    assert len(removed_records) == len(stale_paths)
    logged_paths = {record["path"] for record in removed_records}
    assert logged_paths == {str(path) for path in stale_paths}
    for record in removed_records:
        assert record["source_id"] == STALE_ID


def test_removal_log_carries_no_source_text(tmp_path):
    dirs = _make_dirs(tmp_path)
    secret_text = "VERBATIM SOURCE PROSE THAT MUST NEVER LEAK INTO A LOG"
    chunk_path = dirs.chunks / f"{STALE_ID}.jsonl"
    _write(
        chunk_path,
        json.dumps({"chunk_id": f"{STALE_ID}_1_intro_000", "chunk_text": secret_text}) + "\n",
    )
    note = _prose_note(dirs, STALE_ID, with_source_id=True)
    note.write_text(
        note.read_text(encoding="utf-8").replace("body text", secret_text), encoding="utf-8"
    )
    log_dir = tmp_path / "data" / "logs" / "reconcile"

    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)
    _removed, log_path = remove_orphans(result, log_dir=log_dir)

    log_text = log_path.read_text(encoding="utf-8")
    assert secret_text not in log_text


def test_write_removal_log_does_not_delete_anything(tmp_path):
    dirs = _make_dirs(tmp_path)
    stale_paths = _write_flat_set(dirs, STALE_ID)
    log_dir = tmp_path / "data" / "logs" / "reconcile"
    result = scan_orphans(sources_dir=tmp_path / "data" / "sources", dirs=dirs)

    write_removal_log(result, log_dir=log_dir)

    for path in stale_paths:
        assert path.exists()
