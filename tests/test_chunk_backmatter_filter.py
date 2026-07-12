"""Outer acceptance test for issue #113 (drop clear back-matter sections
BEFORE chunking).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose extraction tree has, among its top-level sections: a
      clear BACK-MATTER section ("Bibliography", plus a case-variant
      "BIBLIOGRAPHY" and a spacing-variant " Bibliography "), a normal prose
      chapter section, and three explicitly KEPT boundary sections ("Notes",
      "Appendix", "Preface") -- every one of these sections carries
      real-looking, non-empty body text, so under todays code EVERY one of
      them produces chunk records and an LLM call
When  axial.chunk.run_chunk is called on that source
Then  the back-matter sections (all three Bibliography spellings) produce
      ZERO chunk records, and the LLM is NEVER called with any prompt
      containing their body text at all (not as a chunking target, not as
      neighbour context) -- they are skipped before any chunk record or LLM
      call is produced
And   the normal prose chapter sections still produce chunk record(s)
And   each of the three explicitly-kept boundary sections ("Notes",
      "Appendix", "Preface") still produces chunk record(s) -- this locks
      the scope so a future, over-eager change cannot silently start
      dropping these too

See GitHub issue #113: run_chunks per-section loop
(src/axial/chunk.py, _section_nodes/the for index, section in
enumerate(sections) loop) has NO title filter at all today -- every
top-level section node with non-empty body text is chunked, including
bibliographies/indexes/etc., which then become vault notes and pollute the
corpus. The fix (built by the implementer, not this test) adds a
deterministic title filter, applied before any chunk record or LLM call is
produced, for a normalized title matching: Index, Bibliography,
References / Works Cited, Table of Contents / Contents, Copyright, List of
Figures / List of Tables / List of Illustrations. Sections that must be kept
(explicitly NOT dropped) per the issue: Endnotes / Notes, Appendix, Preface,
and normal prose chapters.

As of this commit run_chunk has no such filter, so this test is expected
to fail red for exactly that reason: the back-matter sections chunk
records / LLM calls currently exist rather than being absent. It must not
fail on an import error, a fixture-arrangement error, or a call-signature
mismatch -- only on the actual zero back-matter records/calls assertions
below.

Seam decision 1 -- bypassing docling/network entirely via a monkeypatched
axial.chunk.extract, calling run_chunk directly
-----------------------------------------------------------------------
Mirrors tests/test_xref_checkpoint.pys seam exactly (see that files module
docstring, seam decision 1): axial.chunk.run_chunk imports extract directly
into its own module namespace (from axial.extract import ExtractError,
extract), so monkeypatching the module attribute axial.chunk.extract
redirects every call run_chunk makes internally to a fake that returns a
hand-built, synthetic extraction tree -- no real PDF, no docling, no
network. run_chunks own per-section loop and title-filtering logic (the
actual subject of issue #113) is never bypassed; only its upstream
structural-extraction dependency is.

run_chunk also requires a stored envelope on disk before it will do
anything (MissingEnvelopeError otherwise) -- this test writes one directly
to a tmp_path-scoped envelopes_dir passed explicitly to run_chunk, so no
axial envelope pass (and no LLM call for it) is needed to arrange it.

Seam decision 2 -- a fake LLM client that counts calls by section body
marker, never a real network/model call
-----------------------------------------------------------------------
Each synthetic section below is given distinct, greppable body text (no
sections text is a substring of anothers). The fake client
(_MarkerCountingClient) implements the plain duck-typed LLMClient protocol
(complete(prompt, pass_name=None) -> str) and, on every call, records which
of the known markers appear anywhere in the prompt it receives (target
section text AND any neighbour context alike -- issue #113s skipped
before any chunk record or LLM call is produced is read strictly here: a
dropped sections own text must never reach ANY prompt, not just never be
the chunking target of its own prompt). It always returns a single
well-formed chunk-response JSON string, so any section that IS still
processed completes normally without needing a real model.

Seam decision 3 -- why body-text markers, not just checking record.get(
section)
-----------------------------------------------------------------------
The section field on returned chunk records is one direct, load-bearing
proof (a dropped section must produce zero records under that verbatim
heading, in any of its three tested spellings). The marker-count check is a
second, independent proof of the same contract at the LLM-call boundary
itself (an implementation that filtered records post-hoc, after already
paying for an LLM call on the dropped sections text, would pass the first
check but fail this second one) -- together they pin skipped before any
chunk record OR LLM call is produced literally, not just filtered from
the final output.

Test hygiene: every path this test touches (envelopes_dir, the synthetic
source file) lives under pytests own tmp_path, outside this repo
entirely -- nothing here reads or writes any real data/ directory, and no
real LLM/network/docling call is ever made.
"""

