"""Outer acceptance test for issue #207: "Substantive-content gate before
tagging: classify/drop apparatus, merge short chunks (+ per-pass reasoning)".

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Spec: `specs/PRODUCT.md` §7.8 ("Content-detected apparatus" and "Model-backed
classification of flagged candidates"), §7.9 (per-pass model reasoning), and
§8 P0-4 (the MIN-side merge paragraph). See also issue #207's own body for
the root-cause measurement (~1,017 non-content notes + ~2,195 short
fragments leaking to tag/vault/gold on the real 30-source corpus) and its
locked acceptance test outline.

This file pins three independent behaviors from the issue in three test
functions, deliberately kept separate from each other (a failure in one must
never mask or explain a failure in another):

1. `test_content_apparatus_gate_...` -- the router's new content arm: a
   `text`-labelled block that is a dense run of bibliographic citations is
   flagged by a cheap deterministic pre-filter, sent to exactly one bounded
   model classification call, resolved to apparatus, dropped, and recorded
   in the skip sidecar with a distinct reason -- while a block that merely
   cites a source once in passing stays prose and never reaches the model at
   all (conservative gating, zero model spend on the unflagged majority).

2. `test_chunk_min_side_merges_subfloor_chunk_into_same_section_predecessor`
   -- the chunk stage's revised MIN-side band guard: a sub-`CHUNK_MIN` chunk
   with an eligible same-section PREDECESSOR merges backward into it (never
   forward, when a predecessor is available and the merge stays <=
   `CHUNK_MAX`), so it no longer survives as a standalone sub-floor note.
   This is the trailing-short-chunk case §8 P0-4 changes: today's
   `_enforce_min` only ever merges a short chunk FORWARD, so a section's
   trailing short chunk -- with nothing after it to absorb it -- is the one
   documented case allowed to remain below `CHUNK_MIN` (see
   tests/chunk/test_chunk_low_alpha_floor.py's own docstring, which names
   this exact forward-only behavior as *why* a section's tail is the only
   chunk this floor ever has to evaluate in isolation). §207 closes that gap
   by preferring a same-section predecessor merge over leaving the chunk
   stranded.

3. `test_per_pass_reasoning_...` -- reasoning is a per-pass setting (§7.9):
   ON for the structural-envelope pass and the new content-apparatus
   classification gate (both small, judgment-heavy, once/rarely-per-source
   calls), OFF (unchanged, #147) for the high-volume tag/artifacts/xref
   calls. Asserted directly at the wire level -- the JSON body
   `OpenRouterClient.complete()` sends per `pass_name` -- mirroring the
   already-proven idiom in `src/axial/test_llm.py`'s
   `test_openrouter_client_request_body_disables_reasoning`.

Expected new public surface this test locks the implementer to (documented
here since none of it exists yet; see the test-author's own final report for
the same list):

- `axial.chunk.run_chunk_recursive(..., client=None)` -- a new, optional
  `client` keyword (an `LLMClient`, mirroring `axial.tag.run_tag`'s /
  `axial.xref.run_xref`'s own existing `client=` DI seam) threaded down to
  wherever the new content-apparatus classification call is made. When the
  deterministic pre-filter flags zero blocks, `client` must never be called
  -- this test injects a poison client to prove it.
- `axial.llm.CONTENT_APPARATUS_PASS_NAME` -- a new pass-name constant
  (mirroring `TAG_PASS_NAME`/`ARTIFACTS_PASS_NAME`/`XREF_PASS_NAME`) that the
  content-apparatus classification call identifies itself with.
- `axial.llm.ENVELOPE_PASS_NAME` -- a new pass-name constant the envelope
  pass's own `.complete()` call should thread through (today it passes no
  `pass_name` at all), used here directly against `OpenRouterClient` to pin
  the reasoning-per-pass contract independent of `axial.envelope`'s own
  wiring.
- A distinct, non-empty skip-sidecar reason for a content-apparatus drop,
  different from every existing label-driven `axial.router.apparatus_reason`
  string (§7.8: "a distinct content-apparatus reason").
- `OpenRouterClient.complete(prompt, pass_name=...)`'s request body carries
  `{"reasoning": {"enabled": True}}` for `ENVELOPE_PASS_NAME` and
  `CONTENT_APPARATUS_PASS_NAME`, and `{"reasoning": {"enabled": False}}`
  (unchanged) for `TAG_PASS_NAME`/`ARTIFACTS_PASS_NAME`/`XREF_PASS_NAME`.

Seam decisions
-----------------------------------------------------------------------
1. Bypassing docling/network entirely via a monkeypatched
   `axial.chunk.tree_path`/`axial.chunk.load_persisted_tree`, calling
   `run_chunk_recursive` directly -- mirrors
   `tests/ingestion/test_source_router.py`'s own `_patch_tree` helper
   exactly.
2. The content-apparatus classification call is driven by an injected fake
   `LLMClient` (mirroring `tests/ingestion/test_source_router.py`'s
   `_TagCountingClient`/`_XrefCountingClient`), not by `AXIAL_LLM_PROVIDER`
   env-var dispatch -- this lets the test assert an exact call count and
   `pass_name` without needing a new stub canned-response branch wired into
   `axial.llm._canned_response_for` to exist yet.
3. The reasoning-per-pass test talks to `axial.llm.OpenRouterClient`
   directly over an `httpx.MockTransport`, exactly mirroring
   `src/axial/test_llm.py`'s existing
   `test_openrouter_client_request_body_disables_reasoning` -- the cleanest,
   most behavioral seam available (the literal wire payload sent to the
   model), per the issue's own guidance.
4. Every path this test touches (the synthetic source file, `chunks_dir`)
   lives under pytest's own `tmp_path`; no real `data/` directory, network,
   or docling call is ever made.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import axial.chunk as chunk_module
from axial.chunk import CHUNK_MAX, CHUNK_MIN, run_chunk_recursive
from axial.envelope import compute_source_id
from axial.router import apparatus_reason

# =============================================================================
# Shared fixture-tree helpers (mirrors tests/ingestion/test_source_router.py)
# =============================================================================


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


def _patch_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tree: dict) -> None:
    tree_file = tmp_path / "tree.json"
    tree_file.write_text(json.dumps(tree), encoding="utf-8")
    monkeypatch.setattr(chunk_module, "tree_path", lambda source_id: tree_file)
    monkeypatch.setattr(chunk_module, "load_persisted_tree", lambda path: tree)


def _read_skip_records(chunks_dir: Path, source_id: str) -> list[dict]:
    skip_path = chunk_module.chunks_skips_sidecar_path(source_id, chunks_dir)
    if not skip_path.exists():
        return []
    return chunk_module.load_chunk_checkpoint(skip_path)


class _PoisonClient:
    """Fake LLMClient that raises if ever invoked (mirrors
    tests/chunk/test_chunk_recursive.py's `_poison_embedding_and_llm_seams`
    idiom): the strongest available proof that a code path made NO model
    call, not merely "call_count stayed 0 after the fact"."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        raise AssertionError(
            f"the content-apparatus classification model must never be "
            f"called for a block the deterministic pre-filter did not flag "
            f"(§7.8's 'clean prose reaches the chunk stage with zero model "
            f"spend'), but complete() was invoked (pass_name={pass_name!r}, "
            f"prompt[:120]={prompt[:120]!r})"
        )


