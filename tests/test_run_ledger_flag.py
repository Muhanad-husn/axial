"""Outer acceptance test for issue #317: `axial run <pass> --ledger <path>`.

`run_pass` (src/axial/run.py:422) already accepts a `ledger_path` parameter;
this issue is purely about exposing it on the `axial run` subparser and
threading it through the CLI dispatch (`_run`, src/axial/cli.py) so several
detached `axial run` processes -- stage 4.1a's parallel topology -- do not
all append to one shared `data/run/ledger.tsv`.

Restates the issue's own Acceptance criterion gherkin as three scenarios:

  1. Two `axial run` invocations over disjoint worklists, each given its own
     `--ledger` path: each ledger file ends up holding only its own source's
     row -- never the other invocation's.
  2. A re-run over the same worklist with the same `--ledger` path resumes
     from it: the previously-OK source is skipped, and no duplicate row is
     appended.
  3. Omitting `--ledger` entirely still writes to today's default,
     `data/run/ledger.tsv` (`axial.run.LEDGER_PATH`, relative to cwd) -- the
     flag is additive, not a breaking change to the no-flag path.

Pass choice -- `chunk`, mirroring tests/test_run_resume.py
-----------------------------------------------------------------------
`chunk` declares the runner's own LEDGER done-predicate (not a file-exists
one), so a completed run's ledger row is the only signal a re-run has to go
on -- exactly what this test needs to observe. It is LLM-free (recursive/
structural chunking) and succeeds deterministically once a source's tree is
pre-placed, so no fault injection or model call is needed.

Fixtures -- reused verbatim from tests/test_run_resume.py, no new content
-----------------------------------------------------------------------
tests/fixtures/extract/prose_and_table.pdf and
tests/fixtures/envelope/thesis_paper.pdf, each paired with its own
already-committed extraction-tree fixture, pre-placed at
data/trees/<source_id>.json under the isolated cwd so `run_chunk_recursive`
reads the cached tree back instead of running docling.

Test hygiene: every path this test writes lives under `isolated_vault_root`
(tests/conftest.py, issue #68) -- a fresh tmp_path-backed staging root
outside this repo entirely. No real data/ directory is ever read, moved, or
written by this test.
"""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id
from axial.run import LEDGER_PATH

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_EXTRACT = REPO_ROOT / "tests" / "fixtures" / "extract"
FIXTURES_ENVELOPE = REPO_ROOT / "tests" / "fixtures" / "envelope"

