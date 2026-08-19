"""Issue #787 slice 05, the two prompt seams: `compose_draft_prompt` and
`compose_abstract_prompt` carry the domain frame's house style as context
when the frame declares one, and compose byte-identical prompts when it does
not.

**The byte-identity half is the point of the file.** Four slices' worth of
measured prompt behaviour sits behind those two prompts -- slice 01's
counter-position instruction, slice 02's word budget, slice 04's abstract,
and a paid measurement over ten real papers -- so the goldens under
`tests/paper/golden/` were composed from `main` at 5a34d45, the commit this
slice branched from, and are compared byte for byte. A diff there is a
failure of the change, never a golden to update.

**Why one golden per prompt covers every branch, rather than four.** The seam
is a single f-string interpolation of `prompt_block(house_style)`, which
returns `""` for nothing -- so byte-identity on one role/word-budget
combination implies it on all of them. A parametrised test over the role x
word-budget matrix stood here until it was noticed that it compared an
explicit `house_style=None` against an omitted argument whose default IS
`None`: the two calls were identical by construction and the assertion could
not fail, whatever the seam did. It was deleted rather than expanded, because
four more goldens would buy what the interpolation already guarantees.

The goldens are read with `Path.read_text`, whose universal-newline
translation returns LF on this repo's `core.autocrlf: true` checkout as well
as on CI's Linux runner, so the comparison is against the bytes that were
composed rather than against whatever git handed the working tree.
"""

from __future__ import annotations

from pathlib import Path

from axial.paper.abstract import compose_abstract_prompt
from axial.paper.draft import compose_draft_prompt
from axial.paper.house_style import HouseStyle
from axial.paper.lens import Lens
from axial.paper.plan import Section

GOLDEN_DIR = Path(__file__).parent / "golden"

# The exact inputs the goldens were composed from, on 5a34d45.
LENS = Lens(name="political-economy", description="Reads for who pays and who decides.")
THESIS = "Control over the material foundations of rule explains the outcome."
SECTION = Section(
    section_id="s3",
    heading="Rent dependence",
    role="claim",
    assigned_claims=(("fd0c2636d456d0fc", "71ccf81d2b99bad6"),),
)
SECTION_CLAIMS = "- [pc-001] (a) Rent dependence loosened the bargain."
EARLIER_CLAIMS = "(no earlier section has cited a claim)"
ABSTRACT_SECTIONS = [
    {"heading": "The mechanism", "prose": "Rent dependence loosened the bargain [pc-001]."},
    {"heading": "The case against", "prose": "The institutionalist account reads it otherwise."},
]

STYLE = HouseStyle(
    conventions=(
        "Hold one register from the first sentence to the last.",
        "Open with the point, not with an announcement of what is about to be argued.",
    )
)


def _golden(name: str) -> str:
    return (GOLDEN_DIR / f"{name}_prompt_5a34d45.txt").read_text(encoding="utf-8")


def _draft_prompt(house_style: HouseStyle | None) -> str:
    return compose_draft_prompt(
        THESIS,
        LENS,
        SECTION,
        SECTION_CLAIMS,
        EARLIER_CLAIMS,
        house_style=house_style,
    )


# ---------------------------------------------------------------------------
# No house style: both prompts are exactly what they are on 5a34d45.
# ---------------------------------------------------------------------------


def test_a_draft_prompt_with_no_house_style_is_byte_identical_to_main():
    assert _draft_prompt(None) == _golden("draft")


def test_an_abstract_prompt_with_no_house_style_is_byte_identical_to_main():
    assert compose_abstract_prompt(THESIS, ABSTRACT_SECTIONS, house_style=None) == _golden(
        "abstract"
    )


def test_omitting_the_argument_entirely_composes_the_same_two_prompts():
    assert compose_draft_prompt(THESIS, LENS, SECTION, SECTION_CLAIMS, EARLIER_CLAIMS) == _golden(
        "draft"
    )
    assert compose_abstract_prompt(THESIS, ABSTRACT_SECTIONS) == _golden("abstract")


# ---------------------------------------------------------------------------
# A declared house style: the same block, verbatim, in both prompts.
# ---------------------------------------------------------------------------


def test_the_draft_prompt_carries_every_declared_convention():
    prompt = _draft_prompt(STYLE)
    for convention in STYLE.conventions:
        assert convention in prompt


def test_the_abstract_prompt_carries_the_same_block_on_the_same_terms():
    block = STYLE.for_prompt()
    assert block in _draft_prompt(STYLE)
    assert block in compose_abstract_prompt(THESIS, ABSTRACT_SECTIONS, house_style=STYLE)


def test_the_block_appears_once_in_each_prompt():
    block = STYLE.for_prompt()
    assert _draft_prompt(STYLE).count(block) == 1
    assert compose_abstract_prompt(THESIS, ABSTRACT_SECTIONS, house_style=STYLE).count(block) == 1


def test_a_declared_house_style_adds_only_the_block():
    """What the drafter is told about house style is the block and nothing
    else: cut the block back out and every byte of the 5a34d45 prompt is
    still there, in order."""
    inserted = STYLE.for_prompt() + "\n\n"

    head, _, tail = _draft_prompt(STYLE).partition(inserted)
    assert head + tail == _golden("draft")

    abstract = compose_abstract_prompt(THESIS, ABSTRACT_SECTIONS, house_style=STYLE)
    head, _, tail = abstract.partition(inserted)
    assert head + tail == _golden("abstract")
