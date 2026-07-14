"""Acceptance test for issue #111 (xref input guard for non-prose back-matter).

An OCR'd index/bibliography becomes one very large, mostly-non-alphabetic
chunk (real example: tilly chunk 822 = 42,144 chars, ~55% non-alpha) with
zero cross-reference value. Fed to the xref LLM it stalls the completion.
The guard skips such chunks BEFORE the LLM call: no call, no pairs, no
checkpoint, and the pass completes normally on the remaining prose.

Same seams as tests/test_xref_checkpoint.py (issue #110): monkeypatch
`axial.xref.read_chunks` / `run_artifacts` to supply synthetic records
without docling/network, and a fake counting client identified by the
chunk text it sees in the prompt -- so "the guard never called the LLM for
the index chunk" is asserted directly through the call counts.

Migration note (issue #154, slice 04): `axial.xref.run_xref` no longer
computes chunks itself via `axial.chunk.run_chunk` (deleted) -- it reads
the on-disk chunk artifact via `axial.chunk.read_chunks` (imported
directly into `axial.xref`'s own module namespace as `read_chunks`). This
test repoints its monkeypatch from `xref_module.run_chunk` to
`xref_module.read_chunks` accordingly; every assertion below is unchanged.
"""

from __future__ import annotations

import json

import axial.xref as xref_module
from axial.llm import XREF_PASS_NAME

ARTIFACT_ID = "art-1"

# A prose chunk that references the source's one real artifact.
PROSE_TEXT_A = "As shown above, the prose here discusses the argument in detail."
PROSE_TEXT_B = "A second passage of ordinary prose, again citing the same figure."

# An OCR'd index chunk: > 30 000 chars, dominated by "term, page, page" soup
# (mostly digits, commas, spaces -> well over the non-alpha threshold too).
INDEX_TEXT = "Abbasid, 12, 45, 78; Cairo, 3, 9, 210; " * 900


def _make_env(monkeypatch, chunk_records):
    def fake_read_chunks(source_id, **kwargs):
        return chunk_records

    def fake_run_artifacts(path, **kwargs):
        return [{"artifact_id": ARTIFACT_ID}]

    monkeypatch.setattr(xref_module, "read_chunks", fake_read_chunks)
    monkeypatch.setattr(xref_module, "run_artifacts", fake_run_artifacts)


class _CountingClient:
    """Fake LLMClient: counts calls, keyed by which chunk's text is in the
    prompt. Returns a reference to the one known artifact for any prose it
    sees. It must NEVER be called for a guarded (skipped) chunk."""

    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == XREF_PASS_NAME
        self.prompts.append(prompt)
        return json.dumps({"referenced_artifact_ids": [ARTIFACT_ID]})

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def test_oversized_non_prose_chunk_is_skipped_never_sent_to_llm(tmp_path, monkeypatch, capsys):
    chunk_records = [
        {"chunk_id": "prose-a", "text": PROSE_TEXT_A},
        {"chunk_id": "index-822", "text": INDEX_TEXT},
        {"chunk_id": "prose-b", "text": PROSE_TEXT_B},
    ]
    _make_env(monkeypatch, chunk_records)

    source_path = tmp_path / "source.txt"
    source_path.write_text("guard test source", encoding="utf-8")

    client = _CountingClient()
    pairs = xref_module.run_xref(source_path, client=client)

    # The index chunk was never sent to the LLM; only the two prose chunks were.
    assert client.call_count == 2, (
        f"expected exactly 2 LLM calls (the prose chunks only); the 40KB "
        f"index chunk must be skipped before the LLM call, got {client.call_count}"
    )
    assert INDEX_TEXT not in "".join(client.prompts), (
        "the oversized index chunk's text must never reach an LLM prompt"
    )

    # Pairs come only from prose chunks; the skipped chunk contributes none.
    referencing_chunk_ids = {pair["chunk_id"] for pair in pairs}
    assert referencing_chunk_ids == {"prose-a", "prose-b"}, (
        f"expected pairs only from the prose chunks, got {sorted(referencing_chunk_ids)}"
    )
    assert "index-822" not in referencing_chunk_ids

    # The skip is logged to stderr (stdout stays clean for JSON output).
    err = capsys.readouterr().err
    assert "index-822" in err and "skipping" in err, (
        f"expected the skipped chunk to be logged to stderr with a reason, got: {err!r}"
    )


def test_source_of_only_non_prose_completes_with_zero_pairs(tmp_path, monkeypatch):
    """Pathological edge: a source whose only chunk is non-prose back-matter
    skips everything and returns zero pairs without stalling or raising."""
    chunk_records = [{"chunk_id": "index-only", "text": INDEX_TEXT}]
    _make_env(monkeypatch, chunk_records)

    source_path = tmp_path / "source.txt"
    source_path.write_text("only back-matter", encoding="utf-8")

    client = _CountingClient()
    pairs = xref_module.run_xref(source_path, client=client)

    assert client.call_count == 0, "no prose -> no LLM call at all"
    assert pairs == [], "no prose -> no xref pairs"
