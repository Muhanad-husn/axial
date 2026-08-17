"""The citation mode itself: which mode an install starts in, and what an
unrecognised value does.

Issue #785 flipped the unconfigured default from `locator` to `passage`.
`tests/service/test_api_citation.py` covers the same seam through the real
API, but that file needs a Postgres container and so runs only in CI; the
resolution is pure, so it is pinned here too, in the fast tier.
"""

from __future__ import annotations

import pytest

from axial.service.citation import (
    CITATION_MODE_ENV_VAR,
    LOCATOR,
    PASSAGE,
    InvalidCitationModeError,
    resolve_citation_mode,
)


def test_an_unconfigured_install_resolves_to_passage():
    assert resolve_citation_mode(env={}) == PASSAGE


def test_an_empty_value_resolves_to_passage():
    """`AXIAL_CITATION_MODE=` in a `.env` file. This already resolved to the
    old default before #785 -- an empty string is falsy, so it never reached
    the membership check."""
    assert resolve_citation_mode(env={CITATION_MODE_ENV_VAR: ""}) == PASSAGE


def test_a_whitespace_only_value_resolves_to_passage():
    """`AXIAL_CITATION_MODE=" "`. This one used to raise
    `InvalidCitationModeError` at startup: the value survived the `or`,
    stripped to `""`, and failed the membership check -- despite the
    docstring claiming blank was treated as unset. #785 makes the promise
    true."""
    assert resolve_citation_mode(env={CITATION_MODE_ENV_VAR: "   "}) == PASSAGE


def test_locator_is_still_selectable_by_the_deployer():
    assert resolve_citation_mode(env={CITATION_MODE_ENV_VAR: "locator"}) == LOCATOR


def test_an_explicit_argument_still_wins_over_the_environment():
    assert resolve_citation_mode(LOCATOR, env={CITATION_MODE_ENV_VAR: "passage"}) == LOCATOR


def test_an_unrecognised_value_raises_rather_than_falling_back():
    with pytest.raises(InvalidCitationModeError) as excinfo:
        resolve_citation_mode(env={CITATION_MODE_ENV_VAR: "verbatim"})

    assert LOCATOR in str(excinfo.value)
    assert PASSAGE in str(excinfo.value)
