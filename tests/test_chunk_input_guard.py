"""Outer acceptance test for issue #118 (size guard in run_chunk mirroring
#111's xref input guard).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given an extraction tree with three top-level prose sections, the MIDDLE one
      an OCR-garbled / oversized section (> 30,000 chars and mostly
      non-alphabetic -- the same shape as the real tilly index chunk that
      motivated issue #111), and a stored envelope on disk
When  `axial.chunk.run_chunk` is called on that source
Then  the pass COMPLETES without raising (no stall, no exception)
And   the oversized section produces ZERO chunk records and the LLM is NEVER
      called with it as the target section being chunked (skip-before-call,
      exactly like xref's `_non_prose_skip_reason` guard, #111)
And   the skip is logged to stderr (mirrors xref's
      `xref: skipping chunk ...: <reason>` shape)
And   the two NORMAL prose sections on either side of it are still chunked as
      usual -- proving the guard skips only the oversized section, not the
      whole pass

See GitHub issue #118: `run_chunk`'s per-section loop (src/axial/chunk.py,
around line 487) sends every section with chunkable prose straight to the
LLM with no input-size guard at all today, unlike `axial.xref.run_xref`
(src/axial/xref.py:328-335), which already skips a chunk whose text trips
`_non_prose_skip_reason` (> `_XREF_MAX_CHUNK_CHARS` chars, or non-alpha ratio
> `_XREF_MAX_NON_ALPHA_RATIO`, xref.py:54-55/165-177) before ever calling the
LLM. A single oversized/garbled non-prose section reaching `run_chunk`'s LLM
call can stall or blow up the chunk pass exactly the way the ungarded xref
pass used to (issue #111's own motivating incident). The fix (built by the
implementer, not this test) mirrors that guard verbatim into `run_chunk`'s
per-section loop, applied to the section's own body text, before
`compose_chunk_prompt`/`complete_json` are ever called for that section's
turn as the target.

As of this commit `run_chunk` has no such guard, so this test is expected to
fail red for exactly that reason: the oversized section currently DOES get
an LLM call (as the target section), currently DOES produce a chunk record,
and nothing is logged to stderr about skipping it. It must not fail on an
import error, a fixture-arrangement error, or a call-signature mismatch --
only on the guard-behavior assertions below.

Seam decision 1 -- bypassing docling/network via a monkeypatched
axial.chunk.extract, calling run_chunk directly
-----------------------------------------------------------------------
Mirrors tests/test_chunk_backmatter_filter.py's seam exactly (that test's own
module docstring, seam decision 1, itself mirroring
tests/test_xref_checkpoint.py): `axial.chunk.run_chunk` imports `extract`
directly into its own module namespace, so monkeypatching the module
attribute `axial.chunk.extract` redirects every call to a fake returning a
hand-built, synthetic extraction tree -- no real PDF, no docling, no
network. `run_chunk`'s own per-section loop and (once built) size-guard logic
is never bypassed; only its upstream structural-extraction dependency is.

`run_chunk` also requires a stored envelope on disk before it will do
anything (`MissingEnvelopeError` otherwise) -- this test writes one directly
to a tmp_path-scoped `envelopes_dir` passed explicitly to `run_chunk`, so no
`axial envelope` pass (and no LLM call for it) is needed to arrange it.

Seam decision 2 -- a fake LLM client that counts total calls, and refuses to
answer the guarded section's own text
-----------------------------------------------------------------------
Unlike tests/test_chunk_backmatter_filter.py's `_MarkerCountingClient` (which
merely counts marker occurrences across ALL prompts, including legitimate
neighbour-context inclusion), issue #118's guard does not remove the
oversized section from the extraction tree the way issue #113's title filter
does -- it only skips that section's own turn AS THE TARGET being chunked.
The oversized section therefore MAY legitimately still appear as neighbour
context in an adjacent section's own prompt (PRD §5 stage 4 / §8 P0-4,
"envelope + neighbours, not the isolated section" -- already locked by
tests/test_chunk.py and unrelated to this guard). This test does not assert
against that: it asserts the stronger, unambiguous, implementation-agnostic
fact that matters for issue #118 -- the total number of LLM calls made across
the whole run is exactly 2 (one per normal prose section), not 3, proving the
oversized section's own turn as a chunking target never made a call at all --
mirroring tests/test_xref_input_guard.py's identical `call_count == 2`
assertion shape for the equivalent guard in the xref pass.

Test hygiene: every path this test touches (envelopes_dir, the synthetic
source file) lives under pytest's own tmp_path, outside this repo entirely --
nothing here reads or writes any real data/ directory, and no real
LLM/network/docling call is ever made.
"""

