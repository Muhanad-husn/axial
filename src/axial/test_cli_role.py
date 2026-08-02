"""CLI-level tests for the two roles (issue #536): the operator is
unchanged and default; the analyst's whole reachable surface is `axial
ask`, neither listed in `--help` nor runnable for anything else."""

from __future__ import annotations

import pytest

from axial.cli import build_parser, main


def test_operator_is_the_default_role_and_sees_every_command(monkeypatch, capsys):
    monkeypatch.delenv("AXIAL_ROLE", raising=False)
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "intake" in captured.out
    assert "ask" in captured.out


def test_analyst_role_help_lists_only_ask(monkeypatch, capsys):
    monkeypatch.setenv("AXIAL_ROLE", "analyst")
    exit_code = main([])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "ask" in captured.out
    for pipeline_command in (
        "intake",
        "extract",
        "envelope",
        "chunk",
        "interrogate",
        "names",
        "key",
    ):
        assert pipeline_command not in captured.out


def test_analyst_role_cannot_run_a_pipeline_command(monkeypatch, capsys):
    """`intake` is not a recognised subcommand at all under the analyst
    role's pruned parser -- `argparse` rejects it exactly as it would any
    other unknown command, with a non-zero exit."""
    monkeypatch.setenv("AXIAL_ROLE", "analyst")
    with pytest.raises(SystemExit) as excinfo:
        main(["intake", "some.pdf"])
    captured = capsys.readouterr()
    assert excinfo.value.code != 0
    assert "invalid choice" in captured.err.lower()


def test_analyst_role_can_still_reach_ask(monkeypatch, capsys):
    import axial.cli as cli_mod

    monkeypatch.setenv("AXIAL_ROLE", "analyst")
    monkeypatch.setattr(cli_mod, "list_past_turns", lambda: [])

    exit_code = cli_mod.main(["ask", "--list"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "no past questions yet" in captured.out


def test_an_invalid_role_errors_before_any_parsing(monkeypatch, capsys):
    monkeypatch.setenv("AXIAL_ROLE", "superuser")
    exit_code = main(["ask", "--list"])
    captured = capsys.readouterr()
    assert exit_code != 0
    assert "AXIAL_ROLE" in captured.err


def test_operator_role_parser_is_unaffected_by_the_analyst_prune(monkeypatch):
    """A fresh `build_parser()` call still recognises every command after an
    analyst-role `main()` call pruned a DIFFERENT parser instance -- the
    prune must never mutate shared, module-level state."""
    monkeypatch.setenv("AXIAL_ROLE", "analyst")
    main(["ask", "--list"])

    monkeypatch.delenv("AXIAL_ROLE", raising=False)
    parser = build_parser()
    args = parser.parse_args(["intake", "some.pdf"])
    assert args.command == "intake"
