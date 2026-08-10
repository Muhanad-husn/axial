"""Acceptance tests for issue #686's first two "done when"s:

- the same brief from two analysts, against the same corpus pin, triggers
  one generation -- the second is served from cache, marked as such, and
  costs nothing;
- the same brief against a newer corpus pin regenerates rather than being
  served from the old pin's cache entry.

No model is called: `axial.service.worker.run_ask` is stubbed, the same
seam `test_worker.py` uses. Real Postgres backs both `JobStore` and
`PaperCache`."""

from __future__ import annotations

import json
from pathlib import Path

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief
from axial.service import worker as worker_mod
from axial.service.cache import PaperCache
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job

_SNAPSHOT_V1 = Snapshot(
    root=Path("data/snapshots/v1"),
    version="v1",
    corpus_pin="pin-v1",
    map_pin=None,
    sources=(),
    built_at="2026-08-10T00:00:00Z",
)
_SNAPSHOT_V2 = Snapshot(
    root=Path("data/snapshots/v2"),
    version="v2",
    corpus_pin="pin-v2",
    map_pin=None,
    sources=(),
    built_at="2026-08-10T00:00:00Z",
)


def _stub_ask(calls: list[str], pin: str):
    """A fake `run_ask` that writes a real record file (so a cache `store`
    call has real bytes to copy) and counts how many times the engine was
    actually asked to generate under this pin."""

    def fake_ask(question, case, *, client, session_id=None, on_event=None, **kwargs):
        calls.append(pin)
        analyses_dir = Path(kwargs["analyses_dir"])
        analyses_dir.mkdir(parents=True, exist_ok=True)
        record_path = analyses_dir / "b.json"
        record = {
            "corpus_pin": pin,
            "brief_id": "irrelevant-to-the-cache-key",
            "claims": [{"text": f"generated for {pin}"}],
            "cost": {"total_usd": 0.13},
        }
        record_path.write_text(json.dumps(record), encoding="utf-8")
        brief = Brief(brief_id="b1", case=case, request=question)
        return Turn(
            session_id="s1",
            turn_index=1,
            question=question,
            case=case,
            brief=brief,
            result=BriefRunResult(
                record=record,
                path=record_path,
                markdown_path=record_path,
                report={},
                report_path=record_path,
            ),
        )

    return fake_ask


def test_the_second_analysts_identical_brief_is_served_from_cache_at_no_cost(
    job_store: JobStore, paper_cache: PaperCache, tmp_path: Path, monkeypatch
):
    calls: list[str] = []
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(calls, "pin-v1"))

    payload = {"question": "Who led it?", "case": "Syria"}
    job_a = job_store.enqueue(kind="ask", principal="analyst-a", payload=payload)
    job_b = job_store.enqueue(kind="ask", principal="analyst-b", payload=payload)

    worker = Worker(
        job_store,
        run_job=lambda job: run_ask_job(
            job,
            client=object(),
            store=job_store,
            snapshot=_SNAPSHOT_V1,
            work_dir=tmp_path / "work",
            cache=paper_cache,
        ),
    )
    assert worker.run_once() is True
    assert worker.run_once() is True

    # The engine ran exactly once for two identical asks.
    assert calls == ["pin-v1"]

    row_a = job_store.get(job_a)
    row_b = job_store.get(job_b)
    assert row_a["cached"] is False
    assert row_a["cost_usd"] == 0.13
    assert row_b["cached"] is True
    assert row_b["cost_usd"] == 0.0

    # Byte-identical served content.
    served_a = json.loads(Path(row_a["result_ref"]).read_text(encoding="utf-8"))
    served_b = json.loads(Path(row_b["result_ref"]).read_text(encoding="utf-8"))
    assert served_a == served_b

    # A cache hit still produces a terminal event -- #687's client never
    # gets an empty walk.
    events_b = job_store.events_since(job_b)
    assert any("cache" in event["message"].lower() for event in events_b)


def test_a_newer_corpus_pin_regenerates_rather_than_serving_the_old_cache(
    job_store: JobStore, paper_cache: PaperCache, tmp_path: Path, monkeypatch
):
    calls: list[str] = []
    payload = {"question": "Who led it?", "case": "Syria"}

    job_v1 = job_store.enqueue(kind="ask", principal="analyst-a", payload=payload)
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(calls, "pin-v1"))
    worker_v1 = Worker(
        job_store,
        run_job=lambda job: run_ask_job(
            job,
            client=object(),
            store=job_store,
            snapshot=_SNAPSHOT_V1,
            work_dir=tmp_path / "work-v1",
            cache=paper_cache,
        ),
    )
    assert worker_v1.run_once() is True

    job_v2 = job_store.enqueue(kind="ask", principal="analyst-b", payload=payload)
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(calls, "pin-v2"))
    worker_v2 = Worker(
        job_store,
        run_job=lambda job: run_ask_job(
            job,
            client=object(),
            store=job_store,
            snapshot=_SNAPSHOT_V2,
            work_dir=tmp_path / "work-v2",
            cache=paper_cache,
        ),
    )
    assert worker_v2.run_once() is True

    # Regenerated under the new pin, not served from the old pin's cache.
    assert calls == ["pin-v1", "pin-v2"]
    row_v2 = job_store.get(job_v2)
    assert row_v2["cached"] is False
    assert row_v2["corpus_pin"] == "pin-v2"
    assert job_store.get(job_v1)["corpus_pin"] == "pin-v1"


def test_no_cache_argument_always_generates(job_store: JobStore, tmp_path: Path, monkeypatch):
    """`cache=None` (the default) skips the cache entirely -- byte-identical
    to before this issue, and every existing worker test relies on this."""
    calls: list[str] = []
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(calls, "pin-v1"))

    payload = {"question": "Who led it?", "case": "Syria"}
    job_store.enqueue(kind="ask", principal="analyst-a", payload=payload)
    job_store.enqueue(kind="ask", principal="analyst-b", payload=payload)

    worker = Worker(
        job_store,
        run_job=lambda job: run_ask_job(
            job, client=object(), store=job_store, snapshot=_SNAPSHOT_V1, work_dir=tmp_path / "work"
        ),
    )
    assert worker.run_once() is True
    assert worker.run_once() is True

    assert calls == ["pin-v1", "pin-v1"]
