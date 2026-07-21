"""Outer acceptance test for issue #277, slice 02 (unified resume ledger +
per-pass done-predicate): `axial run <pass>` re-run behavior.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Restates plans/run/02-unified-resume-ledger.md's Acceptance criterion
gherkin as two scenarios:

  1. A worklist of three sources for a **ledger-backed** pass (`chunk`): the
     middle source's tree is never persisted, so it deterministically raises
     `axial.chunk.MissingTreeError` (a `ChunkError`) with no LLM call
     involved. A first `axial run chunk --worklist <worklist>` completes with
     that middle source FAIL and the other two OK. Re-running over the SAME
     worklist: exits 0; the two previously-OK sources are skipped (one
     `skip: ... already done (chunk)` line each, SKIP status in the table,
     the runner never invokes `run_chunk_recursive` for them again); the
     FAILed source is attempted again; the ledger's first three rows survive
     byte-for-byte and exactly one new row (the retry) is appended -- no
     duplicate OK row for either skipped source.
  2. A **file-exists-backed** pass (`envelope`): a source whose envelope
     output already exists on disk (placed directly, with no prior `axial
     run` invocation at all) is skipped via the done-predicate on the very
     first `axial run envelope` call for it, and its on-disk envelope file
     is left byte-for-byte unchanged (proving no recompute).

Pass choice -- `chunk` for scenario 1, not `extract`/`envelope`.
-----------------------------------------------------------------------
`extract` and `envelope` both declare a FILE-EXISTS done-predicate over
their own persisted output. Using either one for scenario 1 would collide
with the very state a first successful run produces: a source whose tree/
envelope file is pre-placed (to keep the fixture PDFs fast and
docling-free, mirroring tests/test_run.py's own reasoning) would look
"already done" to the runner from the very start, before `axial run` had
even been invoked once, defeating the "a first run completed OK, a second
run skips" story this scenario needs.

`chunk` has no such self-contained output-file signal at the runner level
(module docstring: chunk/tag/artifacts/xref checkpoint per-chunk, a finer
granularity this runner does not reach into) -- it declares the LEDGER
done-predicate instead, decoupled from any pre-placed fixture file. And its
failure mode is fully deterministic without any LLM-response fault-injection
sequencing: `axial.chunk.run_chunk_recursive` never runs extraction itself
and raises `MissingTreeError` (a genuine `ChunkError`) the moment a source's
tree was never persisted (`axial.chunk._resolve_chunk_inputs`) -- exactly
the same "real pass error caught by its own declared base" propagation path
tests/test_run.py's own `extract`-based scenario exercises, without the
file-exists collision.

Fixtures -- reused verbatim, no new fixture content
-----------------------------------------------------------------------
Scenario 1's two OK sources are tests/fixtures/extract/prose_and_table.pdf
and tests/fixtures/envelope/thesis_paper.pdf, each paired with its own
already-committed extraction-tree fixture, pre-placed at
data/trees/<source_id>.json under the isolated cwd (mirrors
tests/test_run.py's `_place_tree_fixture` helper) so `run_chunk_recursive`
reads the cached tree back instead of running docling. The FAIL source is
tests/fixtures/envelope/topic_titled_paper.pdf, used deliberately WITHOUT
placing its own tree fixture, so `chunk`'s own `MissingTreeError` fires.

Scenario 2 reuses tests/fixtures/extract/prose_and_table.pdf again, purely
to compute a real, stable source_id (`axial run` requires the source file
to exist) -- the placeholder envelope JSON placed at
data/envelopes/<source_id>.json is fabricated inline (its exact content is
the point being asserted: it must survive byte-for-byte), not read from any
fixture file.

Test hygiene: every path this test writes (the worklist, the pre-placed
tree/envelope fixtures) lives under `isolated_vault_root`
(tests/conftest.py, issue #68) -- a fresh tmp_path-backed staging root
outside this repo entirely. No real data/ directory is ever read, moved, or
written by this test.
"""

from __future__ import annotations

import csv
import json
import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_EXTRACT = REPO_ROOT / "tests" / "fixtures" / "extract"
FIXTURES_ENVELOPE = REPO_ROOT / "tests" / "fixtures" / "envelope"

