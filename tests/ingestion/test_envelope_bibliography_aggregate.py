"""Outer acceptance test for issue #222 (envelope bibliography-by-aggregate
exclusion + head-of-tree front-matter prefix skip).

Locked behavioral contract (DEC-1) -- do not edit once committed red.

Given a source whose matched "Conclusion" section's descendants are
      overwhelmingly single-citation / bibliographic leaf nodes (docling
      mis-attaching a bibliography under a body-section heading, the Tilly
      defect, #222) -- a citation wall that clears the character-count
      evidence floor on raw length alone -- AND whose head-of-tree carries a
      leading front-matter / apparatus prefix (title page, copyright/ISBN,
      publisher boilerplate) ahead of its first genuinely substantive body
      prose
When  `compose_prompt(tree)` assembles the envelope evidence
Then  the citation wall is excluded from the matched-section evidence before
      the evidence-floor check (an aggregate signal across the section's
      descendants, not per-block density), so the pass widens to the
      head-of-tree slice
And   that widened slice skips the leading front-matter prefix and begins at
      the first genuinely substantive body prose, so the assembled evidence
      carries real argument prose instead of either the bibliography or the
      boilerplate
And   a normally-sectioned source -- whose matched Introduction/Conclusion
      merely cite sources in passing, inside full argument sentences, not as
      bare citation entries -- is unaffected: its evidence is unchanged.

See specs/PRODUCT.md §7.3 ("Bibliography-by-aggregate exclusion" and the
amended "Evidence floor on the input") and §8 P0-3's two matching
acceptance criteria for the source of truth:

  "A matched intro / abstract / conclusion section whose descendants are
  overwhelmingly single-citation / bibliographic leaves is detected by an
  aggregate citation signal across the section's descendants (not
  per-block density, §7.8) and excluded from the matched-section evidence
  before the evidence-floor check, so the pass widens to the head-of-tree
  slice and carries substantive body prose instead of the bibliography
  (§7.3, #222). ... Observable: given a tree whose matched intro /
  conclusion section is overwhelmingly single-citation bibliographic
  leaves ..., the assembled envelope evidence excludes that section and
  carries substantive body prose instead; given a normally-sectioned
  born-digital source, the assembled envelope evidence is unchanged."

  "The head-of-tree widening slice proceeds in tree order but skips a
  leading front-matter / apparatus prefix (title page, copyright / ISBN,
  preface boilerplate) and begins at the first genuinely substantive body
  prose ..."

Seam decision 1 -- asserting directly on `compose_prompt(tree) -> str`, not
via a subprocess/CLI/LLM round trip
-----------------------------------------------------------------------
`compose_prompt` is a pure, synchronous function of a structural tree: it
makes no LLM call and touches no filesystem state beyond the in-memory
`dict` it is handed. It is the exact seam the envelope pass hands to the
model (`run_envelope` calls it directly and passes its return value
straight into the prompt template's `{sections}` slot), so asserting on its
return value pins the real observable behavior without needing the
`stub`/`record` LLM-provider subprocess harness the other envelope
acceptance tests use for a different reason (proving what a live CLI
invocation records). This test is fully deterministic and requires no
network, no docling run, and no `data/` state.

Seam decision 2 -- the bibliography fixture models the STRUCTURE of the
Tilly defect only, with wholly synthetic content (copyright constraint)
-----------------------------------------------------------------------
`tests/fixtures/envelope/bibliography_aggregate_tree.json` is a
HAND-AUTHORED tree, not a committed real docling extraction and NOT any
excerpt of `data/trees/tilly-from-mobilization-to-revolution-*.json`
(gitignored; book prose must never be committed, DEC-23). It reproduces the
shape observed on that source:
  - A leading front-matter prefix -- a `title`-labeled title-page line, then
    two `text`-labeled blocks (a copyright/ISBN line, then publisher
    boilerplate) -- all PROSE-routed by §7.8 (`title`/`text` are both prose
    labels), so the point genuinely is "this is real, PROSE-routed content
    that happens to be non-substantive front matter", not "the router drops
    it". A distinctive marker, "Quillbrook Fictional Press", and the literal
    ISBN string, sit only in this prefix.
  - A body section ("Argument Overview" -- deliberately NOT titled
    introduction/abstract/conclusion, so `select_envelope_nodes` never
    matches it and the ONLY way the widened slice can reach it is via the
    head-of-tree walk) carrying genuine, invented argument prose -- the
    "Halberstadt convergence thesis" -- several sentences long, our own
    fabricated academic-sounding claim, appearing nowhere else in this
    repository or in any real source.
  - A top-level "Conclusion" section (`select_envelope_nodes` matches it,
    asserted directly below as a fixture sanity check) whose 28 children are
    each a single, wholly invented bibliographic citation entry
    ("Surname, Initial (Year). Fictional Title. Fictional City: Fictional
    Press.") -- fabricated authors/titles/presses, comfortably north of
    2,000 combined characters, clearing any character-count evidence floor
    many times over on raw length alone, mirroring the real Tilly section's
    ~7-9k-character citation wall. Each individual leaf carries exactly ONE
    citation match for `axial.router._INVERTED_AUTHOR_NAME_RE` -- well under
    `axial.router.CONTENT_APPARATUS_CITATION_THRESHOLD` (5) -- so a
    (hypothetical, wrong) per-block content-apparatus check would flag NONE
    of them; only a signal aggregated ACROSS the section's descendants can
    ever catch this fixture, exactly the distinction PRD §7.3 draws between
    the envelope's own aggregate signal and the chunk-stage's §7.8
    per-block arm (asserted directly below as a second fixture sanity
    check).

Total front matter (~310 characters) plus body prose (~550 characters) sits
comfortably inside `_HEAD_OF_TREE_SLICE_CHARS` (6000) with room to spare, so
if the widen were to happen WITHOUT a working front-matter-prefix skip, the
front-matter marker and the body-prose marker would both land in the
composed evidence together -- the front-matter-absence assertion below is
not vacuous, it has real bite against a partial fix that excludes the
bibliography but never skips the leading prefix.

Seam decision 3 -- the control fixture proves the detector is conservative,
not merely "any normal source passes"
-----------------------------------------------------------------------
`tests/fixtures/envelope/bibliography_aggregate_control_tree.json` is a
second hand-authored tree: a normal Introduction/body/Conclusion shape whose
Introduction and Conclusion each cite ONE source in passing, inline, inside
a full argument sentence (not as a bare citation entry) -- exactly the
"ordinary argument prose that merely cites sources in passing" case PRD
§7.3 requires the conservative detector to leave alone ("stays prose").
This is deliberately not a citation-free control: a control with zero
citations would not test the detector's conservatism at all, only its
existence. Its evidence must be unchanged by the new exclusion/prefix-skip
logic -- both its Introduction's and Conclusion's own argument sentences
must still appear in the composed evidence.

Test hygiene: pure `compose_prompt(tree)` calls over hand-loaded fixture
JSON, no filesystem writes, no `data/` state, no LLM client, no subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path

from axial.envelope import compose_prompt, select_envelope_nodes
from axial.router import CONTENT_APPARATUS_CITATION_THRESHOLD, _INVERTED_AUTHOR_NAME_RE

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "envelope"

BIBLIOGRAPHY_TREE_FIXTURE = FIXTURES_DIR / "bibliography_aggregate_tree.json"
CONTROL_TREE_FIXTURE = FIXTURES_DIR / "bibliography_aggregate_control_tree.json"

# The body-prose marker that must survive into the widened head-of-tree
# slice (module docstring, seam decision 2) -- our own fabricated argument
# claim, not drawn from any real source.
BODY_PROSE_MARKER = "Halberstadt convergence thesis"

# Front-matter markers that must NOT appear anywhere in the composed
# evidence -- the leading prefix the widen must skip past (module
# docstring, seam decision 2).
FRONT_MATTER_PUBLISHER_MARKER = "Quillbrook Fictional Press"
FRONT_MATTER_ISBN_MARKER = "ISBN 979-0-00000-001-7"

# Control-fixture markers (module docstring, seam decision 3).
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


def test_bibliography_fixture_matches_only_the_conclusion_heading():
    """Fixture sanity check: `select_envelope_nodes` must match exactly the
    "Conclusion" section (never "Argument Overview", which is deliberately
    NOT intro/abstract/conclusion-titled) -- or the rest of this test would
    not actually be exercising the #222 gap at all (module docstring, seam
    decision 2)."""
    tree = _load_tree(BIBLIOGRAPHY_TREE_FIXTURE)
    matched_headings = [node.get("text") for node in select_envelope_nodes(tree)]
    assert matched_headings == ["Conclusion"], (
        f"expected select_envelope_nodes to match exactly one section, "
        f"'Conclusion', on the bibliography-aggregate fixture, got "
        f"{matched_headings!r}"
    )


def test_bibliography_fixture_citations_clear_evidence_floor_on_raw_length():
    """Fixture sanity check: the citation wall alone (ignoring the
    aggregate-exclusion behavior under test) must comfortably clear the
    envelope's character-count evidence floor, or this fixture would not
    reproduce the actual #222 trap ("that wall of citations clears the
    character-count evidence floor ... so without a further check the pass
    hands the model a bibliography instead of an argument", PRD §7.3)."""
    tree = _load_tree(BIBLIOGRAPHY_TREE_FIXTURE)
    conclusion = _find_top_level_section(tree, "Conclusion")
    citation_children = conclusion.get("children", [])
    total_chars = sum(len(child.get("text") or "") for child in citation_children)
    assert len(citation_children) >= 20, (
        f"expected the bibliography fixture's Conclusion section to carry "
        f"20+ single-citation leaf children (PRD §7.3, 'overwhelmingly "
        f"single-citation / bibliographic leaves'), got "
        f"{len(citation_children)}"
    )
    # Comfortably above the evidence floor by an order of magnitude -- not a
    # borderline case that could pass by accident either way.
    assert total_chars >= 1500, (
        f"expected the bibliography fixture's citation wall to clear the "
        f"evidence floor comfortably (PRD §7.3: 'that wall of citations "
        f"clears the character-count evidence floor'), got only "
        f"{total_chars} combined characters across {len(citation_children)} "
        f"leaves"
    )


