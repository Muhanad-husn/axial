"""Unit tests for `Worker.run_once` (claim -> run -> terminal record) and
for `run_ask_job`'s in-process wiring to `axial.ask.engine.ask`. The
concurrent-claim and killed-worker acceptance tests live in their own files;
this file proves the worker's own lifecycle and the third "done when":
a completed job records the corpus pin it ran against."""

from __future__ import annotations

from pathlib import Path

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief
from axial.service import worker as worker_mod
from axial.service.jobs import DONE, FAILED, JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job

# The snapshot a worker process is bound to (issue #684). Built directly
# rather than published, because these two tests are about `run_ask_job`'s
# own wiring, not about what a published snapshot contains -- that is
# `test_snapshot.py`'s job.
_SNAPSHOT = Snapshot(
    root=Path("data/snapshots/v1"),
    version="v1",
    corpus_pin="sim-2026-08-10",
    map_pin="a1b2c3",
    sources=("alpha-0123456789ab",),
    built_at="2026-08-10T00:00:00Z",
)


def test_run_once_returns_false_when_queue_is_empty(job_store: JobStore):
    worker = Worker(job_store, run_job=lambda job: ("ref", "pin", False, None, None))

    assert worker.run_once() is False


def test_run_once_completes_a_job_and_records_its_corpus_pin(job_store: JobStore):
    job_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
    )
    calls = []

    def fake_run_job(job):
        calls.append(job["id"])
        return "data/analyses/xyz.json", "sim-2026-08-10", False, 0.13, 150

    worker = Worker(job_store, run_job=fake_run_job, heartbeat_interval=0.05)

    claimed_something = worker.run_once()

    assert claimed_something is True
    assert calls == [job_id]
    row = job_store.get(job_id)
    assert row["state"] == DONE
    assert row["corpus_pin"] == "sim-2026-08-10"
    assert row["result_ref"] == "data/analyses/xyz.json"
    assert row["cached"] is False
    assert row["cost_usd"] == 0.13
    assert row["tokens"] == 150


def test_run_once_records_a_raised_error_as_failed(job_store: JobStore):
    job_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
    )

    def failing_run_job(job):
        raise RuntimeError("engine blew up")

    worker = Worker(job_store, run_job=failing_run_job)

    assert worker.run_once() is True
    row = job_store.get(job_id)
    assert row["state"] == FAILED
    assert "engine blew up" in row["error"]


def test_run_ask_job_calls_the_in_process_ask_engine_not_a_subprocess(
    monkeypatch, job_store: JobStore
):
    """The issue's own requirement: the worker calls the existing ask path
    in-process, never a CLI subprocess. Proved by monkeypatching
    `axial.service.worker.run_ask` (the imported `axial.ask.engine.ask`
    symbol) and asserting `run_ask_job` calls it directly with the job's
    payload, no `subprocess`/CLI involved."""
    seen = {}

    def fake_ask(question, case, *, client, session_id=None, on_event=None, **kwargs):
        seen["question"] = question
        seen["case"] = case
        seen["session_id"] = session_id
        seen["map_pin"] = kwargs.get("map_pin")
        seen["analyses_dir"] = kwargs.get("analyses_dir")
        brief = Brief(brief_id="b1", case=case, request=question)
        result = BriefRunResult(
            record={"corpus_pin": "sim-2026-08-10"},
            path=Path("data/analyses/b1.json"),
            markdown_path=Path("data/analyses/b1.md"),
            report={},
            report_path=Path("data/runs/b1.json"),
        )
        return Turn(
            session_id="s1", turn_index=1, question=question, case=case, brief=brief, result=result
        )

    monkeypatch.setattr(worker_mod, "run_ask", fake_ask)

    job_id = job_store.enqueue(
        kind="ask",
        principal="analyst-1",
        payload={"question": "Who led the uprising?", "case": "Syria", "session_id": "s1"},
    )
    job = job_store.claim()
    result_ref, corpus_pin, cached, cost_usd, tokens = run_ask_job(
        job, client=object(), store=job_store, snapshot=_SNAPSHOT, work_dir=Path("data/work")
    )

    assert seen["question"] == "Who led the uprising?"
    assert seen["case"] == "Syria"
    assert seen["session_id"] == "s1"
    assert job["id"] == job_id
    # The snapshot supplies what binding cannot: the map pin, and a
    # writable place for the analyst's own records outside the read-only
    # snapshot (issue #684).
    assert seen["map_pin"] == "a1b2c3"
    # Scoped to the job's own principal (issue #685): "analyst-1" is not
    # the default local principal, so it gets its own subdirectory rather
    # than landing directly under `work_dir`.
    assert seen["analyses_dir"] == Path("data/work/analyses/analyst-1")
    assert corpus_pin == "sim-2026-08-10"
    # No cache was passed in (issue #686): always a miss, always generates,
    # and the record above carries no `cost` key so it is unknown, not zero.
    assert cached is False
    assert cost_usd is None
    # Issue #724: the record carries no `cost` block, so the token count is
    # unknown too -- the same null-preserving rule as `cost_usd`.
    assert tokens is None
    assert result_ref


