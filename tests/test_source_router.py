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
import axial.tag as tag_module
import axial.xref as xref_module
from axial.chunk import HashingEmbedder, run_chunk_embedding
from axial.envelope import compute_source_id
from axial.llm import TAG_PASS_NAME, XREF_PASS_NAME, StubLLMClient
from axial.router import apparatus_reason

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


# =============================================================================
# Outer acceptance test for issue #169 (source-router slice 04:
# gate-retire-examine)
# =============================================================================
#
# Locked behavioral contract (DEC-1) -- do not edit once committed red. This
# section is ADDED to the existing slice-02 contract above (untouched); it
# does not alter a single line of it.
#
# Spec: `specs/PRODUCT.md` §7.8 ("single source of skip truth" -- the
# `non_prose_skip_reason` per-pass guard is "demoted to a backstop for
# genuinely garbled prose that slips type classification; it is no longer
# the primary prose/non-prose gate"), §7.7 (chunk artifact + examine: "the
# count of blocks the router dropped ... with their reasons, read from the
# router-owned skip record ... the single source of skip truth, not a
# per-pass guard"), §8 P0-4b.
#
# Acceptance criterion (issue #169 plan)
# ---------------------------------------------------------------------------
# Given routed prose chunks (data/chunks/<source_id>.jsonl) and the router's
#       recorded drops
# When  the operator runs the downstream passes (tag, xref) and then
#       `axial chunk examine`
# Then  no tag/xref pass re-derives the prose/non-prose decision -- every
#       prose chunk reaches its pass
# And   `axial chunk examine` reports the dropped document_index / index /
#       footnote blocks with the router's reasons (the single source of skip
#       truth)
# And   a genuinely garbled prose chunk is still caught by the retained
#       backstop, not silently tagged
#
# The red lever
# ---------------------------------------------------------------------------
# Today (before this slice), `axial.tag.run_tag` and `axial.xref.run_xref`
# both call `axial.nonprose_guard.non_prose_skip_reason` as their PRIMARY
# gate on every chunk -- a heuristic with TWO independent arms: skip if
# `len(text) > 30_000` chars, OR skip if the non-alphabetic ratio exceeds
# 40%. The size arm alone is what this test levers: `_LARGE_LEGIT_TEXT`
# below is ordinary, low-non-alpha English prose (~17.6% non-alpha) that is
# nonetheless > 30,000 chars -- today's primary gate skips it (never reaches
# an LLM call) purely because it is long, even though it is exactly the kind
# of "legitimate prose" §7.7 says "size never triggers a skip" for. After
# this slice demotes the primary gate to a garble-only backstop (mirroring
# `axial.chunk._garbage_section_skip_reason`'s own "non-alpha arm ONLY"
# precedent), this same chunk MUST reach its pass. `_GARBLED_TEXT` is the
# control: short (well under 30,000 chars) but heavily non-alphabetic
# (~69.2%), so it isolates the RETAINED garble arm from the RETIRED size
# arm -- it must stay skipped both before and after this slice, proving the
# backstop is a deliberate, logged skip, never a silent loss.
#
# Seam decision 1 -- real on-disk chunk artifact, real `read_chunks`, no
# `read_chunks` monkeypatch
# ---------------------------------------------------------------------------
# Unlike tests/test_xref_input_guard.py and tests/test_tag_artifacts_input_
# guard.py (which monkeypatch `read_chunks` to hand back synthetic records
# in-memory), this test writes real chunk records to
# `<chunks_dir>/<source_id>.jsonl` (via the real `axial.chunk.
# build_chunk_records` + `chunks_checkpoint_path`, the same helpers `axial
# chunk` itself uses) and a real router-owned skip sidecar to
# `<chunks_dir>/<source_id>.skips.jsonl` (via the real `axial.chunk.
# chunks_skips_sidecar_path`), then drives `run_tag`/`run_xref` with
# `chunks_dir=` pointed at that directory so they go through the REAL
# `axial.chunk.read_chunks` disk-reading path -- and `axial.chunk.
# examine_chunks` reads the very same on-disk artifact afterward. This is
# the "Given routed prose chunks (data/chunks/<source_id>.jsonl) and the
# router's recorded drops" half of the Gherkin literally, not a stand-in.
#
# Seam decision 2 -- `run_artifacts` is monkeypatched inside `run_xref` only
# ---------------------------------------------------------------------------
# `run_xref` internally calls `run_artifacts`, which calls `axial.artifacts.
# extract` on the real source path -- unrelated to this slice (artifact
# routing/captioning is locked green from slice 03) and no real docling call
# is warranted here, so `xref_module.run_artifacts` is monkeypatched to
# return one fixed, known artifact id, exactly mirroring tests/
# test_xref_input_guard.py's own `_make_env` seam.
#
# Seam decision 3 -- counting stub clients, keyed by chunk_id seen in the
# prompt
# ---------------------------------------------------------------------------
# Mirrors tests/test_tag_artifacts_input_guard.py's `_TagCountingClient` /
# tests/test_xref_input_guard.py's `_CountingClient` exactly: a fake client
# that always answers with a well-formed, schema-valid canned response (so
# no re-ask path ever fires) while recording every prompt it was called
# with. "The guarded item's own turn never reached the LLM at all" is proven
# directly through call counts and prompt-content membership -- the same
# discipline the slice-02/#132 guard tests already use, now applied to
# prove the OPPOSITE outcome for the large-legit chunk (it must be called)
# while still proving it for the garbled chunk (it must not).
#
# Test hygiene: every path this test touches lives under pytest's own
# `tmp_path`; the real `config/domains/syria` domain is loaded (the schema/
# codebook `run_tag` requires to run at all -- the same real, git-tracked
# domain every other in-process `run_tag` acceptance test already relies
# on), but no real LLM/network/docling call is ever made.

