"""Acceptance test for issue #784, slice 01: an ask run through the service
ends in a Phase C paper, and `GET /asks/{id}/paper` serves that essay beside
the analysis record it was drafted from.

`axial ask` has ended in a paper since issue #668 (`_ask_paper`), so nothing
here is new capability -- what is new is that the *service* runs the same
composition, and that the essay reaches a client. The claim list is
untouched: the same `record` and `metrics` this route already returned are
still returned.

No model is called. `axial.service.worker.run_ask` is stubbed, the seam
`test_worker_cache.py` already uses, and the three Phase-C passes are served
by a scripted stub client -- the shape `tests/paper/test_paper_pipeline.py`
uses. Real Postgres backs the `JobStore`.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from axial.answer.record import BriefRunResult
from axial.ask.engine import Turn
from axial.brief.intake import Brief
from axial.context import DEFAULT_PRINCIPAL
from axial.llm import LLMError, StubLLMClient
from axial.service import worker as worker_mod
from axial.service.api import create_app
from axial.service.citation import LOCATOR, PASSAGE
from axial.service.jobs import JobStore
from axial.service.snapshot import Snapshot
from axial.service.worker import Worker, run_ask_job

PIN = "sim-2026-08-10"
BRIEF_ID = "b1"
QUESTION = "Did the mandate build the institutions the Baath later inherited?"
CASE = "Syria, 1920-2024"

SNAPSHOT = Snapshot(
    root=Path("data/snapshots/v1"),
    version="v1",
    corpus_pin=PIN,
    map_pin=None,
    sources=(),
    built_at="2026-08-10T00:00:00Z",
)


def _claim(claim_id: str, text: str) -> dict:
    return {
        "claim_id": claim_id,
        "kind": "a",
        "text": text,
        "confidence": "medium",
        "grounds": [{"ref_type": "chunk", "ref_id": f"src-1999_1_intro_{claim_id}"}],
        "names_touched": ["Syria"],
    }


def _analysis_record() -> dict:
    """One finished Phase-B record, the single input a paper drawn from an
    ask ever has."""
    return {
        "brief_id": BRIEF_ID,
        "brief": {
            "brief_id": BRIEF_ID,
            "case": CASE,
            "request": QUESTION,
            "lens": None,
            "weights": {},
            "fork_answer": None,
        },
        "corpus_pin": PIN,
        "lens": "state-formation",
        "interrogation": {"disposition": "proceed_bounded"},
        "claims": [
            _claim("c1", "The mandate built a centralised bureaucracy."),
            _claim("c2", "Rural notables were co-opted into that bureaucracy."),
            _claim("c3", "The Baath inherited rather than invented the apparatus."),
        ],
        "counter_position": {
            "present": True,
            "stance": "the apparatus was rebuilt after 1963, not inherited",
            "grounds": [{"ref_type": "chunk", "ref_id": "src-1999_1_intro_c3"}],
            "corpus_one_sided": False,
            "one_sided_reason": None,
        },
        "coverage_map": {
            "Syria": {"corpus_note_count": 40, "evidence_note_count": 8, "coverage_band": "medium"}
        },
        "confidence": {"overall_band": "medium", "rationale": "8 of 40 notes on Syria"},
        "cost": {
            "by_pass": {
                "interrogate": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "total_tokens": 1500,
                    "usd": 0.02,
                }
            },
            "total_usd": 0.02,
        },
        "model_by_pass": {"interrogate": "deepseek/deepseek-v4-flash"},
    }


PLAN = {
    "thesis_statement": (
        "The institutions that decided who held power were built under the mandate."
    ),
    "sections": [
        {"section_id": "s1", "heading": "What the question asks", "role": "setup",
         "assigned_claims": []},
        {"section_id": "s2", "heading": "The mandate's bureaucracy", "role": "claim",
         "assigned_claims": [
             {"brief_id": BRIEF_ID, "claim_id": "c1"},
             {"brief_id": BRIEF_ID, "claim_id": "c2"},
         ]},
        {"section_id": "s3", "heading": "The case for a Baathist rebuild", "role": "counter-position",
         "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": "c3"}]},
        {"section_id": "s4", "heading": "Inheritance, not invention", "role": "synthesis",
         "assigned_claims": [{"brief_id": BRIEF_ID, "claim_id": "c2"}]},
    ],
}

DRAFTS = [
    {"prose": "The question is what the mandate left behind.", "new_claims": []},
    {"prose": "A centralised bureaucracy was built [pc-001]. Notables were drawn into it [pc-002].",
     "new_claims": []},
    {"prose": "Against this, the apparatus was rebuilt after 1963 [pc-003].", "new_claims": []},
    {"prose": "The inheritance runs through the notables [pc-002].", "new_claims": []},
]

SECTION_HEADINGS = [section["heading"] for section in PLAN["sections"]]


class PaperStubClient(StubLLMClient):
    """Serves the three Phase-C passes from a script and reports usage, so
    the paper's own cost is a real number rather than `None`. `paper_shape`
    resolves to a different model than `paper_draft` on purpose -- the shape
    check's self-grading guard raises when they match."""

    model_by_pass = {
        "paper_plan": "deepseek/deepseek-v4-flash",
        "paper_draft": "deepseek/deepseek-v4-flash",
        "paper_shape": "stub/shape",
        "paper_abstract": "stub/abstract",
    }

    def __init__(self) -> None:
        super().__init__()
        self._drafts = list(DRAFTS)
        self.passes: list[str] = []

    def complete(self, prompt, pass_name=None, **_):
        self.passes.append(pass_name)
        if pass_name == "paper_plan":
            return json.dumps(PLAN)
        if pass_name == "paper_shape":
            return json.dumps({"band": "strong", "defects": []})
        if pass_name == "paper_abstract":
            return json.dumps({"abstract": "This paper argues its own case."})
        return json.dumps(self._drafts.pop(0))

    def model_for_pass(self, pass_name=None):
        return self.model_by_pass.get(pass_name)

    def usage_for_pass(self, pass_name=None):
        return {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}


