"""Issue #682's third "done when": the CLI and the API produce the same
paper for the same brief.

Proved without spending a paid ask run. Both paths already reach the same
function -- `axial ask` calls `axial.ask.engine.ask`, and the service worker
calls it in-process too (`axial.service.worker.run_ask_job`, issue #681) --
so the honest evidence is that the two callers hand that function the same
question, the same case, and build the byte-identical §7.1 brief from it,
and that the record the API then serves is the record that run produced.
The engine underneath is stubbed at `run_brief_fn`, the seam
`src/axial/ask/test_engine.py` already uses; running it for real would cost
model calls and prove nothing this does not.

One difference between the two callers is real and is asserted rather than
hidden: `axial ask` passes `on_event` (its live progress printer) and
`on_fork` (its interactive prompt for a genuine intake fork). A queued ask
has no analyst on the other end to prompt, so it proceeds with the fork
recorded and unanswered, exactly as a batch `axial brief run` does. Neither
seam is part of the brief, and neither changes what the record's shape is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from axial import cli
from axial.answer.record import BriefRunResult
from axial.ask.engine import ask as real_ask
from axial.service import worker as worker_mod
from axial.service.api import create_app
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job

CASE = "Syria, 2011-2024"
QUESTION = "Who does Batatu argue against on the rural origins of the Ba'th?"


class _StubClient:
    """Neither path calls the client -- both only thread it through to the
    stubbed engine."""


@pytest.fixture
def record_file(tmp_path: Path) -> Path:
    record = {
        "brief_id": "stub",
        "corpus_pin": "sim-2026-08-10",
        "brief": {"case": CASE, "request": QUESTION},
        "claims": [{"kind": "stated", "text": "A claim the engine reached."}],
        "coverage_map": {},
        "confidence": {"band": "adequate", "rationale": "stubbed"},
    }
    path = tmp_path / "stub.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


@pytest.fixture
def engine_calls(monkeypatch, record_file: Path) -> list[dict[str, Any]]:
    """Patch each caller's own reference to `axial.ask.engine.ask` with a
    wrapper that records what that caller passed and then calls the real
    `ask` with a stubbed engine. Nothing about `ask` itself is faked, so
    the brief each path produces is the brief the real function builds."""
    result = BriefRunResult(
        record=json.loads(record_file.read_text(encoding="utf-8")),
        path=record_file,
        markdown_path=record_file.with_suffix(".md"),
        report={},
        report_path=record_file.with_name("report.json"),
    )
    calls: list[dict[str, Any]] = []

    def stub_run_brief(brief, **kwargs):
        return result

    def wrapper(question, case, **kwargs):
        turn = real_ask(question, case, run_brief_fn=stub_run_brief, **kwargs)
        calls.append({"question": question, "case": case, "turn": turn})
        return turn

    monkeypatch.setattr(cli, "ask_question", wrapper)
    monkeypatch.setattr(cli, "get_client", lambda: _StubClient())
    monkeypatch.setattr(worker_mod, "run_ask", wrapper)
    return calls


# The snapshot the service worker is bound to (issue #684). Its pin is the
# stub record's own pin, which is what `run_ask_job` reconciles the run
# against; the CLI path is unbound and unaffected.
_SNAPSHOT = Snapshot(
    root=Path("data/snapshots/v1"),
    version="v1",
    corpus_pin="sim-2026-08-10",
    map_pin=None,
    sources=(),
    built_at="2026-08-10T00:00:00Z",
)


def test_the_cli_and_the_api_produce_the_same_paper_for_the_same_brief(
    job_store: JobStore, engine_calls: list[dict[str, Any]], tmp_path: Path
):
    # `--no-paper` stops at the answer: an ask produces a §7.3 analysis
    # record, and the Phase-C paper draft `axial ask` adds on top is a
    # separate pipeline that neither path's record depends on.
    assert cli.main(["ask", QUESTION, "--case", CASE, "--no-paper"]) == 0
    cli_call = engine_calls[-1]

    with TestClient(create_app(job_store)) as client:
        job_id = client.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        worker = Worker(
            job_store,
            run_job=lambda job: run_ask_job(
                job,
                client=_StubClient(),
                store=job_store,
                snapshot=_SNAPSHOT,
                work_dir=tmp_path / "work",
            ),
            heartbeat_interval=0.1,
        )
        assert worker.run_once() is True
        paper = client.get(f"/asks/{job_id}/paper")

    api_call = engine_calls[-1]
    assert len(engine_calls) == 2

    # Same arguments into the same engine function...
    assert api_call["question"] == cli_call["question"] == QUESTION
    assert api_call["case"] == cli_call["case"] == CASE
    # ...and therefore the byte-identical §7.1 brief, down to the
    # content-keyed brief_id that decides which record the run belongs to.
    assert api_call["turn"].brief == cli_call["turn"].brief

    # And the paper the API serves is the record that run produced.
    assert paper.status_code == 200
    assert paper.json() == cli_call["turn"].result.record
