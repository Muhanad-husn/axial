"""Outer acceptance test for issue #193: a narrow post-split fragment floor
that drops an emitted candidate chunk -- before it reaches the on-disk
artifact -- when it is unambiguous non-content boilerplate: a blank-page
notice, or a fragment with zero alphabetic characters.

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given three sections, each built from TWO genuine, distinct, in-band prose
      paragraphs (long enough, combined, to force the recursive splitter to
      actually split the section rather than emit it whole) followed by ONE
      trailing "tail" piece:
        - "Findings"   -- tail is a blank-page notice, spelled with mixed
                          case and doubled internal whitespace (e.g.
                          "This Page  Intentionally   Left Blank"), which
                          must equal "this page intentionally left blank"
                          after lowercasing + whitespace collapse.
        - "Discussion" -- tail is a no-alphabetic-content fragment,
                          `"13)."` (PRD §7.8's own worked example -- digits
                          and punctuation only, zero alphabetic characters).
        - "Conclusion" -- tail is a genuine SHORT prose sentence, verbatim
                          from PRD §7.8's own worked example:
                          "They consist essentially of three elements." --
                          this one is NOT boilerplate and its TEXT must be
                          KEPT (see #210: kept means the text survives, not
                          that it survives as its own standalone record --
                          below CHUNK_MIN with a same-section predecessor,
                          it merges BACKWARD into that predecessor,
                          CONCLUSION_PARA_2, per §8 P0-4).
      Each section's own body is dominated by real, unambiguous prose (two
      ~2000-char paragraphs each): the section-level garble backstop
      (`_garbage_section_skip_reason`, a non-alphabetic-ratio check over the
      WHOLE joined body) sees almost entirely alphabetic text in every
      section and so never fires -- exactly the gap #193 exists to close.
When  `axial.chunk.run_chunk_recursive` runs against this source
Then  no chunk written to `data/chunks/<source_id>.jsonl` equals the
      blank-page notice (after lowercasing + whitespace collapse)
And   no chunk written to that artifact has zero alphabetic characters
And   the genuine short prose sentence's TEXT ("They consist essentially of
      three elements.") survives in the artifact -- protected, because it
      carries a real word; length alone never triggers a drop. It survives
      as a substring of the merged chunk it was folded backward into
      (§8 P0-4 predecessor-merge, reconciled with §7.8 "genuine short prose
      is protected" in #210 spec-drift), not as its own standalone record.
And   every one of the six genuine long prose paragraphs' content is
      present in the artifact (no over-drop): five verbatim and unsplit;
      CONCLUSION_PARA_2 as a substring of the chunk it absorbed the
      protected tail into (see above)
And   the router-owned skip sidecar (`<source_id>.skips.jsonl`) carries one
      skip record for the "Findings" section's dropped blank-page tail and
      one for the "Discussion" section's dropped zero-alphabetic tail, each
      with a reason string of its own -- distinct from the pre-existing
      apparatus reasons (which always read `"apparatus: ..."`) and from the
      pre-existing garble-backstop reason (which always reads `"high
      non-alpha ratio (...)"`)

See specs/PRODUCT.md §7.8 "Post-split fragment floor (#193)" / "Genuine
short prose is protected (#193)", and §8 P0-4's "post-split fragment floor"
bullet and P0-4b's skip-record bullet, for the source of truth this test
encodes. See GitHub issue #193.

Root-cause note (why three SEPARATE sections, not one section carrying both
junk shapes as adjacent trailing pieces)
-----------------------------------------------------------------------
The junk this floor targets survives today because the existing garble
backstop runs at the SECTION level, on the whole joined body BEFORE the
recursive splitter -- it is blind to a junk *tail chunk* a legitimate,
long prose section leaves behind only after splitting. This test's three
sections each reproduce exactly that shape (dominant real prose, one small
non-content tail) so the section-level backstop provably never fires on any
of them (verified indirectly: this test's assertion that ALL SIX genuine
paragraphs survive, undisturbed, in EVERY section including the two with a
dropped tail, would fail if the section-level backstop had instead skipped
one of those sections wholesale).

Three sections rather than one section carrying two adjacent junk tails is
a deliberate fixture choice, not laziness: `axial.chunk._enforce_min` (the
MIN-side band guard) merges any below-`CHUNK_MIN` chunk FORWARD into
whatever immediately follows it, within its forward pass, regardless of
that next piece's own size. Two below-min junk pieces placed back-to-back
in one section would merge into a single combined chunk before this floor
ever sees two separate candidates -- and a real paragraph placed between
two junk pieces gets absorbed into the first (already-merged) junk chunk
rather than staying an isolated peer. The section's own LAST piece is the
only one the forward pass can leave below `CHUNK_MIN` on its own (nothing
follows it to merge into) -- which is also exactly the real-world shape
(#193's own root-cause note: "the leaking crumbs are section tails"). Since
#207/#210, `_enforce_min` then prefers merging that trailing piece BACKWARD
into its same-section predecessor (within `CHUNK_MAX`) -- UNLESS the
trailing piece is itself fragment-floor material (`_fragment_floor_reason`
is not `None`), in which case the backward merge is deliberately skipped so
this floor can still evaluate and drop it as an isolated candidate. That is
exactly why "Findings" and "Discussion" below stay isolated for the floor:
their trailing tails ARE fragment-floor material, so the backward merge
never fires for them. "Conclusion"'s trailing tail, by contrast, is
genuine short prose -- not fragment-floor material -- so it now merges
backward into CONCLUSION_PARA_2 rather than surviving the floor as its own
standalone record; its TEXT still survives, verbatim, as a substring of
that merged chunk (§7.8 "genuine short prose is protected", reconciled with
the §8 P0-4 predecessor-merge in #210). Three sections, each with its own
single trailing tail, is therefore still the minimal fixture that puts one
isolated candidate junk chunk of each targeted junk shape in front of the
floor, without an unrelated merge behavior confounding which piece the
floor actually had to evaluate.

Seam decision -- band constants imported, not hardcoded
-----------------------------------------------------------------------
Mirroring tests/chunk/test_chunk_recursive.py's own seam decision 5, each
paragraph's target length is derived from `CHUNK_MIN`/`CHUNK_MAX` (their
midpoint) rather than a hardcoded character count, so this fixture keeps
forcing an actual mid-section split (and keeps each paragraph safely
in-band, unsplit) even if the band is retuned later.

Seam decision -- isolation via an isolated tmp cwd
-----------------------------------------------------------------------
Mirroring tests/chunk/test_chunk_recursive.py's own seam decision 4: this
test runs from a freshly created, empty `tmp_path` cwd
(`monkeypatch.chdir`), so `axial.extract.TREES_DIR` / `axial.chunk.CHUNKS_DIR`
resolve under the isolated tmp root and this test never touches the real
repo's `data/` tree. No docling, no network, no LLM, no embedding model --
`run_chunk_recursive` reads only the hand-built tree fixture placed directly
at the expected persisted-tree path.
"""

