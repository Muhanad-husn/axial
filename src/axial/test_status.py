"""Inner unit tests for `axial.status` (issue #530).

The load-bearing case is `test_stage_is_done_from_artifact_even_with_no_ledger_at_all`:
`axial sources` (a concurrent slice) once reported a fully-ingested corpus as
"new" because it asked a resume ledger that did not exist. `axial status`
must never repeat that -- a stage's "done" bit comes from the artifact each
pass persists, never from the ledger, which is corroboration for "pending"
vs "failed" only.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from axial.artifacts import artifacts_checkpoint_path
from axial.chunk import chunks_checkpoint_path
from axial.envelope import compute_source_id, envelope_path
from axial.extract import tree_path
from axial.interrogate import answers_checkpoint_path
from axial.runlog import RunNotFoundError, list_runs, load_run, run_context
from axial.status import (
    STAGES,
    compute_status,
    render_follow_line,
    render_run_list,
    render_run_view,
    render_status,
    resolve_run_dir,
)


@pytest.fixture()
def layout(tmp_path):
    """One fake raw source plus every directory `compute_status` reads,
    all under `tmp_path` -- nothing touches the real cwd-relative `data/`
    tree."""
    sources_dir = tmp_path / "sources"
    sources_dir.mkdir()
    source_path = sources_dir / "book-one.pdf"
    source_path.write_bytes(b"%PDF-1.4 fake source bytes")
    source_id = compute_source_id(source_path)

    dirs = {
        "sources_dir": sources_dir,
        "envelopes_dir": tmp_path / "envelopes",
        "trees_dir": tmp_path / "trees",
        "chunks_dir": tmp_path / "chunks",
        "answers_dir": tmp_path / "answers",
        "artifacts_dir": tmp_path / "artifacts",
        "vault_dir": tmp_path / "vault",
        "evals_dir": tmp_path / "evals",
        "ledger_path": tmp_path / "run" / "ledger.tsv",
        "logs_root": tmp_path / "logs",
    }
    for key, path in dirs.items():
        if key.endswith("_dir"):
            path.mkdir(parents=True, exist_ok=True)

    return {"source_id": source_id, "source_path": source_path, **dirs}


def _write_all_artifacts(layout):
    """Create every stage's own persisted artifact for `layout`'s one
    source -- the exact paths each pass module writes, never a fabricated
    convention of this test's own."""
    source_id = layout["source_id"]
    tree_path(source_id, layout["trees_dir"]).write_text("{}", encoding="utf-8")
    envelope_path(source_id, layout["envelopes_dir"]).write_text("{}", encoding="utf-8")
    chunks_checkpoint_path(source_id, layout["chunks_dir"]).write_text("", encoding="utf-8")
    answers_checkpoint_path(source_id, layout["answers_dir"]).write_text("", encoding="utf-8")
    artifacts_checkpoint_path(source_id, layout["artifacts_dir"]).write_text("", encoding="utf-8")

    prose_dir = layout["vault_dir"] / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    hash12 = source_id[-12:]
    (prose_dir / f"{source_id}_1-0_intro_001.md").write_text("note", encoding="utf-8")
    assert hash12 in (prose_dir / f"{source_id}_1-0_intro_001.md").name


def _compute(layout, **overrides):
    kwargs = dict(
        sources_dir=layout["sources_dir"],
        envelopes_dir=layout["envelopes_dir"],
        trees_dir=layout["trees_dir"],
        chunks_dir=layout["chunks_dir"],
        answers_dir=layout["answers_dir"],
        artifacts_dir=layout["artifacts_dir"],
        vault_dir=layout["vault_dir"],
        evals_dir=layout["evals_dir"],
        ledger_path=layout["ledger_path"],
        logs_root=layout["logs_root"],
    )
    kwargs.update(overrides)
    return compute_status(**kwargs)