_LARGE_LEGIT_SENTENCE = (
    "The council debated policy long into the night, and eventually reached a "
    "fragile compromise that satisfied few but was accepted by all as workable "
    "for the coming season. "
)
_LARGE_LEGIT_TEXT = _LARGE_LEGIT_SENTENCE * 200
assert len(_LARGE_LEGIT_TEXT) > 30000, "fixture must exceed the retired size-arm threshold"
_LARGE_LEGIT_NON_ALPHA_RATIO = sum(1 for c in _LARGE_LEGIT_TEXT if not c.isalpha()) / len(
    _LARGE_LEGIT_TEXT
)
assert _LARGE_LEGIT_NON_ALPHA_RATIO <= 0.4, (
    "fixture must stay well under the retained non-alpha backstop threshold "
    "-- only the size arm should ever have gated this text"
)

_PROSE_A_TEXT = "As shown above, the prose here discusses the argument in ordinary detail."

# Short (well under the retired 30,000-char size threshold) but heavily
# non-alphabetic ("term, page, page" soup), the identical fixture shape
# tests/test_xref_input_guard.py and tests/test_tag_artifacts_input_guard.py
# already use for their own guard fixtures -- kept short here specifically
# so it can ONLY be caught by the retained non-alpha backstop, never by the
# retired size arm, isolating exactly what this slice must still catch.
_GARBLED_TEXT = "Abbasid, 12, 45, 78; Cairo, 3, 9, 210; " * 200
assert len(_GARBLED_TEXT) < 30000, "fixture must stay under the retired size-arm threshold"
_GARBLED_NON_ALPHA_RATIO = sum(1 for c in _GARBLED_TEXT if not c.isalpha()) / len(_GARBLED_TEXT)
assert _GARBLED_NON_ALPHA_RATIO > 0.4, "fixture must exceed the retained backstop threshold"

_TOC_REASON = apparatus_reason("document_index")
_FOOTNOTE_REASON = apparatus_reason("footnote")


