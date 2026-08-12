"""Fixtures for tests/service (issue #681). No test-DB convention already
exists in this repo (checked: no docker-compose, no testcontainers, no
Postgres fixture anywhere under tests/ or src/) so this is the new one,
kept as small as the acceptance bar allows.

The issue's own bar is "test with a real concurrent run... not a mock", so
these tests run against a real Postgres, never sqlite or an in-memory
stand-in (SQLite has no `FOR UPDATE SKIP LOCKED`, which is the exact
mechanism under test). `DATABASE_URL`, when set, is used as-is; otherwise a
`postgres:16-alpine` container is started via the `docker` CLI for the test
session -- no `testcontainers` dependency added since a `docker run`/
`docker rm` pair is the entire need. GitHub Actions' `ubuntu-latest` runners
ship Docker pre-installed and running, so this also self-serves in CI
without any workflow change.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import psycopg
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from jwt.algorithms import RSAAlgorithm

from axial.context import DEFAULT_PRINCIPAL
from axial.service.api import current_principal
from axial.service.auth import JWKS_URL_ENV_VAR
from axial.service.cache import PaperCache
from axial.service.jobs import JobStore
from axial.service.profiles import ProfileStore
from axial.service.quotas import QuotaStore

_IMAGE = "postgres:16-alpine"


def _docker_available() -> bool:
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=True)
    except Exception:
        return False
    return True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_postgres(dsn: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2):
                return
        except Exception as exc:  # noqa: BLE001 - retried until timeout, then raised
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Postgres container never became ready: {last_error}")


@pytest.fixture(scope="session")
def postgres_dsn() -> Iterator[str]:
    env_dsn = os.environ.get("DATABASE_URL")
    if env_dsn:
        yield env_dsn
        return

    if not _docker_available():
        pytest.skip(
            "tests/service needs a real Postgres: set DATABASE_URL, or make "
            "`docker` available so a postgres:16-alpine container can be started"
        )

    port = _free_port()
    name = f"axial-jobs-test-{uuid.uuid4().hex[:8]}"
    dsn = f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            name,
            "-e",
            "POSTGRES_PASSWORD=postgres",
            "-p",
            f"{port}:5432",
            _IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_for_postgres(dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@pytest.fixture
def job_store(postgres_dsn: str) -> JobStore:
    """A `JobStore` over a fresh, empty `jobs` table -- schema created if
    missing, then truncated, so each test starts from zero rows regardless
    of what an earlier test in the session left behind."""
    store = JobStore(postgres_dsn)
    store.create_schema()
    with psycopg.connect(postgres_dsn) as conn:
        # CASCADE: `job_events` (issue #683) carries a foreign key onto
        # `jobs`, so a plain `TRUNCATE jobs` is rejected by Postgres unless
        # the referencing table is truncated along with it.
        conn.execute("TRUNCATE jobs CASCADE")
    return store


@pytest.fixture(autouse=True)
def quota_store(postgres_dsn: str) -> QuotaStore:
    """A `QuotaStore` (issue #686) over a fresh, empty `quotas` table --
    same shape as `job_store` above, but `autouse`: `create_app` builds its
    own `QuotaStore` over `store.dsn` whenever a test's own `client` fixture
    doesn't pass one (every pre-#686 test in this package), so an override
    `set_limits` writes in one test (`test_api_quota.py`) would otherwise
    silently outlive it and leak into any later test asking as the same
    default principal -- the same isolation `TRUNCATE jobs` already gives
    `job_store`, just not opt-in here since the table is touched whether or
    not a test names it."""
    store = QuotaStore(postgres_dsn)
    store.create_schema()
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("TRUNCATE quotas")
    return store


@pytest.fixture
def authed_app():
    """A callable that overrides `current_principal` (issue #763's own
    identity seam) with a fixed principal -- `app.dependency_overrides`,
    the FastAPI-native mechanism the issue itself names, so verifying a
    real token stays this one dependency's job and every other test in
    this package keeps the pre-#763 single-local-analyst behaviour it was
    written against, with no dev-principal environment variable added to
    production code. Returns `app` itself so a call site can wrap
    `create_app(...)` inline: `authed_app(create_app(store))`."""

    def _authed(app: FastAPI, principal: str = DEFAULT_PRINCIPAL) -> FastAPI:
        app.dependency_overrides[current_principal] = lambda: principal
        return app

    return _authed


@pytest.fixture
def paper_cache(postgres_dsn: str) -> PaperCache:
    """A `PaperCache` (issue #686) over a fresh, empty `paper_cache` table
    -- same shape as `job_store` above."""
    cache = PaperCache(postgres_dsn)
    cache.create_schema()
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("TRUNCATE paper_cache")
    return cache


@pytest.fixture(autouse=True)
def profile_store(postgres_dsn: str) -> ProfileStore:
    """A `ProfileStore` (issue #763) over a fresh, empty `profiles` table --
    same shape as `job_store` above, `autouse` for the same reason
    `quota_store` is (its own docstring): `create_app` builds its own
    `ProfileStore` over `store.dsn` whenever a test's own `client` fixture
    doesn't pass one, so a `PUT /me/profile` write in one test would
    otherwise silently outlive it and leak into a later test reading the
    same default principal's theme."""
    store = ProfileStore(postgres_dsn)
    store.create_schema()
    with psycopg.connect(postgres_dsn) as conn:
        conn.execute("TRUNCATE profiles")
    return store


@pytest.fixture
def supabase_jwt(monkeypatch: pytest.MonkeyPatch):
    """A locally-minted Supabase-shaped JWT, for the four "done when"s
    issue #763 says to prove without a live project: a real RSA keypair
    generated here, its public half published as a JWKS dict, and
    `jwt.PyJWKClient.fetch_data` monkeypatched to return it -- so
    `axial.service.auth` fetches this test's own key set exactly the way
    it would fetch a real project's, with no network call underneath.

    The JWKS URL is unique per call (a fresh UUID) so `axial.service.auth.
    _jwks_client`'s `lru_cache(maxsize=1)` never hands one test's cached
    client, keyed on the URL, to another. `AXIAL_SUPABASE_JWKS_URL` is set
    via `monkeypatch.setenv`, so it reverts automatically at teardown.

    Returns an object with `.mint(sub=..., **claim_overrides)` (a signed
    token, `exp` one hour out and `iss`/`aud` correct by default -- a
    caller overrides only the claim its own test is about) and `.kid`, for
    a test that wants to mint a "wrong key" token under the SAME `kid` a
    legitimate signer would use."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = f"test-{uuid.uuid4().hex[:8]}"
    jwk = RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    jwk["kid"] = kid
    jwk["alg"] = "RS256"
    jwk["use"] = "sig"
    jwks = {"keys": [jwk]}

    jwks_url = f"https://{uuid.uuid4().hex}.supabase.co/auth/v1/.well-known/jwks.json"
    issuer = jwks_url.removesuffix("/.well-known/jwks.json")

    monkeypatch.setenv(JWKS_URL_ENV_VAR, jwks_url)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda self: jwks)

    def _mint(
        *,
        sub: str = "11111111-1111-4111-8111-111111111111",
        signing_key: rsa.RSAPrivateKey = private_key,
        headers: dict | None = None,
        **claim_overrides: object,
    ) -> str:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": sub,
            "aud": "authenticated",
            "iss": issuer,
            "iat": now,
            "exp": now + timedelta(hours=1),
            **claim_overrides,
        }
        return jwt.encode(claims, signing_key, algorithm="RS256", headers=headers or {"kid": kid})

    return SimpleNamespace(mint=_mint, kid=kid, jwks_url=jwks_url, issuer=issuer)