# =============================================================================
# 1. Content-apparatus gate (§7.8 "Content-detected apparatus" /
#    "Model-backed classification of flagged candidates")
# =============================================================================

_CHAPTER_HEADING = "Chapter Three"

_CLEAN_PROSE_BODY = (
    "Clean prose sentinel: the provincial council debated the reconstruction "
    "budget for three sessions before finally approving a phased disbursement "
    "plan that prioritized water infrastructure over road repair this year."
)

# Exactly ONE inverted-author-name citation, embedded in substantial ordinary
# analytical prose -- must stay prose (conservative gate: "fires only on
# high-confidence citation density, never on ordinary prose that merely
# cites a source or two in passing", §7.8).
_LIGHT_CITATION_BODY = (
    "Light-citation sentinel: this chapter's argument builds directly on "
    "Omicron, F. (2015), whose account of frontier administration remains "
    "influential, but the present analysis reframes the causal mechanism "
    "entirely around local fiscal capacity instead of external enforcement, "
    "drawing on new archival evidence gathered during the most recent survey."
)

# A dense run of inverted-author-name citation entries -- 14 occurrences of
# `[A-Z][a-z]+,\s+[A-Z]` well past any conservative density threshold, styled
# like a real reference list, but carrying the "text" (prose) label, exactly
# the residual reference-list case §7.8's content arm targets (docling
# labelled it prose; only its content reveals it as apparatus).
_CITATION_NAMES = [
    ("Alpha", "K"),
    ("Beta", "L"),
    ("Gamma", "R"),
    ("Delta", "S"),
    ("Epsilon", "T"),
    ("Zeta", "M"),
    ("Eta", "N"),
    ("Theta", "P"),
    ("Iota", "Q"),
    ("Kappa", "V"),
    ("Lambda", "W"),
    ("Mu", "X"),
    ("Nu", "Y"),
    ("Xi", "Z"),
]