class _RaisingClient(StubLLMClient):
    """Refuses every call. Stands in for two different things: a drafting
    run that fails, and a cache hit that must make no model call at all."""

    def complete(self, prompt, pass_name=None, **_):
        raise LLMError(f"no model available for {pass_name}")

    def model_for_pass(self, pass_name=None):
        return "stub/raising"


def _stub_ask(record: dict):
    """A fake `run_ask` that writes the record where the real engine would
    and returns the `Turn` the worker reads."""

    def fake_ask(question, case, *, client, session_id=None, on_event=None, **kwargs):
        analyses_dir = Path(kwargs["analyses_dir"])
        analyses_dir.mkdir(parents=True, exist_ok=True)
        record_path = analyses_dir / f"{BRIEF_ID}.json"
        record_path.write_text(json.dumps(record), encoding="utf-8")
        return Turn(
            session_id="s1",
            turn_index=1,
            question=question,
            case=case,
            brief=Brief(brief_id=BRIEF_ID, case=case, request=question),
            result=BriefRunResult(
                record=record,
                path=record_path,
                markdown_path=record_path,
                report={},
                report_path=record_path,
            ),
        )

    return fake_ask


def _run_the_ask(job_store: JobStore, work_dir: Path, client, cache=None) -> None:
    """Claim and run whatever is queued, exactly as a deployed worker
    would."""
    worker = Worker(
        job_store,
        lambda job: run_ask_job(
            job,
            client=client,
            store=job_store,
            snapshot=SNAPSHOT,
            work_dir=work_dir,
            cache=cache,
        ),
    )
    assert worker.run_once() is True


