"""`GET /health` (issue #691): the corpus pin the workers are serving, read
off whatever published snapshot is mounted at this process's own cwd -- the
same cwd convention `vault_dir`/citation resolution already commits to
(`axial.service.api` module docstring, issue #690)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from axial.service.api import create_app
from axial.service.jobs import JobStore


@pytest.fixture
def client(job_store: JobStore):
    with TestClient(create_app(job_store)) as test_client:
        yield test_client


def test_health_needs_no_bearer_token(client):
    """Unauthenticated on purpose -- an orchestrator or a deployer's own
    monitoring polls this without a Supabase session."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_no_pin_when_nothing_is_mounted(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    response = client.get("/health")
    assert response.json() == {"status": "ok", "corpus_pin": None}


def test_health_names_the_mounted_snapshots_own_pin(
    client, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest = {
        "version": "v1",
        "corpus_pin": "sim-2026-07-30",
        "map_pin": None,
        "built_at": "2026-08-10T00:00:00Z",
        "sources": [],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    response = client.get("/health")

    assert response.json() == {"status": "ok", "corpus_pin": "sim-2026-07-30"}
