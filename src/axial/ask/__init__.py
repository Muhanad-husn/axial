"""`axial ask` and its underlying engine function (issue #534,
specs/PHASE-B.md §7.1/§7.3). See `axial.ask.engine` for the design: a plain
`ask(question, case, ...)` function `axial ask` is the first caller of, and
the `Turn`/session shape a follow-up threads context through.

`axial.ask.history` (issue #536) finds and reopens a past turn by what it
asked, never by its `brief_id`; `axial.ask.role` sets the two CLI roles
(operator/analyst) this package's asking surface is reachable under either
way.
"""

from __future__ import annotations

from axial.ask.engine import (
    AskError,
    BlankCaseError,
    BlankQuestionError,
    Turn,
    ask,
    new_session_id,
)
from axial.ask.history import PastTurn, list_past_turns, load_turn
from axial.ask.role import ANALYST, OPERATOR, InvalidRoleError, current_role

__all__ = [
    "AskError",
    "BlankCaseError",
    "BlankQuestionError",
    "Turn",
    "ask",
    "new_session_id",
    "PastTurn",
    "list_past_turns",
    "load_turn",
    "ANALYST",
    "OPERATOR",
    "InvalidRoleError",
    "current_role",
]
