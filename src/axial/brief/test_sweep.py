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
    # The §7.15 run report `run_brief` now writes alongside the record
    # (issue #491); the sweep carries its path onto each DrawOutcome.
    report: dict | None = None
    report_path: Path | None = None


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
        cases_dir=None,
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


def test_run_one_draw_records_an_ask_error_as_fail_and_does_not_raise(tmp_path, monkeypatch):
    """issue #572, PR 4 of 4: `AskError` (no map built at this pin, an
    encoder mismatch, an unusable door response) is `run_brief`'s own
    declared failure surface on a `--map` draw, exactly like `QueryError`/
    `SynthesisError` are on the name-layer path -- it must not crash the
    whole sweep."""
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    def _raise(*_args, **_kwargs):
        raise sweep_mod.AskError("no argument map built at this pin")

    monkeypatch.setattr(sweep_mod, "run_brief", _raise)

    outcome, record = sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", lambda: object())
    )

    assert outcome.status == sweep_mod.FAIL_STATUS
    assert "no argument map built" in outcome.reason
    assert record is None


def test_run_one_draw_forwards_arm_map_to_run_brief(tmp_path, monkeypatch):
    """issue #808, revised by #807: `arm="map"` reaches `run_brief` as the
    arm name itself, not as a boolean this module derived from it."""
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)
    captured = {}

    def _fake_run_brief(_brief, *, arm=None, **_kwargs):
        captured["arm"] = arm
        record = {"brief_id": brief.brief_id}
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    sweep_mod._run_one_draw(
        "briefstem.yaml",
        brief,
        0,
        arm="map",
        **_draw_kwargs(tmp_path / "sweep", lambda: object()),
    )

    assert captured["arm"] == "map"


def test_run_one_draw_default_arm_is_name_layer(tmp_path, monkeypatch):
    """No `arm` given is byte-identical in behaviour to today's default:
    the name-layer loop."""
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)
    captured = {}

    def _fake_run_brief(_brief, *, arm=None, **_kwargs):
        captured["arm"] = arm
        record = {"brief_id": brief.brief_id}
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", lambda: object())
    )

    assert captured["arm"] == "name"


def test_run_one_draw_records_the_arm_on_the_draw_outcome(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    def _fake_run_brief(_brief, *, use_map=False, **_kwargs):
        record = {"brief_id": brief.brief_id}
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    outcome, _record = sweep_mod._run_one_draw(
        "briefstem.yaml",
        brief,
        0,
        arm="map",
        **_draw_kwargs(tmp_path / "sweep", lambda: object()),
    )

    assert outcome.arm == "map"


def test_run_one_draw_forwards_the_map_vocab_arm_rather_than_collapsing_it(
    tmp_path, monkeypatch
):
    """issue #807: the third arm reaches `run_brief` as `map+vocab`, and the
    `DrawOutcome` records the same string.

    This is the regression #808's own boolean collapse would have shipped:
    `use_map = arm == MAP_ARM` read `map+vocab` as `use_map=False` and ran
    the NAME layer, while the outcome still said `map+vocab`. #809 reads the
    arms off exactly these directories, so a sweep labelled one arm and
    holding another's draws produces a wrong comparison rather than a
    failure anyone would notice."""
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)
    captured = {}

    def _fake_run_brief(_brief, *, arm=None, **_kwargs):
        captured["arm"] = arm
        record = {"brief_id": brief.brief_id}
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    outcome, _record = sweep_mod._run_one_draw(
        "briefstem.yaml",
        brief,
        0,
        arm="map+vocab",
        **_draw_kwargs(tmp_path / "sweep", lambda: object()),
    )

    assert captured["arm"] == "map+vocab"
    assert outcome.arm == "map+vocab"


def test_run_one_draw_computes_distinct_sources_cited_from_source_usage(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    def _fake_run_brief(_brief, **_kwargs):
        record = {
            "brief_id": brief.brief_id,
            "source_usage": {"sources": [{"source_id": "src-a"}, {"source_id": "src-b"}]},
        }
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    outcome, _record = sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", lambda: object())
    )

    assert outcome.distinct_sources_cited == 2


def test_run_one_draw_distinct_sources_cited_is_none_for_a_failed_draw(tmp_path, monkeypatch):
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    def _raise(*_args, **_kwargs):
        raise sweep_mod.AnswerError("boom")

    monkeypatch.setattr(sweep_mod, "run_brief", _raise)

    outcome, record = sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 0, **_draw_kwargs(tmp_path / "sweep", lambda: object())
    )

    assert outcome.distinct_sources_cited is None
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


