"""Acceptance tests for issue #732: the persisted `.md` `axial ask`/`axial
brief run` writes at the end of a run (`persist_markdown`) surfaces a
`passage`-mode quote the same way `GET /asks/{id}/paper`/`.../export`
already do at serve time (issue #690, #724) -- one resolution function
(`axial.service.citation.render_record_for_serving`), two call sites, never
two different ways of deciding what a citation looks like.

The persisted JSON record itself must stay untouched either way: this
module's own contract (`persist_record`) is that it writes exactly what
`build_record` produced, quote-free regardless of citation mode."""

from __future__ import annotations

import json
from pathlib import Path

from axial.answer.record import persist_markdown
from axial.query import store as note_store

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
        "cost": {"total_usd": 0.13},
    }


def test_an_unconfigured_run_writes_the_quoted_passage(tmp_path: Path, monkeypatch):
    """Unconfigured (no `AXIAL_CITATION_MODE`), exactly like a fresh API
    deployment -- and since issue #785 that resolves to `passage`, so the
    persisted `.md` quotes the book behind each claim."""
    monkeypatch.delenv("AXIAL_CITATION_MODE", raising=False)
    vault_dir = _build_vault(tmp_path)
    record = _record()

    path = persist_markdown("b1", record, analyses_dir=tmp_path / "analyses", vault_dir=vault_dir)

    assert PASSAGE_TEXT in path.read_text(encoding="utf-8")


def test_locator_mode_writes_no_book_text(tmp_path: Path, monkeypatch):
    """A deployer who has chosen `locator` still gets a `.md` with no book
    text in it -- the mode did not go away in #785, it stopped being what an
    install starts in."""
    monkeypatch.setenv("AXIAL_CITATION_MODE", "locator")
    vault_dir = _build_vault(tmp_path)
    record = _record()

    path = persist_markdown("b1", record, analyses_dir=tmp_path / "analyses", vault_dir=vault_dir)

    assert PASSAGE_TEXT not in path.read_text(encoding="utf-8")


def test_passage_mode_writes_the_quoted_passage_into_the_persisted_markdown(
    tmp_path: Path, monkeypatch
):
    """`AXIAL_CITATION_MODE=passage`, the same env var the API reads,
    resolves the quote into the `.md` file `axial ask` writes at the end
    of a run -- the configured-and-paid-for option now does something."""
    monkeypatch.setenv("AXIAL_CITATION_MODE", "passage")
    vault_dir = _build_vault(tmp_path)
    record = _record()

    path = persist_markdown("b1", record, analyses_dir=tmp_path / "analyses", vault_dir=vault_dir)

    assert PASSAGE_TEXT in path.read_text(encoding="utf-8")


def test_passage_mode_never_mutates_the_persisted_json_record(tmp_path: Path, monkeypatch):
    """The record `persist_record` writes as JSON, and the one `run_brief`
    returns to its own caller, must stay exactly what `build_record`
    produced -- `persist_markdown` resolves a deep copy, never `record`
    itself."""
    monkeypatch.setenv("AXIAL_CITATION_MODE", "passage")
    vault_dir = _build_vault(tmp_path)
    record = _record()
    before = json.dumps(record, sort_keys=True)

    persist_markdown("b1", record, analyses_dir=tmp_path / "analyses", vault_dir=vault_dir)

    assert json.dumps(record, sort_keys=True) == before
    assert "citation" not in record["claims"][0]["grounds"][0]
