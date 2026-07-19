"""Regression test pinning a real gap in the #222 bibliography-by-aggregate
detector (`axial.envelope._is_bibliographic_aggregate_section`).

The bug
--------
`_BIBLIOGRAPHIC_LEAF_RE` was proven only against a TIDY synthetic fixture
(`tests/fixtures/envelope/bibliography_aggregate_tree.json`): every leaf
there is "Surname, Initial (Year)." -- an inverted surname followed
immediately by a single initial and a parenthetical year. Real OCR'd
academic bibliographies are messier: full given names spelled out instead of
initials ("CARDEN, MAREN LOCKWOOD (1974)."), multi-author entries with
semicolons and "eds." pushing the year far from the string's start, OCR
noise substituting a digit for a letter in an initial ("DARVALL, F. 0.
(1934)."), "__"/"___" continuation-dash entries for a repeated author,
corporate authors with no comma at all, "JR." suffixes, "and"-joined
two-author entries, and OCR-garbled leading characters in a surname. None of
these match `_BIBLIOGRAPHIC_LEAF_RE`'s narrow anchor -- so on a source whose
bibliography actually looks like this (the real shape observed on the Tilly
source PRD §8 P0-3 names as the acceptance target, per `data/trees/
tilly-from-mobilization-to-revolution-*.json`), the aggregate share sits far
below `_BIBLIOGRAPHIC_LEAF_SHARE_THRESHOLD` (0.8) -- around 0% on this
fixture -- so the section is NEVER excluded, the citation wall clears the
200-char evidence floor on raw length alone, and the model is handed a
bibliography instead of body prose. The detector the issue shipped is a
no-op on the very source it was built for.

Copyright constraint (DEC-23)
------------------------------
`tests/fixtures/envelope/bibliography_real_ocr_tree.json` is a HAND-AUTHORED
tree with wholly INVENTED authors, titles, and publishers -- not an excerpt
of any real book's bibliography (which must never be committed, DEC-23,
gitignored `data/`). It faithfully mirrors the real OCR'd citation SHAPES
described above (full given names, multi-author "eds." entries, OCR-noise
initials, continuation dashes, corporate authors, "JR." suffixes,
"and"-joined co-authors, OCR-garbled surnames) with entirely fabricated
content, exactly as `bibliography_aggregate_tree.json` fabricated its own
tidy "Surname, Initial (Year)" leaves for the #222 acceptance test.

Seam decision -- asserting on `compose_thesis_evidence(tree) -> str` directly
----------------------------------------------------------------------
Same seam as `tests/ingestion/test_envelope_bibliography_aggregate.py`:
originally this test asserted directly on `compose_prompt(tree)`'s full
return value, since before #235 that string carried nothing but this
thesis/scope/stated_argument evidence slot. Issue #235 (hybrid two-signal
`toc` reconstruction) folds a SECOND, front-matter-INCLUSIVE Signal A into
the SAME single envelope prompt (§7.3's dual-role split, required by the
one-call-per-source lock), so `compose_prompt(tree)`'s full text now also
legitimately carries front matter/bibliography content via that separate
signal -- asserting bibliography-marker absence against the WHOLE prompt
would no longer hold, even though the thesis evidence itself is still
exactly as clean as before. `compose_thesis_evidence` is the extracted,
still-KEPT-and-unchanged function that returns precisely what used to be
`compose_prompt`'s own `{sections}` slot, so pointing this test's
assertions at it (instead of the whole prompt) preserves the exact intent
of this contract without weakening a single assertion. It is the exact
function the envelope pass hands into the prompt template's `{sections}`
slot, pure and synchronous over an in-memory tree `dict`, so asserting on
its return value pins the real observable behavior with no LLM call, no
filesystem/`data/` state, and no docling run.

Test hygiene: pure `compose_thesis_evidence(tree)` calls over hand-loaded
fixture JSON, no filesystem writes, no `data/` state, no LLM client, no
subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

from axial.envelope import compose_thesis_evidence, select_envelope_nodes

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"

REAL_OCR_TREE_FIXTURE = FIXTURES_DIR / "bibliography_real_ocr_tree.json"
CONTROL_TREE_FIXTURE = FIXTURES_DIR / "bibliography_aggregate_control_tree.json"

# The body-prose marker that must survive into the widened head-of-tree
# slice once the mis-attached bibliography is correctly excluded -- our own
# fabricated argument claim, not drawn from any real source.
BODY_PROSE_MARKER = "Marrowfield equilibrium thesis"

# A representative sample of the invented citation leaves' distinctive
# surnames/markers, one per real-world OCR shape described in the module
# docstring -- none of these may appear in the composed evidence once the
# bibliography is correctly excluded.
CITATION_SURNAME_MARKERS = (
    "HARROWGATE",  # ALL-CAPS surname + full given names
    "BRANNIGAN",  # multi-author, semicolons, "eds.", year far from start
    "ASHDOWN",  # surname + spelled-out first name + middle initial
    "PEMBERTON",  # initials with OCR noise ("0" for "O.")
    "Histoire des Croquants Fictifs",  # "__" continuation-dash entry
    "NATIONAL FICTIONAL COMMISSION",  # corporate ALL-CAPS author, no comma
    "WHITMORE",  # "JR." suffix
    "FENWICK, SIDNEY, and BEATRICE FENWICK",  # two-author "and"
    "I<ETTLEWELL",  # OCR-garbled leading surname character
)

# Control-fixture markers (mirroring the #222 acceptance test's own control).
CONTROL_INTRO_MARKER = "rotating stewardship rather than fixed leadership"
CONTROL_CONCLUSION_MARKER = (
    "rotating stewardship better explains the guild's durable bargaining power"
)


def _load_tree(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_top_level_section(tree: dict, heading_text: str) -> dict:
    for child in tree.get("children", []):
        if child.get("text") == heading_text:
            return child
    raise AssertionError(
        f"fixture sanity check failed: expected a top-level section headed "
        f"{heading_text!r} in {tree!r}"
    )


def test_real_ocr_fixture_matches_only_the_introduction_heading():
    """Fixture sanity check: `select_envelope_nodes` must match exactly the
    "1 Introduction" section (never "Argument Overview", which is
    deliberately NOT intro/abstract/conclusion-titled) -- or the rest of this
    test would not actually be exercising the mis-attachment gap at all."""
    tree = _load_tree(REAL_OCR_TREE_FIXTURE)
    matched_headings = [node.get("text") for node in select_envelope_nodes(tree)]
    assert matched_headings == ["1 Introduction"], (
        f"expected select_envelope_nodes to match exactly one section, "
        f"'1 Introduction', on the real-OCR bibliography fixture, got "
        f"{matched_headings!r}"
    )


def test_real_ocr_fixture_citations_clear_evidence_floor_on_raw_length():
    """Fixture sanity check: the citation wall alone -- summed over its raw
    leaf text, ignoring whatever the aggregate-exclusion detector decides --
    must comfortably clear the envelope's 200-character evidence floor,
    exactly as the real Tilly section's citation wall does. This guards the
    test below: what must make the model's evidence correct is EXCLUSION of
    the bibliography, not the bibliography being too short to clear the
    floor on its own."""
    tree = _load_tree(REAL_OCR_TREE_FIXTURE)
    intro = _find_top_level_section(tree, "1 Introduction")
    citation_children = intro.get("children", [])
    total_chars = sum(len(child.get("text") or "") for child in citation_children)
    assert len(citation_children) >= 15, (
        f"expected the real-OCR bibliography fixture's Introduction section "
        f"to carry 15+ single-citation leaf children, got "
        f"{len(citation_children)}"
    )
    assert total_chars >= 1000, (
        f"expected the real-OCR bibliography fixture's citation wall to "
        f"clear the 200-character evidence floor comfortably, got only "
        f"{total_chars} combined characters across {len(citation_children)} "
        f"leaves"
    )


def test_compose_prompt_excludes_real_ocr_bibliography_and_reaches_body_prose():
    """The behavior under test: given a section whose citation leaves use
    real-world OCR'd bibliographic shapes (full given names, multi-author
    "eds." entries, OCR-noise initials, continuation dashes, corporate
    authors, "JR." suffixes, "and"-joined co-authors, OCR-garbled surnames --
    NONE of which are the tidy "Surname, Initial (Year)" shape the shipped
    detector's regex actually matches), `compose_prompt` must still exclude
    that citation wall from the matched-section evidence and widen to real
    body prose elsewhere in the tree -- exactly as it already does for the
    tidy fixture. This is the gap #222 shipped a no-op detector against: on
    this fixture the detector's own matched share is ~0%, far below its 0.8
    threshold, so today the wall is NOT excluded and leaks straight into the
    model's evidence instead of the real thesis."""
    tree = _load_tree(REAL_OCR_TREE_FIXTURE)
    evidence = compose_thesis_evidence(tree)

    intro = _find_top_level_section(tree, "1 Introduction")
    citation_texts = [child.get("text") for child in intro.get("children", [])]

    # --- assertion 1: none of the real-OCR-shaped citation leaves appear in
    # the composed evidence -- the aggregate exclusion must fire on messy,
    # real-world citation shapes, not only the tidy synthetic shape the
    # shipped regex happens to match ---
    leaked = [text for text in citation_texts if text in evidence]
    assert not leaked, (
        f"expected NONE of the real-OCR bibliography fixture's "
        f"{len(citation_texts)} single-citation leaves to appear in "
        f"compose_prompt's evidence -- a matched section whose descendants "
        f"are overwhelmingly single-citation/bibliographic leaves must be "
        f"excluded from the matched-section evidence regardless of which "
        f"real-world citation format the leaves use, but {len(leaked)} "
        f"leaked through, e.g. {leaked[0]!r}.\nFull composed evidence:\n"
        f"{evidence}"
    )

    # --- assertion 2 (redundant, per-marker sample): a representative
    # surname/marker from each distinct real-world OCR shape must be absent
    # ---
    present_markers = [m for m in CITATION_SURNAME_MARKERS if m in evidence]
    assert not present_markers, (
        f"expected none of these representative real-OCR citation markers "
        f"to appear in compose_prompt's evidence: {present_markers!r}.\n"
        f"Full composed evidence:\n{evidence}"
    )

    # --- assertion 3: the pass widened to the head-of-tree slice and
    # reached genuine body prose instead ---
    assert BODY_PROSE_MARKER in evidence, (
        f"expected compose_prompt's evidence to carry the distinctive "
        f"body-prose marker {BODY_PROSE_MARKER!r} from the fixture's "
        f"'Argument Overview' section, reachable only via the head-of-tree "
        f"widen once the mis-attached '1 Introduction' bibliography is "
        f"excluded. Its absence means the pass still hands the model the "
        f"citation wall instead of widening to real body prose.\n"
        f"Full composed evidence:\n{evidence}"
    )


