"""Regression test pinning a real gap in the head-of-tree front-matter prefix
skip (`axial.envelope._head_of_tree_lines` / `_is_front_matter_prefix_block`,
PRD §7.3 and §8 P0-3).

The bug
-------
The skip's own rule is "the FIRST non-front-matter-flagged block ends the
skip for good" (`_head_of_tree_lines`'s docstring). That rule silently
assumes a source's front matter always OPENS with a block
`_is_front_matter_prefix_block` recognizes -- a docling `title`-labeled node,
or text carrying a high-confidence copyright marker. Real title pages don't:
the very first block is routinely the book's own title or a
publisher/author line rendered as an ordinary `section_header`/`text` block
(NOT the docling `title` label), carrying no copyright marker at all. On
such a source, `_is_front_matter_prefix_block` returns False on block 0,
`skipping_prefix` flips to `False` immediately, and EVERY subsequent block
-- including the actual copyright/ISBN block, the dedication, and the
preface -- is collected into the widened slice exactly as if none of it were
front matter, because the skip already ended before it ever got a chance to
recognize them. On the real Tilly source this widened slice is ~90% front
matter/preface, with the genuine argument barely surfacing before the
6000-character slice cap (`_HEAD_OF_TREE_SLICE_CHARS`).

Copyright constraint (DEC-23)
------------------------------
`tests/fixtures/envelope/frontmatter_region_tree.json` and
`tests/fixtures/envelope/frontmatter_control_immediate_prose_tree.json` are
HAND-AUTHORED trees with wholly INVENTED titles, authors, publishers, and
preface/body prose -- not excerpts of any real book (DEC-23, `data/`
gitignored). The first fixture mirrors the real Tilly front-matter SHAPE:
an untagged title-page block, an author/affiliation line, an edition line, a
bare page-number run, a copyright/ISBN block (this one DOES carry a real
copyright marker, but arrives too late -- the skip already ended at block
0), publisher boilerplate, a dedication, and a two-paragraph preface with
acknowledgement/seminar-thanks flavor -- all invented -- followed by a
genuinely new chapter and the source's first real body paragraph. The
second fixture is a control: a born-digital paper-style source with NO
title page and NO preface, whose very first block is already real argument
prose.

Seam decision -- asserting on `compose_thesis_evidence(tree) -> str` directly
----------------------------------------------------------------------
Same seam as the sibling #222 tests
(`test_envelope_bibliography_aggregate.py`,
`test_envelope_bibliography_real_ocr.py`): originally this test asserted
directly on `compose_prompt(tree)`'s full return value, since before #235
that string carried nothing but this thesis/scope/stated_argument evidence
slot. Issue #235 (hybrid two-signal `toc` reconstruction) folds a SECOND,
front-matter-INCLUSIVE Signal A into the SAME single envelope prompt (§7.3's
dual-role split, required by the one-call-per-source lock), so
`compose_prompt(tree)`'s full text now also legitimately carries front
matter via that separate signal -- asserting front-matter-marker absence
against the WHOLE prompt would no longer hold, even though the thesis
evidence itself is still exactly as clean as before. `compose_thesis_evidence`
is the extracted, still-KEPT-and-unchanged function that returns precisely
what used to be `compose_prompt`'s own `{sections}` slot -- the matched-
section blocks when they clear the evidence floor, else the pruned,
front-matter-skipped head-of-tree excerpt -- so pointing this test's
assertions at it (instead of the whole prompt) preserves the exact intent
("the THESIS evidence stays clean") without weakening a single assertion.
Neither fixture matches any of intro/abstract/conclusion at the top level
(asserted directly below as a fixture sanity check), so
`compose_thesis_evidence`'s evidence-floor check finds zero matched-section
evidence and MUST widen to the head-of-tree slice for both -- the exact
path `_head_of_tree_lines` and its prefix skip live on.

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

FRONTMATTER_TREE_FIXTURE = FIXTURES_DIR / "frontmatter_region_tree.json"
CONTROL_TREE_FIXTURE = FIXTURES_DIR / "frontmatter_control_immediate_prose_tree.json"

# Markers that must be ABSENT from compose_prompt's evidence once the whole
# front-matter region is correctly skipped (module docstring). Each sits
# only inside the fixture's invented front matter/preface, never in the
# chapter body.
TITLE_MARKER = "The Widening Spiral"
AUTHOR_MARKER = "JANE NETHERFIELD"
COPYRIGHT_MARKER = "Copyright © 1981 by Fictional House, Inc."
ISBN_MARKER = "ISBN: 0-000-00000-0"
DEDICATION_MARKER = "FOR NOBODY IN PARTICULAR"
PREFACE_MARKER = "the now-defunct Institute for Imaginary Studies"

FRONT_MATTER_MARKERS = (
    TITLE_MARKER,
    AUTHOR_MARKER,
    COPYRIGHT_MARKER,
    ISBN_MARKER,
    DEDICATION_MARKER,
    PREFACE_MARKER,
)

# The distinctive body-prose marker that must be PRESENT: the fixture's
# first genuinely substantive argument paragraph, reachable only once the
# entire front-matter region ahead of it is skipped.
BODY_MARKER = "the Vexley threshold principle"

# The control fixture's own distinctive opening-prose marker: a source with
# no front matter at all must never have its very first real paragraph
# eaten by the skip.
CONTROL_MARKER = "the Dunmore continuity argument"

# The bound the skip's own tunable is set to today (module docstring,
# `axial.envelope._FRONT_MATTER_PREFIX_SKIP_CHARS`) -- the fixture's combined
# front-matter region must comfortably clear it, so this test genuinely
# exercises a real-sized front matter, not a toy one.
_CURRENT_SKIP_BUDGET_CHARS = 1500


def _load_tree(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _front_matter_region_chars(tree: dict) -> int:
    """Sum of every leaf's own text under the fixture's front-matter region:
    every top-level child up to (but not including) the final chapter
    heading, plus its descendants' own text. Mirrors exactly what
    `_head_of_tree_lines` must learn to skip in one contiguous run."""
    total = 0
    for child in tree.get("children", []):
        if child.get("text") == "1 The Stuff of the Argument":
            break
        total += len(child.get("text") or "")
        for grandchild in child.get("children", []):
            total += len(grandchild.get("text") or "")
    return total


def test_frontmatter_fixture_matches_no_envelope_heading():
    """Fixture sanity check: neither fixture's top-level headings match
    introduction/abstract/conclusion, so `compose_prompt` MUST take the
    head-of-tree widen path for both -- the only path
    `_head_of_tree_lines`'s prefix skip lives on. If this fails, the rest of
    this test would not be exercising the widen path at all."""
    tree = _load_tree(FRONTMATTER_TREE_FIXTURE)
    assert select_envelope_nodes(tree) == [], (
        "expected the front-matter-region fixture to match no top-level "
        "intro/abstract/conclusion heading, so compose_prompt widens to "
        f"the head-of-tree slice, got {select_envelope_nodes(tree)!r}"
    )

    control_tree = _load_tree(CONTROL_TREE_FIXTURE)
    assert select_envelope_nodes(control_tree) == [], (
        "expected the control fixture to match no top-level intro/abstract/"
        "conclusion heading either, so it also takes the widen path, got "
        f"{select_envelope_nodes(control_tree)!r}"
    )


def test_frontmatter_fixture_region_exceeds_the_current_skip_budget():
    """Fixture sanity check: the front-matter region's combined character
    length (title page through the end of the preface) must exceed the
    skip's own current budget (`_FRONT_MATTER_PREFIX_SKIP_CHARS`, 1500) --
    otherwise this test would only be proving the fix handles a toy-sized
    front matter, not a real-sized one like Tilly's own preface."""
    tree = _load_tree(FRONTMATTER_TREE_FIXTURE)
    region_chars = _front_matter_region_chars(tree)
    assert region_chars > _CURRENT_SKIP_BUDGET_CHARS, (
        f"expected the fixture's front-matter region (title page + "
        f"copyright/ISBN + dedication + preface) to exceed "
        f"{_CURRENT_SKIP_BUDGET_CHARS} combined characters (mirroring a "
        f"real book's own preface size), got only {region_chars}"
    )


