"""`GET /asks/{id}/events` (issue #683): Server-Sent Events over a job's
`on_event` history, replacing the CLI's `_print_event` spinner with a stream
a web client can render. The engine itself is never run here -- every event
below is appended straight to the store, the same way `run_ask_job`
(`test_worker.py::test_run_ask_job_wires_on_event_to_the_store`) does it --
so these tests are the endpoint's own three "done when"s: a live event
reaches the client quickly, a reconnect with `Last-Event-ID` resumes with no
gap and no duplicate, and a failed job ends the stream with its error rather
than hanging -- plus a regression for the terminal-drain race a review found:
the worker's last event and its `done`/`failed` write land back-to-back, and
an early version of this endpoint could observe the terminal state before
re-reading that event, dropping it.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from axial.service.api import DEFAULT_PRINCIPAL, _event_stream, create_app
from axial.service.jobs import JobStore

# Generous relative to `EVENTS_POLL_INTERVAL_SECONDS` (0.5s) so a slow CI
# runner doesn't make this flaky; still far under "seconds" from the issue's
# own acceptance bar.
_JOIN_TIMEOUT = 15.0


@pytest.fixture
def client(job_store: JobStore, authed_app):
    with TestClient(authed_app(create_app(job_store))) as test_client:
        yield test_client


def _iter_sse_frames(response: Response) -> Iterator[dict[str, Any]]:
    """Group an SSE response's lines back into frames: an optional `id:`
    line, one `data:` line, then the blank line that ends the frame."""
    event_id: str | None = None
    data_line: str | None = None
    for line in response.iter_lines():
        if line == "":
            if data_line is not None:
                yield {"id": event_id, "data": json.loads(data_line)}
            event_id = None
            data_line = None
        elif line.startswith("id: "):
            event_id = line[len("id: ") :]
        elif line.startswith("data: "):
            data_line = line[len("data: ") :]


def test_events_stream_is_404_for_an_unknown_id(client):
    assert client.get("/asks/does-not-exist/events").status_code == 404


def test_events_stream_delivers_events_live_and_closes_when_the_job_is_done(
    client, job_store: JobStore
):
    # `DEFAULT_PRINCIPAL` (issue #685): a job read through `client` must be
    # owned by the same principal the client's own dependency authenticates
    # as, or `_require_own_job` refuses it -- this test is about the stream
    # itself, so it stays the owner rather than exercising that refusal.
    job_id = job_store.enqueue(
        kind="ask", principal=DEFAULT_PRINCIPAL, payload={"case": "Syria", "question": "Q"}
    )
    job_store.claim()

    def produce() -> None:
        time.sleep(0.1)
        job_store.append_event(job_id, "interrogating the question", {"stage": "interrogate"})
        time.sleep(0.1)
        job_store.append_event(job_id, "writing the answer", {"stage": "synthesize"})
        time.sleep(0.1)
        job_store.complete(job_id, result_ref="data/analyses/x.json", corpus_pin="sim-2026-08-10")

    producer = threading.Thread(target=produce, daemon=True)
    started = time.perf_counter()
    producer.start()

    frames = []
    with client.stream("GET", f"/asks/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for frame in _iter_sse_frames(response):
            frames.append(frame)
            if len(frames) == 1:
                first_event_elapsed = time.perf_counter() - started

    producer.join(_JOIN_TIMEOUT)

    assert first_event_elapsed < 5.0
    assert [frame["id"] for frame in frames] == ["1", "2"]
    assert [frame["data"]["message"] for frame in frames] == [
        "interrogating the question",
        "writing the answer",
    ]
    assert frames[0]["data"]["detail"] == {"stage": "interrogate"}


def _frame_messages(frames: list[str]) -> list[str]:
    return [json.loads(frame.split("data: ", 1)[1])["message"] for frame in frames]


def test_event_stream_does_not_drop_an_event_written_between_the_last_read_and_done(
    job_store: JobStore, monkeypatch
):
    """Regression: the worker's final `on_event` call and its `store.complete`
    land back-to-back, so `_event_stream`'s state check can observe `done`
    before it has re-read the event that call just wrote. Driven at
    `_event_stream` directly, not through `TestClient` -- an HTTP round trip
    has no hook precise enough to land the append+complete inside the
    generator's own `store.get` call; monkeypatching `job_store.get` does,
    deterministically, with no sleeping."""
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})
    job_store.claim()
    job_store.append_event(job_id, "interrogating the question")

    real_get = job_store.get

    def get_then_finish_the_job(ask_id: str):
        # The exact race: one more event, then done, landing in the window
        # between this generator's last `events_since` read and this call.
        job_store.append_event(job_id, "checking the answer")
        job_store.complete(job_id, result_ref="data/analyses/x.json", corpus_pin="sim-2026-08-10")
        return real_get(ask_id)

    monkeypatch.setattr(job_store, "get", get_then_finish_the_job)

    frames = list(_event_stream(job_store, job_id, after_seq=0))

    assert _frame_messages(frames) == ["interrogating the question", "checking the answer"]


def test_event_stream_does_not_drop_an_event_written_between_the_last_read_and_failed(
    job_store: JobStore, monkeypatch
):
    """Same race, the `failed` path: the drain must still surface the last
    event, and the error frame must still come after it, not before."""
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})
    job_store.claim()
    job_store.append_event(job_id, "interrogating the question")

    real_get = job_store.get

    def get_then_fail_the_job(ask_id: str):
        job_store.append_event(job_id, "retrieving evidence through the argument map")
        job_store.fail(ask_id, error="engine blew up")
        return real_get(ask_id)

    monkeypatch.setattr(job_store, "get", get_then_fail_the_job)

    frames = list(_event_stream(job_store, job_id, after_seq=0))

    assert _frame_messages(frames) == [
        "interrogating the question",
        "retrieving evidence through the argument map",
        "engine blew up",
    ]


def test_event_stream_emits_a_keepalive_comment_on_the_quiet_path(job_store: JobStore, monkeypatch):
    """Issue #751: a stage with nothing new to say used to poll silently --
    no bytes crossed the wire while `store.get` kept coming back `running`.
    Real asks measured 35-54s gaps there, long enough that a browser, a
    proxy, or an edge network reaps the connection before it ever gets a
    real frame. Every quiet poll must now put an SSE comment (`: keepalive`)
    on the wire -- invisible to a client's own parser (no `data:` line, so
    `parseFrames`/`EventSource` both drop it) but enough to keep the
    connection warm."""
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})
    job_store.claim()

    real_get = job_store.get
    calls = {"n": 0}

    def get_then_finish_after_two_quiet_polls(ask_id: str):
        calls["n"] += 1
        if calls["n"] >= 3:
            job_store.complete(
                ask_id, result_ref="data/analyses/x.json", corpus_pin="sim-2026-08-10"
            )
        return real_get(ask_id)

    monkeypatch.setattr(job_store, "get", get_then_finish_after_two_quiet_polls)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    frames = list(_event_stream(job_store, job_id, after_seq=0))

    assert frames.count(": keepalive\n\n") == 2


def test_a_failed_job_ends_the_stream_with_its_error(client, job_store: JobStore):
    job_id = job_store.enqueue(
        kind="ask", principal=DEFAULT_PRINCIPAL, payload={"case": "Syria", "question": "Q"}
    )
    job_store.claim()
    job_store.append_event(job_id, "interrogating the question")
    job_store.fail(job_id, error="engine blew up")

    with client.stream("GET", f"/asks/{job_id}/events") as response:
        frames = list(_iter_sse_frames(response))

    assert [frame["data"]["message"] for frame in frames] == [
        "interrogating the question",
        "engine blew up",
    ]
    # The synthetic failure frame is not a stored, replayable event.
    assert frames[-1]["id"] is None


def test_reconnecting_with_last_event_id_resumes_with_no_gap_or_duplicate(
    client, job_store: JobStore
):
    job_id = job_store.enqueue(
        kind="ask", principal=DEFAULT_PRINCIPAL, payload={"case": "Syria", "question": "Q"}
    )
    job_store.claim()
    job_store.append_event(job_id, "one")
    job_store.append_event(job_id, "two")
    job_store.append_event(job_id, "three")
    job_store.complete(job_id, result_ref="data/analyses/x.json", corpus_pin="sim-2026-08-10")

    # A first client reads the whole history, then disconnects having only
    # processed through "two" (a crash, a tab closed mid-render -- either
    # way it never saw "three").
    with client.stream("GET", f"/asks/{job_id}/events") as response:
        first_connection = list(_iter_sse_frames(response))
    assert [frame["data"]["message"] for frame in first_connection] == ["one", "two", "three"]
    last_seen_id = first_connection[1]["id"]

    with client.stream(
        "GET", f"/asks/{job_id}/events", headers={"Last-Event-ID": last_seen_id}
    ) as response:
        resumed = list(_iter_sse_frames(response))

    # No gap (event three is not missing) and no duplicate (events one and
    # two are not repeated) -- exactly what the reconnecting client missed.
    assert [frame["data"]["message"] for frame in resumed] == ["three"]


def test_a_completed_job_replays_its_full_history_and_closes(client, job_store: JobStore):
    job_id = job_store.enqueue(
        kind="ask", principal=DEFAULT_PRINCIPAL, payload={"case": "Syria", "question": "Q"}
    )
    job_store.claim()
    job_store.append_event(job_id, "interrogating the question")
    job_store.append_event(job_id, "writing the answer")
    job_store.complete(job_id, result_ref="data/analyses/x.json", corpus_pin="sim-2026-08-10")

    with client.stream("GET", f"/asks/{job_id}/events") as response:
        frames = list(_iter_sse_frames(response))

    assert [frame["data"]["message"] for frame in frames] == [
        "interrogating the question",
        "writing the answer",
    ]
