"""Generator for tests/fixtures/extract/* binary fixtures.

Ephemeral-toolchain script -- NOT a test-time dependency. Run with:

    uv run --with reportlab python tests/fixtures/extract/_generate.py

Regenerates the committed fixture binary in this directory. The test suite
(tests/test_extract.py) depends only on the committed binary and never
invokes this script.

Companion fixture -- prose_and_table_tree.json (issue #45, tree-cache)
-----------------------------------------------------------------------
tests/fixtures/extract/prose_and_table_tree.json is the REAL persisted
structural tree `axial extract` produces for prose_and_table.pdf, committed
so downstream tests that only CONSUME the tree (tests/test_artifacts.py,
tests/test_xref.py) can pre-place it at data/trees/<source_id>.json (source_id
via axial.envelope.compute_source_id) instead of paying for a real docling
run just to obtain input they never assert on. This is not a mystery blob: it
is exactly `axial extract`'s own stdout for this fixture, and it must stay
byte-identical to what a fresh extraction produces, since axial.extract.extract
reuses a persisted tree verbatim (PRD §7.4) -- a stale/hand-edited fixture
here would silently diverge from real behavior. Regenerate it after any
change to prose_and_table.pdf or to the extraction/normalization logic with:

    rm -f data/trees/*.json  # ensure a fresh, non-cached extraction
    uv run axial extract tests/fixtures/extract/prose_and_table.pdf > /dev/null
    cp data/trees/prose_and_table-*.json tests/fixtures/extract/prose_and_table_tree.json
    rm -f data/trees/*.json  # don't leave scratch state behind

Verify the regenerated fixture matches a second fresh extraction (determinism
check) before committing:

    rm -f data/trees/*.json
    uv run axial extract tests/fixtures/extract/prose_and_table.pdf > /tmp/fresh.json
    diff <(python -m json.tool tests/fixtures/extract/prose_and_table_tree.json) <(python -m json.tool /tmp/fresh.json)
    rm -f data/trees/*.json
"""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FIXTURES_DIR = Path(__file__).resolve().parent

styles = getSampleStyleSheet()


def make_prose_and_table_pdf(path: Path) -> None:
    """A born-digital PDF with two prose sections and one bordered grid table.

    Section 1 ("Introduction") and Section 2 ("Discussion") are each a
    heading followed by multiple paragraphs of real, extractable body text.
    Between them sits an unmistakable bordered grid table (header row +
    data cells, full GRID box) so a structural parser reliably detects it
    as a distinct, non-text artifact rather than more prose.
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

    # --- Section 1: prose ---
    story.append(Paragraph("Introduction", styles["Heading1"]))
    story.append(
        Paragraph(
            "This document is a fixture for testing structural extraction. "
            "It contains ordinary prose describing a simple argument about "
            "state formation, followed by a table of illustrative data.",
            styles["BodyText"],
        )
    )
    story.append(
        Paragraph(
            "The argument proceeds in two stages: first a claim is stated, "
            "then supporting evidence is presented in tabular form below.",
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 0.25 * inch))

    # --- Table: unmistakable bordered grid artifact ---
    table_data = [
        ["Case", "Year", "Outcome"],
        ["Alpha", "1990", "Consolidated"],
        ["Beta", "2001", "Fragmented"],
        ["Gamma", "2015", "Consolidated"],
    ]
    table = Table(table_data, colWidths=[1.8 * inch, 1.2 * inch, 1.8 * inch])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.25 * inch))

    # --- Section 2: prose ---
    story.append(Paragraph("Discussion", styles["Heading1"]))
    story.append(
        Paragraph(
            "The table above illustrates three cases with divergent "
            "outcomes despite similar starting conditions, motivating the "
            "comparative discussion that follows.",
            styles["BodyText"],
        )
    )
    story.append(
        Paragraph(
            "A second paragraph of discussion prose closes out this "
            "section, giving the fixture at least two paragraphs per "
            "prose section as required by the acceptance test.",
            styles["BodyText"],
        )
    )

    doc.build(story)


def main() -> None:
    make_prose_and_table_pdf(FIXTURES_DIR / "prose_and_table.pdf")
    print("Generated fixtures in", FIXTURES_DIR)


if __name__ == "__main__":
    main()
