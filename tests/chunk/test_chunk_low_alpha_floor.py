"""Outer acceptance test for issue #197: generalizing the post-split
fragment floor from "zero alphabetic characters" (#193) to a **low
alphabetic-ratio** test.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

See specs/PRODUCT.md §7.8 "Post-split fragment floor (#193, generalized in
#197)" and "Genuine short prose is protected (#193)", and §8 P0-4's
fragment-floor bullet, for the source of truth this test encodes.

Contract encoded here (see §7.8 for the full statement): after the chunk
stage splits a section and applies the MIN-side band guard, it drops an
emitted candidate chunk -- before it reaches the on-disk artifact -- when
its **alphabetic ratio** (count of alphabetic characters / total character
count) is **below 0.45**, in addition to the unchanged blank-page-notice
shape. This subsumes #193's zero-alpha rule (ratio 0 is simply the ratio-0
special case of "below 0.45"). A chunk with alphabetic ratio **>= 0.45 is
always kept, however short** -- length alone never triggers a drop. Each
drop is recorded to the router-owned skip sidecar
(`chunks_skips_sidecar_path`) with its own distinct low-alpha-ratio reason,
never the pre-existing apparatus (`"apparatus: ..."`) or section-level
garble-backstop (`"high non-alpha ratio (...)"`) reasons.

What is NEW here vs #193's own locked test
(tests/chunk/test_chunk_fragment_floor.py, which this file does not touch):
#193 only ever dropped ratio-EXACTLY-0 crumbs (digits/punctuation only).
This test's crux is the **0 < ratio < 0.45 band** that #193 left in scope
for #197 to close -- citation and significance-star crumbs that carry a few
alphabetic characters but are still overwhelmingly non-alphabetic. Two
worked examples straight from PRD §7.8/§8 exercise that new band:
  - `"Berman 1996: 78 )."` -- alphabetic ratio 6/18 = 0.3333 (a bare
    citation crumb)
  - `"∗ p < 0."` -- alphabetic ratio 1/8 = 0.125 (a significance-star
    crumb)
Both must now drop, even though neither has zero alphabetic characters and
so neither would have been caught by #193's old rule.

Alongside those, this test carries forward two invariants from #193 to
prove no regression:
  - the ratio-0 shape (`"13)."`) must still drop (#193's own worked
    example, now just the ratio-0 special case of the generalized rule)
  - a genuine short sentence at ratio >= 0.45 -- PRD §7.8's own protected
    worked example, `"Yet, the U.S."` (alphabetic ratio 8/13 = 0.6154) --
    must have its TEXT survive, however short. Per #210 spec-drift
    (reconciling #207's MIN-side predecessor-merge with #193's "genuine
    short prose is protected"), "protected" means the text is never
    dropped -- not that it survives as its own standalone record: below
    CHUNK_MIN with a same-section predecessor (PROTECTED_PARA_2), it now
    merges BACKWARD into that predecessor (§8 P0-4), so this test checks
    for it as a substring of the merged chunk, not verbatim as a record of
    its own. This is still the protection invariant that blocks a naive
    "just lower the length floor" non-fix from passing: a test that only
    checked "the citation crumb is gone" would also be satisfied by a
    broken implementation that dropped every short chunk's text
    regardless of content.

Fixture design and root-cause note
-----------------------------------------------------------------------
This test copies tests/chunk/test_chunk_fragment_floor.py's proven fixture
pattern exactly, for the same documented reason: the leaking crumbs this
floor targets survive today because the section-level garble backstop
(`_garbage_section_skip_reason`) runs on the WHOLE joined section body
BEFORE the recursive splitter, so it is blind to a junk *tail chunk* that a
legitimate, long-prose section leaves behind only after splitting. Each
section below is built from TWO genuine, distinct, in-band prose paragraphs
(long enough, combined, to force the recursive splitter to actually split
the section) followed by ONE trailing "tail" piece carrying the shape under
test. Each section's own body is dominated by real, unambiguous prose, so
the section-level garble backstop never fires on any of them -- verified
indirectly by this test's own assertion that every genuine paragraph
survives undisturbed in every section, including the three with a dropped
tail (if the section-level backstop had instead skipped one of those
sections wholesale, that assertion would fail).

Four sections, each with a single trailing tail (not fewer, and not two
junk shapes crammed into one section), for the same reason #193's test used
three: `axial.chunk._enforce_min` (the MIN-side band guard) merges any
below-`CHUNK_MIN` chunk FORWARD into whatever immediately follows it,
within its forward pass. The section's own last piece is the only one the
forward pass can leave below `CHUNK_MIN` on its own (nothing follows it to
merge into) -- which is also the real-world shape (the leaking crumbs are
section tails). Since #207/#210, `_enforce_min` then prefers merging that
trailing piece BACKWARD into its same-section predecessor (within
`CHUNK_MAX`) -- UNLESS the trailing piece is itself fragment-floor material
(`_fragment_floor_reason` is not `None`), in which case the backward merge
is deliberately skipped so this floor can still evaluate and drop it as an
isolated candidate. That is exactly why "Citation", "Significance", and
"Blank" below stay isolated for the floor: their trailing tails ARE
fragment-floor material, so the backward merge never fires for them.
"Protected"'s trailing tail, by contrast, is genuine short prose -- not
fragment-floor material -- so it now merges backward into
PROTECTED_PARA_2 rather than surviving the floor as its own standalone
record; its TEXT still survives, verbatim, as a substring of that merged
chunk (§7.8 "genuine short prose is protected", reconciled with the §8
P0-4 predecessor-merge in #210). Four sections, each with its own single
trailing tail, is therefore still the minimal fixture that puts one
isolated candidate junk (or protected) chunk of each targeted shape in
front of the floor, without an unrelated merge behavior confounding which
piece the floor actually had to evaluate:
  - "Citation"       -- tail is the bare-citation crumb (ratio 0.33, NEW
                         band) -- must drop
  - "Significance"   -- tail is the significance-star crumb (ratio 0.125,
                         NEW band) -- must drop
  - "Blank"          -- tail is the ratio-0 crumb (regression check on
                         #193's original rule) -- must still drop
  - "Protected"      -- tail is the genuine short sentence (ratio 0.6154)
                         -- its text must survive (merged backward into
                         PROTECTED_PARA_2, #210 / §8 P0-4), proving no
                         over-drop

Seam decisions (band constants imported, isolated tmp cwd) mirror
tests/chunk/test_chunk_fragment_floor.py's own seam decisions 4 and 5 --
see that file's docstring for the full rationale.
"""

