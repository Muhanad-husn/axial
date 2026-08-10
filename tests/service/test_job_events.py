"""`JobStore.append_event`/`events_since` (issue #683): the persistence half
of "progress streams to the client as events, not a spinner". The HTTP
surface these back is proved in `test_api_events.py`; this file is the store
alone -- monotonic per-job `seq`, and the `after_seq` cursor `Last-Event-ID`
resume relies on."""

from __future__ import annotations

from axial.service.jobs import JobStore


def test_append_event_assigns_a_monotonic_per_job_seq_starting_at_one(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})

    first_seq = job_store.append_event(
        job_id, "interrogating the question", {"stage": "interrogate"}
    )
    second_seq = job_store.append_event(job_id, "writing the answer", {"stage": "synthesize"})

    assert (first_seq, second_seq) == (1, 2)


def test_append_event_seqs_are_independent_per_job(job_store: JobStore):
    first_job = job_store.enqueue(kind="ask", principal="analyst-1", payload={})
    second_job = job_store.enqueue(kind="ask", principal="analyst-1", payload={})

    job_store.append_event(first_job, "first job's only event")
    seq = job_store.append_event(second_job, "second job's first event")

    assert seq == 1


def test_events_since_returns_only_events_after_the_given_seq_in_order(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})
    job_store.append_event(job_id, "one")
    job_store.append_event(job_id, "two")
    job_store.append_event(job_id, "three")

    events = job_store.events_since(job_id, after_seq=1)

    assert [event["seq"] for event in events] == [2, 3]
    assert [event["message"] for event in events] == ["two", "three"]


def test_events_since_defaults_to_the_full_history(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})
    job_store.append_event(job_id, "one")
    job_store.append_event(job_id, "two")

    events = job_store.events_since(job_id)

    assert [event["seq"] for event in events] == [1, 2]


def test_append_event_persists_the_detail_dict_as_json(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})

    job_store.append_event(job_id, "retrieving evidence", {"tool": "find_names", "hits": 12})

    (event,) = job_store.events_since(job_id)
    assert event["detail"] == {"tool": "find_names", "hits": 12}


def test_append_event_defaults_detail_to_an_empty_dict(job_store: JobStore):
    job_id = job_store.enqueue(kind="ask", principal="analyst-1", payload={})

    job_store.append_event(job_id, "checking the answer")

    (event,) = job_store.events_since(job_id)
    assert event["detail"] == {}