def test_the_job_row_names_the_paper_it_drafted(job_store: JobStore, tmp_path: Path, monkeypatch):
    """The path travels on the row, never derived at serve time. A
    follow-up turn's thesis is the question the analyst typed while its
    record's own `request` carries the previous turn folded in, so the two
    hash to different `paper_brief_id`s and a recomputed filename would miss
    -- silently, and looking correct."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))
    job_id = job_store.enqueue(
        kind="ask", principal=DEFAULT_PRINCIPAL, payload={"case": CASE, "question": QUESTION}
    )

    _run_the_ask(job_store, tmp_path / "work", PaperStubClient())

    row = job_store.get(job_id)
    assert row["state"] == "done"
    assert row["paper_ref"] is not None
    paper_path = Path(row["paper_ref"])
    assert paper_path.is_file()
    # Under the principal's own scoped directory, never the repo's data/papers.
    assert paper_path.parent == tmp_path / "work" / "papers"


def test_a_finished_ask_serves_an_argued_essay(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """The slice's acceptance criterion. An analyst asks a question and the
    route that used to return a claim list returns the essay drawn from it,
    with the claim list still beside it."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))
    client_stub = PaperStubClient()

    with TestClient(authed_app(create_app(job_store))) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", client_stub)

        payload = http.get(f"/asks/{ask_id}/paper").json()

    essay = payload["essay"]
    assert PLAN["thesis_statement"] in essay
    for heading in SECTION_HEADINGS:
        assert heading in essay
    # Plan order, never re-sorted (PHASE-C §7.2).
    positions = [essay.index(heading) for heading in SECTION_HEADINGS]
    assert positions == sorted(positions)

    # The claim list and its metrics are untouched beside it.
    assert [claim["claim_id"] for claim in payload["record"]["claims"]] == ["c1", "c2", "c3"]
    assert payload["metrics"]["confidence"]["overall_band"] == "medium"