SOURCE_1_OK = FIXTURES_EXTRACT / "prose_and_table.pdf"
SOURCE_1_TREE = FIXTURES_EXTRACT / "prose_and_table_tree.json"
SOURCE_2_FAIL = FIXTURES_ENVELOPE / "topic_titled_paper.pdf"
SOURCE_3_OK = FIXTURES_ENVELOPE / "thesis_paper.pdf"
SOURCE_3_TREE = FIXTURES_ENVELOPE / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent subcommand (mirrors
# tests/test_run.py exactly).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "axial", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=env,
    )


def _assert_not_argparse_fallback(result: subprocess.CompletedProcess, command: str) -> None:
    combined = result.stdout + result.stderr
    for marker in ARGPARSE_FALLBACK_MARKERS:
        assert marker not in combined, (
            f"expected a real `{command}` behavior path, not an argparse "
            f"fallback (found {marker!r}) -- this means the `{command}` "
            f"subcommand does not exist yet or was never reached:\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )


def _place_tree_fixture(source_path: Path, tree_fixture: Path, root: Path) -> None:
    source_id = compute_source_id(source_path)
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture.read_bytes())


def _write_worklist(path: Path, source_paths: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(p) for p in source_paths) + "\n", encoding="utf-8")


def _parse_run_table(stdout: str) -> dict[str, dict[str, str]]:
    """Parse `axial run`'s per-source outcome table from stdout (mirrors
    tests/test_run.py's own helper): source_path -> row fields by column
    name. Skips the trailing `run: ...` tally line (no tab characters, never
    matches the header shape)."""
    lines = [line for line in stdout.splitlines() if line.strip()]

    header_index = None
    header_cols: list[str] | None = None
    for index, line in enumerate(lines):
        cols = [col.strip() for col in line.split("\t")]
        if "source_path" in cols and "status" in cols:
            header_index = index
            header_cols = cols
            break

    if header_index is None or header_cols is None:
        return {}

    rows: dict[str, dict[str, str]] = {}
    for line in lines[header_index + 1 :]:
        cols = [col.strip() for col in line.split("\t")]
        if len(cols) != len(header_cols):
            continue
        row = dict(zip(header_cols, cols))
        rows[row["source_path"]] = row
    return rows


def _skip_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("skip:")]


def _ledger_path(root: Path) -> Path:
    return root / "data" / "logs" / "run" / "ledger.tsv"


def _read_ledger_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# ---------------------------------------------------------------------------
# Scenario 1: ledger-backed pass (`chunk`) -- re-run skips OK sources doing
# zero pipeline work, retries the FAIL source, appends no duplicate row, and
# the first run's ledger rows survive unchanged.
# ---------------------------------------------------------------------------


