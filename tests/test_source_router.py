"""Outer acceptance test for issue #167 (source-router slice 02: router-core).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Spec: `specs/PRODUCT.md` §7.8 (routing decisions / source router), §5 step 2b,
§8 P0-4. Between structural extraction and the passes that consume the tree,
a single source router classifies every tree BLOCK (not just whole sections)
by its docling structural `label` into exactly one of three routes:

- **prose** -- `text`, `section_header`, `title`, and an in-body `list_item`.
  The only blocks that ever reach the chunk path.
- **artifact** -- `table`, `picture`, `caption`. Routed to the (not-yet-built)
  artifact pass; never chunked, and NOT recorded as a router drop (it isn't
  dropped -- it goes somewhere else).
- **apparatus** -- `document_index` (TOC/index), `footnote`
  (endnotes/footnotes), `page_header`, `page_footer`, and a `list_item` whose
  enclosing section is back-matter. DROPPED: not chunked, not
  artifact-noted, and each drop is recorded to the router-owned skip
  artifact with a reason.
- Unknown/absent/empty label fails open to **prose** (never silently
  dropped).

Acceptance criterion (issue #167 plan)
---------------------------------------------------------------------------
Given a persisted tree with prose sections, a table-of-contents
      (document_index) block, an endnotes (footnote) block, an in-body
      list, and a captioned figure
When   the operator runs `axial chunk` on the source
Then   only the prose sections and the in-body list are chunked into
       data/chunks/<source_id>.jsonl
And    the document_index and footnote blocks are absent from the chunks
       and are recorded in the router skip artifact with a reason
And    the caption text is absent from the chunks (routed to the artifact
       path, not dropped as apparatus)
And    a list_item under a back-matter section (e.g. a reference list) is
       dropped as apparatus, not chunked

Why this is a BLOCK-level test, not merely a section-level one
---------------------------------------------------------------------------
`_is_back_matter` (issue #113) already drops an entire section pre-chunking
when its own TITLE matches a fixed back-matter set (see
`tests/test_chunk_backmatter_filter.py`) -- that is section-granularity
filtering on the section's own heading, and it existed before this issue.
The source router (§7.8) is a genuinely different, finer-grained mechanism:
it classifies each BLOCK inside a section by that block's OWN `label`, so a
document_index or footnote block sitting *inside* an otherwise-ordinary
section (sibling to real kept prose) must be dropped while its prose
siblings in the very same section are still chunked. To actually exercise
that (and not accidentally pass this test via the pre-existing whole-section
title filter), the document_index and footnote blocks below are nested
inside sections whose OWN heading does NOT match `_is_back_matter`'s title
set at all -- "Front Matter" and "Chapter Two" respectively -- so the only
thing that can legitimately keep their body text out of the emitted chunks
is genuine block-level, label-driven routing.

The back-matter `list_item` case (§7.8's own worked example: "a `list_item`
... apparatus only when its enclosing section is back-matter") is, by
contrast, deliberately built inside a section titled "References" --
`_is_back_matter`'s own recognized title -- per the issue's own mechanics
note ("reuse a back-matter section title `chunk._is_back_matter`
recognizes"). This assertion is a scope lock (mirroring
`test_chunk_backmatter_filter.py`'s own "explicitly-kept boundary sections"
locks): it must keep holding as the router lands, whichever of the two
existing/new mechanisms is doing the dropping.

Seam decision 1 -- bypassing docling/network entirely via a monkeypatched
axial.chunk.tree_path/load_persisted_tree, calling run_chunk_embedding
directly
---------------------------------------------------------------------------
Mirrors `tests/test_chunk_backmatter_filter.py`'s own `_patch_tree` helper
exactly: `run_chunk_embedding` reads the persisted structural tree via
`axial.chunk.tree_path`/`axial.chunk.load_persisted_tree` (imported directly
into `axial.chunk`'s own module namespace), so monkeypatching those two
module attributes redirects the read to a hand-built, synthetic extraction
tree -- no real PDF, no docling, no network, no envelope.

Seam decision 2 -- proving "dropped/routed away", not merely "absent from
this run's output": body-text markers checked as a substring of EVERY
emitted chunk's text
---------------------------------------------------------------------------
Every block below carries distinct, greppable body text (no block's text is
a substring of another's), so this test asserts a dropped/artifact-routed
block's own marker text never appears as a substring of ANY emitted chunk's
`text` field -- not just that no chunk record happens to carry a particular
section label. An implementation that filtered records post-hoc after
already merging an apparatus/artifact block's body into a section's overall
chunked text (a body-concatenation bug) would fail this stronger check even
if it "looked" filtered at the section-summary level.

Seam decision 3 -- the skip-artifact assertions stay agnostic to the exact
per-block field layout
---------------------------------------------------------------------------
The router-owned skip sidecar (`chunks_skips_sidecar_path`,
`<source_id>.skips.jsonl`) is documented today (see `axial.chunk`'s own
docstrings) as one JSON object per line; issue #167's mechanics note
describes it as carrying (at least) a `reason` per drop. This test does not
assume which field the implementer uses to name a within-section apparatus
block's own provenance (the enclosing section's heading vs. the block's own
order/text) -- that is an implementation choice the router slice is free to
make. What the test DOES lock down, because the spec requires it
unconditionally: (a) at least one skip record exists per apparatus block
dropped (document_index, footnote), each carrying a non-empty `reason`; and
(b) the caption's own marker text never appears anywhere in the skip
artifact at all (a caption is artifact-routed, not apparatus-dropped, so it
must never surface in the "dropped with a reason" log -- conflating the two
routes would be a real bug this test must catch).

Test hygiene: every path this test touches (the synthetic source file,
`chunks_dir`) lives under pytest's own `tmp_path`, outside this repo
entirely -- nothing here reads or writes any real `data/` directory, and no
real LLM/network/docling call is ever made (the embedding chunk stage makes
none, full stop).
"""