def _build_dense_citation_body() -> str:
    entries = []
    for index, (surname, initial) in enumerate(_CITATION_NAMES, start=1):
        entries.append(
            f"{surname}, {initial}. ({2000 + index}) Frontier Studies Volume "
            f"{index}, Capital Press, pp. {index * 10}-{index * 10 + 20}."
        )
    return " ".join(entries)


_DENSE_CITATION_BODY = _build_dense_citation_body()


class _ContentApparatusCountingClient:
    """Fake LLMClient for the content-apparatus classification gate:
    asserts every call it receives carries the expected `pass_name`, counts
    calls, and resolves every call to apparatus (this fixture's one flagged
    block is unambiguously a reference list)."""

    def __init__(self, expected_pass_name: str):
        self._expected_pass_name = expected_pass_name
        self.prompts: list[str] = []

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        assert pass_name == self._expected_pass_name, (
            f"expected the content-apparatus classification call to "
            f"identify itself via pass_name={self._expected_pass_name!r} "
            f"(mirroring TAG_PASS_NAME/ARTIFACTS_PASS_NAME/XREF_PASS_NAME's "
            f"own out-of-band dispatch convention), got {pass_name!r}"
        )
        self.prompts.append(prompt)
        return json.dumps({"route": "apparatus"})

    @property
    def call_count(self) -> int:
        return len(self.prompts)


