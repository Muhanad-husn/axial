"""Outer acceptance test for issue #526 (CLI-1): `axial.run.run_pass` wired
into the run-log seam (`axial.runlog.run_context`) -- the operator can watch
a corpus-wide run happen and read what it cost.

Restates the issue's own acceptance bar as observations on one real `axial
run chunk --worklist <worklist>` invocation:

  - A live progress line appears on stdout at each source's own START, not
    only once it finishes -- the "progress appears while a source runs" bar.
  - The run directory `axial.runlog.run_context` opens carries `meta.json`
    (status `"ok"` once the process has exited, a `corpus_pin` naming the
    worklist) and `heartbeat.json` -- both readable by this test process
    (a separate process from the one that ran the pass), proving "a run in
    progress is fully readable from a separate process" for the artifacts
    that persist past the run's own exit.
  - `events.jsonl` carries a `source_start`/`source_finish` pair per
    attempted source -- finer than the existing one-per-source `run.jsonl`.
  - `run.jsonl` still carries exactly one record per attempted source
    (unchanged granularity), each with a real, non-negative `duration_sec`.
  - `report.json` -- the end-of-run report -- names both sources, sums to
    the same OK/FAIL/SKIP counts as the printed tally, and carries a
    `tokens_and_cost`/`outstanding`/`failures_by_cause` shape re-readable
    long after the run finished.
  - None of `axial.run`'s existing contracts moved: the printed TSV table,
    the tally line, and the resume ledger are all still exactly what
    tests/test_run_resume.py itself already pins.

Pass choice -- `chunk`, mirroring tests/test_run_resume.py's own scenario 1
-----------------------------------------------------------------------
`chunk` is LLM-free (recursive/structural chunking) and succeeds
deterministically once a source's tree is pre-placed, so both worklist
sources genuinely run (not skipped -- `chunk` has no file-exists
done-predicate) without any docling or model call, keeping this test fast.

Fixtures -- reused verbatim from tests/test_run_resume.py, no new content
-----------------------------------------------------------------------
tests/fixtures/extract/prose_and_table.pdf and
tests/fixtures/envelope/thesis_paper.pdf, each paired with its own
already-committed extraction-tree fixture, pre-placed at
data/trees/<source_id>.json under the isolated cwd.

Test hygiene: every path this test writes lives under `isolated_vault_root`
(tests/conftest.py, issue #68) -- a fresh tmp_path-backed staging root
outside this repo entirely. No real data/ directory is ever read, moved, or
written by this test.
"""

from __future__ import annotations

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
SOURCE_2_OK = FIXTURES_ENVELOPE / "thesis_paper.pdf"
SOURCE_2_TREE = FIXTURES_ENVELOPE / "thesis_paper_tree.json"

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"


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


def _place_tree_fixture(source_path: Path, tree_fixture: Path, root: Path) -> str:
    source_id = compute_source_id(source_path)
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_bytes(tree_fixture.read_bytes())
    return source_id


def _write_worklist(path: Path, source_paths: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(p) for p in source_paths) + "\n", encoding="utf-8")