from __future__ import annotations

import json
import re
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
# per #207/#210's predecessor-merge; see CONCLUSION_PARA_2 below) and
# comfortably < CHUNK_MAX (so a paragraph is never itself split further).
# Two of these together, plus a short tail, safely exceed CHUNK_MAX,
# forcing the recursive splitter to actually divide each section rather
# than emit it as one whole chunk.
_PARAGRAPH_TARGET_CHARS = (CHUNK_MIN + CHUNK_MAX) // 2

_BLANK_PAGE_NOTICE_NORMALIZED = "this page intentionally left blank"
# Mixed case + doubled internal whitespace: exercises the "after lowercasing
# and whitespace collapse" half of the contract, not just a literal match.
_BLANK_PAGE_TAIL_TEXT = "This Page  Intentionally   Left Blank"

# PRD §7.8's own worked example of a no-alphabetic-content fragment: digits
# and punctuation only, zero alphabetic characters.
_ZERO_ALPHA_TAIL_TEXT = "13)."

# PRD §7.8's own worked example of genuine short prose that must survive.
_PROTECTED_SHORT_SENTENCE = "They consist essentially of three elements."

_FINDINGS_SENTENCES_1 = [
    "Fieldwork sentinel Alpha: the provincial survey documented shifting patterns of "
    "market activity across three districts after the ceasefire took hold.",
    "Local administrators reported gradual improvements in water access even as "
    "electricity supply remained unreliable through the reporting period.",
    "Interview transcripts from municipal offices described a slow but steady return "
    "of displaced households to peripheral neighborhoods.",
    "Aid coordination meetings moved from the capital to regional hubs, reflecting a "
    "broader decentralization of relief planning across the province.",
]
_FINDINGS_SENTENCES_2 = [
    "Fieldwork sentinel Beta: survey respondents in the eastern sub-district cited "
    "road access as the single most persistent obstacle to recovery efforts.",
    "Provincial budgets for reconstruction were revised twice during the survey "
    "window, complicating any year-over-year comparison of spending totals.",
    "Cross-border trade resumed unevenly, concentrated around a small number of "
    "newly reopened crossings near the northern administrative corridor.",
    "Local councils began coordinating shared municipal services for the first time "
    "since the conflict disrupted ordinary provincial governance.",
]
_DISCUSSION_SENTENCES_1 = [
    "Discussion sentinel Gamma: the observed variation in service delivery tracks "
    "closely with pre-conflict administrative capacity in each district.",
    "This pattern suggests continuity in local institutional strength rather than a "
    "clean break driven solely by the intensity of recent fighting.",
    "A competing reading emphasizes external aid targeting as the dominant factor "
    "behind the uneven recovery observed across the sampled districts.",
    "Neither explanation alone accounts for the full spread of outcomes recorded "
    "during the fieldwork period described above.",
]
_DISCUSSION_SENTENCES_2 = [
    "Discussion sentinel Delta: triangulating the interview data against the "
    "administrative records narrows the plausible explanations considerably.",
    "Officials interviewed in the western districts consistently described capacity "
    "constraints predating the conflict by several years.",
    "The eastern districts, by contrast, reported capacity losses concentrated in "
    "the final eighteen months of active fighting specifically.",
    "This divergence argues for a locally differentiated account rather than one "
    "single province-wide explanatory mechanism.",
]
_CONCLUSION_SENTENCES_1 = [
    "Conclusion sentinel Epsilon: taken together, the findings support a cautious, "
    "differentiated account of post-conflict administrative recovery.",
    "No single factor -- pre-conflict capacity, aid targeting, or fighting intensity "
    "-- explains the full pattern observed across every sampled district.",
    "Future fieldwork should track these same districts longitudinally to test "
    "whether the observed divergence narrows or widens over time.",
    "The present study's scope was limited to one province, so generalizing beyond "
    "it requires independent replication elsewhere.",
]
_CONCLUSION_SENTENCES_2 = [
    "Conclusion sentinel Zeta: the policy implications favor differentiated, "
    "district-specific recovery support over a uniform province-wide program.",
    "Donors coordinating future assistance should weight pre-conflict capacity "
    "alongside conflict intensity when allocating reconstruction funding.",
    "This recommendation follows directly from the divergence documented between "
    "the eastern and western districts earlier in this report.",
    "It does not resolve which single mechanism dominates, only that a single "
    "uniform policy would poorly fit the documented variation.",
]


