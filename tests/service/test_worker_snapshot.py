"""Acceptance tests for issue #684's first two "done when" clauses:

- publishing a new snapshot while a job is running leaves that job's result
  computed entirely against the old one, and its recorded pin says so;
- two workers on two different snapshots can serve the same queue.

Both are proved with real worker processes (`_snapshot_worker.py`), because
a snapshot is bound with `os.chdir` and two objects in one process cannot
have two working directories. No model is called: the harness stubs the
engine and reads the corpus off disk.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief
from axial.service import worker as worker_mod
from axial.service.jobs import DONE, FAILED, JobStore
from axial.service.snapshot import Snapshot, SnapshotPinMismatchError, publish
from axial.service.worker import run_ask_job
from _corpus import PIN_NAME, build_corpus_root

_HARNESS = Path(__file__).parent / "_snapshot_worker.py"
_V2_PIN = "sim-test-v2"


def _wait_for(path: Path, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} never appeared")


def _start_worker(dsn: str, snapshot: Snapshot, work_dir: Path, gate: Path | None = None):
    argv = [sys.executable, str(_HARNESS), dsn, str(snapshot.root), str(work_dir)]
    if gate is not None:
        gate.mkdir(parents=True, exist_ok=True)
        argv.append(str(gate))
    return subprocess.Popen(argv)


def _result(row: dict) -> dict:
    return json.loads(Path(row["result_ref"]).read_text(encoding="utf-8"))


def test_publishing_mid_job_leaves_the_running_job_on_the_old_snapshot(
    job_store: JobStore, postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    operator = build_corpus_root(tmp_path / "operator", passage="the first passage")
    monkeypatch.chdir(operator)
    snapshots_dir = tmp_path / "snapshots"
    v1 = publish("v1", snapshots_dir=snapshots_dir)

    job_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
    )
    gate = tmp_path / "gate"
    proc = _start_worker(postgres_dsn, v1, tmp_path / "work", gate=gate)
    try:
        _wait_for(gate / "claimed")

        # The operator rebuilds and publishes, mid-query.
        build_corpus_root(operator, passage="a second, later passage", pin=_V2_PIN)
        v2 = publish("v2", snapshots_dir=snapshots_dir)
        assert v2.corpus_pin == _V2_PIN

        (gate / "go").write_text("1", encoding="utf-8")
        assert proc.wait(timeout=60) == 0
    finally:
        if proc.poll() is None:  # pragma: no cover - only on a failed run
            proc.kill()
            proc.wait(timeout=10)

    row = job_store.get(job_id)
    assert row["state"] == DONE
    assert row["corpus_pin"] == PIN_NAME

    # Computed ENTIRELY against v1: what the job read after the publish is
    # byte-identical to what it read before it.
    result = _result(row)
    assert result["first"] == result["second"]
    assert result["first"]["pin"] == PIN_NAME
    assert result["first"]["passage"] == "the first passage"


def test_two_workers_on_two_snapshots_drain_the_same_queue(
    job_store: JobStore, postgres_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    operator = build_corpus_root(tmp_path / "operator", passage="the first passage")
    monkeypatch.chdir(operator)
    snapshots_dir = tmp_path / "snapshots"
    v1 = publish("v1", snapshots_dir=snapshots_dir)

    build_corpus_root(operator, passage="a second, later passage", pin=_V2_PIN)
    v2 = publish("v2", snapshots_dir=snapshots_dir)

    for _ in range(2):
        job_store.enqueue(
            kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
        )

    procs = [
        _start_worker(postgres_dsn, v1, tmp_path / "work-v1"),
        _start_worker(postgres_dsn, v2, tmp_path / "work-v2"),
    ]
    try:
        for proc in procs:
            assert proc.wait(timeout=60) == 0
    finally:
        for proc in procs:
            if proc.poll() is None:  # pragma: no cover - only on a failed run
                proc.kill()
                proc.wait(timeout=10)

    rows = job_store.list_for_principal("analyst-1")
    assert len(rows) == 2
    assert [row["state"] for row in rows] == [DONE, DONE]
    assert {row["corpus_pin"] for row in rows} == {PIN_NAME, _V2_PIN}

    # Each job's recorded pin is its own worker's snapshot -- and the
    # passage it read comes from that same snapshot, not the other one.
    passage_by_pin = {PIN_NAME: "the first passage", _V2_PIN: "a second, later passage"}
    for row in rows:
        assert _result(row)["second"]["passage"] == passage_by_pin[row["corpus_pin"]]


def _fake_turn(pin: str, path: Path) -> Turn:
    brief = Brief(brief_id="b1", case="Syria", request="Q")
    return Turn(
        session_id="s1",
        turn_index=1,
        question="Q",
        case="Syria",
        brief=brief,
        result=BriefRunResult(
            record={"corpus_pin": pin},
            path=path,
            markdown_path=path,
            report={},
            report_path=path,
        ),
    )


def test_run_ask_job_records_the_snapshots_own_pin(
    job_store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """One source of truth: the pin the row carries is the snapshot's, and
    the snapshot is also where `resolve_pin_id` reads from once bound."""
    monkeypatch.chdir(build_corpus_root(tmp_path / "operator"))
    snapshot = publish("v1", snapshots_dir=tmp_path / "snapshots")

    monkeypatch.setattr(
        worker_mod,
        "run_ask",
        lambda question, case, **kwargs: _fake_turn(PIN_NAME, tmp_path / "r.json"),
    )
    job_store.enqueue(kind="ask", principal="a", payload={"question": "Q", "case": "Syria"})
    job = job_store.claim()

    result_ref, corpus_pin, cached, cost_usd, tokens = run_ask_job(
        job, client=None, store=job_store, snapshot=snapshot, work_dir=tmp_path / "work"
    )

    assert corpus_pin == snapshot.corpus_pin == PIN_NAME
    assert result_ref == str(tmp_path / "r.json")
    assert cached is False


def test_a_job_whose_engine_read_a_different_corpus_is_refused_not_mislabelled(
    job_store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The binding is meant to be total; if it ever leaks, the job must fail
    loudly rather than record the snapshot's pin over an answer that was
    computed from somewhere else."""
    monkeypatch.chdir(build_corpus_root(tmp_path / "operator"))
    snapshot = publish("v1", snapshots_dir=tmp_path / "snapshots")

    monkeypatch.setattr(
        worker_mod,
        "run_ask",
        lambda question, case, **kwargs: _fake_turn("some-other-pin", tmp_path / "r.json"),
    )
    job_id = job_store.enqueue(
        kind="ask", principal="a", payload={"question": "Q", "case": "Syria"}
    )
    job = job_store.claim()

    with pytest.raises(SnapshotPinMismatchError):
        run_ask_job(
            job, client=None, store=job_store, snapshot=snapshot, work_dir=tmp_path / "work"
        )

    job_store.fail(job_id, error="x")
    assert job_store.get(job_id)["state"] == FAILED