def test_bibliography_fixture_citations_are_each_below_the_per_block_threshold():
    """Fixture sanity check: every individual citation leaf, in isolation,
    must carry FEWER inverted-author-name matches than
    `CONTENT_APPARATUS_CITATION_THRESHOLD` (5) -- so a per-block density
    check (the §7.8 content-apparatus arm's own signal) flags NONE of them
    individually, and only a signal aggregated ACROSS the section's
    descendants can ever catch this fixture. This is exactly the
    distinction PRD §7.3 draws: 'the §7.8 content-apparatus arm keys on
    citation density within a single block, and this bibliography's
    citations are fragmented one-per-leaf, each leaf below that per-block
    threshold ... the envelope needs its own aggregate signal.'"""
    tree = _load_tree(BIBLIOGRAPHY_TREE_FIXTURE)
    conclusion = _find_top_level_section(tree, "Conclusion")
    for child in conclusion.get("children", []):
        text = child.get("text") or ""
        match_count = len(_INVERTED_AUTHOR_NAME_RE.findall(text))
        assert 0 < match_count < CONTENT_APPARATUS_CITATION_THRESHOLD, (
            f"expected every individual citation leaf to carry between 1 "
            f"and {CONTENT_APPARATUS_CITATION_THRESHOLD - 1} inverted-"
            f"author-name matches (so no single leaf trips the §7.8 "
            f"per-block content-apparatus threshold on its own), got "
            f"{match_count} in leaf text {text!r}"
        )


