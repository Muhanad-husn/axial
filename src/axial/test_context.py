"""`RequestContext` (issue #685): a bare default carries the same single
local user every caller got before this existed, so building one with no
arguments changes nothing."""

from __future__ import annotations

from axial.context import DEFAULT_PRINCIPAL, RequestContext


def test_a_bare_context_is_the_default_local_principal_with_no_pin():
    context = RequestContext()

    assert context.principal == DEFAULT_PRINCIPAL
    assert context.corpus_pin is None


def test_a_context_carries_whatever_principal_and_pin_it_is_given():
    context = RequestContext(principal="analyst-42", corpus_pin="sim-2026-08-10")

    assert context.principal == "analyst-42"
    assert context.corpus_pin == "sim-2026-08-10"


def test_request_context_is_frozen():
    context = RequestContext()
    try:
        context.principal = "someone-else"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("RequestContext must be immutable")
