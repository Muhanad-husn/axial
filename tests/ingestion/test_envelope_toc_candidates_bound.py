"""Outer acceptance test for issue #232 (envelope toc-candidate block must be
BOUNDED, with a truncation note, on a pathological tree -- while staying
untruncated on any real-scale tree at or below the corpus ceiling).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source's structural tree yields a POST-front-matter-region heading
      list (`axial.envelope._toc_candidates_for_prompt`, #231) that
      `compose_prompt` appends to the envelope prompt as an explicit
      candidate-heading block (`_TOC_CANDIDATES_BLOCK`)
When  that heading list is PATHOLOGICALLY large -- far beyond anything a
      real, once-per-source extraction tree produces (measured ceiling
      across the 31 cached `data/trees/*.json` sources: max 260 headings /
      8328 characters)
Then  the candidate block `compose_prompt` emits must be BOUNDED (both in
      heading count and in character length) by a stated module tunable,
      and the prompt must carry an explicit, human-readable note that the
      candidate list was truncated -- never a silent cut
And, conversely,
When  that heading list sits at a REAL-SCALE size, at or below the measured
      corpus ceiling (this test uses exactly that ceiling, 260 headings)
Then  every single one of those headings -- INCLUDING the final, latest-
      ordered one -- must survive into the candidate block VERBATIM, and no
      truncation note may appear: the bound is a pathological-input safety
      rail set ABOVE the real-corpus ceiling, never a routine trimmer.

See specs/PRODUCT.md §7.3 ("Structural envelope") and §5 stage 3. Issue
#231 (already shipped, tests/ingestion/test_envelope_llm_toc_selection.py)
established that the model's final `toc` answer is reconciled against the
tree's own FULL, unfiltered `structural_toc` (`axial.envelope._resolve_toc`)
-- the model can only ever narrow real headings it was actually shown, never
invent one. That is exactly why an unbounded PROMPT candidate list is a real
defect, not merely an aesthetic one: if a genuine late-ordered chapter were
silently cut from the prompt's candidate presentation, the model could never
name it, and `_resolve_toc`'s own intersection-narrowing would then drop
that real chapter from the final envelope `toc` -- a correctness bug wearing
the shape of a purely cosmetic bound. This test therefore does NOT assert
truncation happens on ordinary, real-scale input (that would encode exactly
the wrong behavior) -- it asserts the opposite: real-scale input must reach
the model whole, and only a pathological outlier ever gets bounded, with an
explicit note rather than a silent cut.

The bug (PRD-relevant gap, not yet fixed)
-----------------------------------------------------------------------
Today `_TOC_CANDIDATES_BLOCK`'s heading list is populated straight from
`_toc_candidates_for_prompt(tree)` with no size cap at all -- confirmed by
measurement across every cached `data/trees/*.json` tree (max observed: 260
headings / 8328 chars) -- already larger than this module's OTHER bounded
prose slice (`_HEAD_OF_TREE_SLICE_CHARS`, 6000). Every other evidence input
`compose_prompt` assembles is an explicitly bounded, stated tunable; this
one alone is not.

The fix this test locks in (for the implementer, not built here)
-----------------------------------------------------------------------
A new bounded tunable, `axial.envelope._TOC_CANDIDATES_MAX`, caps how many
candidate headings the block may ever carry, with TRUNCATION-WITH-NOTE
(never a silent hard cut) when a tree's candidate list exceeds it. This test
references that constant BY NAME (`getattr`/attribute access, not a
hardcoded literal), so it tracks whatever value the implementer proves in,
and fails with a clean, legible `AttributeError`-shaped message today,
before the constant exists.

Seam decision -- drive `compose_prompt(tree)` directly, with in-fixture
synthetic trees (DEC-23)
-----------------------------------------------------------------------
Same public seam as every other envelope acceptance test in this suite
(`test_envelope_frontmatter_region_skip.py`,
`test_envelope_structural_toc.py`, `test_envelope_llm_toc_selection.py`):
`compose_prompt` is the pure, synchronous function whose return value is
exactly what lands in the real prompt, so asserting on it pins the real
observable behavior with no LLM call and no filesystem/`data/` state.
Both trees this test builds are synthesized directly in Python (a flat list
of `section_header` children with distinctive, numbered synthetic heading
text) rather than loaded from a fixture file or any real book excerpt
(DEC-23) -- a pathological 1000-heading tree has no sensible hand-authored
fixture-file precedent anyway.

Seam decision -- isolating the CANDIDATE BLOCK from the rest of the prompt
-----------------------------------------------------------------------
`compose_prompt`'s OTHER evidence path (the head-of-tree widen,
`_head_of_tree_lines`) ALSO walks a heading-only tree's `section_header`
children as ordinary PROSE lines (§7.8: `section_header` routes to PROSE)
and is independently bounded by `_HEAD_OF_TREE_SLICE_CHARS` -- so counting
"how many synthetic headings appear anywhere in the full prompt" would be
contaminated by that unrelated, already-bounded evidence slice, letting a
still-unbounded candidate block hide behind the OTHER bound's own trimming.
Every assertion below therefore isolates the region of the prompt BEFORE the
literal `"Sections:\n\n"` marker (`_PROMPT_TEMPLATE`: `{toc_guidance}Sections:
\n\n{sections}`) -- the toc-candidates block plus fixed instruction prose,
never the evidence section -- and counts/searches only within that region.

Test hygiene: pure `compose_prompt(tree)` calls over in-fixture synthetic
trees, no filesystem writes, no `data/` state, no LLM client, no
subprocess.
"""