def test_compose_prompt_excludes_bibliography_and_reaches_body_prose():
    tree = _load_tree(BIBLIOGRAPHY_TREE_FIXTURE)
    evidence = compose_prompt(tree)

    conclusion = _find_top_level_section(tree, "Conclusion")
    citation_texts = [child.get("text") for child in conclusion.get("children", [])]

    # --- assertion 1: the aggregate-detected bibliography is excluded from
    # the matched-section evidence (PRD §7.3, "Bibliography-by-aggregate
    # exclusion") -- not one citation sampled, EVERY citation in the wall ---
    leaked = [text for text in citation_texts if text in evidence]
    assert not leaked, (
        f"expected NONE of the bibliography fixture's {len(citation_texts)} "
        f"single-citation leaves to appear in compose_prompt's evidence "
        f"(PRD §7.3, 'Bibliography-by-aggregate exclusion': a matched "
        f"section 'overwhelmingly single-citation / bibliographic leaves' "
        f"must be 'excluded from the matched-section evidence before the "
        f"evidence-floor check'), but {len(leaked)} leaked through, e.g. "
        f"{leaked[0]!r}.\nFull composed evidence:\n{evidence}"
    )

    # --- assertion 2: the pass widened to the head-of-tree slice and
    # reached genuine body prose instead (PRD §7.3: "the pass widens to the
    # head-of-tree slice and finds real body prose") ---
    assert BODY_PROSE_MARKER in evidence, (
        f"expected compose_prompt's evidence to carry the distinctive body-"
        f"prose marker {BODY_PROSE_MARKER!r} from the fixture's "
        f"'Argument Overview' section, reached only via the head-of-tree "
        f"widen once the bibliographic 'Conclusion' section is excluded "
        f"(PRD §7.3, #222). Its absence means the pass either still hands "
        f"the model the citation wall (no aggregate exclusion happened) or "
        f"widened to a slice that never reaches real body prose.\n"
        f"Full composed evidence:\n{evidence}"
    )

    # --- assertion 3: the leading front-matter/apparatus prefix is skipped,
    # not what the widened slice leads with (PRD §7.3, the head-of-tree
    # prefix-skip criterion, #222) ---
    assert FRONT_MATTER_PUBLISHER_MARKER not in evidence, (
        f"expected compose_prompt's evidence to NOT carry the leading "
        f"front-matter marker {FRONT_MATTER_PUBLISHER_MARKER!r} (the "
        f"fixture's title-page/publisher-boilerplate prefix) -- PRD §7.3: "
        f"'the slice ... skips a leading front-matter / apparatus prefix "
        f"... and begins at the first genuinely substantive body prose'. "
        f"Its presence means the head-of-tree widen still leads with "
        f"boilerplate instead of skipping past it to reach real argument "
        f"prose.\nFull composed evidence:\n{evidence}"
    )
    assert FRONT_MATTER_ISBN_MARKER not in evidence, (
        f"expected compose_prompt's evidence to NOT carry the leading "
        f"front-matter ISBN marker {FRONT_MATTER_ISBN_MARKER!r} (PRD §7.3, "
        f"prefix-skip criterion) -- its presence means the copyright/ISBN "
        f"block was not skipped.\nFull composed evidence:\n{evidence}"
    )