def test_compose_prompt_skips_the_whole_frontmatter_region_and_reaches_body():
    """The behavior under test: given a source whose head-of-tree opens with
    an untagged title-page block (no docling `title` label, no copyright
    marker), followed by author/edition/page-number lines, a copyright/ISBN
    block, publisher boilerplate, a dedication, and a full preface -- ALL of
    that front matter must be skipped, and the widened slice must reach the
    source's first genuinely substantive body prose (PRD §7.3, §8 P0-3:
    "skip ... preface scaffolding ... and begin counting at the first
    genuinely substantive body prose").

    Today the skip's own rule ends at the very first non-flagged block
    (the untagged title, block 0) and never resumes, so every front-matter
    marker below leaks into the evidence and the body marker either never
    appears or only appears after being truncated away by the slice cap."""
    tree = _load_tree(FRONTMATTER_TREE_FIXTURE)
    evidence = compose_thesis_evidence(tree)

    leaked = [marker for marker in FRONT_MATTER_MARKERS if marker in evidence]
    assert not leaked, (
        f"expected NONE of the front-matter/preface markers "
        f"{FRONT_MATTER_MARKERS!r} to appear in compose_prompt's evidence "
        f"-- PRD §7.3/§8 P0-3 require the whole leading front-matter "
        f"region (title page, copyright/ISBN, preface scaffolding) to be "
        f"skipped before counting toward the head-of-tree slice, but "
        f"{leaked!r} leaked through.\nFull composed evidence:\n{evidence}"
    )

    assert BODY_MARKER in evidence, (
        f"expected compose_prompt's evidence to reach the fixture's first "
        f"genuinely substantive body paragraph (containing "
        f"{BODY_MARKER!r}) once the entire front-matter region ahead of it "
        f"is skipped. Its absence means the widened slice never reaches "
        f"real argument prose -- either because the front matter still "
        f"leaks into the slice ahead of it, or because the slice's "
        f"character cap is exhausted by unskipped front matter before "
        f"reaching the body paragraph.\nFull composed evidence:\n{evidence}"
    )


def test_compose_prompt_control_source_keeps_its_opening_prose():
    """Guard against over-skip: a source with NO title page and NO preface --
    a born-digital paper whose head-of-tree opens immediately with real
    argument prose -- must have that opening prose land in the evidence
    unchanged. A fix that widens the skip to handle a real-sized front
    matter must never learn to eat legitimate early body prose on a source
    that never had any front matter to begin with."""
    tree = _load_tree(CONTROL_TREE_FIXTURE)
    evidence = compose_thesis_evidence(tree)

    assert CONTROL_MARKER in evidence, (
        f"expected the control fixture's own opening body paragraph "
        f"(containing {CONTROL_MARKER!r}) to appear in compose_prompt's "
        f"evidence unchanged -- a source with no front matter must never "
        f"have its first real paragraph skipped.\nFull composed evidence:\n"
        f"{evidence}"
    )
