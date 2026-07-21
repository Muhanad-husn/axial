"""Outer acceptance test for issue #277, slice 01 (runner core + per-source
failure isolation): `axial run <pass> --worklist <file>`.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Restates plans/run/01-runner-core-and-failure-isolation.md's Acceptance
criterion gherkin as three scenarios:

  1. A worklist naming three sources, the middle one crafted to make the
     running pass raise its own declared error, with AXIAL_LLM_PROVIDER=stub:
     `axial run <pass> --worklist <worklist>` exits 0, attempts all three
     sources in worklist order, records the middle one FAIL with a short
     reason, and records the first and third OK.
  2. A worklist path that does not exist: exits non-zero, prints a fatal
     error naming the unreadable worklist, and attempts no source.
  3. A pass name absent from the registry: exits non-zero, prints a fatal
     error naming the unknown pass, and attempts no source.

Pass choice -- `extract`, not `tag`/`envelope`/etc.
-----------------------------------------------------------------------
`extract` is the only registered pass whose declared error
(`axial.extract.ExtractError`) can be raised deterministically without any
LLM-response fault-injection sequencing. `AXIAL_STUB_TAG_FAIL_AT` and its
siblings (src/axial/llm.py) drive their fault injection off a PER-PROCESS
call counter shared across every source `axial run` drives in one
invocation -- scripting "source 2's Nth call misbehaves, but sources 1 and 3
stay clean" would require hardcoding call order across sources, exactly what
tests/ingestion/test_pipeline_ready.py's own module docstring (seam decision
4) deliberately avoids by giving each fault-injection scenario its own
single-source invocation. This test instead needs three sources sharing ONE
worklist and ONE invocation, so it picks a pass whose failure needs no such
sequencing: an existing file with an unsupported extension
(tests/fixtures/intake/unsupported.txt) fails intake validation before any
docling/LLM call happens at all (`axial.intake.UnsupportedExtensionError` ->
`axial.extract.SourceValidationError`, a genuine `ExtractError`) -- fully
deterministic, and it exercises the same propagation path (a real pass error
caught by its own declared base) any other registered pass would use.

Fixtures -- reused verbatim, no new fixture content
-----------------------------------------------------------------------
The two OK sources are tests/fixtures/extract/prose_and_table.pdf and
tests/fixtures/envelope/thesis_paper.pdf, each paired with its own already-
committed extraction-tree fixture (`*_tree.json`), pre-placed at
data/trees/<source_id>.json under the isolated cwd (mirrors
tests/ingestion/test_pipeline_ready.py's `_place_tree_fixture` helper) so
`axial run extract` reads the cached tree back instead of running docling --
keeping this test fast and independent of docling/model behavior.
`axial.extract.extract` still runs `axial.intake.intake` FIRST even on a
cache hit (see extract.py's own docstring), so this stays a genuine, if
fast, extract-pass run, not a bypass.

Test hygiene: every path this test writes (the worklist, the pre-placed tree
fixtures) lives under `isolated_vault_root` (tests/conftest.py, issue #68) --
a fresh tmp_path-backed staging root outside this repo entirely. No real
data/ directory is ever read, moved, or written by this test.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_EXTRACT = REPO_ROOT / "tests" / "fixtures" / "extract"
FIXTURES_ENVELOPE = REPO_ROOT / "tests" / "fixtures" / "envelope"
FIXTURES_INTAKE = REPO_ROOT / "tests" / "fixtures" / "intake"

SOURCE_1_OK = FIXTURES_EXTRACT / "prose_and_table.pdf"
SOURCE_1_TREE = FIXTURES_EXTRACT / "prose_and_table_tree.json"
SOURCE_2_FAIL = FIXTURES_INTAKE / "unsupported.txt"
SOURCE_3_OK = FIXTURES_ENVELOPE / "thesis_paper.pdf"
SOURCE_3_TREE = FIXTURES_ENVELOPE / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent subcommand -- any of
# these substrings in the combined output means `run` does not exist yet or
# was never reached (mirrors tests/ingestion/test_pipeline_ready.py exactly).
ARGPARSE_FALLBACK_MARKERS = (
    "invalid choice",
    "unrecognized arguments",
)


def _run_axial(
    args: list[str],
    provider: str,
    *,
    cwd: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env[PROVIDER_ENV_VAR] = provider
    if extra_env:
        env.update(extra_env)
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
    """Pre-place a committed extraction-tree fixture at
    <root>/data/trees/<source_id>.json (module docstring), so `axial run
    extract` reuses it verbatim instead of running docling/Unstructured."""
    source_id = compute_source_id(source_path)
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture.read_bytes())


def _write_worklist(path: Path, source_paths: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(p) for p in source_paths) + "\n", encoding="utf-8")


def _parse_run_table(stdout: str) -> dict[str, dict[str, str]]:
    """Parse `axial run`'s per-source outcome table from stdout: a header
    row whose tab-separated columns include (at least) `source_path` and
    `status`, followed by one row per attempted source
    (`axial.run.TABLE_COLUMNS`). Returns source_path -> that row's fields (by
    column name), so every assertion below looks a source up by its own
    path, never by row position. The trailing `run: ...` tally line has no
    tab characters and never matches the header shape, so it is skipped
    automatically."""
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


# ---------------------------------------------------------------------------
# Scenario 1: three sources, the middle one crafted to fail -> isolated,
# loop continues, exit 0.
# ---------------------------------------------------------------------------


def test_middle_source_failure_is_isolated_and_loop_continues(isolated_vault_root):
    root = isolated_vault_root
    _place_tree_fixture(SOURCE_1_OK, SOURCE_1_TREE, root)
    _place_tree_fixture(SOURCE_3_OK, SOURCE_3_TREE, root)

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_1_OK, SOURCE_2_FAIL, SOURCE_3_OK])

    result = _run_axial(["run", "extract", "--worklist", str(worklist_path)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode == 0, (
        f"expected exit code 0 when only a per-source failure occurs (isolated, "
        f"loop continues past it), got {result.returncode}\nstdout: "
        f"{result.stdout!r}\nstderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert len(table) == 3, (
        f"expected the runner to have attempted all three worklist sources, "
        f"got {len(table)} row(s): {sorted(table.keys())}"
    )

    row_1 = table[str(SOURCE_1_OK)]
    row_2 = table[str(SOURCE_2_FAIL)]
    row_3 = table[str(SOURCE_3_OK)]

    assert row_1["status"] == "OK", f"expected the first source OK, got row: {row_1!r}"
    assert row_3["status"] == "OK", f"expected the third source OK, got row: {row_3!r}"

    assert row_2["status"] == "FAIL", f"expected the middle source FAIL, got row: {row_2!r}"
    assert row_2.get("reason", "").strip(), (
        f"expected the middle source's FAIL row to carry a short, non-empty "
        f"reason, got row: {row_2!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 2: an unreadable worklist -> fatal, non-zero exit, no source
# attempted.
# ---------------------------------------------------------------------------


def test_unreadable_worklist_is_fatal_and_attempts_no_source(isolated_vault_root, tmp_path):
    root = isolated_vault_root
    missing_worklist = tmp_path / "does-not-exist.txt"

    result = _run_axial(["run", "extract", "--worklist", str(missing_worklist)], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for an unreadable worklist, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert str(missing_worklist) in result.stderr, (
        f"expected the fatal error to name the unreadable worklist "
        f"{str(missing_worklist)!r}, got stderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert table == {}, (
        f"expected no source to have been attempted for a fatal, unreadable "
        f"worklist, got rows: {sorted(table.keys())}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: a pass name absent from the registry -> fatal, non-zero exit,
# no source attempted.
# ---------------------------------------------------------------------------


def test_unknown_pass_name_is_fatal_and_attempts_no_source(isolated_vault_root):
    root = isolated_vault_root
    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_1_OK])

    result = _run_axial(
        ["run", "not-a-real-pass", "--worklist", str(worklist_path)], "stub", cwd=root
    )
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for an unknown pass name, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "not-a-real-pass" in result.stderr, (
        f"expected the fatal error to name the unknown pass 'not-a-real-pass', "
        f"got stderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert table == {}, (
        f"expected no source to have been attempted for an unknown pass name, "
        f"got rows: {sorted(table.keys())}"
    )