def test_run_ask_job_wires_on_event_to_the_store(monkeypatch, job_store: JobStore):
    """The event-persistence half of #683: `run_ask_job` must pass an
    `on_event` into `axial.ask.engine.ask` that lands in `job_events` under
    this job's own id, since that table is what `GET /asks/{id}/events`
    reads from."""

    def fake_ask(question, case, *, client, session_id=None, on_event=None, **kwargs):
        on_event("interrogating the question", {"stage": "interrogate"})
        on_event("writing the answer", {"stage": "synthesize"})
        brief = Brief(brief_id="b1", case=case, request=question)
        result = BriefRunResult(
            record={"corpus_pin": "sim-2026-08-10"},
            path=Path("data/analyses/b1.json"),
            markdown_path=Path("data/analyses/b1.md"),
            report={},
            report_path=Path("data/runs/b1.json"),
        )
        return Turn(
            session_id="s1", turn_index=1, question=question, case=case, brief=brief, result=result
        )

    monkeypatch.setattr(worker_mod, "run_ask", fake_ask)

    job_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
    )
    job = job_store.claim()
    run_ask_job(
        job, client=object(), store=job_store, snapshot=_SNAPSHOT, work_dir=Path("data/work")
    )

    events = job_store.events_since(job_id)
    assert [event["message"] for event in events] == [
        "interrogating the question",
        "writing the answer",
    ]
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0]["detail"] == {"stage": "interrogate"}


def test_two_principals_asking_against_the_same_worker_get_separate_analyses_dirs(
    monkeypatch, job_store: JobStore
):
    """The plan's own "done when" for paths.py's per-principal scoping
    (#685 step 3): two principals querying the same worker get separate
    saved work under the same `work_dir`, the same corpus."""
    seen_dirs: list[Path] = []

    def fake_ask(question, case, *, client, session_id=None, on_event=None, **kwargs):
        seen_dirs.append(kwargs["analyses_dir"])
        brief = Brief(brief_id="b1", case=case, request=question)
        result = BriefRunResult(
            record={"corpus_pin": "sim-2026-08-10"},
            path=Path("data/analyses/b1.json"),
            markdown_path=Path("data/analyses/b1.md"),
            report={},
            report_path=Path("data/runs/b1.json"),
        )
        return Turn(
            session_id="s1", turn_index=1, question=question, case=case, brief=brief, result=result
        )

    monkeypatch.setattr(worker_mod, "run_ask", fake_ask)

    for principal in ("alice", "bob"):
        job_store.enqueue(
            kind="ask", principal=principal, payload={"question": "Q", "case": "Syria"}
        )
        job = job_store.claim()
        run_ask_job(
            job, client=object(), store=job_store, snapshot=_SNAPSHOT, work_dir=Path("data/work")
        )

    assert seen_dirs == [Path("data/work/analyses/alice"), Path("data/work/analyses/bob")]
    assert seen_dirs[0] != seen_dirs[1]