def test_run_one_draw_tags_a_run_id_aware_client_with_brief_stem_and_draw(tmp_path, monkeypatch):
    """A client exposing `set_run_id` (the real `OpenRouterClient`'s shape)
    is tagged with `"<brief_stem>:draw<n>"` before `run_brief` ever sees it
    -- the seam #362's benchmark table needs to attribute API time back to a
    brief. A client with no such method (every stub/record/exploding test
    double, and a bare `object()`) is simply left alone."""
    brief = Brief(brief_id="abc123", case="c", request="r", lens=None)

    class _FakeRunIdAwareClient:
        def __init__(self) -> None:
            self.run_id: str | None = None

        def set_run_id(self, run_id: str) -> None:
            self.run_id = run_id

    built_client = _FakeRunIdAwareClient()

    def _fake_run_brief(_brief, *, client, **_kwargs):
        assert client.run_id == "briefstem:draw2"
        record = {"brief_id": brief.brief_id}
        return _FakeBriefRunResult(record=record, path=Path("x.json"), markdown_path=Path("x.md"))

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    sweep_mod._run_one_draw(
        "briefstem.yaml", brief, 2, **_draw_kwargs(tmp_path / "sweep", lambda: built_client)
    )

    assert built_client.run_id == "briefstem:draw2"


# --- run_sweep orchestration ---------------------------------------------------


def test_run_sweep_rejects_a_non_positive_draws_count(tmp_path):
    worklist = tmp_path / "wl.txt"
    worklist.write_text("brief.yaml\n", encoding="utf-8")
    with pytest.raises(sweep_mod.SweepError):
        sweep_mod.run_sweep(worklist, draws=0, sweep_dir=tmp_path / "sweep")


def test_run_sweep_raises_sweep_error_for_an_unreadable_worklist(tmp_path):
    with pytest.raises(sweep_mod.SweepError):
        sweep_mod.run_sweep(tmp_path / "nope.txt", draws=1, sweep_dir=tmp_path / "sweep")


_FAKE_COMMIT_SHA = "deadbeefcafefeed0000111122223333deadbeef"


def _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path: dict[str, Brief]):
    """Replace `read_worklist`/`load_brief`/`run_brief`/`resolve_trusted`/
    `run_gate`/`write_report`/`_current_commit_sha` with deterministic fakes
    so `run_sweep`'s own orchestration (draw multiplication, tallying,
    per-brief gate scoping) is pinned without a real LLM provider, vault,
    gate computation, or a subprocess call to `git`."""
    monkeypatch.setattr(sweep_mod, "read_worklist", lambda _path: list(briefs_by_path))
    monkeypatch.setattr(sweep_mod, "load_brief", lambda path: briefs_by_path[path])
    monkeypatch.setattr(sweep_mod, "_current_commit_sha", lambda: _FAKE_COMMIT_SHA)

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
        assert all(outcome.arm == "name" for outcome in result.draws)
        assert result.quorum.n_draws == 3

    # 4 gates x 2 briefs, each scored over exactly that brief's own 3 draws
    # -- never pooled across briefs.
    assert len(gate_calls) == 2 * len(sweep_mod.SWEEP_GATE_NAMES)
    assert all(count == 3 for _gate_name, count in gate_calls)

    # issue #808: a plain sweep with neither `arm` nor `use_map` given runs
    # the (default) "name" arm, and the sweep's own summary records it plus
    # the commit `run_sweep` ran at.
    assert summary.arm == "name"
    assert summary.commit == _FAKE_COMMIT_SHA


def test_run_sweep_forwards_use_map_to_every_draws_run_brief(tmp_path, monkeypatch):
    """issue #572, PR 4 of 4: `run_sweep(use_map=True)` -- the seam
    `axial.brief.smoke.run_smoke(use_map=True)` uses -- reaches every single
    `(brief, draw)` pair's own `run_brief` call, not just the first. The
    legacy boolean is resolved to `arm="map"` once, in `run_sweep` itself
    (issue #807), so what every draw actually receives is the arm name."""
    briefs_by_path = {
        "briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None),
        "briefB.yaml": Brief(brief_id="idB", case="B", request="rB", lens=None),
    }
    monkeypatch.setattr(sweep_mod, "read_worklist", lambda _path: list(briefs_by_path))
    monkeypatch.setattr(sweep_mod, "load_brief", lambda path: briefs_by_path[path])
    monkeypatch.setattr(sweep_mod, "resolve_trusted", lambda evals_dir=None: (None, False))

    captured_arms: list[str | None] = []

    def _fake_run_brief(brief, *, analyses_dir, arm=None, **_kwargs):
        captured_arms.append(arm)
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

    sweep_mod.run_sweep(
        "worklist-ignored-by-fake-read_worklist",
        draws=2,
        sweep_dir=tmp_path / "sweep",
        client_factory=lambda: object(),
        score_gates=False,
        use_map=True,
    )

    assert captured_arms == ["map"] * 4  # 2 briefs x 2 draws


