"""CLI-level tests for `axial ask` (issue #534): the thin dispatch layer
over `axial.ask.ask`. The engine itself is stubbed throughout (via
`cli_mod.ask_question`) -- this file proves the CLI wires case/question/
session/follow-up correctly and never spends money doing it, mirroring
`test_cli.py`'s own `monkeypatch.setattr(cli_mod, ...)` convention."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief


def _turn(session_id: str, turn_index: int, question: str, case: str) -> Turn:
    brief = Brief(brief_id=f"id-{turn_index}", case=case, request=question)
    result = BriefRunResult(
        record={"claims": [], "brief": {"case": case, "request": question}},
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
