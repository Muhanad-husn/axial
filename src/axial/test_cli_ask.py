"""CLI-level tests for `axial ask` (issue #534): the thin dispatch layer
over `axial.ask.ask`. The engine itself is stubbed throughout (via
`cli_mod.ask_question`) -- this file proves the CLI wires case/question/
session/follow-up correctly and never spends money doing it, mirroring
`test_cli.py`'s own `monkeypatch.setattr(cli_mod, ...)` convention.

Since issue #668 a turn also ends in a drafted paper, so `run_paper` is
stubbed by the same convention -- `_stub_paper` below is autouse, because
drafting is now the default and every test in this file would otherwise
reach the Phase-C pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief


def _turn(
    session_id: str,
    turn_index: int,
    question: str,
    case: str,
    disposition: str = "proceed",
) -> Turn:
    brief = Brief(brief_id=f"id-{turn_index}", case=case, request=question)
    result = BriefRunResult(
        record={
            "brief_id": brief.brief_id,
            "claims": [],
            "brief": {"case": case, "request": question},
            "interrogation": {"disposition": disposition},
        },
        path=Path(f"data/analyses/{brief.brief_id}.json"),
        markdown_path=Path(f"data/analyses/{brief.brief_id}.md"),
        report={},
        report_path=Path(f"data/runs/{brief.brief_id}.json"),
    )
    return Turn(
        session_id=session_id,
        turn_index=turn_index,
        question=question,
        case=case,
        brief=brief,
        result=result,
    )


def _paper_record(paper_brief_id: str = "paper-1") -> dict[str, Any]:
    return {
        "paper_brief_id": paper_brief_id,
        "paper_markdown_path": f"data/papers/{paper_brief_id}.md",
        "corpus_pin": "sim-2026-07-30",
        "lens": "political-economy",
        "plan": {"sections": [{"section_id": "s1"}]},
        "claims": [{"paper_claim_id": "pc-001"}],
        "confidence": {"overall_band": "low"},
        "shape": {"band": "strong", "defects": []},
    }


@pytest.fixture(autouse=True)
def _stub_paper(monkeypatch):
    """Every `axial ask` turn drafts a paper since #668. Stub the pipeline
    for the whole file and hand each test the recorded calls, so no test
    here reaches Phase C or spends anything.

    Stubbed one layer lower than `axial.cli` since issue #784: the
    composition itself moved to `axial.ask.paper` so the service worker
    could run it too, and `run_paper` is what that module calls. Every
    assertion below is unchanged -- the recorded value is still the
    `PaperBrief` the composition built."""
    import axial.ask.paper as paper_mod

    calls: list[Any] = []

    def _fake_run_paper(client, paper_brief, **_):
        calls.append(paper_brief)
        return _paper_record()

    monkeypatch.setattr(paper_mod, "run_paper", _fake_run_paper)
    return calls


def test_build_parser_recognises_ask_with_question_and_case():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["ask", "Who led the uprising?", "--case", "Syria"])

    assert args.command == "ask"
    assert args.question == "Who led the uprising?"
    assert args.case == "Syria"


def test_build_parser_recognises_ask_with_nothing_given():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["ask"])

    assert args.command == "ask"
    assert args.question is None
    assert args.case is None


def test_build_parser_collects_repeated_weight_flags():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(
        ["ask", "Q", "--case", "Syria", "--weight", "beshara-2011=0.1", "--weight", "vignal-2021=2"]
    )

    assert args.weight == ["beshara-2011=0.1", "vignal-2021=2"]


def test_build_parser_weight_defaults_to_none_when_omitted():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["ask"])

    assert args.weight is None


def test_one_shot_ask_answers_and_exits_without_any_prompt(monkeypatch, capsys):
    """Issue #534 acceptance: `axial ask "..." --case "..."` runs one turn
    and exits -- no interactive prompt at all."""
    import axial.cli as cli_mod

    calls: list[dict[str, Any]] = []

    def _fake_ask(question, case, **kwargs):
        calls.append({"question": question, "case": case, **kwargs})
        return _turn("sess-1", 1, question, case)

    def _boom_input(label=""):
        raise AssertionError("one-shot ask must never prompt")

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())
    monkeypatch.setattr(cli_mod, "input", _boom_input, raising=False)

    exit_code = cli_mod.main(["ask", "Who led the uprising?", "--case", "Syria"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0]["question"] == "Who led the uprising?"
    assert calls[0]["case"] == "Syria"
    assert calls[0]["previous"] is None
    assert "persisted:" in captured.out


def test_one_shot_ask_reports_an_engine_error_and_exits_nonzero(monkeypatch, capsys):
    import axial.cli as cli_mod
    from axial.ask.engine import AskError as AskSessionError

    def _fake_ask(question, case, **kwargs):
        raise AskSessionError("simulated engine failure")

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "A question", "--case", "Syria"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "simulated engine failure" in captured.err


def test_interactive_session_carries_the_first_turn_forward_as_previous(monkeypatch, capsys):
    """A follow-up in an interactive session passes the first turn as
    `previous`, and a blank line ends the session (issue #534: "watch the
    work happen in plain words, read the answer, ask a follow-up")."""
    import axial.cli as cli_mod

    calls: list[dict[str, Any]] = []
    returned_turns: list[Turn] = []
    prompts = iter(["Syria", "Where did it start?", "Why did it spread?", ""])

    def _fake_input(label=""):
        return next(prompts)

    def _fake_ask(question, case, **kwargs):
        turn = _turn(kwargs.get("session_id") or "sess-x", kwargs["turn_index"], question, case)
        calls.append({"question": question, "case": case, "previous": kwargs.get("previous")})
        returned_turns.append(turn)
        return turn

    monkeypatch.setattr(cli_mod, "input", _fake_input, raising=False)
    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(calls) == 2
    assert calls[0]["case"] == "Syria"
    assert calls[0]["question"] == "Where did it start?"
    assert calls[0]["previous"] is None
    assert calls[1]["question"] == "Why did it spread?"
    # The second call's `previous` is exactly the first turn `ask_question`
    # returned -- proof the CLI threads a real prior turn forward, not a
    # placeholder.
    assert calls[1]["previous"] is returned_turns[0]
    assert "session ended." in captured.out


def test_a_blank_case_is_rejected_before_any_engine_call(monkeypatch, capsys):
    import axial.cli as cli_mod

    def _fake_input(label=""):
        return "   "

    def _boom(*args, **kwargs):
        raise AssertionError("must not run the engine on a blank case")

    monkeypatch.setattr(cli_mod, "input", _fake_input, raising=False)
    monkeypatch.setattr(cli_mod, "ask_question", _boom)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "case is required" in captured.err


def test_a_blank_question_ends_the_session_cleanly(monkeypatch, capsys):
    import axial.cli as cli_mod

    prompts = iter(["Syria", ""])

    def _fake_input(label=""):
        return next(prompts)

    def _boom(*args, **kwargs):
        raise AssertionError("must not run the engine on a blank question")

    monkeypatch.setattr(cli_mod, "input", _fake_input, raising=False)
    monkeypatch.setattr(cli_mod, "ask_question", _boom)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "nothing to do" in captured.out


# --- issue #639: --weight parsing and threading -----------------------------


def test_parse_weight_args_returns_empty_dict_when_none_given():
    from axial.cli import _parse_weight_args

    assert _parse_weight_args(None) == {}


def test_parse_weight_args_parses_repeated_flags():
    from axial.cli import _parse_weight_args

    assert _parse_weight_args(["beshara-2011=0.1", "vignal-2021=2"]) == {
        "beshara-2011": 0.1,
        "vignal-2021": 2.0,
    }


def test_parse_weight_args_a_later_repeat_of_the_same_source_wins():
    from axial.cli import _parse_weight_args

    assert _parse_weight_args(["beshara-2011=0.1", "beshara-2011=0.5"]) == {"beshara-2011": 0.5}


def test_parse_weight_args_rejects_a_missing_equals_sign():
    from axial.cli import WeightArgError, _parse_weight_args

    try:
        _parse_weight_args(["beshara-2011"])
        assert False, "expected WeightArgError"
    except WeightArgError as exc:
        assert "beshara-2011" in str(exc)


def test_parse_weight_args_rejects_a_non_numeric_value():
    from axial.cli import WeightArgError, _parse_weight_args

    try:
        _parse_weight_args(["beshara-2011=big"])
        assert False, "expected WeightArgError"
    except WeightArgError:
        pass


def test_parse_weight_args_rejects_a_negative_value():
    from axial.cli import WeightArgError, _parse_weight_args

    try:
        _parse_weight_args(["beshara-2011=-1"])
        assert False, "expected WeightArgError"
    except WeightArgError:
        pass


def test_a_malformed_weight_flag_is_rejected_before_any_engine_call(monkeypatch, capsys):
    import axial.cli as cli_mod

    def _boom(*args, **kwargs):
        raise AssertionError("must not run the engine on a malformed --weight")

    monkeypatch.setattr(cli_mod, "ask_question", _boom)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "Q", "--case", "Syria", "--weight", "not-a-valid-weight"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "invalid --weight" in captured.err


def test_a_well_formed_weight_flag_reaches_ask_question(monkeypatch, capsys):
    import axial.cli as cli_mod

    calls: list[dict[str, Any]] = []

    def _fake_ask(question, case, **kwargs):
        calls.append(kwargs)
        return _turn("sess-1", 1, question, case)

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "Q", "--case", "Syria", "--weight", "beshara-2011=0.1"])

    assert exit_code == 0
    assert calls[0]["weights"] == {"beshara-2011": 0.1}


