"""Acceptance test for issue #784 slice 03: sections stream as they draft
(plan `plans/784-ask-ends-in-an-essay/03-sections-stream-as-they-draft.md`).

While an ask is drafting its essay, `GET /asks/{id}/events` must keep
narrating: the arc it planned and its section count, then one event per
section as that section finishes, each naming its heading -- all of it
arriving after the analysis stages and before the job reaches `done`.

Driven the same way `tests/service/test_api_events.py` and
`tests/service/test_worker.py` already do: `axial.service.worker.run_ask`
and `axial.service.worker.draft_paper_for_turn` are monkeypatched to fast,
scripted stand-ins that call the `on_event` they are given, so this proves
the WIRING -- `run_ask_job` -> `_draft_the_essay` -> `draft_paper_for_turn`
-> `run_paper` -> `draft_section` -- reaches the store and the store reaches
an HTTP client, with no real model call and no real corpus underneath."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from fastapi.testclient import TestClient
from httpx import Response

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief
from axial.service import worker as worker_mod
from axial.service.api import DEFAULT_PRINCIPAL, create_app
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job

_SNAPSHOT = Snapshot(
    root=Path("data/snapshots/v1"),
    version="v1",
    corpus_pin="sim-2026-08-10",
    map_pin="a1b2c3",
    sources=("alpha-0123456789ab",),
    built_at="2026-08-10T00:00:00Z",
)

_SECTION_HEADINGS = ("Setup", "The bellicist account", "Synthesis")


def _iter_sse_frames(response: Response) -> Iterator[dict[str, Any]]:
    """Group an SSE response's lines back into frames -- the same grouping
    `test_api_events.py`'s own helper does."""
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


def _fake_ask(question, case, *, client, session_id=None, on_event=None, **kwargs):
    on_event("interrogating the question", {"stage": "interrogate"})
    on_event("wrote the answer -- 3 claim(s)", {"stage": "synthesize"})
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


def _fake_draft_paper_for_turn(client, turn, *, on_event=None, **kwargs):
    """Stands in for `axial.ask.paper.draft_paper_for_turn`, narrating a
    three-section paper through `on_event` exactly the way production
    `run_paper` now does: one plan event, one event per section as it
    finishes, one when the paper is written."""
    on_event(
        f"planned the paper's arc -- {len(_SECTION_HEADINGS)} section(s)",
        {"stage": "draft", "section_count": len(_SECTION_HEADINGS)},
    )
    for heading in _SECTION_HEADINGS:
        on_event(f"drafted the '{heading}' section", {"stage": "draft", "heading": heading})
    on_event("wrote the paper", {"stage": "draft"})
    return {"paper_brief_id": "pb-1"}


def test_ask_events_stream_narrates_the_planned_arc_and_each_section_as_it_drafts(
    monkeypatch, job_store: JobStore, authed_app
):
    monkeypatch.setattr(worker_mod, "run_ask", _fake_ask)
    monkeypatch.setattr(worker_mod, "draft_paper_for_turn", _fake_draft_paper_for_turn)

    job_id = job_store.enqueue(
        kind="ask",
        principal=DEFAULT_PRINCIPAL,
        payload={"case": "Syria", "question": "What made the state?"},
    )

    worker = Worker(
        job_store,
        run_job=lambda job: run_ask_job(
            job, client=object(), store=job_store, snapshot=_SNAPSHOT, work_dir=Path("data/work")
        ),
    )
    assert worker.run_once() is True

    with TestClient(authed_app(create_app(job_store))) as client:
        with client.stream("GET", f"/asks/{job_id}/events") as response:
            assert response.status_code == 200
            frames = list(_iter_sse_frames(response))

        # The stream closes once the job is done, and a `GET /asks/{id}`
        # confirms it -- the boundary the Gherkin's own "before the job
        # reaches done" refers to.
        assert client.get(f"/asks/{job_id}").json()["state"] == "done"

    messages = [frame["data"]["message"] for frame in frames]

    # The analysis stages, then the arc, then one event per section in plan
    # order, then the paper written -- all in that order, nothing dropped.
    assert messages == [
        "interrogating the question",
        "wrote the answer -- 3 claim(s)",
        "planned the paper's arc -- 3 section(s)",
        "drafted the 'Setup' section",
        "drafted the 'The bellicist account' section",
        "drafted the 'Synthesis' section",
        "wrote the paper",
    ]

    plan_frame = frames[2]
    assert plan_frame["data"]["detail"] == {"stage": "draft", "section_count": 3}

    section_frames = frames[3:6]
    assert [frame["data"]["detail"]["heading"] for frame in section_frames] == list(
        _SECTION_HEADINGS
    )
    # `detail.stage` is what the walk discriminates a phase badge on --
    # every paper-narration event, plan/section/written alike, carries it.
    assert all(frame["data"]["detail"]["stage"] == "draft" for frame in frames[2:])

    # Every stored event shares one monotonic sequence, analysis and paper
    # events alike -- there is no second stream for the essay's own work.
    ids = [int(frame["id"]) for frame in frames]
    assert ids == sorted(ids)
    assert ids == list(range(1, len(frames) + 1))