def test_rerun_skips_ok_sources_retries_fail_source_no_duplicate_ledger_row(isolated_vault_root):
    root = isolated_vault_root
    _place_tree_fixture(SOURCE_1_OK, SOURCE_1_TREE, root)
    _place_tree_fixture(SOURCE_3_OK, SOURCE_3_TREE, root)
    # SOURCE_2_FAIL deliberately gets no persisted tree -- `chunk` raises
    # MissingTreeError for it, deterministically, no LLM involved.

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_1_OK, SOURCE_2_FAIL, SOURCE_3_OK])

    # --- run 1: a genuine first pass over all three sources ---------------
    result_1 = _run_axial(["run", "chunk", "--worklist", str(worklist_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result_1, "run")
    assert result_1.returncode == 0, (
        f"expected exit 0 with only a per-source failure, got "
        f"{result_1.returncode}\nstdout: {result_1.stdout!r}\nstderr: {result_1.stderr!r}"
    )

    table_1 = _parse_run_table(result_1.stdout)
    assert len(table_1) == 3, f"expected all three sources attempted, got {sorted(table_1)}"
    assert table_1[str(SOURCE_1_OK)]["status"] == "OK"
    assert table_1[str(SOURCE_3_OK)]["status"] == "OK"
    assert table_1[str(SOURCE_2_FAIL)]["status"] == "FAIL"
    assert table_1[str(SOURCE_2_FAIL)]["reason"].strip()

    ledger_path = _ledger_path(root)
    assert ledger_path.exists(), "run 1 must have created the ledger"
    rows_after_run_1 = _read_ledger_rows(ledger_path)
    assert len(rows_after_run_1) == 3, (
        f"expected one ledger row per attempted source, got {rows_after_run_1}"
    )

    # --- run 2: the same worklist, same cwd -> ledger is now populated ----
    result_2 = _run_axial(["run", "chunk", "--worklist", str(worklist_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result_2, "run")
    assert result_2.returncode == 0, (
        f"expected exit 0 on re-run, got {result_2.returncode}\n"
        f"stdout: {result_2.stdout!r}\nstderr: {result_2.stderr!r}"
    )

    table_2 = _parse_run_table(result_2.stdout)
    assert table_2[str(SOURCE_1_OK)]["status"] == "SKIP", (
        f"expected the first already-OK source skipped on re-run, got row: "
        f"{table_2[str(SOURCE_1_OK)]!r}"
    )
    assert table_2[str(SOURCE_3_OK)]["status"] == "SKIP", (
        f"expected the third already-OK source skipped on re-run, got row: "
        f"{table_2[str(SOURCE_3_OK)]!r}"
    )
    assert table_2[str(SOURCE_2_FAIL)]["status"] == "FAIL", (
        "expected the previously FAILed source to be attempted again (and fail "
        f"again, deterministically), got row: {table_2[str(SOURCE_2_FAIL)]!r}"
    )

    skip_lines = _skip_lines(result_2.stdout)
    assert len(skip_lines) == 2, f"expected exactly two skip lines, got: {skip_lines!r}"
    for source in (SOURCE_1_OK, SOURCE_3_OK):
        assert any(str(source) in line and "chunk" in line for line in skip_lines), (
            f"expected a skip line naming {source} and the pass 'chunk', got: {skip_lines!r}"
        )
    assert not any(str(SOURCE_2_FAIL) in line for line in skip_lines), (
        f"the retried FAIL source must never appear in a skip line, got: {skip_lines!r}"
    )

    rows_after_run_2 = _read_ledger_rows(ledger_path)
    assert len(rows_after_run_2) == 4, (
        f"expected exactly one new row (the retried FAIL source) appended, "
        f"no duplicate rows for the two skipped OK sources, got: {rows_after_run_2}"
    )
    assert rows_after_run_2[:3] == rows_after_run_1, (
        "the first run's three rows must survive byte-for-byte unchanged after "
        f"the re-run; before={rows_after_run_1!r} after={rows_after_run_2[:3]!r}"
    )
    new_row = rows_after_run_2[3]
    assert new_row["source_path"] == str(SOURCE_2_FAIL)
    assert new_row["status"] == "FAIL"
    assert new_row["pass"] == "chunk"


# ---------------------------------------------------------------------------
# Scenario 2: file-exists-backed pass (`envelope`) -- a source whose output
# already exists on disk is skipped on the very first `axial run` call for
# it, without recomputing (rewriting) that output.
# ---------------------------------------------------------------------------


def test_preexisting_output_file_is_skipped_without_recompute(isolated_vault_root):
    root = isolated_vault_root
    source_id = compute_source_id(SOURCE_1_OK)
    envelope_path = root / "data" / "envelopes" / f"{source_id}.json"
    envelope_path.parent.mkdir(parents=True, exist_ok=True)
    placeholder = {"placeholder": True, "source_id": source_id}
    envelope_path.write_text(json.dumps(placeholder), encoding="utf-8")

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_1_OK])

    result = _run_axial(["run", "envelope", "--worklist", str(worklist_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert table[str(SOURCE_1_OK)]["status"] == "SKIP", (
        f"expected the source with a pre-existing envelope skipped on its very "
        f"first `axial run` invocation, got row: {table[str(SOURCE_1_OK)]!r}"
    )

    skip_lines = _skip_lines(result.stdout)
    assert len(skip_lines) == 1, f"expected exactly one skip line, got: {skip_lines!r}"
    assert str(SOURCE_1_OK) in skip_lines[0] and "envelope" in skip_lines[0]

    assert json.loads(envelope_path.read_text(encoding="utf-8")) == placeholder, (
        "expected the pre-existing envelope file left byte-for-byte unchanged "
        "(no recompute) once the done-predicate reported it done"
    )

    ledger_path = _ledger_path(root)
    assert not ledger_path.exists(), (
        "a skip must never touch the ledger -- extract/envelope's done-signal "
        "is their own output file, not the ledger"
    )
