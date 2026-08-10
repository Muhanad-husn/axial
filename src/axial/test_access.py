"""`can_access` (issue #685): total, table-driven, in the style of
`axial.brief.interrogate.disposition_for`'s own test file. The load-bearing
case is the last one -- a correct id belonging to someone else is refused by
ownership, not merely absent from a list."""

from __future__ import annotations

import pytest

from axial.access import CORPUS, READ, WORK, WRITE, Resource, can_access
from axial.ask.role import ANALYST, OPERATOR


@pytest.mark.parametrize(
    ("principal", "role", "action", "resource", "expected"),
    [
        pytest.param(
            "op", OPERATOR, WRITE, Resource(CORPUS), True, id="operator-writes-the-corpus"
        ),
        pytest.param(
            "op",
            OPERATOR,
            WRITE,
            Resource(WORK, owner="someone-else"),
            True,
            id="operator-writes-anyones-work",
        ),
        pytest.param("alice", ANALYST, READ, Resource(CORPUS), True, id="analyst-reads-the-corpus"),
        pytest.param(
            "alice", ANALYST, WRITE, Resource(CORPUS), False, id="analyst-cannot-write-the-corpus"
        ),
        pytest.param(
            "alice",
            ANALYST,
            READ,
            Resource(WORK, owner="alice"),
            True,
            id="analyst-reads-their-own-work",
        ),
        pytest.param(
            "alice",
            ANALYST,
            WRITE,
            Resource(WORK, owner="alice"),
            True,
            id="analyst-writes-their-own-work",
        ),
        pytest.param(
            "alice",
            ANALYST,
            READ,
            Resource(WORK, owner="bob"),
            False,
            id="a-correct-id-for-someone-elses-work-is-still-refused",
        ),
        pytest.param(
            "alice", "guest", READ, Resource(CORPUS), False, id="an-unknown-role-is-refused"
        ),
    ],
)
def test_can_access_is_total_and_table_driven(principal, role, action, resource, expected):
    assert can_access(principal, role, action, resource) is expected