from __future__ import annotations

import json

import axial.chunk as chunk_module
from axial.chunk import HashingEmbedder, run_chunk_embedding
from axial.envelope import compute_source_id

# --- distinct, greppable sentinel body text for every block ----------------
# No sentinel's text is a substring of any other's -- so a leak of ANY block
# into ANY emitted chunk is unambiguously detectable.

_CHAPTER_ONE_BODY = (
    "Chapter one prose sentinel: the harvest failed twice in three years, and "
    "the resulting grain shortage forced the council to ration bread supplies."
)
_INBODY_LIST_BODY = (
    "In-body list sentinel item: first, secure the perimeter; second, count "
    "the remaining stores; third, notify the neighboring garrison at once."
)
_CAPTION_BODY = (
    "Caption sentinel: figure showing the fortress wall breach photographed "
    "by the survey team during the autumn assessment expedition."
)
_FRONT_MATTER_BODY = (
    "Front matter prose sentinel: this volume collects three decades of "
    "correspondence between the two commanders during the long campaign."
)
_TOC_BODY = (
    "Table-of-contents sentinel entry: Chapter One .. 1, Chapter Two .. 45, "
    "Appendix .. 210, listing every part of the volume in reading order."
)
_CHAPTER_TWO_BODY = (
    "Chapter two prose sentinel: negotiations stalled for weeks over the "
    "disputed river crossing until a neutral envoy proposed a compromise."
)
_FOOTNOTE_BODY = (
    "Footnote sentinel: see the earlier discussion of the treaty's third "
    "clause for the disputed translation of the original diplomatic cable."
)
_BACKMATTER_LIST_BODY = (
    "Back-matter list sentinel entry: Alpha, K. (2015) On River Boundaries, "
    "Frontier Press, pp. 12-40; Beta, L. (2016) Envoys and Treaties, Capital."
)

_KEPT_BODIES = [
    _CHAPTER_ONE_BODY,
    _INBODY_LIST_BODY,
    _FRONT_MATTER_BODY,
    _CHAPTER_TWO_BODY,
]
_DROPPED_OR_ROUTED_AWAY_BODIES = [
    _CAPTION_BODY,
    _TOC_BODY,
    _FOOTNOTE_BODY,
    _BACKMATTER_LIST_BODY,
]
# Apparatus drops that MUST surface in the router skip artifact with a
# reason (caption is deliberately excluded -- it is artifact-routed, not
# apparatus-dropped; see seam decision 3).
_APPARATUS_DROP_BODIES = [_TOC_BODY, _FOOTNOTE_BODY]


def _leaf(order: str, label: str, text: str) -> dict:
    return {"type": "prose", "order": order, "text": text, "label": label}


def _section(order: str, heading: str, children: list[dict]) -> dict:
    return {
        "type": "prose",
        "order": order,
        "text": heading,
        "label": "section_header",
        "children": children,
    }


def _build_synthetic_tree() -> dict:
    return {
        "children": [
            # Section 1: ordinary prose section mixing a normal paragraph,
            # an in-body list (kept -- prose by default), and a caption
            # (artifact-routed, must vanish from chunk output but NOT be
            # logged as a router drop).
            _section(
                "1",
                "Chapter One",
                [
                    _leaf("1.1", "text", _CHAPTER_ONE_BODY),
                    _leaf("1.2", "list_item", _INBODY_LIST_BODY),
                    _leaf("1.3", "caption", _CAPTION_BODY),
                ],
            ),
            # Section 2: heading does NOT match `_is_back_matter`'s title
            # set, so only genuine block-level, label-driven routing can
            # keep the document_index block's text out of the chunk output
            # (see the module docstring's "why this is a block-level test").
            _section(
                "2",
                "Front Matter",
                [
                    _leaf("2.1", "text", _FRONT_MATTER_BODY),
                    _leaf("2.2", "document_index", _TOC_BODY),
                ],
            ),
            # Section 3: same reasoning, for the footnote/endnote label.
            _section(
                "3",
                "Chapter Two",
                [
                    _leaf("3.1", "text", _CHAPTER_TWO_BODY),
                    _leaf("3.2", "footnote", _FOOTNOTE_BODY),
                ],
            ),
            # Section 4: a `list_item` whose ENCLOSING SECTION is back-matter
            # (title "References", recognized by `_is_back_matter`) -- per
            # §7.8, apparatus only in this case. Reuses the existing
            # back-matter title on purpose (issue #167's own mechanics
            # note); see the module docstring for why this is a scope lock,
            # not the test's primary source of redness.
            _section(
                "4",
                "References",
                [
                    _leaf("4.1", "list_item", _BACKMATTER_LIST_BODY),
                ],
            ),
        ]
    }