def test_content_apparatus_gate_drops_dense_citations_but_keeps_light_citation_prose(
    tmp_path, monkeypatch
):
    from axial.llm import CONTENT_APPARATUS_PASS_NAME

    source_path = tmp_path / "content_apparatus_gate_source.txt"
    source_path.write_text(
        "synthetic source for issue #207 content-apparatus gate", encoding="utf-8"
    )
    source_id = compute_source_id(source_path)

    tree = {
        "children": [
            _section(
                "1",
                _CHAPTER_HEADING,
                [
                    _leaf("1.1", "text", _CLEAN_PROSE_BODY),
                    _leaf("1.2", "text", _LIGHT_CITATION_BODY),
                    _leaf("1.3", "text", _DENSE_CITATION_BODY),
                ],
            )
        ]
    }
    _patch_tree(monkeypatch, tmp_path, tree)

    chunks_dir = tmp_path / "chunks"
    client = _ContentApparatusCountingClient(CONTENT_APPARATUS_PASS_NAME)

    records = run_chunk_recursive(source_path, chunks_dir=chunks_dir, client=client)

    assert isinstance(records, list) and records, (
        f"expected at least one kept prose chunk record, got {records!r}"
    )

    all_text = "\n".join(r.get("text", "") for r in records)

    assert _CLEAN_PROSE_BODY in all_text, (
        "expected the ordinary clean-prose block (zero citations) to survive as prose"
    )
    assert _LIGHT_CITATION_BODY in all_text, (
        "expected the light-citation block (exactly one passing citation, "
        "surrounded by substantial ordinary prose) to survive as prose -- "
        "§7.8's content arm is conservative and must never fire on a block "
        "that merely cites a source or two in passing"
    )
    assert _DENSE_CITATION_BODY not in all_text, (
        "expected the dense-citation block (14 inverted-author-name entries, "
        "styled as a reference list) to be re-routed to apparatus and "
        "DROPPED -- it must never leak into any emitted chunk's text"
    )

    assert client.call_count == 1, (
        f"expected exactly ONE bounded content-apparatus classification "
        f"call -- the dense-citation block is the only one the "
        f"deterministic pre-filter should flag; the clean-prose and "
        f"light-citation blocks must never reach the model at all (§7.8: "
        f"'clean prose ... reaches the chunk stage with zero model spend'; "
        f"'fires only on high-confidence citation density'). Got "
        f"{client.call_count} call(s): {client.prompts!r}"
    )

    skip_records = _read_skip_records(chunks_dir, source_id)
    assert skip_records, (
        "expected the dense-citation drop to be recorded in the "
        "router-owned skip sidecar (§7.8: 'each drop is recorded with a "
        "reason'), got none"
    )

    known_label_driven_reasons = {
        apparatus_reason(label)
        for label in ("document_index", "footnote", "page_header", "page_footer", "list_item")
    }
    for record in skip_records:
        reason = record.get("reason")
        assert isinstance(reason, str) and reason.strip(), (
            f"expected every skip record to carry a non-empty 'reason', got {record!r}"
        )
        assert reason not in known_label_driven_reasons, (
            f"expected the content-apparatus drop's reason to be DISTINCT "
            f"from every existing label-driven apparatus reason (§7.8: 'its "
            f"reason recorded ... with a distinct content-apparatus "
            f"reason'), but got the generic label-driven reason {reason!r}"
        )


def test_content_apparatus_gate_makes_zero_model_calls_on_wholly_clean_prose(tmp_path, monkeypatch):
    """A section with NO citation-like content at all must never reach the
    model -- the deterministic pre-filter gates it entirely (§7.8: "the
    pre-filter gates it, clean prose ... reaches the chunk stage with zero
    model spend"). Poisons the client so any call at all fails loudly,
    rather than merely checking a counter after the fact."""
    source_path = tmp_path / "wholly_clean_prose_source.txt"
    source_path.write_text("synthetic wholly-clean-prose source for issue #207", encoding="utf-8")

    tree = {
        "children": [
            _section(
                "1",
                _CHAPTER_HEADING,
                [_leaf("1.1", "text", _CLEAN_PROSE_BODY)],
            )
        ]
    }
    _patch_tree(monkeypatch, tmp_path, tree)

    chunks_dir = tmp_path / "chunks"
    records = run_chunk_recursive(source_path, chunks_dir=chunks_dir, client=_PoisonClient())

    assert records and _CLEAN_PROSE_BODY in records[0]["text"], (
        f"expected the clean-prose block to survive as a chunked prose "
        f"record with zero model spend, got {records!r}"
    )


# =============================================================================
# 2. Chunk MIN-side: sub-floor chunk merges into its same-section
#    PREDECESSOR (§8 P0-4), not left stranded as a standalone note
# =============================================================================

_DISCUSSION_HEADING = "Discussion"

_PARAGRAPH_TARGET_CHARS = (CHUNK_MIN + CHUNK_MAX) // 2

_P1_SENTENCES = [
    "The provincial reconstruction budget grew steadily across each survey "
    "wave despite recurring administrative delays across the region.",
    "Field teams documented a gradual return of displaced households to the "
    "eastern districts throughout the entire survey period this year.",
    "Local water authorities coordinated repair schedules more closely once "
    "emergency funding was restored in full across every district office.",
    "Municipal councils reported improved attendance at planning sessions "
    "as security conditions stabilized further across the whole province.",
]