SOURCE_A = FIXTURES_EXTRACT / "prose_and_table.pdf"
SOURCE_A_TREE = FIXTURES_EXTRACT / "prose_and_table_tree.json"
SOURCE_B = FIXTURES_ENVELOPE / "thesis_paper.pdf"
SOURCE_B_TREE = FIXTURES_ENVELOPE / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent flag (mirrors
# tests/test_run.py exactly).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(args: list[str], provider: str, *, cwd: Path) -> subprocess.CompletedProcess:
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
            f"subcommand/flag does not exist yet or was never reached:\n"
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
    """Mirrors tests/test_run.py's own helper: source_path -> row fields by
    column name, skipping the trailing `run: ...` tally line."""
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


def _read_ledger_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


# ---------------------------------------------------------------------------
# Scenario 1: two disjoint worklists, each given its own --ledger path --
# each ledger file ends up holding only its own source's row.
# ---------------------------------------------------------------------------


def test_disjoint_worklists_with_own_ledger_write_only_their_own_rows(isolated_vault_root):
    root = isolated_vault_root
    _place_tree_fixture(SOURCE_A, SOURCE_A_TREE, root)
    _place_tree_fixture(SOURCE_B, SOURCE_B_TREE, root)

    worklist_a = root / "worklist_a.txt"
    worklist_b = root / "worklist_b.txt"
    _write_worklist(worklist_a, [SOURCE_A])
    _write_worklist(worklist_b, [SOURCE_B])

    ledger_a = root / "worker-a" / "ledger.tsv"
    ledger_b = root / "worker-b" / "ledger.tsv"

    result_a = _run_axial(
        ["run", "chunk", "--worklist", str(worklist_a), "--ledger", str(ledger_a)],
        "stub",
        cwd=root,
    )
    _assert_not_argparse_fallback(result_a, "run")
    assert result_a.returncode == 0, (
        f"expected exit 0, got {result_a.returncode}\n"
        f"stdout: {result_a.stdout!r}\nstderr: {result_a.stderr!r}"
    )
    table_a = _parse_run_table(result_a.stdout)
    assert table_a[str(SOURCE_A)]["status"] == "OK", f"row: {table_a.get(str(SOURCE_A))!r}"

    result_b = _run_axial(
        ["run", "chunk", "--worklist", str(worklist_b), "--ledger", str(ledger_b)],
        "stub",
        cwd=root,
    )
    _assert_not_argparse_fallback(result_b, "run")
    assert result_b.returncode == 0, (
        f"expected exit 0, got {result_b.returncode}\n"
        f"stdout: {result_b.stdout!r}\nstderr: {result_b.stderr!r}"
    )
    table_b = _parse_run_table(result_b.stdout)
    assert table_b[str(SOURCE_B)]["status"] == "OK", f"row: {table_b.get(str(SOURCE_B))!r}"

    assert ledger_a.exists(), "expected --ledger to have created its own file for worker A"
    assert ledger_b.exists(), "expected --ledger to have created its own file for worker B"

    rows_a = _read_ledger_rows(ledger_a)
    rows_b = _read_ledger_rows(ledger_b)

    source_a_id = compute_source_id(SOURCE_A)
    source_b_id = compute_source_id(SOURCE_B)

    assert [row["source_id"] for row in rows_a] == [source_a_id], (
        f"expected worker A's ledger to hold only its own source's row, got: {rows_a!r}"
    )
    assert [row["source_id"] for row in rows_b] == [source_b_id], (
        f"expected worker B's ledger to hold only its own source's row, got: {rows_b!r}"
    )
    assert source_b_id not in [row["source_id"] for row in rows_a], (
        "worker A's ledger must never receive worker B's row"
    )
    assert source_a_id not in [row["source_id"] for row in rows_b], (
        "worker B's ledger must never receive worker A's row"
    )

    default_ledger = root / LEDGER_PATH
    assert not default_ledger.exists(), (
        "neither invocation named --ledger explicitly on the default path, so "
        "the shared default ledger must never have been created"
    )


# ---------------------------------------------------------------------------
# Scenario 2: a re-run with the same --ledger path resumes from it --
# already-done source skipped, no duplicate row.
# ---------------------------------------------------------------------------


def test_rerun_with_same_ledger_path_resumes_and_skips(isolated_vault_root):
    root = isolated_vault_root
    _place_tree_fixture(SOURCE_A, SOURCE_A_TREE, root)

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_A])
    ledger_path = root / "worker-a" / "ledger.tsv"

    result_1 = _run_axial(
        ["run", "chunk", "--worklist", str(worklist_path), "--ledger", str(ledger_path)],
        "stub",
        cwd=root,
    )
    _assert_not_argparse_fallback(result_1, "run")
    assert result_1.returncode == 0
    assert _parse_run_table(result_1.stdout)[str(SOURCE_A)]["status"] == "OK"

    rows_after_run_1 = _read_ledger_rows(ledger_path)
    assert len(rows_after_run_1) == 1

    result_2 = _run_axial(
        ["run", "chunk", "--worklist", str(worklist_path), "--ledger", str(ledger_path)],
        "stub",
        cwd=root,
    )
    _assert_not_argparse_fallback(result_2, "run")
    assert result_2.returncode == 0

    table_2 = _parse_run_table(result_2.stdout)
    assert table_2[str(SOURCE_A)]["status"] == "SKIP", (
        f"expected the already-OK source resumed (skipped) from the same "
        f"--ledger path, got row: {table_2[str(SOURCE_A)]!r}"
    )

    rows_after_run_2 = _read_ledger_rows(ledger_path)
    assert rows_after_run_2 == rows_after_run_1, (
        "a re-run over the same --ledger path must append no duplicate row "
        f"for an already-done source; before={rows_after_run_1!r} "
        f"after={rows_after_run_2!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: omitting --ledger keeps today's default,
# data/run/ledger.tsv (axial.run.LEDGER_PATH).
# ---------------------------------------------------------------------------


def test_omitting_ledger_flag_keeps_default_ledger_path(isolated_vault_root):
    root = isolated_vault_root
    _place_tree_fixture(SOURCE_A, SOURCE_A_TREE, root)

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_A])

    result = _run_axial(["run", "chunk", "--worklist", str(worklist_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")
    assert result.returncode == 0
    assert _parse_run_table(result.stdout)[str(SOURCE_A)]["status"] == "OK"

    default_ledger = root / LEDGER_PATH
    assert default_ledger.exists(), (
        "expected omitting --ledger to fall back to the default ledger path"
    )
    rows = _read_ledger_rows(default_ledger)
    assert [row["source_id"] for row in rows] == [compute_source_id(SOURCE_A)]
