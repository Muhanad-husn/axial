"""Outer acceptance test for issue #270, slice 02 (run-logging seam fan-out):
`axial.runlog.run_context` driving the `envelope` pass end-to-end --
model-bearing passes `extract` (slice 01, tests/test_runlog.py) did not
cover. This file originally also covered the `tag` pass (retired along with
the tag pass itself, issue #414, `plans/phase-a-v1/README.md` D4/D5) and the
`eval` pass (retired along with the gold-set scoring harness it wrapped,
issue #710).

Locked behavioral contract (DEC-1) -- do not edit once committed red, except
for a documented deviation (CLAUDE.local.md: tests are contracts owned by the
product, not locked artifacts -- an edit needs a justification, not a
rewrite).

Restates plans/run-logging/02-wire-remaining-passes.md's Acceptance
criterion gherkin: given a fixture source with a stored envelope and chunk
records, AXIAL_LLM_PROVIDER=stub, an explicit run directory, and a fixed
clock, when the envelope pass runs through its run_context, it writes a
data/logs/envelope-<fixed-ts>/ containing run.jsonl and console.log; the
run.jsonl record carries a non-null model (the stub provider's id), a status,
and a numeric duration_sec; a source that fails the pass records
status="error" with a short error string; no run.jsonl record contains
source text (DEC-23); and the pass's existing stdout is unchanged.

In-process, not a subprocess CLI run (mirrors tests/test_runlog.py, slice
01): this test injects `root`/`clock` directly into `axial.cli._envelope`,
the same determinism seam slice 01 established for `_extract`. Production
(`axial envelope` from the real CLI) passes neither and gets the real
`data/logs/<name>-<now>/`.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf +
thesis_paper_tree.json (already the shared envelope/tag fixture pair --
tests/ingestion/test_tag.py's own arrange step reuses the identical fixture
for the same reason: a real Introduction/Conclusion pair the envelope pass
needs, and prose the chunk pass splits cleanly).
"""

from __future__ import annotations

import json
from pathlib import Path

import axial.envelope as envelope_mod
import axial.extract as extract_mod
from axial.cli import _envelope
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_ENVELOPE = REPO_ROOT / "tests" / "fixtures" / "envelope"
FIXTURE_PDF = FIXTURES_ENVELOPE / "thesis_paper.pdf"
FIXTURE_TREE = FIXTURES_ENVELOPE / "thesis_paper_tree.json"

FIXED_TS = "20260721T000000Z"

# A distinctive substring of the fixture's own prose (see
# thesis_paper_tree.json) -- used to prove DEC-23: run.jsonl must never
# carry a source passage, only ids, values, and status.
FIXTURE_PROSE_SNIPPET = "infrastructural reach"


def _place_tree_fixture(trees_dir: Path) -> str:
    """Pre-place the committed extraction-tree fixture at
    <trees_dir>/<source_id>.json (mirrors tests/test_runlog.py's slice-01
    helper), so `extract()` (called internally by both the envelope and
    chunk passes) hits the persisted-tree cache instead of running docling."""
    source_id = compute_source_id(FIXTURE_PDF)
    tree_path = trees_dir / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(FIXTURE_TREE.read_bytes())
    return source_id


def _one_record(jsonl_path: Path) -> dict:
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1, f"expected exactly one run.jsonl record, got {len(lines)}: {lines!r}"
    return json.loads(lines[0])


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------


def test_envelope_pass_writes_run_dir_with_stub_model_record(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "stub")
    trees_dir = tmp_path / "trees"
    envelopes_dir = tmp_path / "envelopes"
    logs_root = tmp_path / "logs"
    monkeypatch.setattr(extract_mod, "TREES_DIR", trees_dir)
    monkeypatch.setattr(envelope_mod, "_default_envelopes_dir", lambda config_path: envelopes_dir)
    source_id = _place_tree_fixture(trees_dir)

    exit_code = _envelope(str(FIXTURE_PDF), root=logs_root, clock=lambda: FIXED_TS)

    assert exit_code == 0, "expected a clean exit for a fresh (uncached) envelope run"

    run_dir = logs_root / f"envelope-{FIXED_TS}"
    assert (run_dir / "console.log").is_file()
    assert (run_dir / "summary.md").is_file()

    raw_text = (run_dir / "run.jsonl").read_text(encoding="utf-8")
    record = _one_record(run_dir / "run.jsonl")
    assert record["source_id"] == source_id
    assert record["pass"] == "envelope"
    assert record["model"] == "stub", "expected the stub provider's id, not null"
    assert record["status"] == "ok"
    assert isinstance(record["duration_sec"], (int, float))
    assert record["duration_sec"] >= 0
    assert record["error"] is None

    # DEC-23: ids, values, and status only -- never source text.
    assert FIXTURE_PROSE_SNIPPET not in raw_text

    # The pass's existing stdout is unchanged: the record is added, not
    # substituted -- the envelope CLI's own JSON print still happens.
    captured = capsys.readouterr()
    printed = json.loads(captured.out.strip())
    assert printed["thesis"], "expected the envelope CLI's own stdout print to be unchanged"


def test_envelope_pass_error_path_records_status_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "stub")
    logs_root = tmp_path / "logs"
    missing_source = tmp_path / "does-not-exist.pdf"

    exit_code = _envelope(str(missing_source), root=logs_root, clock=lambda: FIXED_TS)

    assert exit_code == 1
    run_dir = logs_root / f"envelope-{FIXED_TS}"
    record = _one_record(run_dir / "run.jsonl")
    assert record["pass"] == "envelope"
    assert record["status"] == "error"
    assert record["error"], "expected a short, non-empty error string"
    assert record["duration_sec"] >= 0
