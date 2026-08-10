"""The HTTP surface (issue #682): submit an ask, poll it, fetch the paper,
list your own asks. Every test drives the real FastAPI app over the real
`JobStore` and the real Postgres fixture -- the only thing ever stubbed is
the paid engine run itself.

`GET /asks/{id}/paper` serves the §7.3 analysis record an ask produces
(`BriefRunResult.record`, persisted at the job's `result_ref`), not a
Phase-C paper -- that is a separate pipeline that runs off an analysis
record. The route path is the issue's own, and #687's client is written
against it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from axial.service.api import DEFAULT_PRINCIPAL, create_app, current_principal
from axial.service.jobs import DONE, QUEUED, JobStore


@pytest.fixture
def client(job_store: JobStore):
    with TestClient(create_app(job_store)) as test_client:
        yield test_client


def test_post_asks_queues_a_job_without_running_it(client, job_store: JobStore):
    response = client.post("/asks", json={"case": "Syria, 2011-2024", "request": "Who led it?"})

    assert response.status_code == 202
    job_id = response.json()["id"]
    assert response.json()["state"] == QUEUED

    row = job_store.get(job_id)
    assert row["state"] == QUEUED
    assert row["kind"] == "ask"
    assert row["principal"] == DEFAULT_PRINCIPAL
    assert row["payload"]["case"] == "Syria, 2011-2024"
    assert row["payload"]["question"] == "Who led it?"
    assert row["claimed_at"] is None


def test_post_asks_carries_the_optional_weights_lens_and_session(client, job_store: JobStore):
    response = client.post(
        "/asks",
        json={
            "case": "Syria",
            "request": "Who led it?",
            "weights": {"batatu-1999": 2.0},
            "lens": "political-economy",
            "session_id": "session-7",
        },
    )

    payload = job_store.get(response.json()["id"])["payload"]
    assert payload["weights"] == {"batatu-1999": 2.0}
    assert payload["lens"] == "political-economy"
    assert payload["session_id"] == "session-7"


def test_post_asks_rejects_a_blank_case_or_request(client):
    assert client.post("/asks", json={"case": "   ", "request": "Q"}).status_code == 422
    assert client.post("/asks", json={"case": "Syria", "request": "  "}).status_code == 422


def test_get_ask_reports_state_timings_pin_and_result_reference(client, job_store: JobStore):
    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]

    queued = client.get(f"/asks/{job_id}").json()
    assert queued["state"] == QUEUED
    assert queued["created_at"] is not None
    assert queued["claimed_at"] is None
    assert queued["finished_at"] is None
    assert queued["corpus_pin"] is None
    assert queued["result_ref"] is None

    job_store.claim()
    job_store.complete(job_id, result_ref="data/analyses/abc.json", corpus_pin="sim-2026-08-10")

    done = client.get(f"/asks/{job_id}").json()
    assert done["state"] == DONE
    assert done["claimed_at"] is not None
    assert done["finished_at"] is not None
    assert done["corpus_pin"] == "sim-2026-08-10"
    assert done["result_ref"] == "data/analyses/abc.json"


def test_get_ask_is_404_for_an_unknown_id(client):
    assert client.get("/asks/does-not-exist").status_code == 404


def test_get_paper_serves_the_persisted_record_as_json(client, job_store: JobStore, tmp_path: Path):
    record = {"brief_id": "b1", "corpus_pin": "sim-2026-08-10", "claims": [{"text": "A claim"}]}
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]
    job_store.claim()
    job_store.complete(job_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10")

    response = client.get(f"/asks/{job_id}/paper")

    assert response.status_code == 200
    assert response.json() == record


def test_get_paper_is_409_while_the_ask_is_not_finished(client):
    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]

    response = client.get(f"/asks/{job_id}/paper")

    assert response.status_code == 409
    assert QUEUED in response.json()["detail"]


def test_get_paper_is_409_for_a_failed_ask(client, job_store: JobStore):
    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]
    job_store.claim()
    job_store.fail(job_id, error="engine blew up")

    assert client.get(f"/asks/{job_id}/paper").status_code == 409


def test_get_paper_is_404_for_an_unknown_id(client):
    assert client.get("/asks/does-not-exist/paper").status_code == 404


def test_list_asks_returns_the_callers_own_asks_newest_first(client):
    first = client.post("/asks", json={"case": "Syria", "request": "First"}).json()["id"]
    second = client.post("/asks", json={"case": "Syria", "request": "Second"}).json()["id"]
    third = client.post("/asks", json={"case": "Syria", "request": "Third"}).json()["id"]

    listed = client.get("/asks").json()

    assert [ask["id"] for ask in listed] == [third, second, first]


def test_list_asks_excludes_another_principals_asks(client, job_store: JobStore):
    job_store.enqueue(
        kind="ask", principal="someone-else", payload={"case": "Syria", "question": "Theirs"}
    )
    mine = client.post("/asks", json={"case": "Syria", "request": "Mine"}).json()["id"]

    listed = client.get("/asks").json()

    assert [ask["id"] for ask in listed] == [mine]


def test_the_principal_comes_from_an_overridable_dependency(job_store: JobStore):
    """#688 lands real identity by replacing this one dependency. Until
    then every request is the same local analyst -- proved here by
    overriding it, which is exactly the seam #688 takes over."""
    app = create_app(job_store)
    app.dependency_overrides[current_principal] = lambda: "analyst-42"

    with TestClient(app) as client:
        job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]

    assert job_store.get(job_id)["principal"] == "analyst-42"