from __future__ import annotations

import json
from pathlib import Path

from axial.chunk import (
    CHUNK_MAX,
    CHUNK_MIN,
    chunks_checkpoint_path,
    chunks_skips_sidecar_path,
    run_chunk_recursive,
)
from axial.envelope import compute_source_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE_PDF = REPO_ROOT / "tests" / "fixtures" / "envelope" / "thesis_paper.pdf"

# Midpoint of the current band: comfortably >= CHUNK_MIN (so a paragraph
# never itself gets merged forward into its neighbor -- it may still
# receive a backward merge FROM a below-CHUNK_MIN tail that follows it,
# per #207/#210's predecessor-merge; see PROTECTED_PARA_2 below) and
# comfortably < CHUNK_MAX (so a paragraph is never itself split further).
# Two of these together, plus a short tail, safely exceed CHUNK_MAX,
# forcing the recursive splitter to actually divide each section rather
# than emit it as one whole chunk.
_PARAGRAPH_TARGET_CHARS = (CHUNK_MIN + CHUNK_MAX) // 2

# --- The low-alpha threshold contract (PRD §7.8/§8): ratio < 0.45 drops,
# ratio >= 0.45 is always kept. All four tail texts below are PRD §7.8's own
# worked examples; ratios are computed here (not hardcoded) so the fixture
# stays self-documenting and re-verifies itself against the real formula. ---
_LOW_ALPHA_THRESHOLD = 0.45


def _alpha_ratio(text: str) -> float:
    """`(count of alphabetic characters) / (total character count)` --
    exactly the formula PRD §7.8 defines for the low-alpha fragment shape.
    Callers only ever pass non-empty text."""
    assert text, "internal fixture bug: _alpha_ratio called on empty text"
    alpha = sum(1 for c in text if c.isalpha())
    return alpha / len(text)


