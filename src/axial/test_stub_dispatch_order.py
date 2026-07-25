"""Regression tests for issue #370: a concurrently-dispatched group of calls
must each receive the scripted response matching its own SUBMISSION-order
index, never one intended for a sibling draw.

The bug was timing-dependent, so these tests do not hope for an unlucky
schedule -- they **force** the worst case. `_reverse_order_gate` blocks every
worker until all of them have entered the stub, then releases them in exactly
reverse submission order. Under the old code (a shared counter advanced by
whichever worker won the lock first) that inversion is deterministic and the
responses come back reversed; under the fix they come back in submission
order regardless of who runs when.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

import axial.llm as llm_mod
from axial.llm import (
    STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR,
    TAG_PASS_NAME,
    StubLLMClient,
    dispatch_slot,
    reserve_tag_dispatch_slots,
)

DRAWS = 3


@pytest.fixture(autouse=True)
def _reset_counter():
    llm_mod._tag_pass_call_count = 0
    yield
    llm_mod._tag_pass_call_count = 0


def _reverse_order_gate(n: int):
    """Return a `wait(position)` that releases workers in reverse order.

    Every worker reports in and blocks; once all `n` have arrived, the last
    submitted is freed first and each frees its predecessor. Execution order
    is therefore the exact inverse of submission order, deterministically.
    """
    arrived = threading.Barrier(n)
    gates = [threading.Event() for _ in range(n)]

    def wait(position: int) -> None:
        arrived.wait(timeout=10)
        if position == n - 1:
            gates[position].set()
        gates[position].wait(timeout=10)
        if position > 0:
            gates[position - 1].set()

    return wait


def _script(monkeypatch, responses: list[str]) -> None:
    monkeypatch.setenv(STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR, json.dumps(responses))


def test_each_draw_receives_its_own_scripted_response_under_reversed_execution(monkeypatch):
    """The acceptance criterion of issue #370."""
    _script(monkeypatch, ["draw-1", "draw-2", "draw-3"])
    client = StubLLMClient()
    wait = _reverse_order_gate(DRAWS)
    slots = reserve_tag_dispatch_slots(DRAWS)

    def draw(position: int) -> str:
        wait(position)
        with dispatch_slot(slots[position]):
            return client.complete("identical prompt", pass_name=TAG_PASS_NAME)

    with ThreadPoolExecutor(max_workers=DRAWS) as executor:
        futures = [executor.submit(draw, position) for position in range(DRAWS)]
        results = [future.result(timeout=10) for future in futures]

    assert results == ["draw-1", "draw-2", "draw-3"]


def test_slots_are_reserved_in_submission_order_before_any_worker_runs():
    """Reservation happens in the submitting thread, so the positions are
    decided before thread scheduling has any say."""
    assert reserve_tag_dispatch_slots(3) == [1, 2, 3]
    assert reserve_tag_dispatch_slots(2) == [4, 5], "a second group continues the sequence"


def test_consecutive_groups_do_not_reuse_positions():
    """Two chunks' worth of draws must walk the sequence, not restart it --
    the reason a slot carries an absolute position rather than a per-group
    draw index."""
    first = reserve_tag_dispatch_slots(DRAWS)
    second = reserve_tag_dispatch_slots(DRAWS)
    assert set(first).isdisjoint(second)
    assert second == [4, 5, 6]


def test_sequential_calls_still_advance_the_counter(monkeypatch):
    """No slot bound: unchanged behavior for every non-concurrent caller."""
    _script(monkeypatch, ["a", "b", "c"])
    client = StubLLMClient()
    results = [client.complete("p", pass_name=TAG_PASS_NAME) for _ in range(3)]
    assert results == ["a", "b", "c"]


def test_a_bound_slot_does_not_double_advance_the_counter(monkeypatch):
    """The reservation already moved the counter; advancing again inside the
    worker would shift every later call's position."""
    _script(monkeypatch, ["a", "b", "c", "d"])
    client = StubLLMClient()
    slots = reserve_tag_dispatch_slots(2)
    for slot in slots:
        with dispatch_slot(slot):
            client.complete("p", pass_name=TAG_PASS_NAME)

    assert llm_mod._tag_pass_call_count == 2
    assert client.complete("p", pass_name=TAG_PASS_NAME) == "c", (
        "the next sequential call must take position 3, not 5"
    )


def test_dispatch_slot_restores_the_previous_binding(monkeypatch):
    """Pooled worker threads are reused, so a leaked binding would poison a
    later, unrelated call on the same thread."""
    _script(monkeypatch, ["a", "b"])
    client = StubLLMClient()
    with dispatch_slot(2):
        assert client.complete("p", pass_name=TAG_PASS_NAME) == "b"
    assert client.complete("p", pass_name=TAG_PASS_NAME) == "a", (
        "with the binding released, the call takes counter position 1"
    )


def test_fault_injection_fires_on_the_submitted_draw_not_the_racing_one(monkeypatch):
    """AXIAL_STUB_TAG_FAIL_AT keys on the same position, so an injected
    failure lands on the draw a test aimed it at."""
    monkeypatch.setenv(llm_mod.STUB_TAG_FAIL_AT_ENV_VAR, "2")
    client = StubLLMClient()
    slots = reserve_tag_dispatch_slots(DRAWS)
    wait = _reverse_order_gate(DRAWS)
    outcomes: list[str] = [""] * DRAWS

    def draw(position: int) -> None:
        wait(position)
        try:
            with dispatch_slot(slots[position]):
                client.complete("p", pass_name=TAG_PASS_NAME)
            outcomes[position] = "ok"
        except llm_mod.StubInjectedTagFailureError:
            outcomes[position] = "failed"

    with ThreadPoolExecutor(max_workers=DRAWS) as executor:
        for future in [executor.submit(draw, position) for position in range(DRAWS)]:
            future.result(timeout=10)

    assert outcomes == ["ok", "failed", "ok"]
