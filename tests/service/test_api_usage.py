"""Acceptance tests for issue #724's second "done when": `GET /me/usage`
reports cost and tokens for the session and for the month to date, per
principal, plus quota state.

Two rules from the founder's own comment are pinned here as acceptance
criteria, not niceties: a `null` `cost_usd` is unknown and must never be
summed as `$0.00`, and `count_since` excludes a cached row -- "asks made"
and "asks charged against quota" are two different counts, and this
endpoint serves both, named so neither can be mislabelled as the other.
"""

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


def _submit_and_complete(
    client: TestClient,
    job_store: JobStore,
    *,
    cost_usd: float | None,
    tokens: int | None,
    cached: bool = False,
    session_id: str | None = None,
) -> str:
    payload = {"case": "Syria", "request": "Q"}
    if session_id is not None:
        payload["session_id"] = session_id
    job_id = client.post("/asks", json=payload).json()["id"]
    job_store.claim()
    job_store.complete(
        job_id, result_ref="x", corpus_pin="p", cached=cached, cost_usd=cost_usd, tokens=tokens
    )
    return job_id


def test_usage_with_no_asks_reports_unknown_cost_and_zero_counts(client):
    response = client.get("/me/usage")

    assert response.status_code == 200
    body = response.json()
    assert body["principal"] == _PRINCIPAL
    assert body["session"] is None
    assert body["month_to_date"] == {
        "cost_usd": None,
        "tokens": None,
        "asks_made": 0,
        "asks_charged": 0,
    }


def test_month_to_date_sums_cost_and_tokens_across_finished_asks(client, job_store: JobStore):
    _submit_and_complete(client, job_store, cost_usd=0.10, tokens=400)
    _submit_and_complete(client, job_store, cost_usd=0.25, tokens=600)

    month = client.get("/me/usage").json()["month_to_date"]

    assert month["cost_usd"] == pytest.approx(0.35)
    assert month["tokens"] == 1000
    assert month["asks_made"] == 2
    assert month["asks_charged"] == 2


def test_a_null_cost_is_never_summed_as_zero(client, job_store: JobStore):
    """The founder's own rule, verbatim: an unpriced model's cost is
    unknown, not a real zero -- mixed with a known cost, the sum reports
    only what is known, exactly like `JobStore.sum_spend_for_principal`
    itself (`test_quotas.py`), never coercing the unknown row to `0.0`."""
    _submit_and_complete(client, job_store, cost_usd=0.30, tokens=None)
    _submit_and_complete(client, job_store, cost_usd=None, tokens=None)

    month = client.get("/me/usage").json()["month_to_date"]

    assert month["cost_usd"] == pytest.approx(0.30)
    assert month["asks_made"] == 2


def test_every_ask_unpriced_reports_cost_as_none_not_zero(client, job_store: JobStore):
    _submit_and_complete(client, job_store, cost_usd=None, tokens=None)

    month = client.get("/me/usage").json()["month_to_date"]

    assert month["cost_usd"] is None
    assert month["tokens"] is None
    assert month["asks_made"] == 1
    # No cost is known, but the ask still happened.
    assert month["asks_charged"] == 1


def test_a_cached_ask_counts_as_made_but_not_as_charged(client, job_store: JobStore):
    _submit_and_complete(client, job_store, cost_usd=0.20, tokens=500)
    _submit_and_complete(client, job_store, cost_usd=0.0, tokens=0, cached=True)

    month = client.get("/me/usage").json()["month_to_date"]

    # Both asks were made...
    assert month["asks_made"] == 2
    # ...but only the real generation was charged against quota.
    assert month["asks_charged"] == 1
    # The cache hit's own cost/tokens are real, known zeros -- they still
    # add nothing to the sum, but for a different reason than "unknown".
    assert month["cost_usd"] == pytest.approx(0.20)
    assert month["tokens"] == 500


def test_no_session_block_when_no_session_id_is_given(client, job_store: JobStore):
    _submit_and_complete(client, job_store, cost_usd=0.10, tokens=100, session_id="s1")

    body = client.get("/me/usage").json()

    assert body["session"] is None


def test_session_block_scopes_to_the_named_session_only(client, job_store: JobStore):
    _submit_and_complete(client, job_store, cost_usd=0.10, tokens=100, session_id="s1")
    _submit_and_complete(client, job_store, cost_usd=0.50, tokens=900, session_id="s2")
    _submit_and_complete(client, job_store, cost_usd=0.05, tokens=10)  # no session at all

    body = client.get("/me/usage", params={"session_id": "s1"}).json()

    assert body["session"] == {
        "cost_usd": pytest.approx(0.10),
        "tokens": 100,
        "asks_made": 1,
        "asks_charged": 1,
    }
    # The session window is independent of the month-to-date one, which
    # still covers every ask this principal made this month.
    assert body["month_to_date"]["asks_made"] == 3


def test_quota_block_reuses_the_same_limits_and_reset_times_as_the_429_path(
    client, job_store: JobStore, quota_store: QuotaStore
):
    quota_store.set_limits(_PRINCIPAL, daily=5, monthly=50)
    _submit_and_complete(client, job_store, cost_usd=0.10, tokens=100)

    quota = client.get("/me/usage").json()["quota"]

    assert quota["day"]["limit"] == 5
    assert quota["day"]["used"] == 1
    assert quota["month"]["limit"] == 50
    assert quota["month"]["used"] == 1
    for window in ("day", "month"):
        reset_at = datetime.fromisoformat(quota[window]["reset_at"])
        assert reset_at.tzinfo is not None
        assert reset_at > datetime.now(timezone.utc)


def test_a_cache_hit_does_not_move_the_quota_used_count(
    client, job_store: JobStore, quota_store: QuotaStore
):
    quota_store.set_limits(_PRINCIPAL, daily=5, monthly=50)
    _submit_and_complete(client, job_store, cost_usd=0.0, tokens=0, cached=True)

    quota = client.get("/me/usage").json()["quota"]

    assert quota["day"]["used"] == 0
    assert quota["month"]["used"] == 0
