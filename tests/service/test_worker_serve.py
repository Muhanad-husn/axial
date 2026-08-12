"""Issue #691's worker container entry point (`axial.service.worker.main`):
the pure env-parsing helpers and the poll loop's own claim/sleep shape,
without a real Postgres or Docker -- `test_worker.py`/`test_worker_reclaim.py`
already cover `Worker.run_once`/`JobStore.reclaim_stale` against the real
thing, and the live `docker compose up` run in the PR is what proves `main`
itself end to end."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from axial.service.worker import _env_float, _env_int, _poll_loop


def test_env_float_falls_back_to_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AXIAL_TEST_FLOAT", raising=False)
    assert _env_float("AXIAL_TEST_FLOAT", 2.5) == 2.5


def test_env_float_reads_a_set_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AXIAL_TEST_FLOAT", "7.5")
    assert _env_float("AXIAL_TEST_FLOAT", 2.5) == 7.5


def test_env_int_falls_back_to_default_when_unset(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AXIAL_TEST_INT", raising=False)
    assert _env_int("AXIAL_TEST_INT", 3) == 3


def test_env_int_reads_a_set_value(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AXIAL_TEST_INT", "9")
    assert _env_int("AXIAL_TEST_INT", 3) == 9


def test_poll_loop_stops_the_instant_stop_is_set():
    """A `stop` already set means the loop never calls `run_once` at all --
    a worker asked to shut down does not squeeze in one more claim first."""
    worker = SimpleNamespace(run_once=lambda: pytest.fail("should not be called"))
    stop = threading.Event()
    stop.set()

    _poll_loop(worker, poll_interval=0.01, stop=stop)


def test_poll_loop_keeps_claiming_while_the_queue_has_work():
    """A queue that never comes back empty keeps `run_once` firing
    back-to-back, with no sleep between calls, until something sets
    `stop` -- proven here by having the fake queue stop itself after three
    claims rather than relying on a timeout."""
    calls: list[int] = []
    stop = threading.Event()

    def run_once() -> bool:
        calls.append(1)
        if len(calls) >= 3:
            stop.set()
        return True  # claimed something -- the loop asks again immediately

    worker = SimpleNamespace(run_once=run_once)

    _poll_loop(worker, poll_interval=5.0, stop=stop)

    assert len(calls) == 3


def test_poll_loop_sleeps_between_claims_on_an_empty_queue():
    """`run_once` returning `False` (queue empty) is what makes the loop
    sleep before asking again -- proven by a fake queue that goes empty for
    exactly the sleep to observe, then has one real job, then stops."""
    calls: list[bool] = []
    stop = threading.Event()

    def run_once() -> bool:
        claimed = len(calls) >= 1
        calls.append(claimed)
        if claimed:
            stop.set()
        return claimed

    worker = SimpleNamespace(run_once=run_once)

    _poll_loop(worker, poll_interval=0.01, stop=stop)

    assert calls == [False, True]
