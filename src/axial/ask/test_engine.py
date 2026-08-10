"""Acceptance tests for `axial.ask.engine.ask` (issue #534): a question and
a case go in, a full engine run comes out, with no brief file ever
authored -- and a follow-up folds the previous turn's question and claims
into its own request text rather than answering from memory. The engine
itself (`run_brief`) is stubbed throughout: this module tests `ask`'s own
seam -- what it builds, what it passes through, what a follow-up carries
forward -- never the real, paid pipeline (per issue #534: "prove the whole
flow against a stubbed engine")."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from axial.answer.record import BriefRunResult
from axial.ask.engine import (
    BlankCaseError,
    BlankQuestionError,
    Turn,
    ask,
    new_session_id,
)
from axial.brief.intake import Brief
from axial.context import RequestContext


class _FakeClient:
    """`ask` never calls the client directly -- it only threads it through
    to `run_brief_fn` -- so an opaque sentinel is enough."""


def _stub_result(claims: list[dict[str, Any]] | None = None) -> BriefRunResult:
    record: dict[str, Any] = {"claims": claims if claims is not None else []}
    return BriefRunResult(
        record=record,
        path=Path("data/analyses/stub.json"),
        markdown_path=Path("data/analyses/stub.md"),
        report={},
        report_path=Path("data/runs/stub.json"),
    )


def _recording_run_brief(calls: list[dict[str, Any]], result: BriefRunResult | None = None):
    def _fake(brief, **kwargs):
        calls.append({"brief": brief, **kwargs})
        return result if result is not None else _stub_result()

    return _fake


def test_ask_builds_a_brief_from_case_and_question_with_no_file_authored():
    calls: list[dict[str, Any]] = []
    turn = ask(
        "Who led the uprising?",
        "Syria, 2011-2024",
        client=_FakeClient(),
        run_brief_fn=_recording_run_brief(calls),
    )

    assert isinstance(turn, Turn)
    assert turn.case == "Syria, 2011-2024"
    assert turn.question == "Who led the uprising?"
    assert isinstance(turn.brief, Brief)
    assert turn.brief.case == "Syria, 2011-2024"
    assert turn.brief.request == "Who led the uprising?"
    assert len(calls) == 1
    assert calls[0]["brief"] is turn.brief


def test_ask_assigns_a_fresh_session_id_when_none_given():
    turn_a = ask("Q1", "Case", client=_FakeClient(), run_brief_fn=_recording_run_brief([]))
    turn_b = ask("Q2", "Case", client=_FakeClient(), run_brief_fn=_recording_run_brief([]))

    assert turn_a.session_id
    assert turn_b.session_id
    assert turn_a.session_id != turn_b.session_id


def test_ask_threads_a_given_session_id_through_to_the_engine_call():
    calls: list[dict[str, Any]] = []
    session_id = new_session_id()

    turn = ask(
        "Q1",
        "Case",
        client=_FakeClient(),
        session_id=session_id,
        run_brief_fn=_recording_run_brief(calls),
    )

    assert turn.session_id == session_id
    assert calls[0]["session_id"] == session_id


def test_ask_forwards_on_event_to_the_engine_call():
    calls: list[dict[str, Any]] = []

    def _on_event(message: str, detail: dict[str, Any]) -> None:
        pass

    ask(
        "Q1",
        "Case",
        client=_FakeClient(),
        on_event=_on_event,
        run_brief_fn=_recording_run_brief(calls),
    )

    assert calls[0]["on_event"] is _on_event


def test_blank_case_is_rejected():
    with pytest.raises(BlankCaseError):
        ask("A question", "   ", client=_FakeClient(), run_brief_fn=_recording_run_brief([]))


def test_blank_question_is_rejected():
    with pytest.raises(BlankQuestionError):
        ask("  ", "A case", client=_FakeClient(), run_brief_fn=_recording_run_brief([]))


def test_a_followup_folds_the_previous_question_and_claims_into_the_request():
    first_result = _stub_result(
        claims=[{"text": "The uprising began in Daraa."}, {"text": "It spread within weeks."}]
    )
    calls: list[dict[str, Any]] = []
    first = ask(
        "Where did it start?",
        "Syria",
        client=_FakeClient(),
        run_brief_fn=_recording_run_brief(calls, first_result),
    )

    followup = ask(
        "Why did it spread so fast?",
        "Syria",
        client=_FakeClient(),
        session_id=first.session_id,
        turn_index=2,
        previous=first,
        run_brief_fn=_recording_run_brief(calls, _stub_result()),
    )

    assert followup.session_id == first.session_id
    assert followup.turn_index == 2
    # The follow-up's own brief carries the prior context in its request --
    # the acceptance rule (issue #534): a follow-up is a full run of its
    # own, never a chat turn answering from memory of the last one, so the
    # context has to travel INTO the new brief that gets interrogated and
    # retrieved against, not sit outside it.
    assert "Where did it start?" in followup.brief.request
    assert "The uprising began in Daraa." in followup.brief.request
    assert "It spread within weeks." in followup.brief.request
    assert "Why did it spread so fast?" in followup.brief.request
    # The case is carried forward unchanged, same as any other turn.
    assert followup.brief.case == "Syria"


def test_a_followup_after_a_claimless_turn_states_that_plainly():
    calls: list[dict[str, Any]] = []
    first = ask(
        "An unanswerable question",
        "Syria",
        client=_FakeClient(),
        run_brief_fn=_recording_run_brief(calls, _stub_result(claims=[])),
    )

    followup = ask(
        "A follow-up anyway",
        "Syria",
        client=_FakeClient(),
        previous=first,
        run_brief_fn=_recording_run_brief(calls, _stub_result()),
    )

    assert "reached no claims" in followup.brief.request


def test_a_followup_is_a_full_run_with_its_own_distinct_brief_id():
    calls: list[dict[str, Any]] = []
    first = ask(
        "Q1", "Case", client=_FakeClient(), run_brief_fn=_recording_run_brief(calls, _stub_result())
    )
    followup = ask(
        "Q2",
        "Case",
        client=_FakeClient(),
        previous=first,
        run_brief_fn=_recording_run_brief(calls, _stub_result()),
    )

    # Two full, distinct engine runs -- never the same persisted record.
    assert first.brief.brief_id != followup.brief.brief_id
    assert len(calls) == 2


# --- issue #639: weights fold into this turn's own brief -------------------


def test_ask_with_no_weights_yields_an_empty_weights_dict_on_the_brief():
    turn = ask(
        "Q1", "Case", client=_FakeClient(), run_brief_fn=_recording_run_brief([], _stub_result())
    )
    assert turn.brief.weights == {}


def test_ask_folds_weights_into_the_turns_own_brief():
    turn = ask(
        "Q1",
        "Case",
        client=_FakeClient(),
        weights={"beshara-2011": 0.1},
        run_brief_fn=_recording_run_brief([], _stub_result()),
    )
    assert turn.brief.weights == {"beshara-2011": 0.1}


def test_ask_with_weights_changes_the_brief_id_from_the_unweighted_one():
    plain = ask(
        "Q1", "Case", client=_FakeClient(), run_brief_fn=_recording_run_brief([], _stub_result())
    )
    weighted = ask(
        "Q1",
        "Case",
        client=_FakeClient(),
        weights={"beshara-2011": 0.1},
        run_brief_fn=_recording_run_brief([], _stub_result()),
    )
    assert plain.brief.brief_id != weighted.brief.brief_id


def test_a_followup_does_not_inherit_the_prior_turns_weights_automatically():
    """The analyst supplies weights with the question they go with (module
    docstring) -- a follow-up that passes none of its own gets none, even
    when the turn before it carried some."""
    first = ask(
        "Q1",
        "Case",
        client=_FakeClient(),
        weights={"beshara-2011": 0.1},
        run_brief_fn=_recording_run_brief([], _stub_result()),
    )
    followup = ask(
        "Q2",
        "Case",
        client=_FakeClient(),
        previous=first,
        run_brief_fn=_recording_run_brief([], _stub_result()),
    )
    assert followup.brief.weights == {}


def test_ask_is_reachable_as_a_function_without_the_cli():
    """Issue #534's own acceptance line: "the engine is reachable as a
    function, not only as a command." No CLI machinery is imported or
    exercised anywhere in this module."""
    turn = ask(
        "A direct question",
        "A direct case",
        client=_FakeClient(),
        run_brief_fn=_recording_run_brief([]),
    )
    assert turn.result.record == {"claims": []}


# -- RequestContext (issue #685) ---------------------------------------------


def test_ask_with_no_context_resolves_the_same_dirs_as_before_685(tmp_path):
    """`context=None` (every call site before this parameter existed,
    `axial ask` among them) must resolve to exactly the same directories a
    caller who never heard of `RequestContext` would get."""
    from axial.paths import default_analyses_dir, default_runs_dir

    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "paths:\n  analyses_dir: data/analyses\n  runs_dir: data/runs\n", encoding="utf-8"
    )
    calls: list[dict[str, Any]] = []

    ask(
        "Q",
        "Case",
        client=_FakeClient(),
        config_path=config,
        run_brief_fn=_recording_run_brief(calls),
    )

    assert calls[0]["analyses_dir"] == default_analyses_dir(config)
    assert calls[0]["runs_dir"] == default_runs_dir(config)


def test_ask_with_a_context_scopes_analyses_and_runs_dirs_to_its_principal(tmp_path):
    config = tmp_path / "pipeline.yaml"
    config.write_text(
        "paths:\n  analyses_dir: data/analyses\n  runs_dir: data/runs\n", encoding="utf-8"
    )
    calls: list[dict[str, Any]] = []

    ask(
        "Q",
        "Case",
        client=_FakeClient(),
        config_path=config,
        context=RequestContext(principal="analyst-42"),
        run_brief_fn=_recording_run_brief(calls),
    )

    assert calls[0]["analyses_dir"] == Path("data/analyses") / "analyst-42"
    assert calls[0]["runs_dir"] == Path("data/runs") / "analyst-42"


def test_ask_context_never_overrides_explicit_directories(tmp_path):
    """A caller that already supplies its own `analyses_dir`/`runs_dir`
    (the worker, bound to a published snapshot, per
    `axial.service.worker.run_ask_job`) is unaffected by `context` --
    those directories are never corpus-config-relative."""
    calls: list[dict[str, Any]] = []
    explicit_analyses = tmp_path / "work" / "analyses"
    explicit_runs = tmp_path / "work" / "runs"

    ask(
        "Q",
        "Case",
        client=_FakeClient(),
        analyses_dir=explicit_analyses,
        runs_dir=explicit_runs,
        context=RequestContext(principal="analyst-42"),
        run_brief_fn=_recording_run_brief(calls),
    )

    assert calls[0]["analyses_dir"] == explicit_analyses
    assert calls[0]["runs_dir"] == explicit_runs