def test_stage_is_done_from_artifact_even_with_no_ledger_at_all(layout):
    """The core regression: every artifact exists, the ledger file is
    entirely absent (not empty -- never created). Every stage must report
    `done`, not `pending` -- the exact failure mode a real ledgerless corpus
    hit."""
    assert not layout["ledger_path"].exists()
    _write_all_artifacts(layout)

    report = _compute(layout)

    assert report.sources_total == 1
    for stage in STAGES:
        s = report.stages[stage]
        assert (s.done, s.pending, s.failed) == (1, 0, 0), f"{stage} not reported done"
    assert report.ready is True

    rendered = render_status(report)
    assert "ready to query: yes" in rendered


def test_stage_with_no_artifact_and_no_ledger_row_is_pending_not_failed(layout):
    report = _compute(layout)  # no artifacts written at all

    for stage in STAGES:
        s = report.stages[stage]
        assert (s.done, s.pending, s.failed) == (0, 1, 0)
    assert report.ready is False


def test_a_stale_ok_ledger_row_alone_never_fabricates_done(layout):
    """A ledger claiming OK, with no matching artifact on disk, must not
    make a stage report done -- the ledger corroborates absence, it never
    substitutes for the artifact (the inverse of the core regression)."""
    layout["ledger_path"].parent.mkdir(parents=True, exist_ok=True)
    with layout["ledger_path"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["pass", "source_path", "source_id", "status", "reason", "timestamp"])
        writer.writerow(["extract", "book-one.pdf", layout["source_id"], "OK", "", "t"])

    report = _compute(layout)

    assert report.stages["extract"].done == 0
    assert report.stages["extract"].pending == 1


def test_a_ledger_fail_row_with_no_artifact_reports_failed_with_reason(layout):
    layout["ledger_path"].parent.mkdir(parents=True, exist_ok=True)
    with layout["ledger_path"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["pass", "source_path", "source_id", "status", "reason", "timestamp"])
        writer.writerow(
            ["interrogate", "book-one.pdf", layout["source_id"], "FAIL", "LLMError: 500", "t"]
        )

    report = _compute(layout)

    stage = report.stages["interrogate"]
    assert (stage.done, stage.pending, stage.failed) == (0, 0, 1)
    assert stage.failures == [(layout["source_id"], "LLMError: 500")]

    rendered = render_status(report)
    assert "LLMError: 500" in rendered
    assert "ready to query: no" in rendered


def test_a_later_ok_ledger_row_clears_an_earlier_fail(layout):
    layout["ledger_path"].parent.mkdir(parents=True, exist_ok=True)
    with layout["ledger_path"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["pass", "source_path", "source_id", "status", "reason", "timestamp"])
        writer.writerow(
            ["interrogate", "book-one.pdf", layout["source_id"], "FAIL", "LLMError: 500", "t1"]
        )
        writer.writerow(["interrogate", "book-one.pdf", layout["source_id"], "OK", "", "t2"])

    report = _compute(layout)  # still no artifact -- OK row alone never marks done

    stage = report.stages["interrogate"]
    assert (stage.done, stage.pending, stage.failed) == (0, 1, 0)


def test_corpus_pin_missing_is_reported_not_raised(layout):
    report = _compute(layout)
    assert report.corpus_pin_status == "missing"
    assert "run `axial pin write" in render_status(report)


def test_corpus_pin_ok_names_the_live_pin(layout):
    (layout["evals_dir"] / "baseline.json").write_text("{}", encoding="utf-8")
    report = _compute(layout)
    assert report.corpus_pin_status == "ok"
    assert report.corpus_pin_name == "baseline"
    assert "corpus pin: baseline" in render_status(report)


def test_vault_note_and_name_page_counts_are_cheap_filename_counts(layout):
    (layout["vault_dir"] / "prose").mkdir(parents=True, exist_ok=True)
    (layout["vault_dir"] / "prose" / "a.md").write_text("x", encoding="utf-8")
    (layout["vault_dir"] / "prose" / "b.md").write_text("x", encoding="utf-8")
    (layout["vault_dir"] / "names").mkdir(parents=True, exist_ok=True)
    (layout["vault_dir"] / "names" / "Some Name.md").write_text("x", encoding="utf-8")

    report = _compute(layout)

    assert report.prose_notes == 2
    assert report.name_pages == 1
    assert "2 prose note(s)" in render_status(report)
    assert "1 name page(s)" in render_status(report)


