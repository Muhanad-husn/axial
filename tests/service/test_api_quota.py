"""Acceptance test for issue #686's third "done when": an analyst over
quota gets a clear `429` refusal naming the limit and the reset time, and
no job row is created -- checked BEFORE `store.enqueue`
(`axial.service.api._check_quota`)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from axial.service.api import create_app
from axial.service.jobs import JobStore
from axial.service.quotas import QuotaStore

_PRINCIPAL = "local-analyst"  # axial.context.DEFAULT_PRINCIPAL, unauthenticated default


@pytest.fixture
def client(job_store: JobStore, quota_store: QuotaStore):
    with TestClient(create_app(job_store, quota_store)) as test_client:
        yield test_client


def test_a_request_within_quota_is_accepted(client):
    response = client.post("/asks", json={"case": "Syria", "request": "Q1"})

    assert response.status_code == 202


def test_an_analyst_over_the_daily_quota_gets_a_429_naming_the_limit_and_reset_time(
    client, quota_store: QuotaStore
):
    quota_store.set_limits(_PRINCIPAL, daily=1, monthly=100)

    first = client.post("/asks", json={"case": "Syria", "request": "Q1"})
    assert first.status_code == 202

    second = client.post("/asks", json={"case": "Syria", "request": "Q2"})

    assert second.status_code == 429
    body = second.json()["detail"]
    assert body["window"] == "day"
    assert body["limit"] == 1
    # An exact, statable UTC instant a client can render verbatim --
    # parseable, and in the future.
    reset_at = datetime.fromisoformat(body["reset_at"])
    assert reset_at.tzinfo is not None
    assert reset_at > datetime.now(timezone.utc)
    assert "1" in body["message"] and "daily" in body["message"].lower()


def test_an_analyst_over_the_monthly_quota_gets_a_429_naming_that_window(
    client, quota_store: QuotaStore
):
    quota_store.set_limits(_PRINCIPAL, daily=100, monthly=1)

    first = client.post("/asks", json={"case": "Syria", "request": "Q1"})
    assert first.status_code == 202

    second = client.post("/asks", json={"case": "Syria", "request": "Q2"})

    assert second.status_code == 429
    assert second.json()["detail"]["window"] == "month"


def test_an_over_quota_request_creates_no_job_row(client, quota_store: QuotaStore, job_store):
    quota_store.set_limits(_PRINCIPAL, daily=1, monthly=100)
    client.post("/asks", json={"case": "Syria", "request": "Q1"})

    client.post("/asks", json={"case": "Syria", "request": "Q2"})

    assert len(job_store.list_for_principal(_PRINCIPAL)) == 1


def test_a_cache_hit_does_not_consume_quota(client, quota_store: QuotaStore, job_store: JobStore):
    quota_store.set_limits(_PRINCIPAL, daily=1, monthly=100)
    job_id = client.post("/asks", json={"case": "Syria", "request": "Q1"}).json()["id"]
    job_store.claim()
    job_store.complete(job_id, result_ref="x", corpus_pin="p", cached=True, cost_usd=0.0)

    second = client.post("/asks", json={"case": "Syria", "request": "Q2"})

    assert second.status_code == 202