def test_no_weight_flag_passes_an_empty_dict_to_ask_question(monkeypatch, capsys):
    import axial.cli as cli_mod

    calls: list[dict[str, Any]] = []

    def _fake_ask(question, case, **kwargs):
        calls.append(kwargs)
        return _turn("sess-1", 1, question, case)

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "Q", "--case", "Syria"])

    assert exit_code == 0
    assert calls[0]["weights"] == {}


# ---------------------------------------------------------------------------
# Issue #668: a question ends in a paper
# ---------------------------------------------------------------------------


def test_build_parser_recognises_no_paper():
    from axial.cli import build_parser

    parser = build_parser()

    assert parser.parse_args(["ask", "Q", "--case", "Syria"]).no_paper is False
    assert parser.parse_args(["ask", "Q", "--case", "Syria", "--no-paper"]).no_paper is True


def test_ask_drafts_a_paper_from_the_turns_own_record(monkeypatch, capsys, _stub_paper):
    """Issue #668 acceptance: the question becomes the paper's thesis and the
    record the turn just persisted is its single source (PHASE-C §7.1)."""
    import axial.cli as cli_mod

    def _fake_ask(question, case, **kwargs):
        return _turn("sess-1", 1, question, case)

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "Who led the uprising?", "--case", "Syria"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert len(_stub_paper) == 1
    paper_brief = _stub_paper[0]
    assert paper_brief.thesis == "Who led the uprising?"
    assert paper_brief.analysis_ids == ("id-1",)
    assert paper_brief.lens is None
    assert paper_brief.paper_brief_id
    assert "paper_brief_id:" in captured.out
    assert "paper-1.md" in captured.out