def _write_meta(run_dir: Path, status: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "meta.json").write_text(
        json.dumps({"run_id": run_dir.name, "name": "run-interrogate", "status": status}),
        encoding="utf-8",
    )


def _write_heartbeat(run_dir: Path, updated_at: datetime) -> None:
    (run_dir / "heartbeat.json").write_text(
        json.dumps({"updated_at": updated_at.isoformat()}), encoding="utf-8"
    )


def test_live_run_with_a_fresh_heartbeat_is_reported_alive(layout):
    now = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
    run_dir = layout["logs_root"] / "run-interrogate-20260802T115000Z"
    _write_meta(run_dir, "running")
    _write_heartbeat(run_dir, now - timedelta(seconds=3))

    report = _compute(layout, now=now)

    assert report.live_run is not None
    assert report.live_run.run_id == run_dir.name
    assert report.live_run_heartbeat_age_sec == pytest.approx(3.0, abs=0.5)
    assert "is alive" in render_status(report)


def test_a_run_whose_heartbeat_went_stale_is_reported_stale_not_running(layout):
    """A hard-killed process leaves `meta.json` stuck at `"running"`
    forever (axial.runlog's own module docstring) -- `axial status` must
    read that as stale, never as a currently-alive run."""
    now = datetime(2026, 8, 2, 12, 0, 0, tzinfo=timezone.utc)
    run_dir = layout["logs_root"] / "run-interrogate-20260802T100000Z"
    _write_meta(run_dir, "running")
    _write_heartbeat(run_dir, now - timedelta(minutes=30))

    report = _compute(layout, now=now)

    assert report.live_run is None
    assert report.most_recent_run is not None
    assert report.most_recent_run.alive is False
    rendered = render_status(report)
    assert "STALE" in rendered
    assert "is alive" not in rendered


# ---------------------------------------------------------------------------
# Watching a run: axial runs list|show|follow's own rendering helpers.
# ---------------------------------------------------------------------------


def test_resolve_run_dir_accepts_a_bare_run_id(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: "20260802T000000Z") as run:
        run.record(source_id="s1", pass_name="extract", model=None, status="OK", duration_sec=1.0)

    resolved = resolve_run_dir("demo-20260802T000000Z", root=tmp_path)

    assert resolved == tmp_path / "demo-20260802T000000Z"


def test_resolve_run_dir_accepts_a_real_path_verbatim(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: "20260802T000000Z") as run:
        pass

    resolved = resolve_run_dir(str(run.run_dir), root=tmp_path)

    assert resolved == run.run_dir


def test_resolve_run_dir_raises_a_clear_error_for_an_unknown_run(tmp_path):
    with pytest.raises(RunNotFoundError):
        resolve_run_dir("no-such-run", root=tmp_path)


def test_render_run_list_shows_status_and_liveness(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: "20260802T000000Z"):
        pass

    rendered = render_run_list(list_runs(root=tmp_path))

    assert "demo-20260802T000000Z" in rendered
    assert "ok" in rendered


def test_render_run_list_handles_no_runs(tmp_path):
    assert render_run_list(list_runs(root=tmp_path)) == "no runs recorded"


def test_render_run_view_tallies_records_and_names_failures(tmp_path):
    with run_context("demo", root=tmp_path, clock=lambda: "20260802T000000Z") as run:
        run.record(
            source_id="s1", pass_name="interrogate", model=None, status="OK", duration_sec=1.0
        )
        run.record(
            source_id="s2",
            pass_name="interrogate",
            model=None,
            status="FAIL",
            duration_sec=0.5,
            error="LLMError: 500",
        )

    view = load_run(tmp_path / "demo-20260802T000000Z")
    rendered = render_run_view(view)

    assert "records: 2 (FAIL: 1, OK: 1)" in rendered
    assert "s2: LLMError: 500" in rendered


def test_render_follow_line_covers_record_event_and_status_streams():
    assert "[record]" in render_follow_line(
        {"stream": "record", "pass": "extract", "source_id": "s1", "status": "OK"}
    )
    assert "[event]" in render_follow_line(
        {"stream": "event", "kind": "source_start", "source_id": "s1"}
    )
    assert render_follow_line({"stream": "status", "status": "stale"}) == "[status] stale"