from __future__ import annotations

import axial.envelope as envelope_module
from axial.envelope import compose_prompt

# The measured real-corpus ceiling (module docstring / issue #232 report):
# the largest candidate-heading list observed across all 31 cached
# `data/trees/*.json` sources was 260 headings / 8328 characters. Used
# directly as this test's REAL-SCALE heading count -- not a toy number, the
# actual documented ceiling itself.
REAL_SCALE_HEADING_COUNT = 260

# Far beyond anything a real, once-per-source extraction tree produces --
# nearly 4x the measured real-corpus ceiling above.
PATHOLOGICAL_HEADING_COUNT = 1000

# The literal boundary `_PROMPT_TEMPLATE` places between the (optional)
# toc-candidates block and the evidence section (`{toc_guidance}Sections:
# \n\n{sections}`) -- splitting on this isolates the candidates region from
# the unrelated, independently-bounded head-of-tree evidence slice (module
# docstring, "isolating the CANDIDATE BLOCK").
_SECTIONS_MARKER = "Sections:\n\n"

# A human-legible marker: any implementer's truncation note is expected to
# use some form of the word "truncat(ed/ion)" -- checked case-insensitively,
# never tied to one exact sentence, since the implementer chooses the note's
# precise wording.
_TRUNCATION_WORD = "truncat"


def _make_heading_tree(headings: list[str]) -> dict:
    """A minimal synthetic extraction tree: a flat list of top-level
    `section_header` children carrying only the given heading texts, no
    front matter and no matched intro/abstract/conclusion section -- the
    exact flattened shape a real book's docling extraction produces (issue
    #231's own module docstring: "70-260 entries... flattened to the same
    nesting depth"). No real book text anywhere (DEC-23)."""
    return {"children": [{"label": "section_header", "text": heading} for heading in headings]}


def _pathological_headings() -> list[str]:
    """`PATHOLOGICAL_HEADING_COUNT` distinct, zero-padded synthetic
    headings -- no heading's text is ever a substring of another's (fixed
    4-digit zero-padding with nothing appended after the number), so a
    literal-substring presence check against any of them is unambiguous."""
    return [f"Pathological Filler Heading {i:04d}" for i in range(PATHOLOGICAL_HEADING_COUNT)]


def _real_scale_headings() -> list[str]:
    """`REAL_SCALE_HEADING_COUNT` distinct, zero-padded synthetic headings,
    mirroring the measured real-corpus ceiling exactly -- the LAST one
    carries a distinctive marker standing in for "a genuine late-ordered
    chapter" (the concrete case #232's fix must never drop from the prompt
    candidate presentation, per this module's own docstring on why an
    unbounded-vs-silently-cut distinction matters for `_resolve_toc`'s
    downstream narrowing)."""
    headings = [
        f"Chapter {i:03d}: Real-Scale Heading Marker" for i in range(1, REAL_SCALE_HEADING_COUNT)
    ]
    headings.append(LATE_CHAPTER_MARKER)
    return headings


