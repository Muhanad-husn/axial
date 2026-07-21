"""Outer acceptance test for issue #270, slice 01 (run-logging seam):
`axial.runlog.run_context` driving the `extract` pass end-to-end.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Restates plans/run-logging/01-run-logging-seam.md's Acceptance criterion
gherkin: given a fixture source and a run-logging seam given an explicit run
directory and a fixed clock, when the extract pass runs over the fixture
through `run_context("extract")`, then the run directory contains
`run.jsonl`, `console.log`, and a `summary.md` stub; `run.jsonl` holds
exactly one JSON record for the source, carrying `source_id`, `pass`
`"extract"`, `model=null`, `status="ok"`, a numeric `duration_sec`, and
`error=null`, with no source text anywhere in the file; and the pass's
existing stdout is unchanged (the record is added, not substituted).

In-process, not a subprocess CLI run (unlike tests/test_run.py): this test
injects `root`/`clock` directly into `axial.cli._extract`, the determinism
seam plans/run-logging/01-run-logging-seam.md specifies for `run_context`
itself. Production (`axial extract <path>` from the real CLI) passes
neither and gets the real `data/logs/<name>-<now>/`.

Fixture reuse: `tests/fixtures/extract/prose_and_table.pdf` +
`prose_and_table_tree.json`, the same pair tests/test_run.py pre-places at
`data/trees/<source_id>.json` so `extract()` reads the cached tree back
instead of running docling -- fast and deterministic.
"""

from __future__ import annotations

import json
from pathlib import Path

import axial.extract as extract_mod
from axial.cli import _extract
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_EXTRACT = REPO_ROOT / "tests" / "fixtures" / "extract"
FIXTURE_PDF = FIXTURES_EXTRACT / "prose_and_table.pdf"
FIXTURE_TREE = FIXTURES_EXTRACT / "prose_and_table_tree.json"

FIXED_TS = "20260721T000000Z"

# A distinctive substring of the fixture tree's own prose (see
# prose_and_table_tree.json) -- used to prove DEC-23: run.jsonl must never
# carry a source passage, only ids, values, and status.
FIXTURE_PROSE_SNIPPET = "state formation"


def _place_tree_fixture(trees_dir: Path) -> str:
    """Pre-place the committed extraction-tree fixture at
    <trees_dir>/<source_id>.json (mirrors tests/test_run.py's
    `_place_tree_fixture`), so `extract()` hits the persisted-tree cache
    instead of running docling."""
    source_id = compute_source_id(FIXTURE_PDF)
    tree_path = trees_dir / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(FIXTURE_TREE.read_bytes())
    return source_id


def test_extract_pass_writes_run_dir_with_jsonl_console_summary(monkeypatch, tmp_path, capsys):
    trees_dir = tmp_path / "trees"
    logs_root = tmp_path / "logs"
    monkeypatch.setattr(extract_mod, "TREES_DIR", trees_dir)
    source_id = _place_tree_fixture(trees_dir)

    exit_code = _extract(str(FIXTURE_PDF), root=logs_root, clock=lambda: FIXED_TS)

    assert exit_code == 0, "expected a clean exit for a source with a pre-cached tree"

    run_dir = logs_root / f"extract-{FIXED_TS}"
    assert run_dir.is_dir(), f"expected the run directory {run_dir} to exist"
    assert (run_dir / "console.log").is_file(), "expected console.log under the run directory"
    assert (run_dir / "summary.md").is_file(), "expected a summary.md stub under the run directory"

    jsonl_path = run_dir / "run.jsonl"
    assert jsonl_path.is_file(), "expected run.jsonl under the run directory"
    raw_text = jsonl_path.read_text(encoding="utf-8")
    lines = raw_text.strip().splitlines()
    assert len(lines) == 1, f"expected exactly one record for one source, got {len(lines)}"

    record = json.loads(lines[0])
    assert record["source_id"] == source_id
    assert record["pass"] == "extract"
    assert record["model"] is None
    assert record["status"] == "ok"
    assert isinstance(record["duration_sec"], (int, float))
    assert record["duration_sec"] >= 0
    assert record["error"] is None

    # DEC-23: ids, values, and status only -- never source text.
    assert FIXTURE_PROSE_SNIPPET not in raw_text, "run.jsonl must never carry source prose (DEC-23)"

    # The pass's existing stdout is unchanged: the record is added, not
    # substituted -- the extract CLI's own tree-JSON print still happens.
    captured = capsys.readouterr()
    printed_tree = json.loads(captured.out.strip())
    assert printed_tree["children"], "expected the extract CLI's own tree print to be unchanged"
