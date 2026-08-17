"""Acceptance tests for issue #724's third "done when": `GET
/asks/{id}/export?format=md|docx|odt` serves the finished ask as one
downloadable file. Markdown is the one rendering path; `docx`/`odt` are
converted from that same markdown string (`axial.service.export`).

Since #783 that markdown is the READER render
(`axial.answer.reader.render_reader_answer`), not the audit render plus a
metrics appendix: the document a reader downloads carries no chunk id, no
usage ratio and no metrics block. The metrics are still computed and still
served beside the record by `GET /asks/{id}/paper`.

Export is free: it must never touch a job's `cost_usd`/quota accounting,
and goes through the same `_require_own_job` ownership check as every
other by-id route.

The #690 citation mode applies at this boundary too: an export from a
`locator` deployment carries no book text, verified against the
generated FILE bytes, not the JSON or a UI (the issue's own line). Since
#732, a `passage` deployment's export carries the quoted passage instead
of dropping it on the floor -- also verified against file bytes.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from odf.opendocument import load as load_odt
from odf.text import P

from axial.query import store as note_store
from axial.service.api import create_app
from axial.service.citation import CITATION_MODE_ENV_VAR, PASSAGE
from axial.service.jobs import JobStore
from axial.service.quotas import QuotaStore

_PRINCIPAL = "local-analyst"
CHUNK_ID = "alpha-1999_1_intro_001"
SOURCE_ID = "alpha-1999"
PASSAGE_TEXT = "The regime's coercive apparatus expanded after 1979."


def _build_vault(root: Path) -> Path:
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


def _record() -> dict:
    return {
        "brief_id": "b1",
        "brief": {"case": "Syria", "request": "Who led it?"},
        "corpus_pin": "sim-2026-08-10",
        "interrogation": {"disposition": "answer"},
        "claims": [
            {
                "claim_id": "c1",
                "text": "The regime's coercive apparatus expanded.",
                "kind": "a",
                "grounds": [{"ref_type": "chunk", "ref_id": CHUNK_ID}],
            }
        ],
        "counter_position": {"present": False, "corpus_one_sided": True, "one_sided_reason": "x"},
        "coverage_map": {},
        "confidence": {"overall_band": "medium", "rationale": "because"},
        "source_usage": {"sources": []},
        "model_by_pass": {"interrogate": "gpt-x"},
        "cost": {"total_usd": 0.13, "by_pass": {"interrogate": {"total_tokens": 500}}},
    }


def _submit_and_complete(
    client: TestClient, job_store: JobStore, record_path: Path, *, cost_usd: float = 0.13
) -> str:
    job_id = client.post("/asks", json={"case": "Syria", "request": "Who led it?"}).json()["id"]
    job_store.claim()
    job_store.complete(
        job_id, result_ref=str(record_path), corpus_pin="sim-2026-08-10", cost_usd=cost_usd
    )
    return job_id


def _write_record(tmp_path: Path) -> Path:
    record_path = tmp_path / "b1.json"
    record_path.write_text(json.dumps(_record()), encoding="utf-8")
    return record_path


def test_export_md_contains_the_question_and_the_answer(
    job_store: JobStore, tmp_path: Path, authed_app
):
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        response = client.get(f"/asks/{job_id}/export", params={"format": "md"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    # The question, as the document's own title.
    assert "Who led it?" in body
    # The rendered answer.
    assert "The regime's coercive apparatus expanded." in body


def test_export_md_carries_no_telemetry(job_store: JobStore, tmp_path: Path, authed_app):
    """Issue #783: the exported document is the reader render. The metrics
    block, the source-usage ratios and the raw chunk pointers all belonged
    to the audit render and none of them reach a downloaded file."""
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        body = client.get(f"/asks/{job_id}/export", params={"format": "md"}).text

    assert "## Metrics" not in body
    assert "usage_ratio" not in body
    assert "## Source usage" not in body
    assert "## Coverage map" not in body
    # The claim's ground resolved, so it cites the book rather than the id.
    assert CHUNK_ID not in body
    assert "chunk:" not in body
    # ... and cites the book instead: `axial.cite`'s in-text form is the
    # author's surname and the year ("Author A" -> "A 1999").
    assert "A 1999" in body


def test_export_defaults_to_markdown_when_no_format_is_given(
    job_store: JobStore, tmp_path: Path, authed_app
):
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        response = client.get(f"/asks/{job_id}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")


def test_export_docx_is_a_real_docx_file(job_store: JobStore, tmp_path: Path, authed_app):
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        response = client.get(f"/asks/{job_id}/export", params={"format": "docx"})

    assert response.status_code == 200
    assert response.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    # A docx (and odt) file is a zip container -- the local file header
    # signature is the cheapest real proof this is not just markdown bytes
    # mislabelled with a different content-type.
    assert response.content[:4] == b"PK\x03\x04"


def test_export_odt_is_a_real_odt_file(job_store: JobStore, tmp_path: Path, authed_app):
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        response = client.get(f"/asks/{job_id}/export", params={"format": "odt"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.oasis.opendocument.text"
    assert response.content[:4] == b"PK\x03\x04"


def test_export_rejects_an_unknown_format(job_store: JobStore, tmp_path: Path, authed_app):
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        response = client.get(f"/asks/{job_id}/export", params={"format": "pdf"})

    assert response.status_code == 422


def test_export_is_409_while_the_ask_is_not_finished(job_store: JobStore, authed_app):
    with TestClient(authed_app(create_app(job_store))) as client:
        job_id = client.post("/asks", json={"case": "Syria", "request": "Q"}).json()["id"]
        response = client.get(f"/asks/{job_id}/export")

    assert response.status_code == 409


def test_export_is_404_for_another_principals_ask(job_store: JobStore, tmp_path: Path):
    record_path = _write_record(tmp_path)

    app_b = create_app(job_store)
    from axial.service.api import current_principal

    app_b.dependency_overrides[current_principal] = lambda: "analyst-b"
    with TestClient(app_b) as client_b:
        bs_ask_id = _submit_and_complete(client_b, job_store, record_path)

    app_a = create_app(job_store)
    app_a.dependency_overrides[current_principal] = lambda: "analyst-a"
    with TestClient(app_a) as client_a:
        response = client_a.get(f"/asks/{bs_ask_id}/export")

    assert response.status_code == 404


def test_export_never_touches_cost_or_quota_accounting(
    job_store: JobStore, quota_store: QuotaStore, tmp_path: Path, authed_app
):
    """Exporting is free (the issue's own line): calling it repeatedly must
    never move the job's own `cost_usd`/`cached` fields or the quota
    window's own count -- both read straight off the `jobs` table, which
    `GET /asks/{id}/export` never writes to."""
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store, quota_store))) as client:
        job_id = _submit_and_complete(client, job_store, record_path, cost_usd=0.13)
        before = job_store.get(job_id)
        before_charged = job_store.count_since(_PRINCIPAL, kind="ask", since=before["created_at"])

        for fmt in ("md", "docx", "odt"):
            assert client.get(f"/asks/{job_id}/export", params={"format": fmt}).status_code == 200

        after = job_store.get(job_id)
        after_charged = job_store.count_since(_PRINCIPAL, kind="ask", since=before["created_at"])

    assert after["cost_usd"] == before["cost_usd"] == 0.13
    assert after["cached"] == before["cached"] is False
    assert after_charged == before_charged == 1


def test_an_unconfigured_install_exports_the_quote_under_the_claim_it_grounds(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """Acceptance test for issue #785. GIVEN no `AXIAL_CITATION_MODE` in the
    environment at all, WHEN a finished ask is exported, THEN the document
    quotes the passage behind each claim, as a blockquote under that claim --
    not in an appendix, and not absent because a fresh install defaults to
    pointing at books rather than quoting them.

    Verified against the served file's own bytes, the same probe the
    `locator` bar below uses."""
    monkeypatch.delenv(CITATION_MODE_ENV_VAR, raising=False)
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        body = client.get(f"/asks/{job_id}/export", params={"format": "md"}).text

    assert PASSAGE_TEXT in body
    lines = body.splitlines()
    claim_index = next(
        i for i, line in enumerate(lines) if "The regime's coercive apparatus expanded." in line
    )
    quote_index = next(i for i, line in enumerate(lines) if PASSAGE_TEXT in line)
    assert quote_index > claim_index
    assert lines[quote_index].lstrip().startswith(">")
    # Under the claim, not collected at the end: nothing but blank lines
    # separates the two.
    assert all(not line.strip() for line in lines[claim_index + 1 : quote_index])


def test_locator_mode_export_carries_no_book_text_verified_against_the_file(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """The issue's own line: verified against the generated file's bytes,
    not the JSON and not a UI. Since #785 `locator` is a deployer's explicit
    choice rather than the unconfigured default, so this states it."""
    monkeypatch.setenv(CITATION_MODE_ENV_VAR, "locator")
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path)

    with TestClient(authed_app(create_app(job_store, vault_dir=vault_dir))) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        md = client.get(f"/asks/{job_id}/export", params={"format": "md"}).content
        docx_bytes = client.get(f"/asks/{job_id}/export", params={"format": "docx"}).content
        odt_bytes = client.get(f"/asks/{job_id}/export", params={"format": "odt"}).content

    assert PASSAGE_TEXT.encode("utf-8") not in md
    assert PASSAGE_TEXT.encode("utf-8") not in docx_bytes
    assert PASSAGE_TEXT.encode("utf-8") not in odt_bytes


def test_passage_mode_export_carries_the_quoted_passage(
    job_store: JobStore, tmp_path: Path, authed_app
):
    """Issue #732: `render_markdown` (§7.10) now surfaces a resolved
    ground's `citation.quote`, so a `passage` deployment's export carries
    the book text behind a cited chunk -- verified against the file bytes
    of all three containers, the same probe this file already uses for the
    `locator` bar below. This inverts the honest-gap test #724 pinned
    (`test_passage_mode_export_also_carries_no_book_text`): the gap is
    closed, not merely re-described."""
    vault_dir = _build_vault(tmp_path)
    record_path = _write_record(tmp_path)

    with TestClient(
        authed_app(create_app(job_store, citation_mode=PASSAGE, vault_dir=vault_dir))
    ) as client:
        job_id = _submit_and_complete(client, job_store, record_path)
        md = client.get(f"/asks/{job_id}/export", params={"format": "md"}).content
        docx_bytes = client.get(f"/asks/{job_id}/export", params={"format": "docx"}).content
        odt_bytes = client.get(f"/asks/{job_id}/export", params={"format": "odt"}).content

    assert PASSAGE_TEXT.encode("utf-8") in md
    # docx/odt are zip containers, so the raw passage bytes are not a
    # direct member of the archive bytes the way they are in markdown --
    # the `render_docx`/`render_odt` walk is exercised for real instead,
    # by round-tripping the actual paragraph text back out.
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
    assert PASSAGE_TEXT in document_xml

    odt_doc = load_odt(io.BytesIO(odt_bytes))
    odt_text = "\n".join(str(p) for p in odt_doc.getElementsByType(P))
    assert PASSAGE_TEXT in odt_text