LATE_CHAPTER_MARKER = "Chapter 260: Final Late Chapter -- The Vermillion Accord"


def _candidates_region(prompt: str) -> str:
    """The portion of `compose_prompt`'s return value BEFORE the literal
    `"Sections:\\n\\n"` marker -- the toc-candidates block plus fixed
    instruction prose, isolated from the independently-bounded head-of-tree
    evidence section that follows it (module docstring, "isolating the
    CANDIDATE BLOCK")."""
    before, separator, _after = prompt.partition(_SECTIONS_MARKER)
    assert separator, (
        f"expected compose_prompt's output to contain the literal "
        f"{_SECTIONS_MARKER!r} marker from `_PROMPT_TEMPLATE` -- its "
        f"absence means the prompt template itself changed shape in a way "
        f"this test's region-isolation no longer accounts for.\n"
        f"Full prompt:\n{prompt}"
    )
    return before


def test_pathological_tree_candidate_block_is_bounded_with_a_truncation_note():
    """The core defect this issue fixes: a pathological, far-beyond-real-
    scale heading list must be BOUNDED in the candidate block `compose_
    prompt` emits, and the prompt must carry an explicit truncation note --
    never a silent cut."""
    tree = _make_heading_tree(_pathological_headings())
    prompt = compose_prompt(tree)
    region = _candidates_region(prompt)

    # --- the bound itself must exist as a named module tunable (referenced
    # by name, not a hardcoded literal, so this test tracks whatever value
    # the implementer proves in) ---
    bound = getattr(envelope_module, "_TOC_CANDIDATES_MAX", None)
    assert bound is not None, (
        "expected axial.envelope to define a bounded toc-candidates tunable "
        "named `_TOC_CANDIDATES_MAX` (issue #232) -- it does not exist yet, "
        "which is exactly the defect this test locks in: today's "
        "`_TOC_CANDIDATES_BLOCK` heading list has NO size cap at all."
    )

    headings = _pathological_headings()
    present_count = sum(1 for heading in headings if heading in region)

    assert present_count <= bound, (
        f"expected the candidate-heading block to carry at most "
        f"`_TOC_CANDIDATES_MAX` ({bound}) headings for a pathological, "
        f"{PATHOLOGICAL_HEADING_COUNT}-heading tree, but {present_count} "
        f"of them appeared in the candidates region of the prompt -- the "
        f"block is not actually bounded by the stated tunable.\n"
        f"Candidates region:\n{region}"
    )
    assert present_count < len(headings), (
        f"expected the pathological tree's {len(headings)}-heading list to "
        f"be genuinely TRUNCATED in the candidate block (not merely "
        f"'happen to fit under the bound'), but all {present_count} "
        f"headings were present -- this fixture no longer exercises real "
        f"truncation.\nCandidates region:\n{region}"
    )

    assert _TRUNCATION_WORD in prompt.lower(), (
        f"expected the composed prompt to carry an explicit, human-"
        f"readable truncation note (some form of {_TRUNCATION_WORD!r}) "
        f"once the candidate-heading list is cut for exceeding "
        f"`_TOC_CANDIDATES_MAX` -- PRD-relevant gap #232 requires "
        f"truncation-WITH-NOTE, never a silent cut, so the model is told "
        f"its candidate list is incomplete rather than being left to "
        f"assume it is exhaustive.\nFull prompt:\n{prompt}"
    )