# -- ownership (issue #685) --------------------------------------------------


def _client_as(job_store: JobStore, principal: str) -> TestClient:
    app = create_app(job_store)
    app.dependency_overrides[current_principal] = lambda: principal
    return TestClient(app)


def test_analyst_a_cannot_read_analyst_bs_ask_by_id_even_guessing_it_correctly(
    job_store: JobStore,
):
    """The issue's own acceptance line, verbatim. B's ask id is not
    secret here -- A gets it exactly right -- and the refusal still has to
    come from `can_access` (ownership), never from an accident of how the
    row was queried."""
    with _client_as(job_store, "analyst-b") as client_b:
        bs_ask_id = client_b.post(
            "/asks", json={"case": "Syria", "request": "B's question"}
        ).json()["id"]

    with _client_as(job_store, "analyst-a") as client_a:
        assert client_a.get(f"/asks/{bs_ask_id}").status_code == 404
        assert client_a.get(f"/asks/{bs_ask_id}/events").status_code == 404


def test_analyst_a_cannot_read_analyst_bs_paper_by_id(job_store: JobStore, tmp_path):
    record = {"brief_id": "b1", "corpus_pin": "sim-2026-08-10", "claims": [{"text": "B's claim"}]}
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with _client_as(job_store, "analyst-b") as client_b:
        bs_ask_id = client_b.post(
            "/asks", json={"case": "Syria", "request": "B's question"}
        ).json()["id"]
    job_store.claim()
    job_store.complete(bs_ask_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10")

    with _client_as(job_store, "analyst-a") as client_a:
        response = client_a.get(f"/asks/{bs_ask_id}/paper")

    assert response.status_code == 404


def test_analyst_b_can_still_read_their_own_ask_and_paper(job_store: JobStore, tmp_path):
    """The refusal above is about ownership, not a blanket ban on by-id
    reads -- the owner themself must still be able to read it."""
    record = {"brief_id": "b1", "corpus_pin": "sim-2026-08-10", "claims": [{"text": "B's claim"}]}
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with _client_as(job_store, "analyst-b") as client_b:
        bs_ask_id = client_b.post(
            "/asks", json={"case": "Syria", "request": "B's question"}
        ).json()["id"]
        job_store.claim()
        job_store.complete(bs_ask_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10")

        assert client_b.get(f"/asks/{bs_ask_id}").status_code == 200
        paper = client_b.get(f"/asks/{bs_ask_id}/paper")
        assert paper.status_code == 200
        assert paper.json() == record
