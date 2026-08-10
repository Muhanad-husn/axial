"""Unit tests for per-analyst quotas (issue #686): the `quotas` table's own
default/override behaviour, the calendar-UTC window helpers, and the two
`JobStore` methods a quota check and a spend query both read the `jobs`
table through -- `count_since` (excludes a `cached` row) and
`sum_spend_for_principal` (issue #686's fourth "done when": spend per
analyst is queryable, `None`-preserving)."""

from __future__ import annotations

from datetime import datetime, timezone

from axial.service.jobs import JobStore
from axial.service.quotas import (
    QuotaStore,
    next_daily_reset,
    next_monthly_reset,
    start_of_day_utc,
    start_of_month_utc,
)


def test_a_principal_with_no_row_gets_the_environment_default(quota_store: QuotaStore, monkeypatch):
    monkeypatch.setenv("AXIAL_QUOTA_ASKS_PER_DAY", "7")
    monkeypatch.setenv("AXIAL_QUOTA_ASKS_PER_MONTH", "70")

    limits = quota_store.limits_for("nobody-configured")

    assert limits.daily == 7
    assert limits.monthly == 70


def test_the_operator_can_raise_one_principals_limit_by_hand(quota_store: QuotaStore):
    quota_store.set_limits("heavy-user", daily=100, monthly=1000)

    assert quota_store.limits_for("heavy-user").daily == 100
    assert quota_store.limits_for("heavy-user").monthly == 1000
    # Nobody else is affected -- this is a per-principal override, not a
    # new global default.
    assert quota_store.limits_for("someone-else").daily != 100


def test_set_limits_can_be_called_again_to_change_an_existing_override(quota_store: QuotaStore):
    quota_store.set_limits("heavy-user", daily=100, monthly=1000)
    quota_store.set_limits("heavy-user", daily=5, monthly=50)

    assert quota_store.limits_for("heavy-user").daily == 5
    assert quota_store.limits_for("heavy-user").monthly == 50


def test_daily_and_monthly_windows_are_calendar_utc_not_rolling():
    now = datetime(2026, 8, 10, 23, 30, tzinfo=timezone.utc)

    assert start_of_day_utc(now) == datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    assert next_daily_reset(now) == datetime(2026, 8, 11, 0, 0, tzinfo=timezone.utc)
    assert start_of_month_utc(now) == datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
    assert next_monthly_reset(now) == datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)


def test_next_monthly_reset_rolls_over_the_year():
    now = datetime(2026, 12, 15, tzinfo=timezone.utc)

    assert next_monthly_reset(now) == datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_count_since_excludes_a_cached_row(job_store: JobStore):
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    job_store.enqueue(kind="ask", principal="a", payload={})
    cached_id = job_store.enqueue(kind="ask", principal="a", payload={})
    job_store.claim()
    job_store.claim()
    job_store.complete(cached_id, result_ref="x", corpus_pin="p", cached=True, cost_usd=0.0)

    # One real row counts; the cache hit does not (issue #686's third
    # decision: a hit spends nothing, so it must never count against the
    # budget that exists to bound spend).
    assert job_store.count_since("a", kind="ask", since=since) == 1


def test_count_since_counts_a_still_queued_row_conservatively(job_store: JobStore):
    since = datetime(2020, 1, 1, tzinfo=timezone.utc)
    job_store.enqueue(kind="ask", principal="a", payload={})

    # Every row starts `cached = FALSE`, so a job not yet resolved either
    # way counts until a hit is proven -- the conservative default.
    assert job_store.count_since("a", kind="ask", since=since) == 1


def test_count_since_ignores_a_different_principal_or_kind_or_window(job_store: JobStore):
    since = datetime(2026, 8, 10, tzinfo=timezone.utc)
    job_store.enqueue(kind="ask", principal="someone-else", payload={})
    job_store.enqueue(kind="ingest", principal="a", payload={})

    assert job_store.count_since("a", kind="ask", since=since) == 0


def test_sum_spend_for_principal_is_none_with_no_finished_jobs(job_store: JobStore):
    assert job_store.sum_spend_for_principal("nobody") is None


def test_sum_spend_for_principal_sums_known_costs_and_ignores_unknown(job_store: JobStore):
    for cost in (0.10, None, 0.25):
        job_id = job_store.enqueue(kind="ask", principal="a", payload={})
        job_store.claim()
        job_store.complete(job_id, result_ref="x", corpus_pin="p", cost_usd=cost)

    assert job_store.sum_spend_for_principal("a") == 0.35


def test_sum_spend_for_principal_is_none_when_every_finished_job_is_unpriced(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="a", payload={})
    job_store.claim()
    job_store.complete(job_id, result_ref="x", corpus_pin="p", cost_usd=None)

    # Unknown, not zero -- an unpriced model's cost is a fact the record
    # itself never coerces to 0.0 (§7.14), and this sum must not either.
    assert job_store.sum_spend_for_principal("a") is None


def test_sum_spend_for_principal_counts_a_real_cache_zero(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="a", payload={})
    job_store.claim()
    job_store.complete(job_id, result_ref="x", corpus_pin="p", cached=True, cost_usd=0.0)

    # A cache hit's cost is a genuinely known zero -- distinct from an
    # unpriced model's unknown cost, and it must show up as 0.0, not None.
    assert job_store.sum_spend_for_principal("a") == 0.0