from __future__ import annotations

import json

import axial.chunk as chunk_module
from axial.envelope import compute_source_id
from axial.llm import CHUNK_PASS_NAME

_INTRO_BODY = (
    "Introduction sentinel: this opening section states the paper's central "
    "claim and previews the comparative cases that will support it."
)
_CONCLUSION_BODY = (
    "Conclusion sentinel: this closing section restates the paper's central "
    "claim in light of the comparative cases surveyed across the body."
)

# An OCR-garbled / oversized non-prose section: > 30,000 chars, and heavily
# non-alphabetic (~69% non-alpha) -- the same shape as the real tilly index
# chunk (42,144 chars, ~55% non-alpha) that motivated issue #111's guard in
# the xref pass. Well over both of xref's own thresholds
# (_XREF_MAX_CHUNK_CHARS = 30000, _XREF_MAX_NON_ALPHA_RATIO = 0.4), which
# issue #118 requires run_chunk to mirror exactly.
GUARDED_BODY = "Abbasid, 12, 45, 78; Cairo, 3, 9, 210; " * 900
assert len(GUARDED_BODY) > 30000
assert (sum(1 for c in GUARDED_BODY if not c.isalpha()) / len(GUARDED_BODY)) > 0.4

_GUARDED_HEADING = "Scanned Materials"

_SECTION_SPECS = [
    ("Introduction", _INTRO_BODY),
    (_GUARDED_HEADING, GUARDED_BODY),
    ("Conclusion", _CONCLUSION_BODY),
]

_VALID_CHUNK_RESPONSE = json.dumps({"chunks": [{"text": "a synthetic stub chunk of prose"}]})


def _build_synthetic_tree():
    children = []
    for index, (heading, body) in enumerate(_SECTION_SPECS, start=1):
        children.append(
            {
                "type": "section",
                "order": str(index),
                "text": heading,
                "children": [{"type": "prose", "order": f"{index}.1", "text": body}],
            }
        )
    return {"type": "root", "order": "0", "children": children}