# PRD §7.8's own worked example of a bare-citation crumb: NEW band (0 <
# ratio < 0.45) that #193's zero-alpha-only rule did NOT catch.
_CITATION_TAIL_TEXT = "Berman 1996: 78 )."
_CITATION_TAIL_RATIO = _alpha_ratio(_CITATION_TAIL_TEXT)
assert abs(_CITATION_TAIL_RATIO - 0.3333) < 0.001, (
    f"internal fixture bug: expected the citation crumb's alphabetic ratio to match "
    f"PRD §7.8's stated 0.33, got {_CITATION_TAIL_RATIO!r}"
)
assert _CITATION_TAIL_RATIO < _LOW_ALPHA_THRESHOLD, (
    "internal fixture bug: citation crumb must sit below the low-alpha threshold"
)

# PRD §7.8's own worked example of a significance-star crumb: NEW band,
# even lower ratio than the citation crumb.
_SIGNIFICANCE_TAIL_TEXT = "∗ p < 0."
_SIGNIFICANCE_TAIL_RATIO = _alpha_ratio(_SIGNIFICANCE_TAIL_TEXT)
assert abs(_SIGNIFICANCE_TAIL_RATIO - 0.125) < 0.001, (
    f"internal fixture bug: expected the significance-star crumb's alphabetic ratio to "
    f"match PRD §7.8's stated 0.12, got {_SIGNIFICANCE_TAIL_RATIO!r}"
)
assert _SIGNIFICANCE_TAIL_RATIO < _LOW_ALPHA_THRESHOLD, (
    "internal fixture bug: significance-star crumb must sit below the low-alpha threshold"
)

# #193's own worked example: zero alphabetic characters -- the ratio-0
# special case of the generalized rule. Carried forward as a regression
# check, not the crux of this test.
_ZERO_ALPHA_TAIL_TEXT = "13)."
_ZERO_ALPHA_TAIL_RATIO = _alpha_ratio(_ZERO_ALPHA_TAIL_TEXT)
assert _ZERO_ALPHA_TAIL_RATIO == 0.0, (
    "internal fixture bug: the #193 regression crumb must have ratio exactly 0"
)

# PRD §7.8's own worked example of genuine short prose that must survive:
# ratio >= 0.45, the protection invariant.
_PROTECTED_SHORT_SENTENCE = "Yet, the U.S."
_PROTECTED_SENTENCE_RATIO = _alpha_ratio(_PROTECTED_SHORT_SENTENCE)
assert abs(_PROTECTED_SENTENCE_RATIO - 0.6154) < 0.001, (
    f"internal fixture bug: expected the protected sentence's alphabetic ratio to match "
    f"PRD §7.8's stated 0.62, got {_PROTECTED_SENTENCE_RATIO!r}"
)
assert _PROTECTED_SENTENCE_RATIO >= _LOW_ALPHA_THRESHOLD, (
    "internal fixture bug: the protected sentence must sit at or above the low-alpha "
    "threshold -- otherwise it would not test the protection invariant"
)

