"""Unit tests for `JobStore`'s claim/heartbeat/complete/fail/reclaim
lifecycle in isolation, over a real Postgres (see conftest.py) -- the
concurrent-claim and killed-worker acceptance tests live in
test_concurrent_claims.py and test_worker_reclaim.py."""

from __future__ import annotations

import time

from axial.service.jobs import DONE, FAILED, QUEUED, RUNNING, JobStore


def test_claim_moves_a_queued_job_to_running(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})

    claimed = job_store.claim()

    assert claimed is not None
    assert claimed["id"] == job_id
    assert claimed["state"] == RUNNING
    assert claimed["claimed_at"] is not None
    assert claimed["heartbeat_at"] is not None

    row = job_store.get(job_id)
    assert row["state"] == RUNNING


def test_claim_returns_none_when_queue_is_empty(job_store: JobStore):
    assert job_store.claim() is None


def test_claim_ignores_jobs_already_running(job_store: JobStore):
    job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    job_store.claim()

    assert job_store.claim() is None


def test_heartbeat_advances_heartbeat_at(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    claimed = job_store.claim()
    first_beat = claimed["heartbeat_at"]

    time.sleep(0.05)
    job_store.heartbeat(job_id)

    row = job_store.get(job_id)
    assert row["heartbeat_at"] > first_beat


def test_complete_records_result_ref_and_corpus_pin(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    job_store.claim()

    job_store.complete(job_id, result_ref="data/analyses/abc.json", corpus_pin="sim-2026-08-10")

    row = job_store.get(job_id)
    assert row["state"] == DONE
    assert row["result_ref"] == "data/analyses/abc.json"
    assert row["corpus_pin"] == "sim-2026-08-10"
    assert row["finished_at"] is not None


def test_fail_records_the_error(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    job_store.claim()

    job_store.fail(job_id, error="boom")

    row = job_store.get(job_id)
    assert row["state"] == FAILED
    assert row["error"] == "boom"
    assert row["finished_at"] is not None


def test_reclaim_stale_returns_a_running_job_to_queued(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    job_store.claim()
    time.sleep(0.2)

    reclaimed = job_store.reclaim_stale(stale_after_seconds=0.1)

    assert reclaimed == 1
    row = job_store.get(job_id)
    assert row["state"] == QUEUED
    assert row["claimed_at"] is None
    assert row["heartbeat_at"] is None


def test_reclaim_stale_leaves_a_fresh_running_job_alone(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    job_store.claim()

    reclaimed = job_store.reclaim_stale(stale_after_seconds=60.0)

    assert reclaimed == 0
    row = job_store.get(job_id)
    assert row["state"] == RUNNING


def test_a_reclaimed_job_is_claimable_again(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={"q": "x"})
    job_store.claim()
    time.sleep(0.2)
    job_store.reclaim_stale(stale_after_seconds=0.1)

    reclaimed_job = job_store.claim()

    assert reclaimed_job is not None
    assert reclaimed_job["id"] == job_id
    assert reclaimed_job["state"] == RUNNING
