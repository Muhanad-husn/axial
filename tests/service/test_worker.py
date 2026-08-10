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
from axial.service.worker import Worker, run_ask_job


def test_run_once_returns_false_when_queue_is_empty(job_store: JobStore):
    worker = Worker(job_store, run_job=lambda job: ("ref", "pin"))

    assert worker.run_once() is False


def test_run_once_completes_a_job_and_records_its_corpus_pin(job_store: JobStore):
    job_id = job_store.enqueue(
        kind="ask", principal="analyst-1", payload={"question": "Q", "case": "Syria"}
    )
    calls = []

    def fake_run_job(job):
        calls.append(job["id"])
        return "data/analyses/xyz.json", "sim-2026-08-10"

    worker = Worker(job_store, run_job=fake_run_job, heartbeat_interval=0.05)

    claimed_something = worker.run_once()

    assert claimed_something is True
    assert calls == [job_id]
    row = job_store.get(job_id)
    assert row["state"] == DONE
    assert row["corpus_pin"] == "sim-2026-08-10"
    assert row["result_ref"] == "data/analyses/xyz.json"


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

    def fake_ask(
        question, case, *, client, session_id=None, lens=None, weights=None, on_event=None
    ):
        seen["question"] = question
        seen["case"] = case
        seen["session_id"] = session_id
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
    result_ref, corpus_pin = run_ask_job(job, client=object(), store=job_store)

    assert seen["question"] == "Who led the uprising?"
    assert seen["case"] == "Syria"
    assert seen["session_id"] == "s1"
    assert job["id"] == job_id


def test_run_ask_job_wires_on_event_to_the_store(monkeypatch, job_store: JobStore):
    """The event-persistence half of #683: `run_ask_job` must pass an
    `on_event` into `axial.ask.engine.ask` that lands in `job_events` under
    this job's own id, since that table is what `GET /asks/{id}/events`
    reads from."""

    def fake_ask(
        question, case, *, client, session_id=None, lens=None, weights=None, on_event=None
    ):
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
    run_ask_job(job, client=object(), store=job_store)

    events = job_store.events_since(job_id)
    assert [event["message"] for event in events] == [
        "interrogating the question",
        "writing the answer",
    ]
    assert [event["seq"] for event in events] == [1, 2]
    assert events[0]["detail"] == {"stage": "interrogate"}
