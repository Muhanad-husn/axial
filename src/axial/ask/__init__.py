"""`axial ask` and its underlying engine function (issue #534,
specs/PHASE-B.md §7.1/§7.3). See `axial.ask.engine` for the design: a plain
`ask(question, case, ...)` function `axial ask` is the first caller of, and
the `Turn`/session shape a follow-up threads context through.
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

__all__ = [
    "AskError",
    "BlankCaseError",
    "BlankQuestionError",
    "Turn",
    "ask",
    "new_session_id",
]