_CITATION_SENTENCES_1 = [
    "Citation sentinel Alpha: the archival review traced how successive administrations "
    "framed border security legislation across three distinct legislative sessions.",
    "Committee testimony from the period described a gradual tightening of enforcement "
    "priorities even as funding allocations remained contested year over year.",
    "Correspondence between agency heads revealed disagreements over which metrics best "
    "captured operational effectiveness at regional checkpoints.",
    "Subsequent hearings shifted attention from enforcement volume toward processing "
    "capacity, reflecting a broader reprioritization of agency resources.",
]
_CITATION_SENTENCES_2 = [
    "Citation sentinel Beta: budget documents from the same window show enforcement "
    "spending rising even as apprehension counts fluctuated independently of it.",
    "Legislative staff interviewed for the review cited unresolved definitional "
    "disputes as the central obstacle to any lasting bipartisan compromise.",
    "Regional field offices adopted divergent local practices despite nominally "
    "operating under one unified national policy framework throughout the period.",
    "Later audits found these divergent practices had gone largely undocumented in "
    "official agency reporting for several consecutive fiscal years.",
]
_SIGNIFICANCE_SENTENCES_1 = [
    "Significance sentinel Gamma: the survey instrument measured attitudes toward "
    "resettlement policy across four demographic strata within the sampled population.",
    "Respondents in urban strata expressed markedly different views from those in "
    "rural strata, a divergence that persisted across every wave of the panel.",
    "Statistical models controlling for income and education still left a sizable "
    "residual gap attributable to strata alone rather than these covariates.",
    "The authors interpret this residual gap as evidence of a distinct regional "
    "political culture rather than a simple compositional artifact of the sample.",
]
_SIGNIFICANCE_SENTENCES_2 = [
    "Significance sentinel Delta: a follow-up wave conducted eighteen months later "
    "found the urban-rural divergence had narrowed somewhat but not disappeared.",
    "Panel attrition was highest among the youngest respondents, complicating any "
    "clean comparison of the two waves without a weighting adjustment.",
    "The weighted comparison still supports the original finding, though the "
    "authors flag the reduced sample size as a limitation on later strata.",
    "Replication in a neighboring region with a similar demographic profile would "
    "strengthen confidence in the generalizability of this divergence.",
]
_BLANK_SENTENCES_1 = [
    "Blank sentinel Epsilon: the case file review covered municipal permitting "
    "decisions issued across a five-year window in the metropolitan district.",
    "Permit approval rates varied substantially by neighborhood, with peripheral "
    "districts consistently facing longer review timelines than central ones.",
    "Interviews with planning staff attributed some of the variation to staffing "
    "shortages rather than any formal difference in review criteria applied.",
    "A subset of contested permits went to formal appeal, and appellants prevailed "
    "in a minority of those cases across the full review window studied.",
]
_BLANK_SENTENCES_2 = [
    "Blank sentinel Zeta: appeal outcomes showed no strong correlation with permit "
    "type once case complexity was accounted for in the statistical model used.",
    "Cases involving mixed-use development took longer to resolve on appeal than "
    "single-use residential cases did throughout the entire period sampled.",
    "The planning department later revised its intake procedures, though the "
    "revision postdates the window covered by this particular case file review.",
    "Whether the revision improved timelines remains an open question the present "
    "review was not positioned to answer given its fixed historical window.",
]
_PROTECTED_SENTENCES_1 = [
    "Protected sentinel Eta: the trade policy chapter reconstructs how tariff "
    "schedules shifted across three successive rounds of bilateral negotiation.",
    "Negotiators on both sides described early rounds as largely symbolic, with "
    "substantive concessions concentrated almost entirely in the final round.",
    "Domestic industry groups lobbied intensively between rounds, and their "
    "influence is visible in several last-minute schedule amendments recorded.",
    "The final agreement text reflects compromises that satisfied neither side's "
    "opening position, a pattern typical of this kind of protracted negotiation.",
]
_PROTECTED_SENTENCES_2 = [
    "Protected sentinel Theta: implementation of the agreement proceeded unevenly, "
    "with some tariff lines phased in years ahead of others in the same schedule.",
    "Monitoring reports from the following decade documented compliance gaps "
    "concentrated in a small number of politically sensitive product categories.",
    "Dispute resolution proceedings addressed several of these gaps directly, "
    "though enforcement remained inconsistent across the monitored period overall.",
    "The chapter concludes that formal agreement text alone poorly predicts actual "
    "implementation, a gap later chapters return to in other policy domains.",
]


def _build_paragraph(sentences: list[str], target_chars: int) -> str:
    """A single continuous prose string (no `\n` anywhere inside it), built
    by cycling `sentences` until it reaches at least `target_chars`
    characters -- mirrors tests/chunk/test_chunk_fragment_floor.py's own
    helper of the same name."""
    pieces: list[str] = []
    total = 0
    index = 0
    while total < target_chars:
        sentence = sentences[index % len(sentences)]
        pieces.append(sentence)
        total += len(sentence) + 1
        index += 1
    text = " ".join(pieces)
    assert "\n" not in text, "internal fixture bug: paragraph must contain no newlines"
    return text