def _patch_tree(monkeypatch, tmp_path, tree: dict) -> None:
    """Mirrors `tests/test_chunk_backmatter_filter.py`'s own `_patch_tree`
    helper (see module docstring, seam decision 1)."""
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_module, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_module, "load_persisted_tree", lambda path: tree)


def _read_skip_records(chunks_dir, source_id: str) -> list[dict]:
    """Read whatever landed at the router-owned skip sidecar for
    `source_id`, tolerating "file doesn't exist" as "zero skip records"
    (a legitimate outcome to fail an assertion against, not a test error)."""
    skip_path = chunk_module.chunks_skips_sidecar_path(source_id, chunks_dir)
    if not skip_path.exists():
        return []
    return chunk_module.load_chunk_checkpoint(skip_path)


def test_source_router_classifies_blocks_by_label_before_chunking(tmp_path, monkeypatch):
    source_path = tmp_path / "synthetic_source_for_router_test.txt"
    source_path.write_text(
        "synthetic multi-block source for issue #167 source-router test",
        encoding="utf-8",
    )
    source_id = compute_source_id(source_path)

    _patch_tree(monkeypatch, tmp_path, _build_synthetic_tree())

    chunks_dir = tmp_path / "chunks"
    records = run_chunk_embedding(source_path, embedder=HashingEmbedder(), chunks_dir=chunks_dir)

    assert isinstance(records, list), (
        f"expected run_chunk_embedding to return a list, got {type(records).__name__}: {records!r}"
    )
    assert records, "expected at least one chunk record from the kept prose, got none"

    # --- prose route: kept bodies (including the in-body list) must be
    # chunked -----------------------------------------------------------
    for body in _KEPT_BODIES:
        matching = [r for r in records if body in r.get("text", "")]
        assert matching, (
            f"expected a KEPT prose/in-body-list block's own body text to "
            f"appear in at least one emitted chunk's text, got none. "
            f"Marker (start): {body[:80]!r}. Full records: {records!r}"
        )

    # --- apparatus route (document_index, footnote) + artifact route
    # (caption) + back-matter list_item: NONE of these bodies may ever leak
    # into any emitted chunk's text, no matter which route "handled" them
    # ---------------------------------------------------------------------
    for body in _DROPPED_OR_ROUTED_AWAY_BODIES:
        leaked = [r for r in records if body in r.get("text", "")]
        assert not leaked, (
            f"expected this block's own body text to never appear inside "
            f"any emitted chunk's text (source router §7.8: it is either "
            f"apparatus-dropped or artifact-routed, never chunked as "
            f"prose), but it leaked into: {leaked!r}. "
            f"Marker (start): {body[:80]!r}"
        )

    # --- apparatus drops (document_index, footnote) must be recorded in
    # the router skip artifact, each with a non-empty reason (§7.8: "each
    # drop is recorded with a reason") -------------------------------------
    skip_records = _read_skip_records(chunks_dir, source_id)
    assert len(skip_records) >= len(_APPARATUS_DROP_BODIES), (
        f"expected at least {len(_APPARATUS_DROP_BODIES)} router skip "
        f"record(s) -- one per dropped apparatus block (the document_index "
        f"and footnote blocks) -- but found {len(skip_records)}: "
        f"{skip_records!r}"
    )
    for record in skip_records:
        reason = record.get("reason")
        assert isinstance(reason, str) and reason.strip(), (
            f"expected every router skip record to carry a non-empty "
            f"'reason', got record {record!r} (full sidecar: {skip_records!r})"
        )

    # --- the caption must NEVER be conflated with an apparatus drop: its
    # marker text must not surface anywhere in the skip artifact at all
    # (it is artifact-routed, not dropped) ---------------------------------
    skip_blob = json.dumps(skip_records)
    assert _CAPTION_BODY not in skip_blob, (
        f"expected the caption's own body text to never appear in the "
        f"router skip artifact (a caption is artifact-routed, not "
        f"apparatus-dropped, per §7.8 -- it must never be logged as a "
        f"'drop with a reason'), but found it in: {skip_records!r}"
    )