def test_the_asks_reported_cost_includes_the_drafting_passes(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """The issue's own bar: cost per ask measured, not estimated. The three
    Phase-C passes are model calls this ask made, so they belong in the
    spend the analyst is shown."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))
    client_stub = PaperStubClient()

    with TestClient(authed_app(create_app(job_store))) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", client_stub)

        usage = http.get("/me/usage").json()
        paper = http.get(f"/asks/{ask_id}/paper").json()["paper"]

    # The analysis alone cost 0.02 (the fixture record's own `cost`); the
    # reported spend is strictly more than that because the drafting passes
    # this ask also made are counted.
    assert usage["month_to_date"]["cost_usd"] > 0.02
    assert set(paper["cost"]["by_pass"]) == {
        "paper_plan",
        "paper_draft",
        "paper_shape",
        "paper_abstract",
    }
    assert client_stub.passes.count("paper_draft") == len(PLAN["sections"])


def test_a_cache_hit_still_serves_its_essay(
    job_store: JobStore, paper_cache, tmp_path: Path, monkeypatch, authed_app
):
    """A repeat question is free by design (issue #686) -- and a free answer
    that silently loses its essay is a worse answer, not a cheaper one. The
    cached paper is the same artifact: `paper_brief_id` is a content hash
    over the same thesis and the same record."""
    paper_cache.create_schema()
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))
    work_dir = tmp_path / "work"

    with TestClient(authed_app(create_app(job_store))) as http:
        first_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, work_dir, PaperStubClient(), cache=paper_cache)
        first = http.get(f"/asks/{first_id}/paper").json()["essay"]

        second_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        # A client that would raise if asked for anything: a hit must make no
        # model call, for the essay any more than for the answer.
        _run_the_ask(job_store, work_dir, _RaisingClient(), cache=paper_cache)
        second = http.get(f"/asks/{second_id}/paper").json()["essay"]

    assert job_store.get(second_id)["cached"] is True
    assert second == first


def test_a_failed_draft_leaves_the_answer_standing(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """The analysis is already persisted and already paid for. Losing it
    because the essay drawn from it could not be written would charge the
    analyst for an answer they never receive -- so the ask completes, the
    essay is absent, and the failure is on the record as a failure of the
    drafting run."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))

    with TestClient(authed_app(create_app(job_store))) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", _RaisingClient())

        payload = http.get(f"/asks/{ask_id}/paper").json()
        events = http.get(f"/asks/{ask_id}/events").text

    assert job_store.get(ask_id)["state"] == "done"
    assert "essay" not in payload
    assert len(payload["record"]["claims"]) == 3
    assert "writing the essay from it failed" in events


def test_a_refused_ask_serves_no_essay_and_no_paper(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """§7.1 rejects a refused record at paper intake -- it carries no claims.
    A refusal still reads as a refusal, never as a drafting failure."""
    refused = _analysis_record()
    refused["interrogation"] = {"disposition": "refuse", "refusal": {"reason": "out of corpus"}}
    refused["claims"] = []
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(refused))
    client_stub = PaperStubClient()

    with TestClient(authed_app(create_app(job_store))) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", client_stub)

        payload = http.get(f"/asks/{ask_id}/paper").json()
        events = http.get(f"/asks/{ask_id}/events").text

    assert "essay" not in payload and "paper" not in payload
    assert payload["record"]["interrogation"]["disposition"] == "refuse"
    assert client_stub.passes == []
    assert "writing the essay from it failed" not in events


def test_the_export_carries_the_essay_the_analyst_read(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """An export that disagrees with what is on screen is a defect. Once the
    essay is the answer, the downloaded file leads with it -- the claim list
    still follows, for a reader checking the argument offline."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))

    with TestClient(authed_app(create_app(job_store))) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", PaperStubClient())

        exported = http.get(f"/asks/{ask_id}/export?format=md").text

    assert PLAN["thesis_statement"] in exported
    for heading in SECTION_HEADINGS:
        assert heading in exported
    # The claim list survives beneath it.
    assert "The mandate built a centralised bureaucracy." in exported


def test_an_export_with_no_essay_is_what_it_always_was(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """A refused ask, or one whose drafting failed, exports exactly the
    document it exported before this issue -- no empty essay heading, no
    stated absence in a file meant to be read on its own."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))

    with TestClient(authed_app(create_app(job_store))) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", _RaisingClient())

        exported = http.get(f"/asks/{ask_id}/export?format=md").text

    assert PLAN["thesis_statement"] not in exported
    assert "The mandate built a centralised bureaucracy." in exported


PASSAGE_TEXT = "The mandate's bureaucracy outlived the mandate by forty years."


def _build_vault(root: Path) -> Path:
    """A real vault holding the chunks this fixture's claims are grounded
    in, so a citation actually resolves and the mode has something to
    decide about."""
    from axial.query import store as note_store

    vault_dir = root / "vault"
    chunk_ids = [f"src-1999_1_intro_{claim_id}" for claim_id in ("c1", "c2", "c3")]
    note_store.write_store(
        vault_dir / "notes.db",
        sources=[("src-1999", "Author A", "The Book", "1999", 1999)],
        notes=[
            (chunk_id, "src-1999", "Introduction", "Chapter 1: Origins", "claim text", None, 0)
            for chunk_id in chunk_ids
        ],
        names=[],
        note_names=[],
        note_arguing_against=[],
        note_citations=[],
    )
    prose_dir = vault_dir / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for chunk_id in chunk_ids:
        (prose_dir / f"{chunk_id}.md").write_text(
            "---\n"
            f"chunk_id: {chunk_id}\n"
            "section: Introduction\n"
            f'chunk_text: "{PASSAGE_TEXT}"\n'
            "source_meta: {author: Author A, title: The Book, date: '1999'}\n"
            "---\n\nbody\n",
            encoding="utf-8",
        )
    return vault_dir


def _essay_payload_under(mode, job_store, tmp_path, authed_app):
    vault_dir = _build_vault(tmp_path)
    app = create_app(job_store, vault_dir=vault_dir, citation_mode=mode)
    with TestClient(authed_app(app)) as http:
        ask_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, tmp_path / "work", PaperStubClient())
        return http.get(f"/asks/{ask_id}/paper").json()


def test_a_locator_deployment_serves_no_book_text_under_either_new_key(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """The property the whole render-at-the-boundary design exists for
    (DEC-65, DEC-72). A worker resolving `passage` must not be able to put
    book text into a `locator` deployment's response by baking it into the
    file it wrote -- so neither `essay` nor `paper` may carry a quote here.
    This is an oracle, not a judgement: the passage is a known string."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))

    payload = _essay_payload_under(LOCATOR, job_store, tmp_path, authed_app)

    assert PASSAGE_TEXT not in payload["essay"]
    assert PASSAGE_TEXT not in json.dumps(payload["paper"])
    assert PASSAGE_TEXT not in json.dumps(payload["record"])


def test_a_passage_deployment_resolves_the_paper_the_same_way_it_resolves_the_record(
    job_store: JobStore, tmp_path: Path, monkeypatch, authed_app
):
    """The other half: `paper` goes through the same resolution `record`
    does, so a client reading one is not handed raw `chunk:<id>` pointers
    where the other has a book and a chapter."""
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))

    payload = _essay_payload_under(PASSAGE, job_store, tmp_path, authed_app)

    assert PASSAGE_TEXT in json.dumps(payload["paper"])
    assert PASSAGE_TEXT in json.dumps(payload["record"])
    # The essay itself cites book-level in either mode -- it never carries
    # the quoted passage, which is why it stays short.
    assert PASSAGE_TEXT not in payload["essay"]
    assert "(A, 1999)" in payload["essay"]  # `format_citation(form=SHORT)`: APA surname, year


def test_a_hit_whose_entry_has_no_essay_drafts_one_and_repairs_the_entry(
    job_store: JobStore, paper_cache, tmp_path: Path, monkeypatch, authed_app
):
    """A cache hit short-circuits before any drafting, so an entry with no
    essay -- a failed earlier draft, or a row written by a worker predating
    #784 -- would otherwise deny every later ask of that question its essay
    forever. The answer stays free; only the essay is paid for. The third
    ask finds the repaired entry and pays nothing."""
    paper_cache.create_schema()
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(_analysis_record()))
    work_dir = tmp_path / "work"

    with TestClient(authed_app(create_app(job_store))) as http:
        first_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, work_dir, _RaisingClient(), cache=paper_cache)
        assert "essay" not in http.get(f"/asks/{first_id}/paper").json()

        second_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        _run_the_ask(job_store, work_dir, PaperStubClient(), cache=paper_cache)
        second = http.get(f"/asks/{second_id}/paper").json()

        third_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        # Nothing left to pay for: the repaired entry carries the essay.
        _run_the_ask(job_store, work_dir, _RaisingClient(), cache=paper_cache)
        third = http.get(f"/asks/{third_id}/paper").json()

    second_row = job_store.get(second_id)
    # The answer was still served from cache -- no second Phase B run, which
    # is issue #686's own guarantee. Only the essay cost anything.
    assert second_row["cached"] is True
    assert second_row["cost_usd"] > 0
    assert PLAN["thesis_statement"] in second["essay"]

    assert job_store.get(third_id)["cost_usd"] == 0.0
    assert third["essay"] == second["essay"]


def test_a_cached_refusal_stays_a_refusal_and_costs_nothing_to_repeat(
    job_store: JobStore, paper_cache, tmp_path: Path, monkeypatch, authed_app
):
    """The repair path must not mistake a refusal for a missing essay. A
    refusal has none and never will, so a repeat serves it free rather than
    re-attempting a draft on every ask."""
    paper_cache.create_schema()
    refused = _analysis_record()
    refused["interrogation"] = {"disposition": "refuse", "refusal": {"reason": "out of corpus"}}
    refused["claims"] = []
    monkeypatch.setattr(worker_mod, "run_ask", _stub_ask(refused))
    work_dir = tmp_path / "work"

    with TestClient(authed_app(create_app(job_store))) as http:
        http.post("/asks", json={"case": CASE, "request": QUESTION})
        _run_the_ask(job_store, work_dir, PaperStubClient(), cache=paper_cache)

        second_id = http.post("/asks", json={"case": CASE, "request": QUESTION}).json()["id"]
        client = PaperStubClient()
        _run_the_ask(job_store, work_dir, client, cache=paper_cache)
        payload = http.get(f"/asks/{second_id}/paper").json()

    assert job_store.get(second_id)["cached"] is True
    assert job_store.get(second_id)["cost_usd"] == 0.0
    assert client.passes == []
    assert "essay" not in payload
    assert payload["record"]["interrogation"]["disposition"] == "refuse"
