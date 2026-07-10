"""Generator for tests/fixtures/artifacts/* binary fixtures.

Ephemeral-toolchain script -- NOT a test-time dependency. Run with:

    uv run --with reportlab python tests/fixtures/artifacts/_generate.py

Regenerates the committed fixture binary in this directory. The test suite
(tests/test_artifacts_resume.py) depends only on the committed binary and
never invokes this script.

Companion fixture -- multi_artifact_tree.json
-----------------------------------------------------------------------
tests/fixtures/artifacts/multi_artifact_tree.json is the REAL persisted
structural tree `axial extract` produces for multi_artifact.pdf, committed so
tests/test_artifacts_resume.py can pre-place it at
data/trees/<source_id>.json (source_id via axial.envelope.compute_source_id)
instead of paying for a real docling run. This mirrors
tests/fixtures/extract/prose_and_table_tree.json's own regeneration recipe
(see tests/fixtures/extract/_generate.py) exactly, just for a fixture with
SEVERAL artifact nodes instead of one -- needed so an artifact-checkpoint
resume test has a genuine "some classified, some not" split to exercise.
Regenerate it after any change to multi_artifact.pdf or to the
extraction/normalization logic with:

    rm -f data/trees/*.json  # ensure a fresh, non-cached extraction
    uv run axial extract tests/fixtures/artifacts/multi_artifact.pdf > /dev/null
    cp data/trees/multi_artifact-*.json tests/fixtures/artifacts/multi_artifact_tree.json
    rm -f data/trees/*.json  # don't leave scratch state behind

Verify the regenerated fixture matches a second fresh extraction (determinism
check) before committing:

    rm -f data/trees/*.json
    uv run axial extract tests/fixtures/artifacts/multi_artifact.pdf > /tmp/fresh.json
    diff <(python -m json.tool tests/fixtures/artifacts/multi_artifact_tree.json) <(python -m json.tool /tmp/fresh.json)
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


def _make_table(rows: list[list[str]]) -> Table:
    table = Table(rows, colWidths=[1.8 * inch, 1.2 * inch, 1.8 * inch])
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
    return table


def make_multi_artifact_pdf(path: Path) -> None:
    """A born-digital PDF with a single prose section ("Findings") followed
    by FOUR distinct, unmistakable bordered-grid tables, each separated by a
    short paragraph of real body text so a structural parser reliably
    detects each as its own, separate non-text artifact node rather than
    merging them into one -- exactly the "several artifact nodes" shape
    issue #98's checkpoint/resume contract needs (a single-artifact fixture,
    like tests/fixtures/extract/prose_and_table.pdf, cannot exercise a
    partial "some classified, some not" split)."""
    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
    )

    story = []

    story.append(Paragraph("Findings", styles["Heading1"]))
    story.append(
        Paragraph(
            "This document is a fixture for testing per-artifact checkpoint "
            "and resume behavior. It contains four small, unrelated data "
            "tables, each preceded by a short paragraph of prose.",
            styles["BodyText"],
        )
    )

    case_tables = [
        [["Case", "Year", "Outcome"], ["Alpha", "1990", "Consolidated"]],
        [["Case", "Year", "Outcome"], ["Beta", "2001", "Fragmented"]],
        [["Case", "Year", "Outcome"], ["Gamma", "2015", "Consolidated"]],
        [["Case", "Year", "Outcome"], ["Delta", "2022", "Fragmented"]],
    ]
    labels = ("first", "second", "third", "fourth")

    for label, rows in zip(labels, case_tables):
        story.append(Spacer(1, 0.2 * inch))
        story.append(
            Paragraph(
                f"The {label} table below reports one illustrative case.",
                styles["BodyText"],
            )
        )
        story.append(Spacer(1, 0.1 * inch))
        story.append(_make_table(rows))

    doc.build(story)


def main() -> None:
    make_multi_artifact_pdf(FIXTURES_DIR / "multi_artifact.pdf")
    print("Generated fixtures in", FIXTURES_DIR)


if __name__ == "__main__":
    main()
