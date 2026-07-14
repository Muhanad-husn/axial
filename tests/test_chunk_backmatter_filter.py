"""Outer acceptance test for issue #113 (drop clear back-matter sections
BEFORE chunking).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose extraction tree has, among its top-level sections: a
      clear BACK-MATTER section ("Bibliography", plus a case-variant
      "BIBLIOGRAPHY" and a spacing-variant " Bibliography "), a normal prose
      chapter section, and three explicitly KEPT boundary sections ("Notes",
      "Appendix", "Preface") -- every one of these sections carries
      real-looking, non-empty body text, so a filter-less pass would produce
      chunk records for every one of them
When  `axial.chunk.run_chunk_embedding` is called on that source
Then  the back-matter sections (all three Bibliography spellings) produce
      ZERO chunk records, and none of their own body text ever appears
      inside any OTHER section's emitted chunk text either -- they are
      dropped before chunking ever runs on them, not merely filtered from
      the final output
And   the normal prose chapter sections still produce chunk record(s)
And   each of the three explicitly-kept boundary sections ("Notes",
      "Appendix", "Preface") still produces chunk record(s) -- this locks
      the scope so a future, over-eager change cannot silently start
      dropping these too

See GitHub issue #113 for the original report and fix: a deterministic
title filter (`axial.chunk._is_back_matter`), applied before any section is
chunked, for a normalized title matching: Index, Bibliography,
References / Works Cited, Table of Contents / Contents, Copyright, List of
Figures / List of Tables / List of Illustrations. Sections that must be kept
(explicitly NOT dropped): Endnotes / Notes, Appendix, Preface, and normal
prose chapters.

Migration note (issue #154, slice 04 of the chunk-redesign subproject)
-----------------------------------------------------------------------
This test originally drove the retired LLM-echo chunker
(`axial.chunk.run_chunk`, one text-generating LLM call per section) via a
fake `LLMClient` that counted which sections' body text reached a prompt.
`run_chunk` and every one of its LLM-facing seams (`compose_chunk_prompt`,
`parse_response`, the chunk-pass prompt template) are deleted as of this
slice; the sole chunking mechanism is now the embedding-based, LLM-free
`run_chunk_embedding` (issue #151). `_is_back_matter`'s own title-matching
logic is UNCHANGED by that rewrite (same normalized-title set, same KEEP
list) but had no dedicated coverage anywhere in the new mechanism's own
test suite (verified: neither `tests/test_chunk.py` -- slice 01's own
locked outer test, whose fixture carries no back-matter section at all --
nor `src/axial/test_chunk_embedding.py` exercises `_is_back_matter`
directly). This migration is not a mechanical rename: it re-proves the same
behavioral contract (drop before chunking, never a post-hoc filter) against
the actual mechanism that ships today, closing that coverage gap.

Seam decision 1 -- bypassing docling/network entirely via a monkeypatched
axial.chunk.tree_path/load_persisted_tree, calling run_chunk_embedding
directly
-----------------------------------------------------------------------
Mirrors `src/axial/test_chunk_embedding.py`'s own `_patch_tree` helper:
`run_chunk_embedding` reads the persisted structural tree via
`axial.chunk.tree_path`/`axial.chunk.load_persisted_tree` (imported
directly into `axial.chunk`'s own module namespace), so monkeypatching
those two module attributes redirects the read to a hand-built, synthetic
extraction tree -- no real PDF, no docling, no network.
`run_chunk_embedding`'s own per-section loop and back-matter filter (the
actual subject of issue #113) is never bypassed; only its upstream
structural-extraction dependency is. `run_chunk_embedding` needs no stored
envelope at all (issue #151: the embedding chunk stage never reads one),
so unlike this file's pre-migration version, no envelope arrange step is
needed here.

Seam decision 2 -- proving "dropped before chunking", not merely "absent
from output": body-text markers checked against EVERY emitted chunk's text
-----------------------------------------------------------------------
There is no LLM call left to intercept (the whole point of the redesign),
so the old `_MarkerCountingClient`'s "the LLM was never called with this
text" proof has no direct analogue. The equivalent, still-meaningful proof
in the new mechanism is structural: each synthetic section below is given
distinct, greppable body text (no section's text is a substring of
another's), and this test asserts a dropped section's own marker text never
appears as a substring of ANY emitted chunk's `text` field -- not just that
no chunk record carries the dropped section's own `section` label. An
implementation that filtered records post-hoc after already merging a
back-matter section's body into an adjacent section's own chunk text (e.g.
a body-concatenation bug) would pass the weaker "no record labeled
Bibliography" check but fail this stronger one.

Test hygiene: every path this test touches (the synthetic source file,
`chunks_dir`) lives under pytest's own `tmp_path`, outside this repo
entirely -- nothing here reads or writes any real `data/` directory, and no
real LLM/network/docling call is ever made (the embedding chunk stage makes
none, full stop).
"""

from __future__ import annotations

import axial.chunk as chunk_module
from axial.chunk import HashingEmbedder, run_chunk_embedding

