"""Acceptance tests for issue #763's fourth "done when": `GET /me/profile`
reads a principal's own theme (`system` when they have never written one),
`PUT` then `GET` round-trips a choice, and one analyst's theme is invisible
to another.

Ownership here is proved the same way the rest of `tests/service` proves it
(`test_api.py`'s own `_client_as`): `authed_app` overrides `current_principal`
with a fixed principal per client, the FastAPI-native seam -- these tests are
about `ProfileStore`/the route's own behaviour, not token verification,
which `test_api_auth.py` covers on its own."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from axial.service.api import create_app
from axial.service.jobs import JobStore
from axial.service.profiles import DEFAULT_THEME


def _client_as(job_store: JobStore, authed_app, principal: str) -> TestClient:
    return TestClient(authed_app(create_app(job_store), principal))


def test_a_principal_with_no_row_reads_the_system_default(job_store: JobStore, authed_app):
    with _client_as(job_store, authed_app, "analyst-a") as client:
        response = client.get("/me/profile")

    assert response.status_code == 200
    assert response.json()["theme"] == DEFAULT_THEME == "system"


def test_put_then_get_round_trips_a_choice(job_store: JobStore, authed_app):
    with _client_as(job_store, authed_app, "analyst-a") as client:
        put_response = client.put("/me/profile", json={"theme": "dark"})
        get_response = client.get("/me/profile")

    assert put_response.status_code == 200
    assert put_response.json()["theme"] == "dark"
    assert get_response.json()["theme"] == "dark"


def test_a_second_write_changes_the_stored_choice(job_store: JobStore, authed_app):
    with _client_as(job_store, authed_app, "analyst-a") as client:
        client.put("/me/profile", json={"theme": "dark"})
        client.put("/me/profile", json={"theme": "light"})
        response = client.get("/me/profile")

    assert response.json()["theme"] == "light"


def test_one_analysts_theme_is_invisible_to_another(job_store: JobStore, authed_app):
    with _client_as(job_store, authed_app, "analyst-a") as client_a:
        client_a.put("/me/profile", json={"theme": "dark"})

    with _client_as(job_store, authed_app, "analyst-b") as client_b:
        response = client_b.get("/me/profile")

    assert response.json()["theme"] == DEFAULT_THEME


@pytest.mark.parametrize("bad_theme", ["blue", "", "Light", " dark"])
def test_an_invalid_theme_is_rejected(job_store: JobStore, authed_app, bad_theme: str):
    with _client_as(job_store, authed_app, "analyst-a") as client:
        response = client.put("/me/profile", json={"theme": bad_theme})

    assert response.status_code == 422