def _write_routed_chunk_artifact(chunks_dir, source_id: str) -> dict[str, str]:
    """Write a real on-disk chunk artifact (`<chunks_dir>/<source_id>.jsonl`)
    holding three routed prose chunk records -- an ordinary chunk, the large-
    but-legitimate chunk the retired size arm must stop gating, and the
    genuinely garbled chunk the retained backstop must keep gating -- via the
    same `build_chunk_records`/`chunks_checkpoint_path` helpers `axial chunk`
    itself uses. Returns a name -> chunk_id map for the three records."""
    records = (
        chunk_module.build_chunk_records(source_id, "1", "Chapter One", [{"text": _PROSE_A_TEXT}])
        + chunk_module.build_chunk_records(
            source_id, "2", "Front Matter", [{"text": _LARGE_LEGIT_TEXT}]
        )
        + chunk_module.build_chunk_records(source_id, "3", "Chapter Two", [{"text": _GARBLED_TEXT}])
    )
    out_path = chunk_module.chunks_checkpoint_path(source_id, chunks_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return {
        "prose_a": records[0]["chunk_id"],
        "large_legit": records[1]["chunk_id"],
        "garbled": records[2]["chunk_id"],
    }


def _write_router_skip_sidecar(chunks_dir, source_id: str) -> None:
    """Write a real router-owned skip sidecar
    (`<chunks_dir>/<source_id>.skips.jsonl`) recording the two apparatus
    drops the router (slice 02) would have produced for a source with a
    table-of-contents (`document_index`) block and an endnotes (`footnote`)
    block -- the exact `{"section", "section_order", "reason"}` shape
    `axial.chunk._routed_section_body`/`run_chunk_embedding` already write,
    with the SAME reason text the real `axial.router.apparatus_reason`
    produces (never a hand-invented reason string)."""
    skips_path = chunk_module.chunks_skips_sidecar_path(source_id, chunks_dir)
    skip_records = [
        {"section": "Front Matter", "section_order": "2.2", "reason": _TOC_REASON},
        {"section": "Chapter Two", "section_order": "3.2", "reason": _FOOTNOTE_REASON},
    ]
    with skips_path.open("w", encoding="utf-8") as handle:
        for record in skip_records:
            handle.write(json.dumps(record) + "\n")


class _TagCountingClient:
    """Fake LLMClient: counts every tag-pass call made, always answering with
    the well-formed, schema-valid canned tag response (mirrors tests/
    test_tag_artifacts_input_guard.py's `_TagCountingClient`). Must never be
    called for a chunk the backstop is expected to still catch."""

    def __init__(self):
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == TAG_PASS_NAME, (
            f"expected pass_name={TAG_PASS_NAME!r}, got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return StubLLMClient._CANNED_TAG_RESPONSE

    @property
    def call_count(self) -> int:
        return len(self.prompts)


class _XrefCountingClient:
    """Fake LLMClient: counts every xref-pass call made, always answering
    with a reference to the one known artifact (mirrors tests/
    test_xref_input_guard.py's `_CountingClient`). Must never be called for a
    chunk the backstop is expected to still catch."""

    def __init__(self, artifact_id: str):
        self.prompts: list[str] = []
        self._artifact_id = artifact_id

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == XREF_PASS_NAME, (
            f"expected pass_name={XREF_PASS_NAME!r}, got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return json.dumps({"referenced_artifact_ids": [self._artifact_id]})

    @property
    def call_count(self) -> int:
        return len(self.prompts)


_XREF_ARTIFACT_ID = "art-1"

DOMAIN_DIR = "config/domains/syria"


def test_tag_pass_no_longer_pre_skips_large_legit_chunk_but_backstop_still_catches_garble(
    tmp_path, monkeypatch, capsys
):
    source_path = tmp_path / "tag_gate_retire_source.txt"
    source_path.write_text("slice-04 tag gate-retire source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    chunks_dir = tmp_path / "chunks"
    chunk_ids = _write_routed_chunk_artifact(chunks_dir, source_id)

    client = _TagCountingClient()
    records = tag_module.run_tag(
        source_path, client=client, domain_dir=DOMAIN_DIR, chunks_dir=chunks_dir
    )

    assert isinstance(records, list), (
        f"expected run_tag to return a list, got {type(records).__name__}: {records!r}"
    )

    tagged_chunk_ids = {r.get("chunk_id") for r in records}
    assert chunk_ids["large_legit"] in tagged_chunk_ids, (
        f"expected the large-but-legitimate prose chunk {chunk_ids['large_legit']!r} "
        f"(> 30,000 chars, ~{_LARGE_LEGIT_NON_ALPHA_RATIO:.1%} non-alpha) to REACH the "
        f"tag pass -- the retired size arm must no longer pre-skip it -- but it produced "
        f"no tagged record. Tagged chunk_ids: {sorted(tagged_chunk_ids)!r}"
    )
    assert chunk_ids["prose_a"] in tagged_chunk_ids
    assert chunk_ids["garbled"] not in tagged_chunk_ids, (
        f"expected the genuinely garbled chunk {chunk_ids['garbled']!r} "
        f"(~{_GARBLED_NON_ALPHA_RATIO:.1%} non-alpha) to STILL be caught by the "
        f"retained backstop -- it must never be silently tagged -- but found a "
        f"tagged record for it."
    )

    assert client.call_count == 2, (
        f"expected exactly 2 tag-pass LLM calls (prose_a + the large-legit chunk); "
        f"the garbled chunk must be skipped before any LLM call for its own turn, "
        f"got {client.call_count}"
    )
    joined_prompts = "".join(client.prompts)
    assert _LARGE_LEGIT_TEXT in joined_prompts, (
        "the large-but-legitimate chunk's own text must reach a tag-pass LLM prompt "
        "(proving it was not pre-skipped on size)"
    )
    assert _GARBLED_TEXT not in joined_prompts, (
        "the garbled chunk's own text must never reach a tag-pass LLM prompt"
    )

    err = capsys.readouterr().err
    assert chunk_ids["garbled"] in err and "skip" in err.lower(), (
        f"expected the backstop-caught garbled chunk to be logged to stderr with a "
        f"reason, got: {err!r}"
    )
    assert chunk_ids["large_legit"] not in err, (
        f"expected the large-legit chunk to NEVER be logged as skipped, got: {err!r}"
    )


def test_xref_pass_no_longer_pre_skips_large_legit_chunk_but_backstop_still_catches_garble(
    tmp_path, monkeypatch, capsys
):
    source_path = tmp_path / "xref_gate_retire_source.txt"
    source_path.write_text("slice-04 xref gate-retire source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    chunks_dir = tmp_path / "chunks"
    chunk_ids = _write_routed_chunk_artifact(chunks_dir, source_id)

    monkeypatch.setattr(
        xref_module, "run_artifacts", lambda path, **kwargs: [{"artifact_id": _XREF_ARTIFACT_ID}]
    )

    client = _XrefCountingClient(_XREF_ARTIFACT_ID)
    pairs = xref_module.run_xref(source_path, client=client, chunks_dir=chunks_dir)

    referencing_chunk_ids = {pair["chunk_id"] for pair in pairs}
    assert chunk_ids["large_legit"] in referencing_chunk_ids, (
        f"expected the large-but-legitimate prose chunk {chunk_ids['large_legit']!r} "
        f"(> 30,000 chars, ~{_LARGE_LEGIT_NON_ALPHA_RATIO:.1%} non-alpha) to REACH the "
        f"xref pass -- the retired size arm must no longer pre-skip it -- but no pair "
        f"was produced for it. Pairs: {pairs!r}"
    )
    assert chunk_ids["prose_a"] in referencing_chunk_ids
    assert chunk_ids["garbled"] not in referencing_chunk_ids, (
        f"expected the genuinely garbled chunk {chunk_ids['garbled']!r} "
        f"(~{_GARBLED_NON_ALPHA_RATIO:.1%} non-alpha) to STILL be caught by the "
        f"retained backstop -- it must never reach the xref LLM -- but found a pair "
        f"for it."
    )

    assert client.call_count == 2, (
        f"expected exactly 2 xref-pass LLM calls (prose_a + the large-legit chunk); "
        f"the garbled chunk must be skipped before any LLM call for its own turn, "
        f"got {client.call_count}"
    )
    joined_prompts = "".join(client.prompts)
    assert _LARGE_LEGIT_TEXT in joined_prompts, (
        "the large-but-legitimate chunk's own text must reach an xref-pass LLM prompt "
        "(proving it was not pre-skipped on size)"
    )
    assert _GARBLED_TEXT not in joined_prompts, (
        "the garbled chunk's own text must never reach an xref-pass LLM prompt"
    )

    err = capsys.readouterr().err
    assert chunk_ids["garbled"] in err and "skip" in err.lower(), (
        f"expected the backstop-caught garbled chunk to be logged to stderr with a "
        f"reason, got: {err!r}"
    )
    assert chunk_ids["large_legit"] not in err, (
        f"expected the large-legit chunk to NEVER be logged as skipped, got: {err!r}"
    )


def test_chunk_examine_reports_router_apparatus_drops_as_single_source_of_skip_truth(tmp_path):
    source_path = tmp_path / "examine_gate_retire_source.txt"
    source_path.write_text("slice-04 examine source", encoding="utf-8")
    source_id = compute_source_id(source_path)

    chunks_dir = tmp_path / "chunks"
    _write_routed_chunk_artifact(chunks_dir, source_id)
    _write_router_skip_sidecar(chunks_dir, source_id)

    stats = chunk_module.examine_chunks(chunks_dir)
    reasons_seen = {skip.reason for skip in stats.skips if skip.source_id == source_id}
    assert _TOC_REASON in reasons_seen, (
        f"expected `axial chunk examine` to report the router-recorded "
        f"document_index (table-of-contents) drop with its own reason "
        f"{_TOC_REASON!r} -- the single source of skip truth (§7.8) -- but "
        f"found reasons: {reasons_seen!r}"
    )
    assert _FOOTNOTE_REASON in reasons_seen, (
        f"expected `axial chunk examine` to report the router-recorded "
        f"footnote (endnotes) drop with its own reason {_FOOTNOTE_REASON!r} "
        f"-- the single source of skip truth (§7.8) -- but found reasons: "
        f"{reasons_seen!r}"
    )

    report = chunk_module.format_examine_report(stats)
    assert _TOC_REASON in report, (
        f"expected the formatted examine report to surface the "
        f"document_index drop reason {_TOC_REASON!r}, got:\n{report}"
    )
    assert _FOOTNOTE_REASON in report, (
        f"expected the formatted examine report to surface the footnote "
        f"drop reason {_FOOTNOTE_REASON!r}, got:\n{report}"
    )