_PREFACE_BODY = (
    "Preface sentinel: this reflection states the author's aims before the "
    "main argument of the book begins, and explains the project's origins."
)
_CHAPTER_THREE_BODY = (
    "Chapter three prose sentinel: a claim about material scarcity during "
    "the campaign is developed here and then supported with one specific, "
    "documented episode drawn from the archival record."
)
_BIBLIOGRAPHY_BODY = (
    "Bibliography sentinel entry: Smith, J. (2020) Title of a Cited Book, "
    "Publisher Name, pp. 1-400; Jones, A. (2019) Another Cited Work, Press."
)
_NOTES_BODY = (
    "Notes sentinel: endnote one elaborates the chapter three claim with an "
    "additional citation and a short clarifying argument of its own."
)
_BIBLIOGRAPHY_UPPER_BODY = (
    "Bibliography uppercase-variant sentinel entry: Doe, R. (2018) Yet "
    "Another Cited Title, Academic Press, Some City."
)
_APPENDIX_BODY = (
    "Appendix sentinel: supplementary tabulated material is described here "
    "in prose form, explaining the coding procedure used for the dataset."
)
_BIBLIOGRAPHY_SPACED_BODY = (
    "Bibliography spacing-variant sentinel entry: Lee, K. (2017) Final "
    "Cited Reference Title, University Press, Another City."
)
_CHAPTER_FOUR_BODY = (
    "Chapter four prose sentinel: the argument concludes by tying the "
    "earlier material-scarcity claim to the campaign's eventual outcome."
)

_SECTION_SPECS = [
    ("Preface", "keep", _PREFACE_BODY),
    ("Chapter 3: The Long March", "keep", _CHAPTER_THREE_BODY),
    ("Bibliography", "drop", _BIBLIOGRAPHY_BODY),
    ("Notes", "keep", _NOTES_BODY),
    ("BIBLIOGRAPHY", "drop", _BIBLIOGRAPHY_UPPER_BODY),
    ("Appendix", "keep", _APPENDIX_BODY),
    (" Bibliography ", "drop", _BIBLIOGRAPHY_SPACED_BODY),
    ("Chapter 4: Aftermath", "keep", _CHAPTER_FOUR_BODY),
]

_KEEP_LABELS = {label for label, kind, _ in _SECTION_SPECS if kind == "keep"}
_DROP_BODIES = [body for _, kind, body in _SECTION_SPECS if kind == "drop"]
_KEEP_BODIES = [body for _, kind, body in _SECTION_SPECS if kind == "keep"]


def _build_synthetic_tree():
    children = []
    for index, (heading, _kind, body) in enumerate(_SECTION_SPECS, start=1):
        children.append(
            {
                "type": "prose",
                "order": str(index),
                "text": heading,
                "children": [{"type": "prose", "order": f"{index}.1", "text": body}],
            }
        )
    return {"children": children}


def _patch_tree(monkeypatch, tmp_path, tree: dict) -> None:
    """Mirrors `src/axial/test_chunk_embedding.py`'s own `_patch_tree`
    helper (see module docstring, seam decision 1)."""
    import json as _json

    tree_file = tmp_path / "tree.json"
    tree_file.write_text(_json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_module, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_module, "load_persisted_tree", lambda path: tree)


def test_backmatter_sections_are_dropped_before_chunking(tmp_path, monkeypatch):
    source_path = tmp_path / "synthetic_source_with_backmatter.txt"
    source_path.write_text(
        "synthetic multi-section source for issue #113 back-matter filter test",
        encoding="utf-8",
    )

    _patch_tree(monkeypatch, tmp_path, _build_synthetic_tree())

    records = run_chunk_embedding(
        source_path, embedder=HashingEmbedder(), chunks_dir=tmp_path / "chunks"
    )

    assert isinstance(records, list), (
        f"expected run_chunk_embedding to return a list, got {type(records).__name__}: {records!r}"
    )
    assert records, "expected at least one chunk record from the kept sections, got none"

    dropped_sections_seen = {
        record.get("section")
        for record in records
        if isinstance(record.get("section"), str)
        and record["section"].strip().lower() == "bibliography"
    }
    assert not dropped_sections_seen, (
        f"expected ZERO chunk records for any Bibliography-titled section "
        f"(issue #113), but found record(s) carrying section label(s) "
        f"{sorted(dropped_sections_seen)!r}. Full records: {records!r}"
    )

    # Stronger proof (seam decision 2): a dropped section's own body text
    # never leaks into ANY emitted chunk's text, not merely "no record
    # labeled Bibliography".
    for body in _DROP_BODIES:
        leaked = [r for r in records if body in r.get("text", "")]
        assert not leaked, (
            f"expected a dropped back-matter section's own body text to "
            f"never appear inside any emitted chunk's text (issue #113: "
            f"dropped before chunking, not filtered post-hoc), but it "
            f"leaked into: {leaked!r}. Marker (start): {body[:80]!r}"
        )

    prose_sections_seen = {
        record.get("section")
        for record in records
        if record.get("section") in {"Chapter 3: The Long March", "Chapter 4: Aftermath"}
    }
    assert prose_sections_seen == {"Chapter 3: The Long March", "Chapter 4: Aftermath"}, (
        f"expected both normal prose chapter sections to still produce "
        f"chunk record(s), got sections present: {sorted(prose_sections_seen)!r}. "
        f"Full records: {records!r}"
    )

    keep_boundary_labels = {"Notes", "Appendix", "Preface"}
    keep_sections_seen = {
        record.get("section") for record in records if record.get("section") in keep_boundary_labels
    }
    assert keep_sections_seen == keep_boundary_labels, (
        f"expected every explicitly-kept boundary section "
        f"{sorted(keep_boundary_labels)!r} to still produce chunk record(s), "
        f"got sections present: {sorted(keep_sections_seen)!r}. "
        f"Full records: {records!r}"
    )

    for body in _KEEP_BODIES:
        matching = [r for r in records if body in r.get("text", "")]
        assert matching, (
            f"expected a kept section's own body text to appear in at "
            f"least one emitted chunk's text, got none. Marker (start): "
            f"{body[:80]!r}"
        )

    for record in records:
        section = record.get("section")
        assert section in _KEEP_LABELS, (
            f"expected every chunk record's section to be one of this "
            f"fixture's KEEP labels {sorted(_KEEP_LABELS)!r}, got {section!r} "
            f"(full record: {record!r})"
        )
