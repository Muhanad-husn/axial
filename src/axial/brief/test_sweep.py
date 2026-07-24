"""Inner unit tests for `axial.brief.sweep` (issue #368): draw/gates path
shape, quorum computation, cost/token aggregation, per-draw resume/failure
isolation, and the fresh-client-per-draw contract.

Mirrors `src/axial/test_run.py`'s own colocated-inner-unit-test style:
monkeypatch module-level names so each behavior is pinned in isolation,
without a real LLM provider, a real vault, or a real gate. The outer
acceptance test (`tests/analysis/test_brief_sweep.py`) covers the
end-to-end CLI + real-stub-provider contract, including gherkin scenarios
1-2 (no clobbering, resume) via a real subprocess, and 3-4 (failure
isolation, per-brief gate/quorum scoping) via direct `run_sweep()` calls
with real `run_brief`/`run_gate`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

import axial.brief.sweep as sweep_mod
from axial.brief.intake import Brief


@dataclass
class _FakeBriefRunResult:
    record: dict
    path: Path
    markdown_path: Path


def _record(disposition: str, kinds: list[str]) -> dict:
    return {
        "interrogation": {"disposition": disposition},
        "claims": [{"kind": kind} for kind in kinds],
    }


def _cost_record(by_pass: dict) -> dict:
    return {"cost": {"by_pass": by_pass}}


# --- draw_dir / gates_dir path shape ----------------------------------------


def test_draw_dir_is_distinct_per_brief_stem_and_draw_index(tmp_path):
    paths = [
        sweep_mod.draw_dir(tmp_path, "briefA", 0),
        sweep_mod.draw_dir(tmp_path, "briefA", 1),
        sweep_mod.draw_dir(tmp_path, "briefB", 0),
    ]
    assert len(set(paths)) == 3
    assert sweep_mod.gates_dir(tmp_path, "briefA") not in paths


# --- compute_quorum ----------------------------------------------------------


def test_compute_quorum_of_zero_records_reports_no_agreement_figure():
    result = sweep_mod.compute_quorum([])
    assert result.n_draws == 0
    assert result.disposition_agreement_rate is None
    assert result.claim_kind_agreement_rate is None


def test_compute_quorum_full_agreement_reports_rate_one():
    records = [_record("proceed", ["a", "b"]), _record("proceed", ["a", "b"])]
    result = sweep_mod.compute_quorum(records)
    assert result.n_draws == 2
    assert result.disposition_agreement_rate == 1.0
    assert result.claim_kind_agreement_rate == 1.0


def test_compute_quorum_partial_disagreement_reports_modal_fraction():
    records = [
        _record("proceed", ["a"]),
        _record("proceed", ["a", "b"]),
        _record("refuse", ["a"]),
    ]
    result = sweep_mod.compute_quorum(records)
    # modal disposition "proceed": 2 of 3 draws.
    assert result.disposition_agreement_rate == pytest.approx(2 / 3)
    # modal claim-kind signature {a:1,b:0,c:0}: draws 1 and 3, 2 of 3.
    assert result.claim_kind_agreement_rate == pytest.approx(2 / 3)


# --- aggregate_brief_cost -----------------------------------------------------


def test_aggregate_brief_cost_of_zero_records_is_the_honest_empty_summary():
    assert sweep_mod.aggregate_brief_cost([]) == {
        "by_pass": {},
        "total_tokens": 0,
        "total_usd": None,
    }


def test_aggregate_brief_cost_sums_per_pass_tokens_and_usd_across_draws():
    records = [
        _cost_record(
            {
                "interrogate": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "usd": 0.01,
                }
            }
        ),
        _cost_record(
            {
                "interrogate": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                    "usd": 0.02,
                }
            }
        ),
    ]
    result = sweep_mod.aggregate_brief_cost(records)
    assert result["by_pass"]["interrogate"] == {
        "prompt_tokens": 30,
        "completion_tokens": 10,
        "total_tokens": 40,
        "usd": pytest.approx(0.03),
    }
    assert result["total_tokens"] == 40
    assert result["total_usd"] == pytest.approx(0.03)


def test_aggregate_brief_cost_unpriced_pass_stays_null_never_a_fabricated_zero():
    records = [
        _cost_record(
            {
                "synthesize": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "usd": None,
                }
            }
        ),
        _cost_record(
            {
                "synthesize": {
                    "prompt_tokens": 20,
                    "completion_tokens": 5,
                    "total_tokens": 25,
                    "usd": None,
                }
            }
        ),
    ]
    result = sweep_mod.aggregate_brief_cost(records)
    assert result["by_pass"]["synthesize"]["usd"] is None
    assert result["by_pass"]["synthesize"]["total_tokens"] == 40
    assert result["total_tokens"] == 40
    assert result["total_usd"] is None


def test_aggregate_brief_cost_totals_only_the_passes_with_known_usd():
    records = [
        _cost_record(
            {
                "interrogate": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "usd": 0.01,
                },
                "synthesize": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "usd": None,
                },
            }
        )
    ]
    result = sweep_mod.aggregate_brief_cost(records)
    assert result["total_usd"] == pytest.approx(0.01)
    assert result["total_tokens"] == 30


# --- _run_one_draw: resume, failure isolation, fresh client per draw --------


def _draw_kwargs(sweep_dir: Path, client_factory) -> dict:
    return dict(
        client_factory=client_factory,
        sweep_dir=sweep_dir,
        vault_dir=None,
        envelopes_dir=None,
        config_path=Path("config/pipeline.yaml"),
        evals_dir=None,
        lenses_dir=None,
        step_budget=None,
        thin_result_floor=None,
    )


def test_run_one_draw_resumes_a_pair_whose_record_already_exists(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)
    sweep_dir = tmp_path / "sweep"
    record_file = sweep_mod._record_path(sweep_dir, "briefstem", 0, brief.brief_id)
    record_file.parent.mkdir(parents=True)
    stored = {"brief_id": brief.brief_id, "claims": []}
    record_file.write_text(json.dumps(stored), encoding="utf-8")

    def _explode(*_args, **_kwargs):
        raise AssertionError("a resumed draw must never call run_brief")

    monkeypatch.setattr(sweep_mod, "run_brief", _explode)

    outcome, record = sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(sweep_dir, lambda: object())
    )

    assert outcome.status == sweep_mod.SKIP_STATUS
    assert record == stored


def test_run_one_draw_records_a_declared_error_as_fail_and_does_not_raise(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    def _raise(*_args, **_kwargs):
        raise sweep_mod.AnswerError("boom")

    monkeypatch.setattr(sweep_mod, "run_brief", _raise)

    outcome, record = sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", lambda: object())
    )

    assert outcome.status == sweep_mod.FAIL_STATUS
    assert "boom" in outcome.reason
    assert record is None


def test_run_one_draw_propagates_an_undeclared_exception(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    def _raise(*_args, **_kwargs):
        raise RuntimeError("a genuine bug, not a recoverable per-draw outcome")

    monkeypatch.setattr(sweep_mod, "run_brief", _raise)

    with pytest.raises(RuntimeError):
        sweep_mod._run_one_draw(
            "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", lambda: object())
        )


def test_run_one_draw_builds_exactly_one_fresh_client_via_the_factory(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)
    built: list[object] = []

    def _factory():
        client = object()
        built.append(client)
        return client

    captured_clients: list[object] = []

    def _fake_run_brief(_brief, *, client, **_kwargs):
        captured_clients.append(client)
        record = {"brief_id": brief.brief_id}
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", _factory)
    )

    assert len(built) == 1
    assert captured_clients == built


# --- run_sweep orchestration ---------------------------------------------------


def test_run_sweep_rejects_a_non_positive_draws_count(tmp_path):
    worklist = tmp_path / "wl.txt"
    worklist.write_text("brief.yaml\n", encoding="utf-8")
    with pytest.raises(sweep_mod.SweepError):
        sweep_mod.run_sweep(worklist, draws=0, sweep_dir=tmp_path / "sweep")


def test_run_sweep_raises_sweep_error_for_an_unreadable_worklist(tmp_path):
    with pytest.raises(sweep_mod.SweepError):
        sweep_mod.run_sweep(tmp_path / "nope.txt", draws=1, sweep_dir=tmp_path / "sweep")


def _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path: dict[str, Brief]):
    """Replace `read_worklist`/`load_brief`/`run_brief`/`resolve_trusted`/
    `run_gate`/`write_report` with deterministic fakes so `run_sweep`'s own
    orchestration (draw multiplication, tallying, per-brief gate scoping) is
    pinned without a real LLM provider, vault, or gate computation."""
    monkeypatch.setattr(sweep_mod, "read_worklist", lambda _path: list(briefs_by_path))
    monkeypatch.setattr(sweep_mod, "load_brief", lambda path: briefs_by_path[path])

    def _fake_run_brief(brief, *, analyses_dir, **_kwargs):
        record = {
            "brief_id": brief.brief_id,
            "interrogation": {"disposition": "proceed"},
            "claims": [],
            "cost": {"by_pass": {}},
        }
        path = Path(analyses_dir) / f"{brief.brief_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        return _FakeBriefRunResult(record=record, path=path, markdown_path=path)

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)
    monkeypatch.setattr(sweep_mod, "resolve_trusted", lambda evals_dir=None: (None, False))

    gate_calls: list[tuple[str, int]] = []

    def _fake_run_gate(gate_name, records, **_kwargs):
        gate_calls.append((gate_name, len(records)))
        return sweep_mod.GateReport(gate=gate_name, corpus_pin=None, trusted=False, metrics=[])

    monkeypatch.setattr(sweep_mod, "run_gate", _fake_run_gate)
    monkeypatch.setattr(sweep_mod, "write_report", lambda report, reports_dir=None: Path("noop"))
    return gate_calls


def test_run_sweep_runs_every_brief_draws_times_and_scopes_gates_per_brief(tmp_path, monkeypatch):
    briefs_by_path = {
        "briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None),
        "briefB.yaml": Brief(brief_id="idB", case="B", request="rB", lens=None),
    }
    gate_calls = _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)

    summary = sweep_mod.run_sweep(
        "worklist-ignored-by-fake-read_worklist",
        draws=3,
        sweep_dir=tmp_path / "sweep",
        client_factory=lambda: object(),
    )

    assert summary.total_draws == 6  # 2 briefs x 3 draws
    assert summary.ok_count == 6
    assert summary.fail_count == 0
    assert summary.skip_count == 0
    assert len(summary.briefs) == 2
    for result in summary.briefs:
        assert len(result.draws) == 3
        assert all(outcome.status == sweep_mod.OK_STATUS for outcome in result.draws)
        assert result.quorum.n_draws == 3

    # 4 gates x 2 briefs, each scored over exactly that brief's own 3 draws
    # -- never pooled across briefs.
    assert len(gate_calls) == 2 * len(sweep_mod.SWEEP_GATE_NAMES)
    assert all(count == 3 for _gate_name, count in gate_calls)


def test_run_sweep_resume_across_two_invocations_skips_completed_pairs(tmp_path, monkeypatch):
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)
    sweep_dir = tmp_path / "sweep"

    first = sweep_mod.run_sweep("wl", draws=2, sweep_dir=sweep_dir, client_factory=lambda: object())
    assert first.ok_count == 2
    assert first.skip_count == 0

    second = sweep_mod.run_sweep(
        "wl", draws=2, sweep_dir=sweep_dir, client_factory=lambda: object()
    )
    assert second.ok_count == 0
    assert second.skip_count == 2
