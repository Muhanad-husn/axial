"""Generator for tests/fixtures/envelope/* binary fixtures.

Ephemeral-toolchain script -- NOT a test-time dependency. Run with:

    uv run --with reportlab python tests/fixtures/envelope/_generate.py

Regenerates the committed fixture binary in this directory. The test suite
(tests/test_envelope.py) depends only on the committed binary and never
invokes this script.
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


def main() -> None:
    make_thesis_paper_pdf(FIXTURES_DIR / "thesis_paper.pdf")
    print("Generated fixtures in", FIXTURES_DIR)


if __name__ == "__main__":
    main()
