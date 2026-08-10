"""Acceptance test for issue #724's first "done when": `GET
/asks/{id}/paper` carries a metrics block beside the record, not inside
it -- exactly the four fields that exist on the §7.3 analysis record
(`cost`, `model_by_pass`, `coverage_map`, `confidence`), and never
`retries` or a shape band, which are Phase-C-only
(`src/axial/paper/record.py`) and do not exist on an ask's own record at
all."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from axial.service.api import create_app
from axial.service.jobs import JobStore

_METRICS_FIELDS = ("cost", "model_by_pass", "coverage_map", "confidence")


@pytest.fixture
def client(job_store: JobStore):
    with TestClient(create_app(job_store)) as test_client:
        yield test_client


def _record_with_metrics_fields() -> dict:
    return {
        "brief_id": "b1",
        "corpus_pin": "sim-2026-08-10",
        "claims": [{"claim_id": "c1", "text": "A claim", "kind": "a", "grounds": []}],
        "cost": {"total_usd": 0.13, "by_pass": {"interrogate": {"total_tokens": 500}}},
        "model_by_pass": {"interrogate": "gpt-x"},
        "coverage_map": {"Syria": {"corpus_note_count": 3, "evidence_note_count": 2}},
        "confidence": {"overall_band": "medium", "rationale": "because"},
        # A Phase-C-only field, hypothetically present -- proves the
        # metrics block is a field-selective extraction, not a blind copy
        # of everything that looks metrics-shaped.
        "retries": {"synthesize": 2},
    }


def test_paper_carries_a_metrics_block_beside_the_record_not_inside_it(
    client, job_store: JobStore, tmp_path: Path
):
    record = _record_with_metrics_fields()
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]
    job_store.claim()
    job_store.complete(job_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10")

    response = client.get(f"/asks/{job_id}/paper")

    assert response.status_code == 200
    body = response.json()
    # The record is served whole, at its own key...
    assert body["record"] == record
    # ...and the metrics block sits beside it, exactly the four fields.
    assert set(body["metrics"]) == set(_METRICS_FIELDS)
    assert body["metrics"]["cost"] == record["cost"]
    assert body["metrics"]["model_by_pass"] == record["model_by_pass"]
    assert body["metrics"]["coverage_map"] == record["coverage_map"]
    assert body["metrics"]["confidence"] == record["confidence"]
    # `retries` exists on the record (this test's own hypothetical) but is
    # never pulled into the metrics block -- it is Phase-C-only and an ask
    # produces no such field for real.
    assert "retries" not in body["metrics"]


def test_metrics_fields_are_none_when_the_record_carries_none_of_them(
    client, job_store: JobStore, tmp_path: Path
):
    """A record that predates any of the four fields (or one whose run
    never computed them) reports each as `None` -- an honest absence, not
    a missing key a client would have to guess about."""
    record = {"brief_id": "b1", "corpus_pin": "p", "claims": []}
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]
    job_store.claim()
    job_store.complete(job_id, result_ref=str(record_path), corpus_pin="p")

    metrics = client.get(f"/asks/{job_id}/paper").json()["metrics"]

    assert metrics == {
        "cost": None,
        "model_by_pass": None,
        "coverage_map": None,
        "confidence": None,
    }
