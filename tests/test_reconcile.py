"""Outer acceptance test for issue #291, reconcile slice 01
(`axial reconcile gc`).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a temp data tree with a source file in data/sources/ whose derived
      artifacts (tree, envelope, chunks, tags, artifacts, vault notes) exist
      under its live source_id
And   a set of derived artifacts under a stale source_id whose source file
      is absent from data/sources/ (a renamed/re-saved source's old id)
When  the operator runs `axial reconcile gc`
Then  it exits 0 and lists exactly the stale source_id's artifacts as
      orphans, grouped by source_id, and removes nothing (dry run is the
      default)
And   the live source_id's artifacts are absent from the orphan list
When  the operator runs `axial reconcile gc --apply --yes`
Then  the stale source_id's artifacts are removed from every derived dir
And   the live source_id's artifacts remain untouched on disk
And   data/sources/ is unchanged
And   a removal log is written under data/logs/reconcile/ recording the
      removed paths and their orphaned source_ids and the live keep-set,
      with no source text

See plans/reconcile/01-orphan-gc.md for the slice plan this test encodes.

Seam decisions
-----------------------------------------------------------------------
`uv run --project <repo> axial reconcile gc ...` with `cwd` set to a fresh,
isolated `tmp_path_factory` root, mirroring tests/chunk/test_chunk_examine.py
exactly: `--project` lets `uv` locate the repo's pyproject/venv while the
spawned process's own cwd stays the isolated root, so every relative
`data/...` path the CLI resolves (no `config/pipeline.yaml` exists under the
isolated root) lands under it, never under the real repo's `data/`.
`AXIAL_LLM_PROVIDER=explode` poisons any real LLM call, proving the whole
surface is model-free by construction (reconcile never constructs a client
at all, but this is the same belt-and-suspenders the sibling chunk-examine
acceptance test uses). Consent is injected via `--yes` only -- no
interactive prompt is ever driven, per the slice plan.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

LIVE_SOURCE_TEXT = b"this is the real, live source file's bytes"
STALE_ID = "old-paper-aaaaaaaaaaaa"

# Distinctive chunk/section text planted in the stale source_id's chunk
# artifact and vault note, asserted absent from the removal log (DEC-23:
# paths and source_ids only, never source text).
STALE_SECRET_TEXT = "VERBATIM-STALE-SOURCE-PROSE-MUST-NEVER-LEAK-INTO-A-LOG"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_flat_set(root: Path, source_id: str, secret: str | None = None) -> list[Path]:
    """Place one file per directly-source_id-named derived surface (tree,
    envelope, chunks + its .skips sidecar, tags, artifacts, xref) for
    `source_id`, returning every path written."""
    data = root / "data"
    chunk_text = secret or f"ordinary prose for {source_id}"
    paths = [
        data / "trees" / f"{source_id}.json",
        data / "envelopes" / f"{source_id}.json",
        data / "tags" / f"{source_id}.jsonl",
        data / "artifacts" / f"{source_id}.jsonl",
        data / "xref" / f"{source_id}.jsonl",
    ]
    for path in paths:
        _write(path, json.dumps({"source_id": source_id}) + "\n")

    chunks_path = data / "chunks" / f"{source_id}.jsonl"
    _write(
        chunks_path,
        json.dumps({"chunk_id": f"{source_id}_1_intro_000", "section": "Intro", "text": chunk_text})
        + "\n",
    )
    skips_path = data / "chunks" / f"{source_id}.skips.jsonl"
    _write(skips_path, json.dumps({"section": "Junk", "reason": "high non-alpha ratio"}) + "\n")

    return [*paths, chunks_path, skips_path]


def _write_vault_notes(root: Path, source_id: str, secret: str | None = None) -> list[Path]:
    body = secret or f"ordinary vault prose for {source_id}"
    chunk_id = f"{source_id}_1_intro_000"
    prose_path = root / "data" / "vault" / "prose" / f"{chunk_id}.md"
    _write(
        prose_path,
        f'---\nchunk_id: "{chunk_id}"\nsource_id: "{source_id}"\nsection: "Intro"\n---\n{body}\n',
    )

    artifact_id = f"{source_id}_art_1"
    artifact_path = root / "data" / "vault" / "artifacts" / f"{artifact_id}.md"
    _write(
        artifact_path,
        f'---\nartifact_id: "{artifact_id}"\nsource_id: "{source_id}"\n---\nartifact body\n',
    )
    return [prose_path, artifact_path]


@pytest.fixture
def reconcile_root(tmp_path_factory):
    """A fresh, isolated staging root: a live source in data/sources/ plus
    its full set of derived artifacts under its real content-hashed
    source_id, and a matching full set of derived artifacts under a stale
    source_id with NO corresponding data/sources/ file (the renamed/re-
    saved-source scenario). Also plants one unreadable vault note (no
    frontmatter delimiters at all) and one non-source-scoped file sharing
    a derived dir -- both must survive every run untouched."""
    root = tmp_path_factory.mktemp("reconcile_gc")

    sources_dir = root / "data" / "sources"
    sources_dir.mkdir(parents=True)
    source_path = sources_dir / "paper.pdf"
    source_path.write_bytes(LIVE_SOURCE_TEXT)

    live_id = compute_source_id(source_path)

    live_paths = _write_flat_set(root, live_id)
    live_paths += _write_vault_notes(root, live_id)

    stale_paths = _write_flat_set(root, STALE_ID, secret=STALE_SECRET_TEXT)
    stale_paths += _write_vault_notes(root, STALE_ID, secret=STALE_SECRET_TEXT)

    # Non-source-scoped file sharing a derived dir: never attributed, never
    # an orphan, never touched.
    candidates_path = root / "data" / "tags" / "theory_school_candidates.jsonl"
    _write(candidates_path, "{}\n")

    # Unreadable vault note: no frontmatter delimiters at all -- reported
    # unattributed and left in place, never removed (the load-bearing
    # decision this slice pins).
    unreadable_note = root / "data" / "vault" / "prose" / "garbage.md"
    _write(unreadable_note, "not a frontmatter note at all -- no delimiters here")

    return {
        "root": root,
        "live_id": live_id,
        "source_path": source_path,
        "live_paths": live_paths,
        "stale_paths": stale_paths,
        "candidates_path": candidates_path,
        "unreadable_note": unreadable_note,
    }


def _run_reconcile_gc(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = "explode"  # poison: any text-gen LLM call crashes the run
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", "reconcile", "gc", *args],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )


def test_dry_run_lists_only_the_stale_orphans_and_removes_nothing(reconcile_root):
    fixture = reconcile_root
    result = _run_reconcile_gc(fixture["root"])

    assert result.returncode == 0, (
        f"expected exit code 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    stdout = result.stdout
    assert f"orphaned source_id: {STALE_ID}" in stdout
    assert f"orphaned source_id: {fixture['live_id']}" not in stdout

    for path in fixture["stale_paths"]:
        assert path.name in stdout, f"expected orphan {path.name} listed in stdout: {stdout!r}"

    # Dry run: zero deletions, zero writes.
    for path in [*fixture["live_paths"], *fixture["stale_paths"]]:
        assert path.exists(), f"dry run must not delete {path}"
    assert fixture["unreadable_note"].exists()
    assert fixture["candidates_path"].exists()
    assert not (fixture["root"] / "data" / "logs" / "reconcile").exists(), (
        "dry run must not write a removal log"
    )
    assert "unattributed" in stdout
    assert "garbage.md" in stdout


def test_apply_and_yes_removes_stale_artifacts_keeps_live_and_sources_and_logs(reconcile_root):
    fixture = reconcile_root
    root = fixture["root"]

    result = _run_reconcile_gc(root, "--apply", "--yes")

    assert result.returncode == 0, (
        f"expected exit code 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    for path in fixture["stale_paths"]:
        assert not path.exists(), f"expected orphan {path} to be removed"

    for path in fixture["live_paths"]:
        assert path.exists(), f"expected live artifact {path} to remain untouched"

    assert fixture["source_path"].read_bytes() == LIVE_SOURCE_TEXT, (
        "data/sources/ must be unchanged"
    )

    # Never confidently attributable -> never removed.
    assert fixture["unreadable_note"].exists()
    # Non-source-scoped -> never even considered.
    assert fixture["candidates_path"].exists()

    log_dir = root / "data" / "logs" / "reconcile"
    log_files = list(log_dir.glob("*.jsonl"))
    assert len(log_files) == 1, f"expected exactly one removal log, found {log_files}"

    log_lines = [
        json.loads(line) for line in log_files[0].read_text(encoding="utf-8").splitlines() if line
    ]
    header = log_lines[0]
    assert header["type"] == "run"
    assert fixture["live_id"] in header["keep_set"]
    assert STALE_ID not in header["keep_set"]

    removed_records = log_lines[1:]
    assert len(removed_records) == len(fixture["stale_paths"])
    # The CLI subprocess resolves every derived dir as a path relative to
    # ITS OWN cwd (root), so the log's own paths are relative to `root`
    # too -- normalize both sides to that before comparing.
    logged_paths = {Path(record["path"]) for record in removed_records}
    expected_paths = {path.relative_to(root) for path in fixture["stale_paths"]}
    assert logged_paths == expected_paths
    for record in removed_records:
        assert record["source_id"] == STALE_ID

    log_text = log_files[0].read_text(encoding="utf-8")
    assert STALE_SECRET_TEXT not in log_text, "removal log must carry no source text (DEC-23)"


def test_no_orphans_at_all_exits_zero_with_empty_list_and_no_log(tmp_path_factory):
    root = tmp_path_factory.mktemp("reconcile_gc_clean")

    sources_dir = root / "data" / "sources"
    sources_dir.mkdir(parents=True)
    source_path = sources_dir / "paper.pdf"
    source_path.write_bytes(b"only a live source, no derived artifacts at all")
    live_id = compute_source_id(source_path)
    _write_flat_set(root, live_id)

    result = _run_reconcile_gc(root, "--apply", "--yes")

    assert result.returncode == 0
    assert "no orphaned derived artifacts found" in result.stdout
    assert not (root / "data" / "logs" / "reconcile").exists()