def test_run_sweep_forwards_arm_map_to_every_draws_run_brief(tmp_path, monkeypatch):
    """issue #808, revised by #807: `arm="map"` -- the CLI's own named-arm
    seam -- reaches every single `(brief, draw)` pair's own `run_brief`
    call as the arm name, the same guarantee the legacy `use_map=True`
    keyword already had."""
    briefs_by_path = {
        "briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None),
        "briefB.yaml": Brief(brief_id="idB", case="B", request="rB", lens=None),
    }
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)

    captured_call_arm: list[str | None] = []
    captured_arm: list[str] = []

    def _fake_run_brief(brief, *, analyses_dir, arm=None, **_kwargs):
        captured_call_arm.append(arm)
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

    summary = sweep_mod.run_sweep(
        "worklist-ignored-by-fake-read_worklist",
        draws=2,
        sweep_dir=tmp_path / "sweep",
        client_factory=lambda: object(),
        score_gates=False,
        arm="map",
    )

    assert captured_call_arm == ["map"] * 4  # 2 briefs x 2 draws
    assert summary.arm == "map"
    for result in summary.briefs:
        captured_arm.extend(outcome.arm for outcome in result.draws)
    assert captured_arm == ["map", "map", "map", "map"]


def test_run_sweep_arm_takes_precedence_over_use_map_when_both_given(tmp_path, monkeypatch):
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)

    summary = sweep_mod.run_sweep(
        "wl",
        draws=1,
        sweep_dir=tmp_path / "sweep",
        client_factory=lambda: object(),
        score_gates=False,
        use_map=True,
        arm="name",
    )

    assert summary.arm == "name"
    assert summary.briefs[0].draws[0].arm == "name"


def test_run_sweep_accepts_an_arm_name_it_does_not_recognize(tmp_path, monkeypatch):
    """issue #808: `run_sweep` holds no list of valid arms -- an arm no
    lower layer has given meaning to yet is accepted, recorded verbatim on
    every draw and the summary, and simply runs the name-layer default
    today (only `arm == "map"` changes what `run_brief` does)."""
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)

    summary = sweep_mod.run_sweep(
        "wl",
        draws=1,
        sweep_dir=tmp_path / "sweep",
        client_factory=lambda: object(),
        score_gates=False,
        arm="map+vocab",
    )

    assert summary.arm == "map+vocab"
    assert summary.briefs[0].draws[0].arm == "map+vocab"


def test_run_sweep_persists_distinct_sources_cited_per_draw(tmp_path, monkeypatch):
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    monkeypatch.setattr(sweep_mod, "read_worklist", lambda _path: list(briefs_by_path))
    monkeypatch.setattr(sweep_mod, "load_brief", lambda path: briefs_by_path[path])
    monkeypatch.setattr(sweep_mod, "resolve_trusted", lambda evals_dir=None: (None, False))
    monkeypatch.setattr(sweep_mod, "_current_commit_sha", lambda: _FAKE_COMMIT_SHA)

    def _fake_run_brief(brief, *, analyses_dir, **_kwargs):
        record = {
            "brief_id": brief.brief_id,
            "interrogation": {"disposition": "proceed"},
            "claims": [],
            "cost": {"by_pass": {}},
            "source_usage": {"sources": [
                    {"source_id": "src-a"},
                    {"source_id": "src-b"},
                    {"source_id": "src-c"},
                ]},
        }
        path = Path(analyses_dir) / f"{brief.brief_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record), encoding="utf-8")
        return _FakeBriefRunResult(record=record, path=path, markdown_path=path)

    monkeypatch.setattr(sweep_mod, "run_brief", _fake_run_brief)

    summary = sweep_mod.run_sweep(
        "wl", draws=1, sweep_dir=tmp_path / "sweep", client_factory=lambda: object(),
        score_gates=False,
    )

    assert summary.briefs[0].draws[0].distinct_sources_cited == 3


def test_run_sweep_writes_an_arm_marker_file_into_sweep_dir(tmp_path, monkeypatch):
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)
    sweep_dir = tmp_path / "sweep"

    sweep_mod.run_sweep(
        "wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object(), arm="map"
    )

    marker = sweep_dir / sweep_mod.ARM_MARKER_FILENAME
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8").strip() == "map"


def test_run_sweep_resuming_the_same_arm_is_allowed(tmp_path, monkeypatch):
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)
    sweep_dir = tmp_path / "sweep"

    sweep_mod.run_sweep(
        "wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object(), arm="map"
    )
    second = sweep_mod.run_sweep(
        "wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object(), arm="map"
    )

    assert second.skip_count == 1
    assert second.arm == "map"


