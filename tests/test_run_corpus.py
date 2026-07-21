"""Outer acceptance test for issue #277, slice 03 (source-set inputs (corpus
glob) + end-of-run summary): `axial run <pass> --corpus` and the
`--worklist`/`--corpus` mutual-exclusivity usage error.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Restates plans/run/03-source-sets-and-run-summary.md's Acceptance criterion
gherkin as two scenarios:

  1. A fixture `data/sources/` holding two `.pdf`, one `.docx`, and one
     ignored `.txt`, with AXIAL_LLM_PROVIDER=stub: `axial run extract
     --corpus` exits 0, processes exactly the three `.pdf`/`.docx` sources in
     deterministic sorted order (ignoring the `.txt`), and prints an
     end-of-run summary reporting total=3 with OK/FAIL/SKIP counts summing to
     3, listing each source's `source_id`, status, and (for the one crafted
     FAIL) a short reason.
  2. Both `--worklist` and `--corpus`, or neither: `axial run <pass>` with
     that argument combination exits non-zero with a usage error naming the
     conflict, having attempted no source.

Pass choice -- `extract`, mirroring tests/test_run.py / tests/test_run_resume.py
-----------------------------------------------------------------------
Same reasoning as tests/test_run.py's own module docstring: `extract` is the
only registered pass whose declared error (`ExtractError`) fires
deterministically, with no LLM-response fault-injection sequencing needed,
and its file-exists done-predicate lets the OK sources be proven fast via a
pre-placed tree fixture (see below) instead of running real docling.

Fixtures -- reused verbatim, no new fixture content
-----------------------------------------------------------------------
The three corpus-glob members, copied into a fixture `data/sources/`:
  - tests/fixtures/pipeline_ready/clean_pass_1.docx, its tree pre-placed
    from tests/fixtures/pipeline_ready/single_section_tree.json (mirrors
    tests/ingestion/test_pipeline_ready.py's own "seam decision 5": a
    `.docx` needs a real, if trivial, text layer for intake to accept it, so
    a synthetic minimal fixture + one shared, hand-authored tree fixture is
    cheaper than a genuine book excerpt, and lets the runner skip it via the
    file-exists done-predicate instead of running real docling) -- proves
    the corpus resolver picks up `.docx`, not just `.pdf`.
  - tests/fixtures/intake/no_text_layer.pdf, deliberately given NO tree
    fixture: intake rejects an image-only PDF with no text layer before any
    docling/LLM call happens (`axial.intake` -> `IntakeError` ->
    `axial.extract.SourceValidationError`, a genuine `ExtractError`) --
    fully deterministic, the same "real pass error caught by its own
    declared base" propagation path tests/test_run.py's own FAIL source
    exercises.
  - tests/fixtures/extract/prose_and_table.pdf, its tree pre-placed from
    tests/fixtures/extract/prose_and_table_tree.json.

The ignored, non-matching member is tests/fixtures/intake/unsupported.txt,
copied in unchanged to prove the corpus resolver skips it (only
`.pdf`/`.docx` match).

Test hygiene: every path this test writes (`data/sources/`, the pre-placed
tree fixtures) lives under `isolated_vault_root` (tests/conftest.py, issue
#68) -- a fresh tmp_path-backed staging root outside this repo entirely. No
real `data/` directory is ever read, moved, or written by this test.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_EXTRACT = REPO_ROOT / "tests" / "fixtures" / "extract"
FIXTURES_INTAKE = REPO_ROOT / "tests" / "fixtures" / "intake"
FIXTURES_PIPELINE_READY = REPO_ROOT / "tests" / "fixtures" / "pipeline_ready"

SOURCE_DOCX_OK = FIXTURES_PIPELINE_READY / "clean_pass_1.docx"
SOURCE_DOCX_TREE = FIXTURES_PIPELINE_READY / "single_section_tree.json"
SOURCE_PDF_FAIL = FIXTURES_INTAKE / "no_text_layer.pdf"
SOURCE_PDF_OK = FIXTURES_EXTRACT / "prose_and_table.pdf"
SOURCE_PDF_OK_TREE = FIXTURES_EXTRACT / "prose_and_table_tree.json"
IGNORED_TXT = FIXTURES_INTAKE / "unsupported.txt"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"

# argparse's fallback error for an as-yet-nonexistent subcommand/argument --
# any of these substrings in the combined output means `run` or a flag does
# not exist yet or was never reached (mirrors tests/test_run.py exactly).
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
    """Pre-place a committed extraction-tree fixture at
    <root>/data/trees/<source_id>.json (mirrors tests/test_run.py's own
    helper), so `axial run extract --corpus` reuses it verbatim via the
    file-exists done-predicate instead of running docling."""
    source_id = compute_source_id(source_path)
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture.read_bytes())


def _copy_into_sources_dir(source_path: Path, root: Path) -> Path:
    """Copy a committed fixture into <root>/data/sources/, preserving its
    filename (stem) so `compute_source_id`, a content hash keyed by stem,
    resolves to the exact same source_id as the original fixture path.
    Returns the path RELATIVE to `root` (`data/sources/<name>`) -- the
    corpus resolver's own default root is the plain relative
    `Path("data/sources")` (resolved against the subprocess's cwd, `root`
    here), so that is what actually shows up as `source_path` in the printed
    table, not an absolute path."""
    sources_dir = root / "data" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    dest = sources_dir / source_path.name
    dest.write_bytes(source_path.read_bytes())
    return Path("data") / "sources" / source_path.name


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


# ---------------------------------------------------------------------------
# Scenario 1: `--corpus` resolves data/sources/*.pdf|*.docx in sorted order,
# ignoring other extensions, and the printed/returned summary sums to total.
# ---------------------------------------------------------------------------


def test_corpus_resolves_pdf_and_docx_sorted_ignoring_other_extensions_with_summary(
    isolated_vault_root,
):
    root = isolated_vault_root
    docx_path = _copy_into_sources_dir(SOURCE_DOCX_OK, root)
    fail_path = _copy_into_sources_dir(SOURCE_PDF_FAIL, root)
    ok_path = _copy_into_sources_dir(SOURCE_PDF_OK, root)
    _copy_into_sources_dir(IGNORED_TXT, root)  # must never be attempted

    _place_tree_fixture(SOURCE_DOCX_OK, SOURCE_DOCX_TREE, root)
    _place_tree_fixture(SOURCE_PDF_OK, SOURCE_PDF_OK_TREE, root)
    # SOURCE_PDF_FAIL deliberately gets no persisted tree -- intake rejects
    # it (no text layer) before docling/LLM, a genuine deterministic
    # ExtractError.

    result = _run_axial(["run", "extract", "--corpus"], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode == 0, (
        f"expected exit code 0 when only a per-source failure occurs, got "
        f"{result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert len(table) == 3, (
        f"expected the runner to have attempted exactly the three .pdf/.docx "
        f"sources, ignoring the .txt, got {len(table)} row(s): {sorted(table.keys())}"
    )
    assert str(docx_path) in table and str(fail_path) in table and str(ok_path) in table
    assert not any(".txt" in path for path in table), (
        f"the ignored .txt fixture must never appear in the attempted rows, got: "
        f"{sorted(table.keys())}"
    )

    # Deterministic sorted order: the corpus resolver's own row order in the
    # printed table (not filesystem enumeration order).
    attempted_order = list(table.keys())
    assert attempted_order == sorted(attempted_order), (
        f"expected the printed table rows in sorted source-path order, got: {attempted_order!r}"
    )

    # The two pre-placed-tree sources are SKIP (their tree already exists
    # before this `axial run` call even starts -- mirrors tests/test_run.py's
    # own slice-02 note); the no-text-layer source is FAIL with a reason.
    assert table[str(docx_path)]["status"] == "SKIP", f"docx row: {table[str(docx_path)]!r}"
    assert table[str(ok_path)]["status"] == "SKIP", f"pdf OK row: {table[str(ok_path)]!r}"
    assert table[str(fail_path)]["status"] == "FAIL", f"pdf FAIL row: {table[str(fail_path)]!r}"
    assert table[str(fail_path)].get("reason", "").strip(), (
        f"expected the FAIL row to carry a short, non-empty reason, got: {table[str(fail_path)]!r}"
    )
    for path, row in table.items():
        assert row.get("source_id"), f"expected every row to carry a source_id, got: {row!r}"

    # The end-of-run summary: total=3, OK/FAIL/SKIP counts sum to 3.
    tally_lines = [line for line in result.stdout.splitlines() if line.startswith("run: ")]
    assert len(tally_lines) == 1, f"expected exactly one tally line, got: {tally_lines!r}"
    tally = tally_lines[0]
    assert "total=3" in tally, f"expected total=3 in the tally line, got: {tally!r}"

    counts = {
        field: int(match.group(1))
        for field in ("ok", "skipped", "failed")
        if (match := re.search(rf"{field}=(\d+)", tally))
    }
    assert set(counts) == {"ok", "skipped", "failed"}, f"could not parse tally line: {tally!r}"
    assert counts["ok"] + counts["skipped"] + counts["failed"] == 3, (
        f"expected OK/FAIL/SKIP counts to sum to 3, got tally: {tally!r}"
    )
    assert counts["skipped"] == 2 and counts["failed"] == 1


# ---------------------------------------------------------------------------
# Scenario 2: --worklist and --corpus together, or neither -> fatal,
# non-zero exit, no source attempted.
# ---------------------------------------------------------------------------


def test_worklist_and_corpus_together_is_a_fatal_usage_error(isolated_vault_root):
    root = isolated_vault_root
    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_PDF_OK])  # content never read

    result = _run_axial(
        ["run", "extract", "--worklist", str(worklist_path), "--corpus"], "stub", cwd=root
    )
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode != 0, (
        f"expected a non-zero exit code for --worklist and --corpus together, "
        f"got {result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "--worklist" in result.stderr and "--corpus" in result.stderr, (
        f"expected the fatal usage error to name the conflicting flags, got "
        f"stderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert table == {}, (
        f"expected no source attempted for the both-flags usage error, got "
        f"rows: {sorted(table.keys())}"
    )


def test_neither_worklist_nor_corpus_is_a_fatal_usage_error(isolated_vault_root):
    root = isolated_vault_root

    result = _run_axial(["run", "extract"], "stub", cwd=root)
    _assert_not_argparse_fallback(result, "run")

    assert result.returncode != 0, (
        f"expected a non-zero exit code when neither --worklist nor --corpus is "
        f"given, got {result.returncode}\nstdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "--worklist" in result.stderr and "--corpus" in result.stderr, (
        f"expected the fatal usage error to name both source-set flags, got "
        f"stderr: {result.stderr!r}"
    )

    table = _parse_run_table(result.stdout)
    assert table == {}, (
        f"expected no source attempted for the neither-flag usage error, got "
        f"rows: {sorted(table.keys())}"
    )