def test_compose_prompt_control_source_evidence_unchanged():
    """Conservative-control sanity check (reusing the #222 control fixture):
    a normally-sectioned source whose Introduction/Conclusion each cite one
    source in passing, inline, inside a full argument sentence -- never as a
    bare citation entry -- must be entirely unaffected. This guards against
    a fixer over-correcting the detector into a blunt instrument that
    excludes ordinary in-passing citations along with real bibliographies."""
    tree = _load_tree(CONTROL_TREE_FIXTURE)

    matched_headings = [node.get("text") for node in select_envelope_nodes(tree)]
    assert matched_headings == ["Introduction", "Conclusion"], (
        f"fixture sanity check failed: expected the control fixture's "
        f"Introduction and Conclusion sections to both match "
        f"select_envelope_nodes, got {matched_headings!r}"
    )

    evidence = compose_thesis_evidence(tree)

    assert CONTROL_INTRO_MARKER in evidence, (
        f"expected the control fixture's Introduction argument sentence "
        f"(containing {CONTROL_INTRO_MARKER!r}) to still appear in "
        f"compose_prompt's evidence unchanged -- a normally-sectioned "
        f"source's evidence must not be disturbed by a more permissive "
        f"bibliography detector.\nFull composed evidence:\n{evidence}"
    )
    assert CONTROL_CONCLUSION_MARKER in evidence, (
        f"expected the control fixture's Conclusion argument sentence "
        f"(containing {CONTROL_CONCLUSION_MARKER!r}) to still appear in "
        f"compose_prompt's evidence unchanged -- an ordinary in-passing "
        f"citation must never trip a widened bibliography detector.\n"
        f"Full composed evidence:\n{evidence}"
    )