def test_compose_prompt_control_source_evidence_unchanged():
    """A normally-sectioned source, whose matched Introduction/Conclusion
    each cite one source in passing (inside a full argument sentence, not
    as a bare citation entry), is unaffected by the new exclusion/prefix-
    skip logic: its own argument prose is still the evidence (PRD §7.3:
    'given a normally-sectioned born-digital source, the assembled envelope
    evidence is unchanged'; the detector is 'conservative ... never on
    ordinary argument prose that merely cites sources in passing')."""
    tree = _load_tree(CONTROL_TREE_FIXTURE)

    matched_headings = [node.get("text") for node in select_envelope_nodes(tree)]
    assert matched_headings == ["Introduction", "Conclusion"], (
        f"fixture sanity check failed: expected the control fixture's "
        f"Introduction and Conclusion sections to both match "
        f"select_envelope_nodes, got {matched_headings!r}"
    )

    evidence = compose_prompt(tree)

    assert CONTROL_INTRO_MARKER in evidence, (
        f"expected the control fixture's Introduction argument sentence "
        f"(containing {CONTROL_INTRO_MARKER!r}) to still appear in "
        f"compose_prompt's evidence unchanged -- a normally-sectioned "
        f"source's evidence must not be disturbed by the new bibliography-"
        f"exclusion logic (PRD §7.3).\nFull composed evidence:\n{evidence}"
    )
    assert CONTROL_CONCLUSION_MARKER in evidence, (
        f"expected the control fixture's Conclusion argument sentence "
        f"(containing {CONTROL_CONCLUSION_MARKER!r}) to still appear in "
        f"compose_prompt's evidence unchanged -- an ordinary in-passing "
        f"citation must never trip the conservative bibliography detector "
        f"(PRD §7.3: 'a section that merely cites sources in passing stays "
        f"prose').\nFull composed evidence:\n{evidence}"
    )
