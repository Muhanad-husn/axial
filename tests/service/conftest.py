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

import psycopg
import pytest

from axial.service.jobs import JobStore

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