from __future__ import annotations

import json

import axial.chunk as chunk_module
from axial.envelope import compute_source_id
from axial.llm import CHUNK_PASS_NAME

_PREFACE_BODY = (
    "Preface sentinel: this reflection states the authors aims before the "
    "main argument of the book begins, and explains the projects origins."
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
    "earlier material-scarcity claim to the campaigns eventual outcome."
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
                "type": "section",
                "order": str(index),
                "text": heading,
                "children": [{"type": "prose", "order": f"{index}.1", "text": body}],
            }
        )
    return {"type": "root", "order": "0", "children": children}


_VALID_CHUNK_RESPONSE = json.dumps({"chunks": [{"text": "a synthetic stub chunk of prose"}]})


class _MarkerCountingClient:
    def __init__(self, markers):
        self._markers = markers
        self.marker_call_counts = {marker: 0 for marker in markers}
        self.total_calls = 0

    def complete(self, prompt, pass_name=None):
        assert pass_name == CHUNK_PASS_NAME, (
            f"expected pass_name={CHUNK_PASS_NAME!r}, got {pass_name!r}"
        )
        self.total_calls += 1
        for marker in self._markers:
            if marker in prompt:
                self.marker_call_counts[marker] += 1
        return _VALID_CHUNK_RESPONSE


def test_backmatter_sections_are_dropped_before_chunking(tmp_path, monkeypatch):
    source_path = tmp_path / "synthetic_source_with_backmatter.txt"
    source_path.write_text(
        "synthetic multi-section source for issue #113 back-matter filter test",
        encoding="utf-8",
    )
    source_id = compute_source_id(source_path)

    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()
    envelope = {
        "source_id": source_id,
        "author": "Synthetic Author",
        "title": "Synthetic Source With Back-Matter",
        "date": "2026",
        "thesis": "Material scarcity shaped the campaigns course and outcome.",
        "toc": [label for label, _kind, _body in _SECTION_SPECS],
        "scope": "A synthetic single-source fixture for issue #113.",
        "stated_argument": "Material scarcity, not doctrine, decided the campaign.",
    }
    (envelopes_dir / f"{source_id}.json").write_text(
        json.dumps(envelope), encoding="utf-8"
    )

    synthetic_tree = _build_synthetic_tree()

    def fake_extract(path):
        return synthetic_tree

    monkeypatch.setattr(chunk_module, "extract", fake_extract)

    fake_client = _MarkerCountingClient(markers=_DROP_BODIES + _KEEP_BODIES)

    records = chunk_module.run_chunk(
        source_path,
        client=fake_client,
        envelopes_dir=envelopes_dir,
    )

    assert isinstance(records, list), (
        f"expected run_chunk to return a list, got {type(records).__name__}: {records!r}"
    )

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

    for body in _DROP_BODIES:
        count = fake_client.marker_call_counts[body]
        assert count == 0, (
            f"expected the LLM to NEVER be called with a prompt containing "
            f"a dropped back-matter sections own body text (issue #113), "
            f"but its marker appeared in {count} call(s). Marker (start): "
            f"{body[:80]!r}."
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
        count = fake_client.marker_call_counts[body]
        assert count >= 1, (
            f"expected a kept sections own body text to appear in at least "
            f"one chunking prompt, got {count} occurrence(s). Marker "
            f"(start): {body[:80]!r}"
        )

    for record in records:
        section = record.get("section")
        assert section in _KEEP_LABELS, (
            f"expected every chunk records section to be one of this "
            f"fixtures KEEP labels {sorted(_KEEP_LABELS)!r}, got {section!r} "
            f"(full record: {record!r})"
        )