def test_no_paper_skips_the_drafting_step(monkeypatch, capsys, _stub_paper):
    import axial.cli as cli_mod

    def _fake_ask(question, case, **kwargs):
        return _turn("sess-1", 1, question, case)

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "Q", "--case", "Syria", "--no-paper"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert _stub_paper == []
    assert "persisted:" in captured.out


def test_a_refused_record_is_never_drafted(monkeypatch, capsys, _stub_paper):
    """A refusal carries no claims and PHASE-C §7.1 rejects it at intake, so
    the turn ends at the answer rather than failing on a paper nobody can
    write."""
    import axial.cli as cli_mod

    def _fake_ask(question, case, **kwargs):
        return _turn("sess-1", 1, question, case, disposition="refuse")

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask", "Q", "--case", "Syria"])

    assert exit_code == 0
    assert _stub_paper == []


def test_a_failed_draft_does_not_lose_the_answer(monkeypatch, capsys, _stub_paper):
    """The answer is already on screen and already persisted when drafting
    runs. A drafting failure names itself and exits non-zero; it never
    swallows the turn."""
    import axial.ask.paper as paper_mod
    import axial.cli as cli_mod
    from axial.paper.draft import DraftError

    def _fake_ask(question, case, **kwargs):
        return _turn("sess-1", 1, question, case)

    def _boom(client, paper_brief, **_):
        raise DraftError("the drafter fell over")

    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())
    monkeypatch.setattr(paper_mod, "run_paper", _boom)

    exit_code = cli_mod.main(["ask", "Q", "--case", "Syria"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "persisted:" in captured.out
    assert "the drafter fell over" in captured.err


def test_every_turn_of_a_session_drafts_its_own_paper(monkeypatch, capsys, _stub_paper):
    import axial.cli as cli_mod

    replies = iter(["Syria", "first question", "second question", ""])

    def _fake_input(label=""):
        return next(replies)

    turns = iter([1, 2])

    def _fake_ask(question, case, **kwargs):
        return _turn("sess-1", next(turns), question, case)

    monkeypatch.setattr(cli_mod, "input", _fake_input, raising=False)
    monkeypatch.setattr(cli_mod, "ask_question", _fake_ask)
    monkeypatch.setattr(cli_mod, "get_client", lambda: object())

    exit_code = cli_mod.main(["ask"])

    assert exit_code == 0
    assert [b.thesis for b in _stub_paper] == ["first question", "second question"]
    assert [b.analysis_ids for b in _stub_paper] == [("id-1",), ("id-2",)]
