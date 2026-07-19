"""Generator for tests/fixtures/envelope/* binary fixtures.

Ephemeral-toolchain script -- NOT a test-time dependency. Run with:

    uv run --with reportlab python tests/fixtures/envelope/_generate.py

Regenerates the committed fixture binary in this directory. The test suite
(tests/test_envelope.py) depends only on the committed binary and never
invokes this script.

Companion fixture -- thesis_paper_tree.json (issue #45, tree-cache)
-----------------------------------------------------------------------
tests/fixtures/envelope/thesis_paper_tree.json is the REAL persisted
structural tree `axial extract` produces for thesis_paper.pdf, committed so
downstream tests that only CONSUME the tree (tests/test_envelope.py,
tests/test_chunk.py, tests/test_tag.py, tests/test_vault_write.py) can
pre-place it at data/trees/<source_id>.json (source_id via
axial.envelope.compute_source_id) instead of paying for a real docling run
just to obtain input they never assert on. This is not a mystery blob: it is
exactly `axial extract`'s own stdout for this fixture, and it must stay
byte-identical to what a fresh extraction produces, since axial.extract.extract
reuses a persisted tree verbatim (PRD §7.4) -- a stale/hand-edited fixture
here would silently diverge from real behavior. Regenerate it after any
change to thesis_paper.pdf or to the extraction/normalization logic with:

    rm -f data/trees/*.json  # ensure a fresh, non-cached extraction
    uv run axial extract tests/fixtures/envelope/thesis_paper.pdf > /dev/null
    cp data/trees/thesis_paper-*.json tests/fixtures/envelope/thesis_paper_tree.json
    rm -f data/trees/*.json  # don't leave scratch state behind

Verify the regenerated fixture matches a second fresh extraction (determinism
check) before committing:

    rm -f data/trees/*.json
    uv run axial extract tests/fixtures/envelope/thesis_paper.pdf > /tmp/fresh.json
    diff <(python -m json.tool tests/fixtures/envelope/thesis_paper_tree.json) <(python -m json.tool /tmp/fresh.json)
    rm -f data/trees/*.json

Companion fixture -- topic_titled_paper.pdf / topic_titled_paper_tree.json
(issue #201, structural-envelope anti-confabulation)
-----------------------------------------------------------------------
A second born-digital fixture whose top-level section headings are named by
TOPIC only -- "Border Enforcement Regimes", "Fiscal Extraction Networks",
"Digital Surveillance Architecture" -- and deliberately carry no heading
matching `axial.envelope._ENVELOPE_HEADINGS`
("introduction"/"abstract"/"conclusion", case-insensitive substring). This
is not a malformed or unusual document -- topic-titled top-level sections
are a completely normal shape for a source (e.g. a monograph chapter, a
report). `axial.envelope.select_envelope_nodes` matches NOTHING on this
tree, exercising exactly the gap PRD #7.3's "evidence floor" fixes.

Its first body paragraph carries an invented, highly distinctive marker
phrase -- "Kestrel-7 checkpoint protocol" / "threshold-lattice mechanism" --
that cannot plausibly be produced by a model free-associating from the
title/filename alone (unlike a real-world term a model might already know).
tests/test_envelope_structural_grounding.py asserts this exact phrase
reaches the assembled envelope prompt (via the `record` LLM-provider seam,
see that test's module docstring) as its evidence-floor proof: if the
phrase is present, real source text reached the model despite the
heading-heuristic match being empty; if absent, the evidence block was
empty or near-empty for this source, exactly the #201 defect.

Regenerate topic_titled_paper_tree.json after any change to
topic_titled_paper.pdf or to the extraction/normalization logic with:

    rm -f data/trees/*.json  # ensure a fresh, non-cached extraction
    uv run axial extract tests/fixtures/envelope/topic_titled_paper.pdf > /dev/null
    cp data/trees/topic_titled_paper-*.json tests/fixtures/envelope/topic_titled_paper_tree.json
    rm -f data/trees/*.json  # don't leave scratch state behind

Verify determinism the same way as thesis_paper_tree.json above, substituting
topic_titled_paper.pdf/topic_titled_paper_tree.json for the thesis_paper
names.

Companion fixture -- router_prose_filter_paper.pdf / router_prose_filter_paper_tree.json
(issue #216, envelope head-of-tree router filtering)
-----------------------------------------------------------------------
Unlike the two fixtures above, `router_prose_filter_paper_tree.json` is
HAND-AUTHORED, not a committed real docling extraction -- it is not
regenerated from `router_prose_filter_paper.pdf` via `axial extract`, and a
fresh extraction of that PDF is NOT expected to reproduce it byte-for-byte
(docling's own choice of `label` for a reportlab-rendered "Table of
Contents" paragraph is not something this fixture controls or needs to).
`tests/ingestion/test_envelope_router_prose_filter.py` pre-places this tree
directly at `data/trees/<source_id>.json`, so docling never runs against
this PDF in the test; the PDF exists only so `axial.intake.intake` (a real
text-layer probe) passes and `axial.envelope.compute_source_id` has real
file bytes to hash. `make_router_prose_filter_paper_pdf` below renders
prose that loosely mirrors the hand-authored tree's own text for a human
skimming the fixture, but the two are independent artifacts.

The tree's top-level headings ("Border Enforcement Regimes", "Fiscal
Extraction Networks", "Digital Surveillance Architecture") are topic-titled,
exactly like topic_titled_paper_tree.json, so `select_envelope_nodes`
matches nothing and the envelope pass widens to a head-of-tree slice (the
same #201 precondition). Ahead of the first section, at the head of the
tree, sits one `document_index` node (a TOC block) carrying a distinctive
"Quillfeather-19 index locus" marker; the first section's own prose carries
a distinct "Draubourne-4 escrow directive" marker. §7.8's router classifies
`document_index` as APPARATUS and `text`/`section_header` as PROSE -- see
that test module's docstring for the full two-direction proof this fixture
exercises (issue #216: today's head-of-tree walk collects every node's text
regardless of `label`, so the APPARATUS marker leaks into the prompt
alongside the genuine PROSE marker).

Companion fixture -- llm_toc_selection_paper.pdf / llm_toc_selection_tree.json
(issue #231, LLM-selected toc subset)
-----------------------------------------------------------------------
Another HAND-AUTHORED tree (same rationale as router_prose_filter_paper_tree.json
and structural_toc_tree.json above): a front-matter region (an untagged
title-page block, an author line, a copyright block, publisher boilerplate)
followed by ELEVEN top-level `section_header` siblings that mimic the real
FLATTENED shape #231 targets -- real trees carry 70-260 such siblings mixing
genuine chapters, subsection-style headings, OCR-garble fragments, and body
sentences mislabelled as headings, all flattened to the same nesting depth.
Of the eleven: four are genuine chapter titles ("Chapter One: The Onset of
Contention" ... "Chapter Four: Comparative Synthesis"), four are
subsection-style headings ("1.1 Grievance Recognition and Framing", etc.),
one is an OCR-garble fragment ("lalrodac:lioo"), one is a body sentence
mislabelled as a heading ("A successful program does all of them at once."),
and one is an appendix heading ("Appendix A: Supplementary Tables") -- a
real but non-chapter top-level heading. None of the eleven matches
introduction/abstract/conclusion (`select_envelope_nodes` returns `[]`), so
`compose_prompt` widens to the head-of-tree slice, which -- once the small
leading front-matter region is skipped -- carries every one of the eleven
headings well within the slice's own budget. tests/ingestion/
test_envelope_llm_toc_selection.py pins that the envelope's `toc` field must
reflect the MODEL's SELECTED subset of these headings (the real chapters),
never the raw structural dump of all eleven -- see that test's module
docstring for the full rationale.

Companion fixture -- structural_toc_paper.pdf / structural_toc_tree.json
(issue #227, structural toc derivation)
-----------------------------------------------------------------------
Another HAND-AUTHORED tree, not regenerated from the PDF via `axial
extract` (same rationale as router_prose_filter_paper_tree.json above): a
front-matter region (an untagged title-page block, an author line, a
copyright/ISBN block, publisher boilerplate, and a short "Contents" page
listing the source's three chapters) followed by three real top-level
chapter headings (`section_header`-labelled), each with real chapter body
prose. The front-matter region -- INCLUDING the "Contents" page, the
source's only chapter listing -- falls entirely inside
`_front_matter_region_end`'s skip and never reaches the envelope prompt
(verified directly: `compose_prompt` on this tree omits the "Contents:"
text and its "Halvorne-6 pagination ledger" marker). tests/ingestion/
test_envelope_structural_toc.py pins that the envelope's `toc` field must
still reflect the three real chapter headings -- derived structurally from
the tree, not from whatever the (stubbed) model returns -- even though the
only place those chapter titles were literally listed together (the TOC
page) never reaches the model.
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

FIXTURES_DIR = Path(__file__).resolve().parent

styles = getSampleStyleSheet()


def make_thesis_paper_pdf(path: Path) -> None:
    """A born-digital PDF with a real Introduction, a body section, and a
    real Conclusion -- the minimal shape the structural-envelope pass needs
    to find intro/abstract/conclusion nodes to summarize (PRD §5 stage 3).

    Deliberately has a stated thesis sentence in the Introduction and a
    restated argument in the Conclusion, so a real (non-stub) envelope pass
    would have genuine material to extract from -- this fixture is not
    envelope-pass-specific fakery, it is a normal short paper shape.
    """
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    # --- Introduction ---
    story.append(Paragraph("Introduction", styles["Heading1"]))
    story.append(
        Paragraph(
            "This paper argues that state capacity in post-conflict settings "
            "depends more on infrastructural reach than on coercive force "
            "alone. The remainder of the paper develops this thesis across "
            "a survey of comparative cases.",
            styles["BodyText"],
        )
    )
    story.append(
        Paragraph(
            "The scope of the argument is comparative, drawing on cases "
            "from the post-conflict statebuilding literature.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    # --- Body ---
    story.append(Paragraph("Comparative Cases", styles["Heading1"]))
    story.append(
        Paragraph(
            "Case material discussed here is illustrative only and is not "
            "itself part of the envelope this fixture exercises; the "
            "structural-envelope pass reads the introduction and conclusion, "
            "not this body section.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    # --- Conclusion ---
    story.append(Paragraph("Conclusion", styles["Heading1"]))
    story.append(
        Paragraph(
            "In sum, infrastructural power better explains durable "
            "post-conflict order than coercive capacity alone, restating "
            "the paper's stated thesis in light of the cases surveyed.",
            styles["BodyText"],
        )
    )

    doc.build(story)


def make_topic_titled_paper_pdf(path: Path) -> None:
    """A born-digital PDF whose top-level section headings are named by
    TOPIC only -- none matches introduction/abstract/conclusion -- carrying
    a distinctive, unguessable marker phrase in its first body paragraph
    (issue #201; see module docstring, "Companion fixture --
    topic_titled_paper.pdf")."""
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    # --- Section 1: topic-titled, no intro/abstract/conclusion heading ---
    story.append(Paragraph("Border Enforcement Regimes", styles["Heading1"]))
    story.append(
        Paragraph(
            "The Kestrel-7 checkpoint protocol reassigns border-crossing "
            "authority to a rotating tribunal of adjacent administrative "
            "zones, a threshold-lattice mechanism that no centralized "
            "customs regime elsewhere replicates. Officers rotate through "
            "the tribunal on a nine-day cycle tied to lunar tide tables "
            "rather than any fixed jurisdictional calendar.",
            styles["BodyText"],
        )
    )
    story.append(
        Paragraph(
            "This threshold-lattice mechanism is documented only at the "
            "Kestrel-7 site and nowhere else in the comparative literature "
            "on border administration.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    # --- Section 2: topic-titled ---
    story.append(Paragraph("Fiscal Extraction Networks", styles["Heading1"]))
    story.append(
        Paragraph(
            "Provincial tax farmers under this regime remit collected "
            "revenue not to a central treasury but to a rotating escrow "
            "held by the same tribunal described above, a practice with "
            "no analogue in classical fiscal sociology.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    # --- Section 3: topic-titled ---
    story.append(Paragraph("Digital Surveillance Architecture", styles["Heading1"]))
    story.append(
        Paragraph(
            "Automated toll gates log vehicle transponders into a "
            "distributed ledger maintained jointly by the tribunal and a "
            "regional customs union, closing the loop between enforcement "
            "and extraction.",
            styles["BodyText"],
        )
    )

    doc.build(story)


def make_router_prose_filter_paper_pdf(path: Path) -> None:
    """A born-digital PDF whose text loosely mirrors the HAND-AUTHORED
    router_prose_filter_paper_tree.json (issue #216; see module docstring,
    "Companion fixture -- router_prose_filter_paper.pdf"). This PDF is never
    actually extracted by docling in the test suite -- the hand-authored
    tree is pre-placed at data/trees/<source_id>.json instead -- so this
    function exists only to give the fixture a real, valid, text-bearing PDF
    for intake's text-layer probe to accept."""
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    story.append(Paragraph("Table of Contents", styles["Heading2"]))
    story.append(
        Paragraph(
            "I. Border Enforcement Regimes; II. Fiscal Extraction Networks; "
            "III. Digital Surveillance Architecture -- filed under the "
            "Quillfeather-19 index locus.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Border Enforcement Regimes", styles["Heading1"]))
    story.append(
        Paragraph(
            "The opening survey proceeds under the Draubourne-4 escrow "
            "directive, a framework negotiated among the border tribunals "
            "described below to standardize evidentiary intake before any "
            "enforcement action begins.",
            styles["BodyText"],
        )
    )
    story.append(
        Paragraph(
            "Analysts have not previously connected the Draubourne-4 "
            "escrow directive to the tribunal's broader mandate.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Fiscal Extraction Networks", styles["Heading1"]))
    story.append(
        Paragraph(
            "Provincial tax farmers under this regime remit collected "
            "revenue not to a central treasury but to a rotating escrow "
            "held by the same tribunal described above, a practice with "
            "no analogue in classical fiscal sociology.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Digital Surveillance Architecture", styles["Heading1"]))
    story.append(
        Paragraph(
            "Automated toll gates log vehicle transponders into a "
            "distributed ledger maintained jointly by the tribunal and a "
            "regional customs union, closing the loop between enforcement "
            "and extraction.",
            styles["BodyText"],
        )
    )

    doc.build(story)


def make_structural_toc_paper_pdf(path: Path) -> None:
    """A born-digital PDF whose text loosely mirrors the HAND-AUTHORED
    structural_toc_tree.json (issue #227; see
    tests/ingestion/test_envelope_structural_toc.py). Like
    router_prose_filter_paper.pdf, this PDF is never actually extracted by
    docling in the test suite -- the hand-authored tree is pre-placed at
    data/trees/<source_id>.json instead -- so this function exists only to
    give the fixture a real, valid, text-bearing PDF for intake's
    text-layer probe to accept and for compute_source_id to hash."""
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    story.append(Paragraph("The Architecture of Contentious Cycles", styles["Title"]))
    story.append(
        Paragraph("R. ASHWORTH VALE Correntine Institute for Comparative Studies", styles["Normal"])
    )
    story.append(Paragraph("Copyright (c) 1994 by Correntine Institute Press.", styles["Normal"]))
    story.append(
        Paragraph(
            "All rights reserved. No part of this book may be reproduced or "
            "transmitted in any form without permission.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Contents", styles["Heading2"]))
    story.append(
        Paragraph(
            "One, The Onset of Contention, page 3. Two, Escalation Dynamics, "
            "page 41. Three, Settlement and Aftermath, page 88.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Chapter One: The Onset of Contention", styles["Heading1"]))
    story.append(
        Paragraph(
            "Contentious episodes begin not with the loudest grievance but "
            "with the first instance in which previously isolated complaints "
            "are recognized by their bearers as instances of a shared "
            "condition.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Chapter Two: Escalation Dynamics", styles["Heading1"]))
    story.append(
        Paragraph(
            "Once a shared grievance is recognized, escalation follows a "
            "predictable sequence from informal gatherings to semi-formal "
            "assemblies.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Chapter Three: Settlement and Aftermath", styles["Heading1"]))
    story.append(
        Paragraph(
            "Every episode surveyed here eventually settles, whether through "
            "negotiated concession, exhaustion, or suppression.",
            styles["BodyText"],
        )
    )

    doc.build(story)


def make_llm_toc_selection_paper_pdf(path: Path) -> None:
    """A born-digital PDF whose text loosely mirrors the HAND-AUTHORED
    llm_toc_selection_tree.json (issue #231; see
    tests/ingestion/test_envelope_llm_toc_selection.py). Like
    router_prose_filter_paper.pdf and structural_toc_paper.pdf, this PDF is
    never actually extracted by docling in the test suite -- the
    hand-authored tree is pre-placed at data/trees/<source_id>.json instead
    -- so this function exists only to give the fixture a real, valid,
    text-bearing PDF for intake's text-layer probe to accept and for
    compute_source_id to hash."""
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    story.append(Paragraph("The Grammar of Escalation", styles["Title"]))
    story.append(
        Paragraph(
            "A. MERIDIAN THORNE Cross-Basin Institute for Comparative Governance", styles["Normal"]
        )
    )
    story.append(Paragraph("Copyright (c) 1998 by Cross-Basin Institute Press.", styles["Normal"]))
    story.append(
        Paragraph(
            "All rights reserved. No part of this book may be reproduced or "
            "transmitted in any form without permission.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Chapter One: The Onset of Contention", styles["Heading1"]))
    story.append(
        Paragraph(
            "Contentious episodes begin not with the loudest grievance but "
            "with the first instance in which previously isolated complaints "
            "are recognized by their bearers as instances of a shared "
            "condition.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("1.1 Grievance Recognition and Framing", styles["Heading2"]))
    story.append(
        Paragraph(
            "A brief methodological note on how grievances are coded for this study.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("lalrodac:lioo", styles["Heading2"]))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Chapter Two: Escalation Dynamics", styles["Heading1"]))
    story.append(
        Paragraph(
            "Once a shared grievance is recognized, escalation follows a "
            "predictable sequence from informal gatherings to semi-formal "
            "assemblies.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("2.1 Informal Gatherings to Semi-Formal Assemblies", styles["Heading2"]))
    story.append(
        Paragraph(
            "A short note distinguishing informal gatherings from semi-formal "
            "assemblies for coding purposes.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("A successful program does all of them at once.", styles["Heading2"]))
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Chapter Three: Settlement and Aftermath", styles["Heading1"]))
    story.append(
        Paragraph(
            "Every episode surveyed here eventually settles, whether through "
            "negotiated concession, exhaustion, or suppression.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("3.1 Negotiated Concession Pathways", styles["Heading2"]))
    story.append(
        Paragraph(
            "A brief typology of concession pathways observed across the surveyed episodes.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Chapter Four: Comparative Synthesis", styles["Heading1"]))
    story.append(
        Paragraph(
            "Drawing the three preceding chapters together, this closing "
            "chapter compares the onset, escalation, and settlement patterns "
            "across every episode surveyed.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("4.1 Cross-Case Convergence Patterns", styles["Heading2"]))
    story.append(
        Paragraph(
            "A short note on the convergence measure used to compare cases in this section.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.15 * inch))

    story.append(Paragraph("Appendix A: Supplementary Tables", styles["Heading2"]))
    story.append(
        Paragraph(
            "Supplementary tabulations referenced in the preceding chapters "
            "are collected here for reference.",
            styles["BodyText"],
        )
    )

    doc.build(story)


def main() -> None:
    make_thesis_paper_pdf(FIXTURES_DIR / "thesis_paper.pdf")
    make_topic_titled_paper_pdf(FIXTURES_DIR / "topic_titled_paper.pdf")
    make_router_prose_filter_paper_pdf(FIXTURES_DIR / "router_prose_filter_paper.pdf")
    make_structural_toc_paper_pdf(FIXTURES_DIR / "structural_toc_paper.pdf")
    make_llm_toc_selection_paper_pdf(FIXTURES_DIR / "llm_toc_selection_paper.pdf")
    print("Generated fixtures in", FIXTURES_DIR)


if __name__ == "__main__":
    main()