_P2_SENTENCES = [
    "Interviews with district officials pointed to uneven but genuine "
    "progress on road repair across the region during the same period.",
    "Aid coordination shifted toward regional hubs as the capital's own "
    "logistics capacity remained badly strained through the winter months.",
    "Survey respondents consistently named fuel shortages as the single "
    "greatest obstacle to sustained recovery across every district visited.",
    "Cross-border trade resumed unevenly, concentrated overwhelmingly "
    "around a small handful of reopened crossings near the northern edge.",
]

_P3_TAIL_TEXT = "A single short closing remark follows here at the very end."


def _pad_to_length(sentences: list[str], min_chars: int) -> str:
    """Cycle `sentences` (joined with a single space, no newlines) until the
    result is at least `min_chars` long -- mirrors
    tests/chunk/test_chunk_recursive.py's own `_build_wall_of_text` helper."""
    pieces: list[str] = []
    total = 0
    index = 0
    while total < min_chars:
        sentence = sentences[index % len(sentences)]
        pieces.append(sentence)
        total += len(sentence) + 1
        index += 1
    text = " ".join(pieces)
    assert "\n" not in text, "internal fixture bug: paragraph must contain no newlines"
    return text


_P1_TEXT = _pad_to_length(_P1_SENTENCES, _PARAGRAPH_TARGET_CHARS)
_P2_TEXT = _pad_to_length(_P2_SENTENCES, _PARAGRAPH_TARGET_CHARS)

# Sanity-check the fixture's own arithmetic before it's ever handed to the
# chunk stage, so a future CHUNK_MIN/CHUNK_MAX retune can't silently make
# this fixture stop exercising the scenario it claims to.
assert CHUNK_MIN <= len(_P1_TEXT) < CHUNK_MAX, "internal fixture bug: P1 must sit inside the band"
assert CHUNK_MIN <= len(_P2_TEXT) < CHUNK_MAX, "internal fixture bug: P2 must sit inside the band"
assert len(_P3_TAIL_TEXT) < CHUNK_MIN, "internal fixture bug: P3 must sit below CHUNK_MIN"
_TOTAL_WITH_SEPARATORS = len(_P1_TEXT) + len(_P2_TEXT) + len(_P3_TAIL_TEXT) + 4
assert _TOTAL_WITH_SEPARATORS > CHUNK_MAX, (
    "internal fixture bug: the whole section must exceed CHUNK_MAX so the "
    "recursive splitter actually divides it into P1/P2/P3 rather than "
    "emitting it whole"
)
assert len(_P2_TEXT) + 1 + len(_P3_TAIL_TEXT) <= CHUNK_MAX, (
    "internal fixture bug: P2+P3 merged must still fit under CHUNK_MAX -- "
    "otherwise the predecessor merge this test locks would not be eligible"
)


