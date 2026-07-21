"""Outer acceptance test for issue #270, slice 02 (run-logging seam fan-out):
`axial.runlog.run_context` driving the `envelope`, `tag`, and `eval` passes
end-to-end -- the three model-bearing (or, for `eval`, model-free) passes
`extract` (slice 01, tests/test_runlog.py) did not cover.

Locked behavioral contract (DEC-1) -- do not edit once committed red, except
for the two documented deviations below (CLAUDE.local.md: tests are
contracts owned by the product, not locked artifacts -- an edit needs a
justification, not a rewrite).

Restates plans/run-logging/02-wire-remaining-passes.md's Acceptance
criterion gherkin: given a fixture source with a stored envelope and chunk
records, AXIAL_LLM_PROVIDER=stub, an explicit run directory, and a fixed
clock, when each of the envelope, tag, and eval passes runs through its
run_context, then each writes a data/logs/<pass>-<fixed-ts>/ containing
run.jsonl and console.log; each run.jsonl holds one record per source with
pass set to that pass name; each record carries a non-null model (the stub
provider's id), a status, and a numeric duration_sec; a source that fails
its pass records status="error" with a short error string; no run.jsonl
record contains source text (DEC-23); and each pass's existing stdout is
unchanged.

Two documented deviations for `eval` (both because `axial.eval.run_eval`
genuinely differs from `extract`/`envelope`/`tag`, discovered while building
this slice, not because the plan's intent was contested):

1. `model=None` for `eval`'s record, not the stub's id. `run_eval` makes no
   LLM call at all -- its own docstring says so verbatim ("Offline and
   deterministic: no LLM call, no network") and tests/eval/test_eval.py's
   own arrange step runs it under AXIAL_LLM_PROVIDER=explode specifically to
   prove that ("any run that reaches an LLM is a bug"). A non-null model
   here would be fabricated telemetry. This mirrors slice 01's own
   established precedent for a model-free pass (`extract`, `model=null` --
   plans/run-logging/README.md: "That is a feature, not a gap").
2. One record per `axial eval` invocation, not one per source. Unlike
   extract/envelope/tag, `axial eval` takes no source_path argument -- it
   is not source-scoped, it scores the WHOLE gold set (every sampled chunk
   across however many sources) in one atomic offline join, so "one record
   per source" does not apply. The single record's `source_id` is `""`,
   mirroring the CLI's own `_safe_source_id` no-source-resolved fallback.

In-process, not a subprocess CLI run (mirrors tests/test_runlog.py, slice
01): this test injects `root`/`clock` directly into `axial.cli._envelope` /
`axial.cli._tag` / `axial.cli._eval`, the same determinism seam slice 01
established for `_extract`. Production (`axial envelope|tag|eval` from the
real CLI) passes neither and gets the real `data/logs/<name>-<now>/`.

Fixture reuse: tests/fixtures/envelope/thesis_paper.pdf +
thesis_paper_tree.json (already the shared envelope/tag fixture pair --
tests/ingestion/test_tag.py's own arrange step reuses the identical fixture
for the same reason: a real Introduction/Conclusion pair the envelope pass
needs, and prose the chunk pass splits cleanly). `eval` needs no PDF at all
-- it reads two on-disk inputs directly, seeded here as minimal JSON/xlsx
fixtures mirroring tests/eval/test_eval.py's own arrange helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import axial.chunk as chunk_mod
import axial.envelope as envelope_mod
import axial.eval as eval_mod
import axial.extract as extract_mod
from axial.chunk import run_chunk_recursive
from axial.cli import _envelope, _eval, _tag
from axial.envelope import compute_source_id
from axial.eval import _axis_vocabularies
from axial.gold import RECORD_FIELDS, SHEET_COLUMNS, build_workbook
from axial.tag import DEFAULT_DOMAIN_DIR

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


def _place_chunk_fixture(chunks_dir: Path) -> None:
    """Write the real, on-disk chunk artifact for the fixture (issue #154:
    `run_tag` reads `data/chunks/<source_id>.jsonl` via `read_chunks`, never
    recomputing chunks itself), via the real chunk pass -- deterministic,
    zero-embedding, zero-LLM for this clean-prose fixture."""
    run_chunk_recursive(str(FIXTURE_PDF), chunks_dir=chunks_dir)


# --- eval fixture: a single tagger chunk record + a returned label sheet
# that agrees with it on every axis. This test's purpose is the run-logging
# wire, not eval's own scoring correctness (tests/eval/test_eval.py owns
# that contract), so one fully-agreeing record is enough. -------------------

EVAL_TAGGER_RECORD = {
    "chunk_id": "runlog-eval-fixture-c1",
    "source": "runlog-eval-fixture-source",
    "section": "Introduction",
    "chunk_text": "Synthetic prose for the run-logging eval fixture.",
    "field": "state",
    "empirical_scope": "scope:general",
    "polities_touched": [],
    "role_in_argument": "role:claim",
    "claim_type": "state-formation",
    "theory_school": "bellicist",
}

_AXIS_COLUMN_INDEX = {
    name: idx + 1
    for idx, name in enumerate(SHEET_COLUMNS)
    if name in ("field", "empirical_scope", "claim_type", "theory_school")
}


def _seed_eval_fixture(gold_dir: Path) -> None:
    chunks_dir = gold_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    ordered = {key: EVAL_TAGGER_RECORD.get(key) for key in RECORD_FIELDS}
    (chunks_dir / f"{EVAL_TAGGER_RECORD['chunk_id']}.json").write_text(
        json.dumps(ordered, indent=2, sort_keys=True), encoding="utf-8"
    )

    vocabularies = _axis_vocabularies(str(DEFAULT_DOMAIN_DIR))
    workbook = build_workbook([EVAL_TAGGER_RECORD], vocabularies)
    worksheet = workbook.worksheets[0]
    for axis, column in _AXIS_COLUMN_INDEX.items():
        worksheet.cell(row=2, column=column).value = EVAL_TAGGER_RECORD[axis]

    labels_dir = gold_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    workbook.save(labels_dir / "label_sheet.xlsx")


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


# ---------------------------------------------------------------------------
# tag
# ---------------------------------------------------------------------------


def test_tag_pass_writes_one_record_per_source_not_per_chunk(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "stub")
    trees_dir = tmp_path / "trees"
    chunks_dir = tmp_path / "chunks"
    logs_root = tmp_path / "logs"
    monkeypatch.setattr(extract_mod, "TREES_DIR", trees_dir)
    # `axial.chunk._resolve_chunk_inputs` calls `tree_path(source_id)` with
    # no explicit `trees_dir` arg, so it resolves the DEFAULT parameter
    # value bound at chunk.py's import time -- monkeypatching
    # `extract_mod.TREES_DIR` alone does not reach it (unlike `extract()`
    # itself, which passes `TREES_DIR` explicitly). Patch chunk.py's own
    # `tree_path` binding directly instead.
    monkeypatch.setattr(chunk_mod, "tree_path", lambda source_id: trees_dir / f"{source_id}.json")
    monkeypatch.setattr(chunk_mod, "_default_chunks_dir", lambda config_path: chunks_dir)
    source_id = _place_tree_fixture(trees_dir)
    _place_chunk_fixture(chunks_dir)

    exit_code = _tag(
        str(FIXTURE_PDF), str(DEFAULT_DOMAIN_DIR), root=logs_root, clock=lambda: FIXED_TS
    )

    assert exit_code == 0

    run_dir = logs_root / f"tag-{FIXED_TS}"
    raw_text = (run_dir / "run.jsonl").read_text(encoding="utf-8")
    record = _one_record(run_dir / "run.jsonl")
    assert record["source_id"] == source_id
    assert record["pass"] == "tag"
    assert record["model"] == "stub"
    assert record["status"] == "ok"
    assert record["duration_sec"] >= 0
    assert record["error"] is None

    assert FIXTURE_PROSE_SNIPPET not in raw_text

    captured = capsys.readouterr()
    tagged = json.loads(captured.out.strip())
    assert tagged, "expected the tag CLI's own stdout print (tagged records) to be unchanged"


def test_tag_pass_error_path_records_status_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AXIAL_LLM_PROVIDER", "stub")
    logs_root = tmp_path / "logs"
    missing_source = tmp_path / "does-not-exist.pdf"

    exit_code = _tag(
        str(missing_source), str(DEFAULT_DOMAIN_DIR), root=logs_root, clock=lambda: FIXED_TS
    )

    assert exit_code == 1
    run_dir = logs_root / f"tag-{FIXED_TS}"
    record = _one_record(run_dir / "run.jsonl")
    assert record["pass"] == "tag"
    assert record["status"] == "error"
    assert record["error"]
    assert record["duration_sec"] >= 0


# ---------------------------------------------------------------------------
# eval -- see the module docstring's two documented deviations
# ---------------------------------------------------------------------------


def test_eval_pass_writes_one_record_with_null_model(monkeypatch, tmp_path, capsys):
    gold_dir = tmp_path / "gold"
    logs_root = tmp_path / "logs"
    monkeypatch.setattr(eval_mod, "_default_gold_dir", lambda config_path: gold_dir)
    _seed_eval_fixture(gold_dir)

    exit_code = _eval(root=logs_root, clock=lambda: FIXED_TS)

    assert exit_code == 0

    run_dir = logs_root / f"eval-{FIXED_TS}"
    record = _one_record(run_dir / "run.jsonl")
    assert record["source_id"] == ""
    assert record["pass"] == "eval"
    assert record["model"] is None, "eval makes no LLM call -- see module docstring deviation 1"
    assert record["status"] == "ok"
    assert record["duration_sec"] >= 0
    assert record["error"] is None

    captured = capsys.readouterr()
    assert captured.out.strip(), "expected the eval CLI's own stdout print to be unchanged"


def test_eval_pass_error_path_records_status_error(monkeypatch, tmp_path):
    gold_dir = tmp_path / "gold"  # deliberately empty: no chunks, no sheet
    logs_root = tmp_path / "logs"
    monkeypatch.setattr(eval_mod, "_default_gold_dir", lambda config_path: gold_dir)

    exit_code = _eval(root=logs_root, clock=lambda: FIXED_TS)

    assert exit_code == 1
    run_dir = logs_root / f"eval-{FIXED_TS}"
    record = _one_record(run_dir / "run.jsonl")
    assert record["pass"] == "eval"
    assert record["model"] is None
    assert record["status"] == "error"
    assert record["error"]
    assert record["duration_sec"] >= 0
