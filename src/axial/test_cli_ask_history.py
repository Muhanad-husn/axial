"""CLI-level tests for `axial ask --list`/`--reopen` (issue #536): finding
and reopening a past question without a `brief_id` or a file path, and
never spending money doing it. `axial.ask.history` is stubbed throughout
(via `cli_mod.list_past_turns`/`cli_mod.load_turn`), mirroring
`test_cli_ask.py`'s own `monkeypatch.setattr(cli_mod, ...)` convention --
this file proves the CLI's own wiring, not the history module (covered by
`axial/ask/test_history.py`)."""

from __future__ import annotations

from axial.ask.history import PastTurn


def _turn(brief_id: str = "brf_1", case: str = "Syria", question: str = "Who led the uprising?"):
    return PastTurn(
        brief_id=brief_id,
        asked_at=1_700_000_000.0,
        case=case,
        question=question,
        disposition="proceeded",
        cross_source_rate=0.5,
    )


def _record_and_report(case: str = "Syria", question: str = "Who led the uprising?"):
    record = {
        "brief_id": "brf_1",
        "brief": {"case": case, "request": question, "lens": None},
        "interrogation": {"disposition": "proceed"},
        "claims": [],
        "coverage_map": {},
        "confidence": {"overall_band": "medium", "rationale": "r"},
    }
    report = {"operational": {}, "response_quality": {}}
    return record, report


def test_build_parser_recognises_list_and_reopen_flags():
    from axial.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["ask", "--list"])
    assert args.list_past is True
    assert args.reopen is None

    args = parser.parse_args(["ask", "--reopen", "2"])
    assert args.list_past is False
    assert args.reopen == 2


def test_list_never_constructs_a_client_or_prompts(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "list_past_turns", lambda: [_turn()])

    def _boom_client():
        raise AssertionError("--list must never construct a client")

    def _boom_input(label=""):
        raise AssertionError("--list must never prompt")

    monkeypatch.setattr(cli_mod, "get_client", _boom_client)
    monkeypatch.setattr(cli_mod, "input", _boom_input, raising=False)

    exit_code = cli_mod.main(["ask", "--list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Syria" in captured.out
    assert "Who led the uprising?" in captured.out


def test_list_with_no_past_questions_says_so_plainly(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "list_past_turns", lambda: [])
    monkeypatch.setattr(cli_mod, "get_client", lambda: (_ for _ in ()).throw(AssertionError()))

    exit_code = cli_mod.main(["ask", "--list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "no past questions yet" in captured.out


def test_reopen_by_number_renders_the_answer_with_no_brief_id_typed(monkeypatch, capsys):
    import axial.cli as cli_mod

    calls: list[str] = []

    def _fake_load_turn(brief_id):
        calls.append(brief_id)
        return _record_and_report()

    def _boom_client():
        raise AssertionError("--reopen must never construct a client")

    monkeypatch.setattr(cli_mod, "list_past_turns", lambda: [_turn()])
    monkeypatch.setattr(cli_mod, "load_turn", _fake_load_turn)
    monkeypatch.setattr(cli_mod, "get_client", _boom_client)

    exit_code = cli_mod.main(["ask", "--reopen", "1"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert calls == ["brf_1"]  # reopened by NUMBER, resolved to the brief_id internally
    assert "Syria" in captured.out
    assert "Who led the uprising?" in captured.out


def test_reopen_an_out_of_range_number_errors_without_a_traceback(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setattr(cli_mod, "list_past_turns", lambda: [_turn()])

    exit_code = cli_mod.main(["ask", "--reopen", "5"])
    captured = capsys.readouterr()

    assert exit_code != 0
    assert "no past question numbered 5" in captured.err