def test_chunk_min_side_merges_subfloor_chunk_into_same_section_predecessor(tmp_path, monkeypatch):
    source_path = tmp_path / "min_side_predecessor_merge_source.txt"
    source_path.write_text(
        "synthetic source for issue #207 MIN-side predecessor merge", encoding="utf-8"
    )

    tree = {
        "children": [
            _section(
                "1",
                _DISCUSSION_HEADING,
                [
                    _leaf("1.1", "text", _P1_TEXT),
                    _leaf("1.2", "text", _P2_TEXT),
                    _leaf("1.3", "text", _P3_TAIL_TEXT),
                ],
            )
        ]
    }
    _patch_tree(monkeypatch, tmp_path, tree)

    chunks_dir = tmp_path / "chunks"
    records = run_chunk_recursive(source_path, chunks_dir=chunks_dir, client=_PoisonClient())

    assert records, "expected at least one chunk record, got none"

    assert len(records) == 2, (
        f"expected the trailing sub-floor chunk (P3, {len(_P3_TAIL_TEXT)} "
        f"chars, well below CHUNK_MIN={CHUNK_MIN}) to merge INTO its "
        f"same-section predecessor (P2) rather than survive as its own "
        f"third record -- expected exactly 2 records in this section, got "
        f"{len(records)}: {[r['text'][:60] for r in records]!r}"
    )

    for record in records:
        assert len(record["text"]) >= CHUNK_MIN, (
            f"expected every chunk in this section to be >= CHUNK_MIN "
            f"({CHUNK_MIN}) -- no sub-floor chunk should survive when a "
            f"same-section predecessor was available to absorb it -- got "
            f"{len(record['text'])} chars for chunk_id {record['chunk_id']!r}"
        )
        assert len(record["text"]) <= CHUNK_MAX, (
            f"expected the predecessor merge to still respect the MAX band "
            f"guard ({CHUNK_MAX}), got {len(record['text'])} chars for "
            f"chunk_id {record['chunk_id']!r}"
        )

    p1_records = [r for r in records if _P1_TEXT in r["text"]]
    p2_records = [r for r in records if _P2_TEXT in r["text"]]
    p3_records = [r for r in records if _P3_TAIL_TEXT in r["text"]]

    assert len(p1_records) == 1, f"expected P1 to appear in exactly one record, got {p1_records!r}"
    assert len(p2_records) == 1, f"expected P2 to appear in exactly one record, got {p2_records!r}"
    assert len(p3_records) == 1, f"expected P3 to appear in exactly one record, got {p3_records!r}"

    assert p2_records[0] is p3_records[0], (
        "expected the sub-floor tail chunk (P3) to merge into its own "
        "IMMEDIATE PREDECESSOR (P2) specifically -- P2 and P3 must land in "
        "the SAME emitted chunk record"
    )
    assert p1_records[0] is not p3_records[0], (
        "expected P3 to merge with its immediate predecessor P2, not with "
        "P1 (P1 is not P3's predecessor) -- P1 and P3 must NOT land in the "
        "same emitted chunk record"
    )


# =============================================================================
# 3. Per-pass reasoning (§7.9): ON for envelope + content-apparatus gate,
#    OFF (unchanged, #147) for tag/artifacts/xref
# =============================================================================


def test_per_pass_reasoning_on_for_envelope_and_content_apparatus_off_for_tag_artifacts_xref():
    from axial.llm import (
        ARTIFACTS_PASS_NAME,
        CONTENT_APPARATUS_PASS_NAME,
        ENVELOPE_PASS_NAME,
        TAG_PASS_NAME,
        XREF_PASS_NAME,
        OpenRouterClient,
    )

    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    client = OpenRouterClient(api_key="test-key", model="test-model", transport=transport)

    # §7.9: ON for the envelope pass and the new content-apparatus
    # classification gate; OFF (unchanged, #147) for the high-volume
    # tag/artifacts/xref calls.
    expected_reasoning_by_pass = {
        ENVELOPE_PASS_NAME: True,
        CONTENT_APPARATUS_PASS_NAME: True,
        TAG_PASS_NAME: False,
        ARTIFACTS_PASS_NAME: False,
        XREF_PASS_NAME: False,
    }

    for pass_name in expected_reasoning_by_pass:
        client.complete(f"prompt for pass {pass_name}", pass_name=pass_name)

    assert len(captured_requests) == len(expected_reasoning_by_pass), (
        f"expected exactly one request per pass_name, got {len(captured_requests)}"
    )

    for request, (pass_name, reasoning_on) in zip(
        captured_requests, expected_reasoning_by_pass.items()
    ):
        body = json.loads(request.content)
        assert body.get("reasoning") == {"enabled": reasoning_on}, (
            f"expected pass_name={pass_name!r}'s request body to carry "
            f"reasoning.enabled={reasoning_on} (§7.9: reasoning is ON for "
            f"the envelope pass and the content-apparatus classification "
            f"gate, OFF for tag/artifacts/xref), got "
            f"{body.get('reasoning')!r} (full body: {body!r})"
        )