def test_real_scale_tree_is_never_truncated_and_keeps_its_latest_chapter():
    """The converse guarantee: a REAL-SCALE heading list -- this test uses
    the measured real-corpus ceiling itself, 260 headings -- must survive
    into the candidate block WHOLE, with no truncation note, and in
    particular its final, latest-ordered heading (standing in for a genuine
    late chapter) must be present verbatim. The bound is a pathological-
    input safety rail set ABOVE the real-corpus ceiling, never a routine
    trimmer that could cost a real source its own last chapter."""
    headings = _real_scale_headings()
    tree = _make_heading_tree(headings)
    prompt = compose_prompt(tree)
    region = _candidates_region(prompt)

    missing = [heading for heading in headings if heading not in region]
    assert not missing, (
        f"expected EVERY one of this real-scale ({len(headings)}-heading, "
        f"matching the measured real-corpus ceiling) tree's headings to "
        f"survive into the candidate block verbatim -- the bound must "
        f"never engage on real-scale input, only on a pathological "
        f"outlier far beyond it. {len(missing)} heading(s) were missing: "
        f"{missing!r}\nCandidates region:\n{region}"
    )

    assert LATE_CHAPTER_MARKER in region, (
        f"expected the fixture's final, latest-ordered heading "
        f"({LATE_CHAPTER_MARKER!r}, standing in for a genuine late "
        f"chapter) to appear verbatim in the candidate block -- if a real "
        f"chapter this late in a source were silently dropped from the "
        f"prompt's candidate presentation, the model could never name it, "
        f"and #231's own `_resolve_toc` intersection-narrowing would then "
        f"drop that real chapter from the final envelope `toc` entirely "
        f"(module docstring). Its absence here is exactly that failure "
        f"mode.\nCandidates region:\n{region}"
    )

    assert _TRUNCATION_WORD not in prompt.lower(), (
        f"expected NO truncation note anywhere in the composed prompt for "
        f"this real-scale ({len(headings)}-heading) tree -- a truncation "
        f"note's presence here would mean the bound is engaging on "
        f"ordinary, real-scale input rather than only on a pathological "
        f"outlier, exactly the routine-trimmer behavior this issue's "
        f"design explicitly rules out.\nFull prompt:\n{prompt}"
    )

    bound = getattr(envelope_module, "_TOC_CANDIDATES_MAX", None)
    assert bound is not None, (
        "expected axial.envelope to define `_TOC_CANDIDATES_MAX` (issue "
        "#232) -- see test_pathological_tree_candidate_block_is_bounded_"
        "with_a_truncation_note above for the primary assertion of its "
        "existence; this test additionally requires it be set ABOVE the "
        "measured real-corpus ceiling used here."
    )
    assert REAL_SCALE_HEADING_COUNT < bound, (
        f"expected `_TOC_CANDIDATES_MAX` ({bound}) to sit ABOVE the "
        f"measured real-corpus ceiling ({REAL_SCALE_HEADING_COUNT} "
        f"headings) -- the bound is a pathological-input safety rail set "
        f"above the real ceiling, not a routine trimmer that could ever "
        f"engage on genuine corpus-scale input."
    )


def test_no_candidate_block_is_emitted_when_the_tree_has_no_headings():
    """#231's own contract, unweakened: `compose_prompt` appends the
    candidate-heading block ONLY when the tree yields a non-empty
    post-front-matter heading list. A tree with no `section_header`
    children at all -- just ordinary body prose -- must produce a prompt
    with no candidate-block preamble whatsoever, regardless of the new
    bound. This guards against a bounding implementation that accidentally
    always emits SOME block (even an empty one, or a bare truncation note
    with zero headings) on a tree that should omit the block entirely."""
    tree = {
        "children": [
            {
                "label": "text",
                "text": (
                    "This source has no section_header children at all, only "
                    "ordinary body prose, spread across enough characters to "
                    "be a realistic paragraph rather than a token fragment."
                ),
            }
        ]
    }
    prompt = compose_prompt(tree)

    assert "Candidate top-level headings" not in prompt, (
        "expected compose_prompt to omit the toc-candidates block entirely "
        "(#231: appended only when the tree yields a non-empty "
        "post-front-matter structural heading list) for a tree with no "
        "section_header children at all, but the block's own header text "
        f"was present.\nFull prompt:\n{prompt}"
    )
    assert _TRUNCATION_WORD not in prompt.lower(), (
        "expected no truncation note either, since there is no candidate "
        f"block to truncate at all.\nFull prompt:\n{prompt}"
    )