def test_run_sweep_refuses_to_resume_a_sweep_dir_under_a_different_arm(tmp_path, monkeypatch):
    """The acceptance criterion's own hard case (issue #808): a directory
    that already holds draws from one arm refuses a second invocation
    asking for a different one, naming the arm already there, and never
    attempts a single draw under the mismatched arm."""
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)
    sweep_dir = tmp_path / "sweep"

    sweep_mod.run_sweep(
        "wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object(), arm="map"
    )

    def _explode(*_args, **_kwargs):
        raise AssertionError("a refused arm mismatch must never run a draw")

    monkeypatch.setattr(sweep_mod, "run_brief", _explode)

    with pytest.raises(sweep_mod.SweepError, match="map"):
        sweep_mod.run_sweep(
            "wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object(), arm="name"
        )


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


# --- summary.json persistence -------------------------------------------------


def test_run_sweep_writes_a_machine_readable_summary_json(tmp_path, monkeypatch):
    """`run_sweep` writes `<sweep_dir>/summary.json` on every invocation --
    the same figures `format_sweep_summary` prints, but as data a later
    process can read back, never only surviving in a text console log."""
    briefs_by_path = {
        "briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None),
        "briefB.yaml": Brief(brief_id="idB", case="B", request="rB", lens=None),
    }
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)
    sweep_dir = tmp_path / "sweep"

    summary = sweep_mod.run_sweep(
        "wl", draws=3, sweep_dir=sweep_dir, client_factory=lambda: object()
    )

    summary_path = sweep_dir / "summary.json"
    assert summary_path.is_file()
    persisted = json.loads(summary_path.read_text(encoding="utf-8"))

    assert persisted["total_draws"] == summary.total_draws == 6
    assert persisted["ok_count"] == 6
    assert persisted["fail_count"] == 0
    assert persisted["skip_count"] == 0
    assert persisted["arm"] == summary.arm == "name"
    assert persisted["commit"] == summary.commit == _FAKE_COMMIT_SHA
    assert len(persisted["briefs"]) == 2
    for brief_entry in persisted["briefs"]:
        assert len(brief_entry["draws"]) == 3
        assert brief_entry["quorum"]["n_draws"] == 3
        # Every gate name present, JSON-shaped via GateReport.to_json().
        assert set(brief_entry["gate_reports"]) == set(sweep_mod.SWEEP_GATE_NAMES)
        for outcome in brief_entry["draws"]:
            assert outcome["status"] == sweep_mod.OK_STATUS
            assert outcome["latency_seconds"] is not None
            assert outcome["arm"] == "name"


def test_run_sweep_summary_json_carries_none_latency_for_a_resumed_draw(tmp_path, monkeypatch):
    """The exact gap the issue names: a resumed pair's `latency_seconds` is
    `None` in the persisted summary too (not fabricated), so a reader of
    `summary.json` can tell a SKIPped draw from a freshly-timed one."""
    briefs_by_path = {"briefA.yaml": Brief(brief_id="idA", case="A", request="rA", lens=None)}
    _install_fake_pipeline(monkeypatch, tmp_path, briefs_by_path)
    sweep_dir = tmp_path / "sweep"

    sweep_mod.run_sweep("wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object())
    sweep_mod.run_sweep("wl", draws=1, sweep_dir=sweep_dir, client_factory=lambda: object())

    persisted = json.loads((sweep_dir / "summary.json").read_text(encoding="utf-8"))
    outcome = persisted["briefs"][0]["draws"][0]
    assert outcome["status"] == sweep_mod.SKIP_STATUS
    assert outcome["latency_seconds"] is None


def test_write_sweep_summary_returns_the_written_path_and_creates_the_sweep_dir(tmp_path):
    summary = sweep_mod.SweepSummary(
        briefs=[], total_draws=0, ok_count=0, fail_count=0, skip_count=0
    )
    sweep_dir = tmp_path / "does-not-exist-yet"

    out_path = sweep_mod.write_sweep_summary(summary, sweep_dir)

    assert out_path == sweep_dir / "summary.json"
    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8")) == {
        "briefs": [],
        "total_draws": 0,
        "ok_count": 0,
        "fail_count": 0,
        "skip_count": 0,
        "arm": "name",
        "commit": None,
    }


def test_current_commit_sha_returns_a_git_sha_or_none():
    """Exercises the real `git rev-parse HEAD` path once (every other test
    monkeypatches this function away for determinism/speed): whatever it
    returns is either `None` (no git, no history) or a 40-character hex
    commit sha, never something else."""
    sha = sweep_mod._current_commit_sha()
    assert sha is None or (len(sha) == 40 and all(c in "0123456789abcdef" for c in sha))
