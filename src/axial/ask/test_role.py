"""Unit tests for `axial.ask.role` (issue #536): the two CLI roles,
self-hosted, defaulting to operator."""

from __future__ import annotations

import pytest

from axial.ask.role import ANALYST, OPERATOR, InvalidRoleError, current_role


def test_role_defaults_to_operator_when_unset(monkeypatch):
    monkeypatch.delenv("AXIAL_ROLE", raising=False)
    assert current_role() == OPERATOR


def test_role_defaults_to_operator_when_blank(monkeypatch):
    monkeypatch.setenv("AXIAL_ROLE", "  ")
    assert current_role() == OPERATOR


def test_role_reads_analyst_case_insensitively(monkeypatch):
    monkeypatch.setenv("AXIAL_ROLE", "Analyst")
    assert current_role() == ANALYST


def test_an_unrecognised_role_raises_a_named_error(monkeypatch):
    monkeypatch.setenv("AXIAL_ROLE", "superuser")
    with pytest.raises(InvalidRoleError):
        current_role()
