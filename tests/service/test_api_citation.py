"""The citation rendering mode (issue #690): `passage` (the quoted passage,
additive on top of the locator) is the served default since issue #785, and
`locator` (book + chapter/section, no book text) is one `AXIAL_CITATION_MODE`
environment value away -- no client-supplied parameter can choose either, and
no code changes between the two.

**Two premise corrections drive this file's shape.** First, there is no
page number anywhere in this system -- `axial.query.store`'s `notes` table
carries `section`/`chapter`, never a page, so a locator is built from those
plus the source's own `author`/`title`/`date` (`sources` table). Second, a
claim's `grounds` (`axial.answer.record._claim_to_dict`) and a
`counter_position`'s own `grounds` (`axial.analyze.synthesis`) are already
`{ref_type, ref_id}` pointers with no quoted text -- `GET /asks/{id}/paper`
already meets `locator` mode's "no book text" bar with the record
untouched. `passage` mode is therefore additive: it attaches a `citation`
block to each `chunk` ground, `quote` included only in `passage` mode.

**Issue #724 wrapped `GET /asks/{id}/paper`'s response as `{"record":
..., "metrics": ...}`** -- every assertion below that used to read the
response body directly now reads `response["record"]` instead; the
citation rendering itself is unchanged, still applied to the record
before this issue's wrapping ever happens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from axial.query import store as note_store
from axial.service.api import create_app
from axial.service.citation import (
    CITATION_MODE_ENV_VAR,
    InvalidCitationModeError,
    PASSAGE,
)
from axial.service.jobs import JobStore

CHUNK_ID = "alpha-1999_1_intro_001"
SOURCE_ID = "alpha-1999"
PASSAGE_TEXT = "The regime's coercive apparatus expanded after 1979."


def _build_vault(root: Path) -> Path:
    """A real vault: `notes.db` (`notes`/`sources` joined by `source_id`)
    plus the one prose note `<vault_dir>/prose/<chunk_id>.md` -- the two
    things a citation resolves against, per the module docstring."""
    vault_dir = root / "vault"
    note_store.write_store(
        vault_dir / "notes.db",
        sources=[(SOURCE_ID, "Author A", "The Book", "1999", 1999)],
        notes=[(CHUNK_ID, SOURCE_ID, "Introduction", "Chapter 1: Origins", "claim text", None, 0)],
        names=[],
        note_names=[],
        note_arguing_against=[],
        note_citations=[],
    )
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    (prose_dir / f"{CHUNK_ID}.md").write_text(
        "---\n"
        f"chunk_id: {CHUNK_ID}\n"
        "section: Introduction\n"
        f'chunk_text: "{PASSAGE_TEXT}"\n'
        "source_meta: {author: Author A, title: The Book, date: '1999'}\n"
        "---\n\nbody\n",
        encoding="utf-8",
    )
    return vault_dir


def _record_with_grounds() -> dict:
    return {
        "brief_id": "b1",
        "corpus_pin": "sim-2026-08-10",
        "claims": [
            {
                "claim_id": "c1",
                "text": "The regime's coercive apparatus expanded.",
                "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_ID}],
            }
        ],
        "counter_position": {
            "present": True,
            "stance": "opponents dispute the timing",
            "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_ID}],
        },
    }


def _write_record(tmp_path: Path, record: dict) -> Path:
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(record), encoding="utf-8")
    return record_path


def _submit_and_complete(client: TestClient, job_store: JobStore, record_path: Path) -> str:
    job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]
    job_store.claim()
    job_store.complete(job_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10")
    return job_id


def test_the_unconfigured_default_is_passage(
    job_store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authed_app
):
    """Issue #785: an install that has configured nothing quotes the books
    it argues from. `locator` did not go away -- it stopped being the mode a
    deployer gets without deciding."""
    monkeypatch.delenv(CITATION_MODE_ENV_VAR, raising=False)
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path, _record_with_grounds())

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        record = client.get(f"/asks/{job_id}/paper").json()["record"]

    assert record["claims"][0]["grounds"][0]["citation"]["quote"] == PASSAGE_TEXT


def test_locator_mode_carries_no_book_text(
    job_store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authed_app
):
    monkeypatch.setenv(CITATION_MODE_ENV_VAR, "locator")
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path, _record_with_grounds())

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        paper = client.get(f"/asks/{job_id}/paper").json()
    record = paper["record"]

    citation = record["claims"][0]["grounds"][0]["citation"]
    assert citation["chapter"] == "Chapter 1: Origins"
    assert citation["section"] == "Introduction"
    assert citation["author"] == "Author A"
    assert citation["title"] == "The Book"
    assert "quote" not in citation
    # Verified against the response BODY, not the UI, per the issue's own
    # "done when" -- the passage text is nowhere in the served JSON,
    # record or metrics block alike.
    assert PASSAGE_TEXT not in json.dumps(paper)


def test_passage_mode_adds_the_quoted_text_on_claims_and_counter_position(
    job_store: JobStore, tmp_path: Path, authed_app
):
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path, _record_with_grounds())

    with TestClient(
        authed_app(create_app(job_store, citation_mode=PASSAGE, vault_dir=vault_dir))
    ) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        record = client.get(f"/asks/{job_id}/paper").json()["record"]

    assert record["claims"][0]["grounds"][0]["citation"]["quote"] == PASSAGE_TEXT
    assert record["counter_position"]["grounds"][0]["citation"]["quote"] == PASSAGE_TEXT


def test_flipping_to_passage_is_one_env_var_no_code_change(
    job_store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authed_app
):
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path, _record_with_grounds())
    monkeypatch.setenv(CITATION_MODE_ENV_VAR, "passage")

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        record = client.get(f"/asks/{job_id}/paper").json()["record"]

    assert record["claims"][0]["grounds"][0]["citation"]["quote"] == PASSAGE_TEXT


def test_unrecognised_citation_mode_is_a_startup_error_naming_both_modes(
    job_store: JobStore, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(CITATION_MODE_ENV_VAR, "verbatim")

    with pytest.raises(InvalidCitationModeError) as excinfo:
        create_app(job_store)

    assert "locator" in str(excinfo.value)
    assert "passage" in str(excinfo.value)


def test_a_client_cannot_override_the_mode_on_the_request(
    job_store: JobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, authed_app
):
    """Applied at the API boundary (the issue's own line): a request that
    tries to ask for `passage` from a `locator` deployment has no field to
    put it in -- `AskRequest` carries no citation-mode key at all."""
    monkeypatch.setenv(CITATION_MODE_ENV_VAR, "locator")
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path, _record_with_grounds())

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        response = client.post(
            "/asks",
            json={"case": "Syria", "request": "Q", "citation_mode": "passage"},
        )
        job_id = response.json()["id"]
        job_store.claim()
        job_store.complete(job_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10")
        record = client.get(f"/asks/{job_id}/paper").json()["record"]

    assert "quote" not in record["claims"][0]["grounds"][0]["citation"]


def test_a_record_with_no_grounds_is_served_unchanged(
    job_store: JobStore, tmp_path: Path, authed_app
):
    """The pre-#690 shape (mirrors `test_api.py`'s own
    `test_get_paper_serves_the_persisted_record_as_json`): a record whose
    claims carry no `grounds` key at all has nothing to resolve, and comes
    back byte-for-byte -- inside the `record` key issue #724 wraps it in."""
    record = {"brief_id": "b1", "corpus_pin": "p", "claims": [{"text": "A claim"}]}
    record_path = _write_record(tmp_path, record)

    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        assert client.get(f"/asks/{job_id}/paper").json()["record"] == record