class _CountingClient:
    """Fake LLMClient: counts every call made. It always returns a
    well-formed chunk response, so any section that IS still processed
    completes normally without needing a real model."""

    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == CHUNK_PASS_NAME, (
            f"expected pass_name={CHUNK_PASS_NAME!r}, got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return _VALID_CHUNK_RESPONSE

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def _arrange(tmp_path, monkeypatch):
    source_path = tmp_path / "synthetic_source_with_oversized_section.txt"
    source_path.write_text(
        "synthetic multi-section source for issue #118 size-guard test",
        encoding="utf-8",
    )
    source_id = compute_source_id(source_path)

    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()
    envelope = {
        "source_id": source_id,
        "author": "Synthetic Author",
        "title": "Synthetic Source With An Oversized Section",
        "date": "2026",
        "thesis": "A synthetic thesis for issue #118's size-guard fixture.",
        "toc": [heading for heading, _body in _SECTION_SPECS],
        "scope": "A synthetic single-source fixture for issue #118.",
        "stated_argument": "A synthetic stated argument for issue #118's fixture.",
    }
    (envelopes_dir / f"{source_id}.json").write_text(json.dumps(envelope), encoding="utf-8")

    monkeypatch.setattr(chunk_module, "extract", lambda path: _build_synthetic_tree())

    return source_path, envelopes_dir


def test_oversized_section_is_skipped_never_sent_to_llm_as_target(tmp_path, monkeypatch, capsys):
    source_path, envelopes_dir = _arrange(tmp_path, monkeypatch)
    client = _CountingClient()

    records = chunk_module.run_chunk(
        source_path,
        client=client,
        envelopes_dir=envelopes_dir,
    )

    assert isinstance(records, list), (
        f"expected run_chunk to return a list, got {type(records).__name__}: {records!r}"
    )

    # The oversized section must never itself be chunked as a target: no
    # chunk record may carry its section label.
    guarded_records = [r for r in records if r.get("section") == _GUARDED_HEADING]
    assert not guarded_records, (
        f"expected ZERO chunk records for the oversized/garbled section "
        f"{_GUARDED_HEADING!r} (issue #118, mirroring #111's xref guard), "
        f"but found: {guarded_records!r}"
    )

    # Exactly 2 LLM calls total (Introduction, Conclusion) -- the oversized
    # section's own turn as a chunking target never reached the LLM at all.
    # This is the direct, implementation-agnostic proof of "skip before the
    # call", mirroring tests/test_xref_input_guard.py's identical
    # call_count == 2 assertion for xref's equivalent guard.
    assert client.call_count == 2, (
        f"expected exactly 2 LLM calls (the two normal prose sections only); "
        f"the oversized section must be skipped before any LLM call is made "
        f"for its own turn as a chunking target, got {client.call_count}"
    )

    # The normal prose sections on either side are still chunked as usual --
    # proving the guard skips only the oversized section, not the whole pass.
    kept_sections_seen = {r.get("section") for r in records}
    assert kept_sections_seen == {"Introduction", "Conclusion"}, (
        f"expected both normal prose sections to still produce chunk "
        f"record(s), got sections present: {sorted(kept_sections_seen)!r}. "
        f"Full records: {records!r}"
    )

    # The skip is logged to stderr, identifying the guarded section.
    err = capsys.readouterr().err
    assert "skip" in err.lower() and _GUARDED_HEADING in err, (
        f"expected the skipped section to be logged to stderr naming it and "
        f"a reason (mirroring xref's 'xref: skipping chunk ...: <reason>' "
        f"shape), got: {err!r}"
    )


def test_source_of_only_oversized_section_completes_with_zero_chunks(tmp_path, monkeypatch):
    """Pathological edge: a source whose only section is oversized/garbled
    skips everything and returns zero chunk records without stalling or
    raising -- mirrors tests/test_xref_input_guard.py's equivalent edge
    case for the xref pass."""
    source_path = tmp_path / "synthetic_source_only_oversized.txt"
    source_path.write_text("only an oversized section", encoding="utf-8")
    source_id = compute_source_id(source_path)

    envelopes_dir = tmp_path / "envelopes"
    envelopes_dir.mkdir()
    envelope = {
        "source_id": source_id,
        "author": "Synthetic Author",
        "title": "Synthetic Source With Only An Oversized Section",
        "date": "2026",
        "thesis": "A synthetic thesis.",
        "toc": [_GUARDED_HEADING],
        "scope": "A synthetic single-source fixture for issue #118.",
        "stated_argument": "A synthetic stated argument.",
    }
    (envelopes_dir / f"{source_id}.json").write_text(json.dumps(envelope), encoding="utf-8")

    synthetic_tree = {
        "type": "root",
        "order": "0",
        "children": [
            {
                "type": "section",
                "order": "1",
                "text": _GUARDED_HEADING,
                "children": [{"type": "prose", "order": "1.1", "text": GUARDED_BODY}],
            }
        ],
    }
    monkeypatch.setattr(chunk_module, "extract", lambda path: synthetic_tree)

    client = _CountingClient()
    records = chunk_module.run_chunk(
        source_path,
        client=client,
        envelopes_dir=envelopes_dir,
    )

    assert client.call_count == 0, (
        "no prose sections other than the oversized one -> no LLM call at all"
    )
    assert records == [], "no chunkable non-guarded prose -> no chunk records"