def _find_run_dir(pass_name: str) -> Path:
    """The run directory the subprocess just wrote under `AXIAL_LOGS_ROOT`
    -- `tests/conftest.py`'s own autouse `_isolate_runlog_root` fixture
    redirects that env var to a fresh per-test tmp dir and reaches the
    subprocess too (`_run_axial`'s `env=dict(os.environ)` snapshot), so the
    run never lands under `root/data/logs` at all in this suite."""
    logs_root = Path(os.environ["AXIAL_LOGS_ROOT"])
    candidates = sorted(logs_root.glob(f"run-{pass_name}-*"))
    assert len(candidates) == 1, (
        f"expected exactly one run dir under {logs_root}, got {candidates!r}"
    )
    return candidates[0]


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_run_pass_writes_the_run_log_seam_with_live_progress_and_a_report(isolated_vault_root):
    root = isolated_vault_root
    source_id_1 = _place_tree_fixture(SOURCE_1_OK, SOURCE_1_TREE, root)
    source_id_2 = _place_tree_fixture(SOURCE_2_OK, SOURCE_2_TREE, root)

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_1_OK, SOURCE_2_OK])

    result = _run_axial(["run", "chunk", "--worklist", str(worklist_path)], "stub", cwd=root)

    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    # --- existing contracts (tests/test_run_resume.py) are unmoved --------
    assert "OK" in result.stdout and result.stdout.count("OK") >= 2
    assert "run: pass=chunk total=2 ok=2 skipped=0 failed=0" in result.stdout

    # --- live progress: a "progress:" line appears for each source, BEFORE
    # its own outcome row -- proving something prints while a source is
    # running, not only once it is done. ------------------------------------
    progress_lines = [line for line in result.stdout.splitlines() if line.startswith("progress:")]
    assert len(progress_lines) == 2, (
        f"expected one progress line per source, got: {progress_lines!r}"
    )
    assert "1/2" in progress_lines[0] and "2/2" in progress_lines[1]
    first_progress_index = result.stdout.index(progress_lines[0])
    first_ok_row_index = result.stdout.index("\tOK\t") if "\tOK\t" in result.stdout else -1
    assert first_ok_row_index == -1 or first_progress_index < first_ok_row_index

    # --- the run directory is readable from THIS (separate) process -------
    run_dir = _find_run_dir("chunk")

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "ok"
    assert meta["finished_at"] is not None
    assert meta["corpus_pin"] == f"worklist:{worklist_path}"

    heartbeat = json.loads((run_dir / "heartbeat.json").read_text(encoding="utf-8"))
    assert "updated_at" in heartbeat

    # --- events.jsonl: finer than run.jsonl, a start/finish pair per source
    events = _read_jsonl(run_dir / "events.jsonl")
    event_kinds_by_source = {}
    for event in events:
        event_kinds_by_source.setdefault(event["source_id"], []).append(event["kind"])
    assert event_kinds_by_source[source_id_1] == ["source_start", "source_finish"]
    assert event_kinds_by_source[source_id_2] == ["source_start", "source_finish"]

    # --- run.jsonl: unchanged one-record-per-source granularity -----------
    records = _read_jsonl(run_dir / "run.jsonl")
    assert len(records) == 2
    records_by_source = {record["source_id"]: record for record in records}
    for source_id in (source_id_1, source_id_2):
        record = records_by_source[source_id]
        assert record["pass"] == "chunk"
        assert record["status"] == "ok"
        assert record["error"] is None
        assert isinstance(record["duration_sec"], (int, float)) and record["duration_sec"] >= 0
        # Issue #734: `chunk` is LLM-free by design (module docstring), so
        # this pass never captures usage at all -- every new field reads as
        # unmeasured (`None`), never a fabricated zero.
        assert record["prompt_tokens"] is None
        assert record["completion_tokens"] is None
        assert record["total_tokens"] is None
        assert record["usd"] is None

    # --- report.json: the end-of-run report, re-readable after the fact ---
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    assert report["pass_name"] == "chunk"
    assert report["total"] == 2
    assert report["ok_count"] == 2
    assert report["fail_count"] == 0
    assert report["skip_count"] == 0
    assert report["outstanding"] == []
    assert report["failures_by_cause"] == {}
    assert {entry["source_id"] for entry in report["per_source"]} == {source_id_1, source_id_2}
    assert all(entry["duration_sec"] is not None for entry in report["per_source"])
    assert (
        "by_pass" in report["tokens_and_cost"] and "chunk" in report["tokens_and_cost"]["by_pass"]
    )


def test_run_pass_records_a_real_model_id_when_a_source_actually_calls_the_llm(
    isolated_vault_root,
):
    """`chunk` above is LLM-free by design, so its own `record()`s prove
    nothing about the model-detection path itself (issue #526: a model must
    never be fabricated for a pass/source that made no call, mirroring
    tests/test_runlog_passes.py's own `eval` precedent). `envelope` DOES
    call the client, so this is the positive case: a fresh (uncached)
    envelope run must report the stub provider's real model id, read from
    the same before/after `usage_for_pass` comparison the live progress
    line and the report's own cost figure already rely on."""
    root = isolated_vault_root
    source_id = _place_tree_fixture(SOURCE_1_OK, SOURCE_1_TREE, root)

    worklist_path = root / "worklist.txt"
    _write_worklist(worklist_path, [SOURCE_1_OK])

    result = _run_axial(["run", "envelope", "--worklist", str(worklist_path)], "stub", cwd=root)

    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )

    run_dir = _find_run_dir("envelope")
    records = _read_jsonl(run_dir / "run.jsonl")
    assert len(records) == 1
    record = records[0]
    assert record["source_id"] == source_id
    assert record["status"] == "ok"
    assert record["model"] == "stub", "expected the stub provider's real model id, not null"
    # Issue #734: the stub client's fixed per-call usage
    # (`axial.llm._STUB_USAGE_PER_CALL`) round-trips as this source's own
    # token counts. `"stub"` carries no `PRICE_TABLE_USD_PER_1K` entry, so
    # `usd` is null -- real tokens, an honestly unpriced cost, never a
    # silent $0.00 standing in for "nobody has priced this model".
    assert record["prompt_tokens"] == 100
    assert record["completion_tokens"] == 50
    assert record["total_tokens"] == 150
    assert record["usd"] is None