CITATION_PARA_1 = _build_paragraph(_CITATION_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
CITATION_PARA_2 = _build_paragraph(_CITATION_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)
SIGNIFICANCE_PARA_1 = _build_paragraph(_SIGNIFICANCE_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
SIGNIFICANCE_PARA_2 = _build_paragraph(_SIGNIFICANCE_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)
BLANK_PARA_1 = _build_paragraph(_BLANK_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
BLANK_PARA_2 = _build_paragraph(_BLANK_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)
PROTECTED_PARA_1 = _build_paragraph(_PROTECTED_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
PROTECTED_PARA_2 = _build_paragraph(_PROTECTED_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)

_ALL_GENUINE_PARAGRAPHS = [
    CITATION_PARA_1,
    CITATION_PARA_2,
    SIGNIFICANCE_PARA_1,
    SIGNIFICANCE_PARA_2,
    BLANK_PARA_1,
    BLANK_PARA_2,
    PROTECTED_PARA_1,
    PROTECTED_PARA_2,
]

# Sanity on the fixture's own construction (not the contract under test):
# each individual paragraph must stay under CHUNK_MAX (so it is never split
# further), while two of them together must exceed CHUNK_MAX (so the
# section is actually forced through the recursive splitter rather than
# emitted whole).
for _para in _ALL_GENUINE_PARAGRAPHS:
    assert len(_para) < CHUNK_MAX, "internal fixture bug: a paragraph must stay under CHUNK_MAX"
assert len(CITATION_PARA_1) + len(CITATION_PARA_2) > CHUNK_MAX, (
    "internal fixture bug: two paragraphs combined must exceed CHUNK_MAX to force a split"
)


def _leaf(order: str, text: str) -> dict:
    return {"type": "prose", "order": order, "text": text, "label": "text"}


def _section(order: str, heading: str, body_texts: list[str]) -> dict:
    return {
        "type": "prose",
        "order": order,
        "text": heading,
        "label": "section_header",
        "children": [_leaf(f"{order}.{i + 1}", body) for i, body in enumerate(body_texts)],
    }


def _build_fixture_tree() -> dict:
    return {
        "children": [
            _section("1", "Citation", [CITATION_PARA_1, CITATION_PARA_2, _CITATION_TAIL_TEXT]),
            _section(
                "2",
                "Significance",
                [SIGNIFICANCE_PARA_1, SIGNIFICANCE_PARA_2, _SIGNIFICANCE_TAIL_TEXT],
            ),
            _section("3", "Blank", [BLANK_PARA_1, BLANK_PARA_2, _ZERO_ALPHA_TAIL_TEXT]),
            _section(
                "4",
                "Protected",
                [PROTECTED_PARA_1, PROTECTED_PARA_2, _PROTECTED_SHORT_SENTENCE],
            ),
        ]
    }


def _place_fixture_tree(root: Path, source_id: str) -> None:
    tree = _build_fixture_tree()
    tree_path = root / "data" / "trees" / f"{source_id}.json"
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(tree), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"expected {path} to be one JSON object per line, but line {line_no} "
                f"failed to parse ({exc}): {line!r}"
            ) from None
    return records


def _is_known_non_fragment_floor_reason(reason: str) -> bool:
    return reason.startswith("apparatus:") or reason.startswith("high non-alpha ratio")


def test_post_split_fragment_floor_drops_low_alpha_ratio_but_keeps_protected_prose(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    source_id = compute_source_id(FIXTURE_PDF)
    _place_fixture_tree(tmp_path, source_id)

    records = run_chunk_recursive(FIXTURE_PDF)

    chunk_path = chunks_checkpoint_path(source_id)
    on_disk_records = _read_jsonl(chunk_path)
    assert on_disk_records == records, (
        "expected the returned records to match the on-disk artifact exactly"
    )
    assert records, f"expected at least one chunk record in {chunk_path}, got none"

    all_texts = [record.get("text", "") for record in records]

    # --- 1. no emitted chunk has an alphabetic ratio below the low-alpha
    # threshold (0.45) -- the generalized contract, computed generically
    # per chunk rather than checked against specific strings only. ---
    low_alpha_survivors = [
        (text, _alpha_ratio(text))
        for text in all_texts
        if text and _alpha_ratio(text) < _LOW_ALPHA_THRESHOLD
    ]
    assert not low_alpha_survivors, (
        f"expected the generalized post-split fragment floor (#197) to drop every "
        f"emitted chunk with alphabetic ratio below {_LOW_ALPHA_THRESHOLD} before it "
        f"ever reaches the on-disk artifact {chunk_path}, but these survived "
        f"(text, ratio): {low_alpha_survivors!r}. Full records: {records!r}"
    )

    # --- 1b. the two NEW-band worked examples specifically must not survive
    # verbatim (the crux of #197 vs #193: neither has zero alphabetic
    # characters, so #193's old rule alone would not catch them). ---
    assert _CITATION_TAIL_TEXT not in all_texts, (
        f"expected the bare-citation crumb {_CITATION_TAIL_TEXT!r} (alphabetic ratio "
        f"{_CITATION_TAIL_RATIO:.4f}, PRD §7.8's own NEW-band worked example) to be "
        f"dropped by the generalized fragment floor (#197), but it survived in "
        f"{chunk_path}. Full records: {records!r}"
    )
    assert _SIGNIFICANCE_TAIL_TEXT not in all_texts, (
        f"expected the significance-star crumb {_SIGNIFICANCE_TAIL_TEXT!r} (alphabetic "
        f"ratio {_SIGNIFICANCE_TAIL_RATIO:.4f}, PRD §7.8's own NEW-band worked example) "
        f"to be dropped by the generalized fragment floor (#197), but it survived in "
        f"{chunk_path}. Full records: {records!r}"
    )

    # --- 1c. regression check: the #193 ratio-0 shape must still drop. ---
    assert _ZERO_ALPHA_TAIL_TEXT not in all_texts, (
        f"expected the ratio-0 crumb {_ZERO_ALPHA_TAIL_TEXT!r} (#193's own worked "
        f"example, now the ratio-0 special case of the generalized rule) to still be "
        f"dropped -- no regression of #193. Full records: {records!r}"
    )

    # --- 2. the genuine short prose sentence's TEXT (ratio >= 0.45)
    # survives -- the protection invariant. This is what stops a naive
    # "drop everything short" non-fix from passing this test. Per #210
    # spec-drift (reconciling #207's MIN-side predecessor-merge with
    # #193/#197's "genuine short prose is protected"), "protected" means
    # the TEXT is never dropped -- not that it survives as its own
    # standalone record: below CHUNK_MIN with a same-section predecessor
    # (PROTECTED_PARA_2), it merges BACKWARD into that predecessor (§8
    # P0-4), so it is checked here as a substring of whatever chunk it
    # ended up in. ---
    assert any(_PROTECTED_SHORT_SENTENCE in text for text in all_texts), (
        f"expected the genuine short prose sentence {_PROTECTED_SHORT_SENTENCE!r} "
        f"(alphabetic ratio {_PROTECTED_SENTENCE_RATIO:.4f}, PRD §7.8's own protected "
        f"worked example) to survive as a substring of some emitted chunk -- a chunk "
        f"at or above the low-alpha threshold must always have its text kept, "
        f"however short, even though it now merges backward into its same-section "
        f"predecessor (#210 / §8 P0-4) instead of staying its own standalone record. "
        f"Full records: {records!r}"
    )

    # --- 3. every genuine long prose paragraph's content survives (no
    # over-drop). Seven of the eight are emitted verbatim, unsplit and
    # unmerged, because nothing below CHUNK_MIN follows them into a
    # backward merge. PROTECTED_PARA_2 is the one exception: it is the
    # Protected section's predecessor paragraph, and the section's
    # protected short-prose tail (below CHUNK_MIN, not fragment-floor
    # material) merges BACKWARD into it (#210 / §8 P0-4) rather than
    # staying its own standalone record, so PROTECTED_PARA_2's own emitted
    # chunk is `PROTECTED_PARA_2 + " " + tail`, checked here as a
    # substring. ---
    _paragraphs_expected_verbatim = [p for p in _ALL_GENUINE_PARAGRAPHS if p != PROTECTED_PARA_2]
    for paragraph in _paragraphs_expected_verbatim:
        assert paragraph in all_texts, (
            f"expected this genuine long prose paragraph to survive verbatim in the "
            f"on-disk artifact (no over-drop), but it is missing. Paragraph start: "
            f"{paragraph[:80]!r}. Full records: {records!r}"
        )
    assert any(PROTECTED_PARA_2 in text for text in all_texts), (
        f"expected PROTECTED_PARA_2's content to survive as part of some emitted "
        f"chunk (no over-drop) -- it is the Protected section's predecessor "
        f"paragraph, so the protected short-prose tail now merges backward into it "
        f"(#210 / §8 P0-4), but even that merged text is missing. Paragraph start: "
        f"{PROTECTED_PARA_2[:80]!r}. Full records: {records!r}"
    )

    # --- 4. the router-owned skip sidecar records each low-alpha drop with
    # its own fragment-floor reason, distinct from the pre-existing
    # apparatus reasons ("apparatus: ...") and the pre-existing
    # garble-backstop reason ("high non-alpha ratio (...)"). ---
    skips_path = chunks_skips_sidecar_path(source_id)
    skip_records = _read_jsonl(skips_path)

    def _fragment_floor_skips_for(section: str) -> list[dict]:
        return [
            r
            for r in skip_records
            if r.get("section") == section
            and not _is_known_non_fragment_floor_reason(str(r.get("reason", "")))
        ]

    citation_skips = _fragment_floor_skips_for("Citation")
    assert len(citation_skips) == 1, (
        f"expected exactly ONE fragment-floor skip record for the 'Citation' section's "
        f"dropped bare-citation tail (ratio {_CITATION_TAIL_RATIO:.4f}), with its own "
        f"reason distinct from apparatus/garble-backstop reasons (§7.8), recorded to "
        f"{skips_path}, got {len(citation_skips)}: {citation_skips!r}. "
        f"Full skip sidecar: {skip_records!r}"
    )
    assert citation_skips[0].get("reason"), (
        f"expected the 'Citation' fragment-floor skip record to carry a non-empty "
        f"reason: {citation_skips[0]!r}"
    )

    significance_skips = _fragment_floor_skips_for("Significance")
    assert len(significance_skips) == 1, (
        f"expected exactly ONE fragment-floor skip record for the 'Significance' "
        f"section's dropped significance-star tail (ratio "
        f"{_SIGNIFICANCE_TAIL_RATIO:.4f}), with its own reason distinct from "
        f"apparatus/garble-backstop reasons (§7.8), recorded to {skips_path}, got "
        f"{len(significance_skips)}: {significance_skips!r}. "
        f"Full skip sidecar: {skip_records!r}"
    )
    assert significance_skips[0].get("reason"), (
        f"expected the 'Significance' fragment-floor skip record to carry a non-empty "
        f"reason: {significance_skips[0]!r}"
    )

    blank_skips = _fragment_floor_skips_for("Blank")
    assert len(blank_skips) == 1, (
        f"expected exactly ONE fragment-floor skip record for the 'Blank' section's "
        f"dropped ratio-0 tail (regression check on #193), with its own reason "
        f"distinct from apparatus/garble-backstop reasons (§7.8), recorded to "
        f"{skips_path}, got {len(blank_skips)}: {blank_skips!r}. "
        f"Full skip sidecar: {skip_records!r}"
    )
    assert blank_skips[0].get("reason"), (
        f"expected the 'Blank' fragment-floor skip record to carry a non-empty "
        f"reason: {blank_skips[0]!r}"
    )

    # No fragment-floor drop recorded for "Protected" -- its tail is
    # genuine short prose at or above the low-alpha threshold and must
    # never be dropped or logged as a skip.
    protected_skips = _fragment_floor_skips_for("Protected")
    assert not protected_skips, (
        f"expected ZERO fragment-floor skip records for the 'Protected' section (its "
        f"tail is genuine short prose at ratio {_PROTECTED_SENTENCE_RATIO:.4f} >= "
        f"{_LOW_ALPHA_THRESHOLD}, protected, never dropped), got: {protected_skips!r}. "
        f"Full skip sidecar: {skip_records!r}"
    )