def _build_paragraph(sentences: list[str], target_chars: int) -> str:
    """A single continuous prose string (no `\n` anywhere inside it), built
    by cycling `sentences` until it reaches at least `target_chars`
    characters -- mirrors tests/chunk/test_chunk_recursive.py's own
    `_build_wall_of_text` helper."""
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


FINDINGS_PARA_1 = _build_paragraph(_FINDINGS_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
FINDINGS_PARA_2 = _build_paragraph(_FINDINGS_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)
DISCUSSION_PARA_1 = _build_paragraph(_DISCUSSION_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
DISCUSSION_PARA_2 = _build_paragraph(_DISCUSSION_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)
CONCLUSION_PARA_1 = _build_paragraph(_CONCLUSION_SENTENCES_1, _PARAGRAPH_TARGET_CHARS)
CONCLUSION_PARA_2 = _build_paragraph(_CONCLUSION_SENTENCES_2, _PARAGRAPH_TARGET_CHARS)

_ALL_GENUINE_PARAGRAPHS = [
    FINDINGS_PARA_1,
    FINDINGS_PARA_2,
    DISCUSSION_PARA_1,
    DISCUSSION_PARA_2,
    CONCLUSION_PARA_1,
    CONCLUSION_PARA_2,
]

# Sanity on the fixture's own construction (not the contract under test):
# each individual paragraph must stay under CHUNK_MAX (so it is never split
# further), while two of them together must exceed CHUNK_MAX (so the
# section is actually forced through the recursive splitter rather than
# emitted whole).
for _para in _ALL_GENUINE_PARAGRAPHS:
    assert len(_para) < CHUNK_MAX, "internal fixture bug: a paragraph must stay under CHUNK_MAX"
assert (
    FINDINGS_PARA_1 + FINDINGS_PARA_2 and len(FINDINGS_PARA_1) + len(FINDINGS_PARA_2) > CHUNK_MAX
), "internal fixture bug: two paragraphs combined must exceed CHUNK_MAX to force a split"


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
            _section("1", "Findings", [FINDINGS_PARA_1, FINDINGS_PARA_2, _BLANK_PAGE_TAIL_TEXT]),
            _section(
                "2", "Discussion", [DISCUSSION_PARA_1, DISCUSSION_PARA_2, _ZERO_ALPHA_TAIL_TEXT]
            ),
            _section(
                "3",
                "Conclusion",
                [CONCLUSION_PARA_1, CONCLUSION_PARA_2, _PROTECTED_SHORT_SENTENCE],
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


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def test_post_split_fragment_floor_drops_blank_page_and_zero_alpha_tails_but_keeps_short_prose(
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

    # --- 1. no emitted chunk equals the blank-page notice (normalized). ---
    blank_page_survivors = [
        text for text in all_texts if _normalize(text) == _BLANK_PAGE_NOTICE_NORMALIZED
    ]
    assert not blank_page_survivors, (
        f"expected the post-split fragment floor (#193) to drop the blank-page-notice "
        f"tail chunk (normalizes to {_BLANK_PAGE_NOTICE_NORMALIZED!r}) before it ever "
        f"reaches the on-disk artifact {chunk_path}, but it survived: "
        f"{blank_page_survivors!r}. Full records: {records!r}"
    )

    # --- 2. no emitted chunk has zero alphabetic characters. ---
    zero_alpha_survivors = [
        text for text in all_texts if text and not any(c.isalpha() for c in text)
    ]
    assert not zero_alpha_survivors, (
        f"expected the post-split fragment floor (#193) to drop any emitted chunk with "
        f"zero alphabetic characters (e.g. {_ZERO_ALPHA_TAIL_TEXT!r}) before it ever "
        f"reaches the on-disk artifact {chunk_path}, but it survived: "
        f"{zero_alpha_survivors!r}. Full records: {records!r}"
    )

    # --- 3. the genuine short prose sentence's TEXT survives -- protection
    # invariant: length alone must never trigger a drop. This is what stops
    # a naive min-length "fix" from passing this test. Per #210 spec-drift
    # (reconciling #207's MIN-side predecessor-merge with #193's "genuine
    # short prose is protected"), "protected" means the TEXT is never
    # dropped -- not that it survives as its own standalone record: below
    # CHUNK_MIN with a same-section predecessor (CONCLUSION_PARA_2), it
    # merges BACKWARD into that predecessor (§8 P0-4), so it is checked here
    # as a substring of whatever chunk it ended up in, not as a list member
    # in its own right. ---
    assert any(_PROTECTED_SHORT_SENTENCE in text for text in all_texts), (
        f"expected the genuine short prose sentence {_PROTECTED_SHORT_SENTENCE!r} "
        f"(PRD §7.8's own 'genuine short prose is protected' example) to survive as a "
        f"substring of some emitted chunk -- a short chunk carrying a real word must "
        f"always have its text kept, never dropped for its length alone, even though "
        f"it now merges backward into its same-section predecessor (#210 / §8 P0-4) "
        f"instead of staying its own standalone record. Full records: {records!r}"
    )

    # --- 4. every genuine long prose paragraph's content survives (no
    # over-drop). Five of the six are emitted verbatim, unsplit and
    # unmerged, because nothing below CHUNK_MIN follows them into a backward
    # merge. CONCLUSION_PARA_2 is the one exception: it is the Conclusion
    # section's predecessor paragraph, and the section's protected
    # short-prose tail (below CHUNK_MIN, not fragment-floor material) merges
    # BACKWARD into it (#210 / §8 P0-4) rather than staying its own
    # standalone record, so CONCLUSION_PARA_2's own emitted chunk is
    # `CONCLUSION_PARA_2 + " " + tail`, checked here as a substring. ---
    _paragraphs_expected_verbatim = [p for p in _ALL_GENUINE_PARAGRAPHS if p != CONCLUSION_PARA_2]
    for paragraph in _paragraphs_expected_verbatim:
        assert paragraph in all_texts, (
            f"expected this genuine long prose paragraph to survive verbatim in the "
            f"on-disk artifact (no over-drop), but it is missing. Paragraph start: "
            f"{paragraph[:80]!r}. Full records: {records!r}"
        )
    assert any(CONCLUSION_PARA_2 in text for text in all_texts), (
        f"expected CONCLUSION_PARA_2's content to survive as part of some emitted "
        f"chunk (no over-drop) -- it is the Conclusion section's predecessor "
        f"paragraph, so the protected short-prose tail now merges backward into it "
        f"(#210 / §8 P0-4), but even that merged text is missing. Paragraph start: "
        f"{CONCLUSION_PARA_2[:80]!r}. Full records: {records!r}"
    )

    # --- 5. the router-owned skip sidecar records each fragment-floor drop
    # with its own reason, distinct from the pre-existing apparatus reasons
    # ("apparatus: ...") and the pre-existing garble-backstop reason
    # ("high non-alpha ratio (...)"). ---
    skips_path = chunks_skips_sidecar_path(source_id)
    skip_records = _read_jsonl(skips_path)

    def _is_known_non_fragment_floor_reason(reason: str) -> bool:
        return reason.startswith("apparatus:") or reason.startswith("high non-alpha ratio")

    findings_skips = [
        r
        for r in skip_records
        if r.get("section") == "Findings"
        and not _is_known_non_fragment_floor_reason(str(r.get("reason", "")))
    ]
    assert len(findings_skips) == 1, (
        f"expected exactly ONE fragment-floor skip record for the 'Findings' "
        f"section's dropped blank-page-notice tail, with its own reason distinct "
        f"from the apparatus/garble-backstop reasons (§7.8), recorded to "
        f"{skips_path}, got {len(findings_skips)}: {findings_skips!r}. "
        f"Full skip sidecar: {skip_records!r}"
    )
    assert findings_skips[0].get("reason"), (
        f"expected the 'Findings' fragment-floor skip record to carry a non-empty "
        f"reason: {findings_skips[0]!r}"
    )

    discussion_skips = [
        r
        for r in skip_records
        if r.get("section") == "Discussion"
        and not _is_known_non_fragment_floor_reason(str(r.get("reason", "")))
    ]
    assert len(discussion_skips) == 1, (
        f"expected exactly ONE fragment-floor skip record for the 'Discussion' "
        f"section's dropped zero-alphabetic-fragment tail, with its own reason "
        f"distinct from the apparatus/garble-backstop reasons (§7.8), recorded to "
        f"{skips_path}, got {len(discussion_skips)}: {discussion_skips!r}. "
        f"Full skip sidecar: {skip_records!r}"
    )
    assert discussion_skips[0].get("reason"), (
        f"expected the 'Discussion' fragment-floor skip record to carry a "
        f"non-empty reason: {discussion_skips[0]!r}"
    )

    # No fragment-floor drop recorded for "Conclusion" -- its tail is
    # genuine short prose and must never be dropped or logged as a skip.
    conclusion_skips = [
        r
        for r in skip_records
        if r.get("section") == "Conclusion"
        and not _is_known_non_fragment_floor_reason(str(r.get("reason", "")))
    ]
    assert not conclusion_skips, (
        f"expected ZERO fragment-floor skip records for the 'Conclusion' section "
        f"(its tail is genuine short prose, protected, never dropped), got: "
        f"{conclusion_skips!r}. Full skip sidecar: {skip_records!r}"
    )
