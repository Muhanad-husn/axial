"""Acceptance tests for issue #763's "done when"s 1-3: `current_principal`
verifies a Supabase-issued JWT at the API edge, refusing anything that
isn't one, before any route body runs.

Every token here is minted locally against a real RSA keypair
(`supabase_jwt` fixture, `tests/service/conftest.py`) -- no live Supabase
project exists yet (#688's own kickoff note), and none of these tests makes
a network call: `jwt.PyJWKClient.fetch_data` is monkeypatched to hand back
this test's own key set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from axial.service.api import create_app
from axial.service.auth import verify_bearer_token
from axial.service.jobs import JobStore

_VALID_SUB = "11111111-1111-4111-8111-111111111111"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(job_store: JobStore) -> TestClient:
    # No `authed_app` override here -- these tests exercise the real
    # `current_principal` dependency, not the fixed-principal seam the rest
    # of tests/service overrides it with.
    with TestClient(create_app(job_store)) as test_client:
        yield test_client


def test_a_validly_signed_token_resolves_to_its_own_subject(
    client: TestClient, job_store: JobStore, supabase_jwt
):
    token = supabase_jwt.mint(sub=_VALID_SUB)

    response = client.post("/asks", json={"case": "Syria", "request": "Q"}, headers=_bearer(token))

    assert response.status_code == 202
    job_id = response.json()["id"]
    assert job_store.get(job_id)["principal"] == _VALID_SUB


def test_the_already_shipped_per_principal_routes_serve_that_principals_rows(
    client: TestClient, job_store: JobStore, supabase_jwt
):
    mine = supabase_jwt.mint(sub=_VALID_SUB)
    someone_else_sub = "22222222-2222-4222-8222-222222222222"
    theirs = supabase_jwt.mint(sub=someone_else_sub)

    their_ask_id = client.post(
        "/asks", json={"case": "Syria", "request": "Theirs"}, headers=_bearer(theirs)
    ).json()["id"]
    my_ask_id = client.post(
        "/asks", json={"case": "Syria", "request": "Mine"}, headers=_bearer(mine)
    ).json()["id"]

    listed = client.get("/asks", headers=_bearer(mine)).json()
    assert [ask["id"] for ask in listed] == [my_ask_id]

    # A guessed id for someone else's ask is refused by `can_access`
    # (issue #685), not merely absent from the list above.
    assert client.get(f"/asks/{their_ask_id}", headers=_bearer(mine)).status_code == 404


def test_no_token_at_all_is_401(client: TestClient):
    response = client.post("/asks", json={"case": "Syria", "request": "Q"})

    assert response.status_code == 401


def test_a_malformed_token_is_401(client: TestClient):
    response = client.post(
        "/asks", json={"case": "Syria", "request": "Q"}, headers=_bearer("not-a-jwt-at-all")
    )

    assert response.status_code == 401


def test_an_expired_token_is_401(client: TestClient, supabase_jwt):
    now = datetime.now(timezone.utc)
    expired = supabase_jwt.mint(
        sub=_VALID_SUB, iat=now - timedelta(hours=2), exp=now - timedelta(hours=1)
    )

    response = client.post(
        "/asks", json={"case": "Syria", "request": "Q"}, headers=_bearer(expired)
    )

    assert response.status_code == 401


def test_a_token_a_few_seconds_ahead_of_the_verifiers_clock_is_still_accepted(supabase_jwt):
    """Issue #767, live 2026-08-12: the verifying machine's clock trailed
    Supabase's by 5.0s, so a freshly-issued token's `iat` (and `nbf`, which
    Supabase also sets) landed a few seconds in the verifier's future and
    every request 401'd. Calls `verify_bearer_token` directly -- no
    `client`/`job_store` needed, since this is `leeway`'s own behaviour,
    not anything downstream of it."""
    now = datetime.now(timezone.utc)
    drifted = supabase_jwt.mint(
        sub=_VALID_SUB, iat=now + timedelta(seconds=5), nbf=now + timedelta(seconds=5)
    )

    assert verify_bearer_token(drifted) == _VALID_SUB


def test_a_token_expired_well_beyond_the_leeway_is_still_401(supabase_jwt):
    """Proves the 60s leeway added for #767 doesn't quietly widen into a
    real expiry hole: an hour-old `exp` is far outside 60s and must still
    be refused."""
    now = datetime.now(timezone.utc)
    expired = supabase_jwt.mint(
        sub=_VALID_SUB, iat=now - timedelta(hours=2), exp=now - timedelta(hours=1)
    )

    with pytest.raises(HTTPException) as exc_info:
        verify_bearer_token(expired)
    assert exc_info.value.status_code == 401


def test_a_token_signed_by_the_wrong_key_is_401(client: TestClient, supabase_jwt):
    impostor_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # Same `kid` a legitimate signer would use -- so lookup succeeds and it
    # is the SIGNATURE check that must catch this, not a missing key.
    forged = supabase_jwt.mint(sub=_VALID_SUB, signing_key=impostor_key)

    response = client.post("/asks", json={"case": "Syria", "request": "Q"}, headers=_bearer(forged))

    assert response.status_code == 401


@pytest.mark.parametrize("bad_subject", ["..", "a/b", "a\\b", "CON", "NUL", "trailing. "])
def test_a_subject_that_fails_the_shape_check_is_401_and_never_reaches_scoped_for_principal(
    client: TestClient, job_store: JobStore, supabase_jwt, bad_subject: str
):
    """Carried over from #685/#688: `..`, a path separator, or a
    Windows-reserved name is refused at the identity edge, not sanitised
    and forwarded -- proved here by the request never enqueuing a job
    (`scoped_for_principal` is never consulted because the dependency
    itself already raised)."""
    token = supabase_jwt.mint(sub=bad_subject)

    response = client.post("/asks", json={"case": "Syria", "request": "Q"}, headers=_bearer(token))

    assert response.status_code == 401
    assert job_store.list_for_principal(bad_subject) == []


def test_a_token_that_fails_the_shape_check_creates_no_job_row_for_any_principal(
    client: TestClient, job_store: JobStore, supabase_jwt
):
    token = supabase_jwt.mint(sub="../../etc")

    client.post("/asks", json={"case": "Syria", "request": "Q"}, headers=_bearer(token))

    with job_store.connection() as conn:
        (count,) = conn.execute("SELECT count(*) FROM jobs").fetchone()
    assert count == 0
