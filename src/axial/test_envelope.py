"""Inner unit tests for the axial envelope module (issue #16 slice 04 --
structural envelope)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from axial.llm import ExplodingLLMClient, StubLLMClient


def _tree_with_sections(*, include_body=True) -> dict:
    # Body paragraphs are deliberately long enough (see axial.envelope's
    # _EVIDENCE_FLOOR_CHARS) that this well-matched, normal-shaped tree never
    # dips into the #201 head-of-tree widening fallback -- these tests pin
    # the PRIMARY intro/abstract/conclusion heuristic's own behavior.
    return {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": (
                    [
                        {
                            "type": "prose",
                            "order": "1.1",
                            "text": (
                                "This paper argues X: that the observed institutional "
                                "variation across the sampled cases is better explained "
                                "by infrastructural capacity than by coercive enforcement "
                                "alone, a claim developed at length across the following "
                                "comparative case chapters."
                            ),
                        }
                    ]
                    if include_body
                    else []
                ),
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Comparative Cases",
                "children": [
                    {"type": "prose", "order": "2.1", "text": "Body material, not envelope input."}
                ],
            },
            {
                "type": "prose",
                "order": "3",
                "text": "Conclusion",
                "children": [
                    {
                        "type": "prose",
                        "order": "3.1",
                        "text": (
                            "In sum, X is true: the evidence assembled across these "
                            "cases shows that infrastructural power consistently "
                            "outperforms coercive capacity as a predictor of durable "
                            "post-conflict institutional order, confirming the paper's "
                            "opening thesis in full."
                        ),
                    }
                ],
            },
        ]
    }


# --- source_id -------------------------------------------------------------


def test_compute_source_id_is_deterministic_for_the_same_content(tmp_path):
    from axial.envelope import compute_source_id

    path = tmp_path / "paper.pdf"
    path.write_bytes(b"same bytes")

    assert compute_source_id(path) == compute_source_id(path)


def test_compute_source_id_differs_for_different_content(tmp_path):
    from axial.envelope import compute_source_id

    path_a = tmp_path / "paper.pdf"
    path_a.write_bytes(b"content a")
    path_b = tmp_path / "paper.pdf"  # same name, different dir/content below

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    path_b = other_dir / "paper.pdf"
    path_b.write_bytes(b"content b")

    assert compute_source_id(path_a) != compute_source_id(path_b)


def test_compute_source_id_missing_file_raises_missing_source_error(tmp_path):
    from axial.envelope import MissingSourceError, compute_source_id

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError) as exc_info:
        compute_source_id(missing)

    assert missing.name in str(exc_info.value)


# --- node selection / prompt composition ------------------------------------


def test_select_envelope_nodes_picks_only_intro_abstract_conclusion():
    from axial.envelope import select_envelope_nodes

    tree = _tree_with_sections()

    selected = select_envelope_nodes(tree)

    headings = [node["text"] for node in selected]
    assert headings == ["Introduction", "Conclusion"]
    assert "Comparative Cases" not in headings


def test_select_envelope_nodes_matches_case_insensitively():
    from axial.envelope import select_envelope_nodes

    tree = {
        "children": [
            {"type": "prose", "order": "1", "text": "INTRODUCTION", "children": []},
            {"type": "prose", "order": "2", "text": "abstract", "children": []},
        ]
    }

    selected = select_envelope_nodes(tree)

    assert len(selected) == 2


def test_compose_prompt_excludes_body_section_text():
    from axial.envelope import compose_prompt

    tree = _tree_with_sections()

    prompt = compose_prompt(tree)

    assert "This paper argues X" in prompt
    assert "In sum, X is true" in prompt
    assert "Body material, not envelope input." not in prompt


# --- evidence floor / head-of-tree widening (#201) ---------------------------


def test_compose_prompt_widens_when_no_heading_matches():
    """Evidence floor (PRD §7.3): a topic-titled tree whose top-level
    headings match none of intro/abstract/conclusion must still surface
    real source text, drawn in tree order, rather than an empty evidence
    block."""
    from axial.envelope import compose_prompt, select_envelope_nodes

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Border Enforcement Regimes",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "text": "The Kestrel-9 marker phrase appears nowhere else in this repo.",
                    }
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Fiscal Extraction Networks",
                "children": [
                    {"type": "prose", "order": "2.1", "text": "Unrelated later material."}
                ],
            },
        ]
    }
    assert select_envelope_nodes(tree) == []  # fixture sanity check

    prompt = compose_prompt(tree)

    assert "Kestrel-9 marker phrase" in prompt


def test_compose_prompt_widens_when_matched_section_is_near_empty():
    """A matched heading with little/no captured body (PRD §7.3, 'little or
    no text') widens exactly as if nothing had matched -- a bare heading
    match is not itself substantive evidence."""
    from axial.envelope import compose_prompt

    tree = {
        "children": [
            {"type": "prose", "order": "1", "text": "Introduction", "children": []},
            {
                "type": "prose",
                "order": "2",
                "text": "Substantive Content Elsewhere",
                "children": [
                    {
                        "type": "prose",
                        "order": "2.1",
                        "text": "The Falcon-4 marker phrase lives only in this later section.",
                    }
                ],
            },
        ]
    }

    prompt = compose_prompt(tree)

    assert "Falcon-4 marker phrase" in prompt


def test_compose_prompt_widens_when_matched_section_body_is_whitespace_only():
    """#201 finding 1: a matched heading whose captured body is nothing but
    whitespace (e.g. spaces/newlines with no real words) must widen exactly
    like a genuinely empty match -- raw character count alone (250 spaces
    clears the 200-char floor) must NOT be mistaken for substantive evidence
    (PRD §7.3, 'never an empty or whitespace-only section block'). This is
    distinct from the existing near-empty test above, which uses
    `children: []` (zero raw characters); here the body has plenty of raw
    characters, all of them whitespace."""
    from axial.envelope import compose_prompt

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "children": [
                    {"type": "prose", "order": "1.1", "text": " " * 250},
                ],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "Substantive Content Elsewhere",
                "children": [
                    {
                        "type": "prose",
                        "order": "2.1",
                        "text": "The Osprey-2 marker phrase lives only in this later section.",
                    }
                ],
            },
        ]
    }

    prompt = compose_prompt(tree)

    assert "Osprey-2 marker phrase" in prompt


def test_compose_prompt_head_of_tree_slice_is_bounded_and_deterministic():
    """The widening fallback's slice size is a bounded, stated tunable, and
    the same tree always yields the identical slice (#201 finding 2): a
    single node whose own text alone dwarfs the slice budget (e.g. one
    un-split 39000-char paragraph, plausible on real docling output) must
    not leak through whole -- it is truncated so the assembled evidence
    never exceeds the stated `_HEAD_OF_TREE_SLICE_CHARS` target, plus only a
    small, FIXED template/prefix overhead (the "## Source text ..." label
    plus the surrounding prompt template text -- ~909 characters, measured
    independently of both the paragraph's own size and the number of nodes
    contributing to the slice; see the many-small-node companion test below
    for the node-count axis of this same guarantee)."""
    from axial.envelope import _HEAD_OF_TREE_SLICE_CHARS, compose_prompt

    long_paragraph = "Sentence about nothing in particular. " * 1000  # far over the slice size
    tree = {
        "children": [
            {"type": "prose", "order": "1", "text": "Untitled Section", "children": []},
            {
                "type": "prose",
                "order": "2",
                "text": "Later Section",
                "children": [{"type": "prose", "order": "2.1", "text": long_paragraph}],
            },
        ]
    }

    prompt_a = compose_prompt(tree)
    prompt_b = compose_prompt(tree)

    assert prompt_a == prompt_b  # deterministic

    # A real, node-count-independent upper bound: this fails if the whole
    # 39000+-character paragraph leaks through unbounded (that would put
    # len(prompt) well past 39000), and passes once a single node's
    # contribution is capped to the remaining slice budget. The margin
    # covers only the fixed template text + the head-of-tree label, never
    # the paragraph's own bulk.
    _FIXED_OVERHEAD_MARGIN = 1000
    assert len(prompt_a) <= _HEAD_OF_TREE_SLICE_CHARS + _FIXED_OVERHEAD_MARGIN, (
        f"expected the head-of-tree slice to be bounded at roughly "
        f"{_HEAD_OF_TREE_SLICE_CHARS} chars (plus a small fixed overhead), "
        f"got a {len(prompt_a)}-char prompt -- the monster paragraph leaked "
        f"through uncapped"
    )


def test_compose_prompt_head_of_tree_slice_is_bounded_for_many_tiny_nodes():
    """#201 follow-up finding: the widening fallback's join-separator cost
    (the `"\\n"` that `compose_prompt` inserts between every collected line)
    must itself be counted toward the slice budget, not just the sum of the
    nodes' own text lengths -- otherwise a tree fragmented into many tiny
    text nodes (realistic on OCR-adjacent / per-font-garbled / list-heavy
    docling output) leaks separator overhead past the stated bound: 8000
    one-character nodes previously composed a ~12908-char prompt (roughly
    2.15x the 6000-char target) because 5999 join newlines went uncounted.
    The composed prompt must stay within `_HEAD_OF_TREE_SLICE_CHARS` plus
    only the FIXED template/label overhead (~909 characters -- the
    `_PROMPT_TEMPLATE` boilerplate plus the one "## Source text ..." label
    line), never overhead that scales with node count."""
    from axial.envelope import _HEAD_OF_TREE_SLICE_CHARS, compose_prompt

    tiny_nodes = [
        {"type": "prose", "order": str(i), "text": "x", "children": []} for i in range(8000)
    ]
    tree = {"children": tiny_nodes}

    prompt = compose_prompt(tree)

    _FIXED_OVERHEAD_MARGIN = 1000  # same fixed-overhead margin as the single-node test above
    assert len(prompt) <= _HEAD_OF_TREE_SLICE_CHARS + _FIXED_OVERHEAD_MARGIN, (
        f"expected the head-of-tree slice to be bounded at roughly "
        f"{_HEAD_OF_TREE_SLICE_CHARS} chars (plus a small fixed overhead) "
        f"even for a tree of thousands of tiny nodes, got a "
        f"{len(prompt)}-char prompt -- join-separator overhead leaked "
        f"through unbounded"
    )


def test_compose_prompt_does_not_widen_a_normal_well_matched_source():
    """No regression: a normal intro/abstract/conclusion source with real
    matched-section evidence keeps using the heading heuristic's own output
    unchanged -- the widening fallback never fires for it."""
    from axial.envelope import compose_prompt

    tree = _tree_with_sections()

    prompt = compose_prompt(tree)

    # "Comparative Cases" is neither intro/abstract/conclusion nor within
    # the (already ample) evidence floor's reach -- if it leaked in, the
    # primary heuristic's own section-scoping would have broken.
    assert "Body material, not envelope input." not in prompt


def test_compose_prompt_includes_matched_node_own_direct_text():
    """PRD §7.3 'full text of the selected sections': a matched section's
    own direct text is part of the evidence, not merely its children's."""
    from axial.envelope import compose_prompt

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": (
                    "Abstract: this paper's distinctive marker sentence about "
                    "gravitational-lensing anomalies is the entire abstract, sitting "
                    "directly on this node rather than on any child."
                ),
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "text": "A follow-up remark about the same anomalies.",
                    }
                ],
            }
        ]
    }

    prompt = compose_prompt(tree)

    assert "distinctive marker sentence about gravitational-lensing anomalies" in prompt
    assert "A follow-up remark about the same anomalies." in prompt


def test_compose_prompt_carries_the_grounding_instruction():
    """PRD §7.3 'Grounded by construction' / PRD §8 P0-3: the prompt must
    instruct the model to base its answer only on the supplied text, and
    not on the title, the filename, or outside knowledge."""
    from axial.envelope import compose_prompt

    prompt = compose_prompt(_tree_with_sections())
    lowered = prompt.lower()

    assert "only" in lowered and "source text" in lowered
    assert "title" in lowered
    assert "filename" in lowered or "file name" in lowered
    assert "outside knowledge" in lowered or "prior knowledge" in lowered


# --- router-filtered input selection (#216, PRD §7.8) ------------------------


def test_compose_prompt_matched_section_drops_non_prose_descendant():
    """A matched section's body may carry a non-prose descendant (e.g. a
    `table` or `caption` block, §7.8 ARTIFACT) alongside real prose --
    `_matched_section_blocks` must keep only the PROSE-routed descendant text,
    never re-deriving its own prose/non-prose decision outside the shared
    router (`axial.router.route_for`)."""
    from axial.envelope import compose_prompt

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Introduction",
                "label": "section_header",
                "children": [
                    {
                        "type": "prose",
                        "order": "1.1",
                        "text": "The Halcyon-7 marker sentence is genuine prose evidence.",
                        "label": "text",
                    },
                    {
                        "type": "prose",
                        "order": "1.2",
                        "text": "Table caption: Vireo-3 figures by quarter.",
                        "label": "caption",
                    },
                ],
            }
        ]
    }

    prompt = compose_prompt(tree)

    assert "Halcyon-7 marker sentence" in prompt
    assert "Vireo-3 figures by quarter" not in prompt


def test_head_of_tree_lines_skips_non_prose_labeled_nodes():
    """`_head_of_tree_lines` must filter each candidate node through the
    shared router (§7.8) before collecting it: a `document_index` (TOC) node
    ahead of the first prose routes to APPARATUS and must never reach the
    widened slice, even though it sits earliest in tree order."""
    from axial.envelope import _head_of_tree_lines

    tree = {
        "type": "prose",
        "order": "0",
        "children": [
            {
                "type": "prose",
                "order": "1",
                "text": "Table of Contents: the Egret-5 index locus.",
                "label": "document_index",
                "children": [],
            },
            {
                "type": "prose",
                "order": "2",
                "text": "The Egret-5 prose marker opens the body of the source.",
                "label": "text",
                "children": [],
            },
        ],
    }

    lines = _head_of_tree_lines(tree)

    joined = "\n".join(lines)
    assert "The Egret-5 prose marker opens the body of the source." in joined
    assert "Table of Contents: the Egret-5 index locus." not in joined


# --- LLM-selected toc subset (#231) ------------------------------------------


def test_resolve_toc_selects_subset_preserving_structural_order():
    """The model's `toc` answer only ever narrows the tree's own structural
    list -- the RESULT order comes from `structural_toc`'s own tree order,
    never from whatever order the model happened to list its selection in."""
    from axial.envelope import _resolve_toc

    structural_toc = ["Introduction", "Chapter One", "Chapter Two", "Conclusion"]
    model_toc = ["Chapter Two", "Introduction"]  # deliberately out of tree order

    assert _resolve_toc(structural_toc, model_toc) == ["Introduction", "Chapter Two"]


def test_resolve_toc_falls_back_to_full_structural_toc_when_intersection_is_empty():
    """#227's fallback: when the model names headings absent from this tree
    entirely (e.g. a stub/canned answer sharing nothing with the real
    chapters), the full structural list is used rather than an empty toc."""
    from axial.envelope import _resolve_toc

    structural_toc = ["Introduction", "Chapter One", "Conclusion"]
    model_toc = ["Some Other Book's Chapter"]

    assert _resolve_toc(structural_toc, model_toc) == structural_toc


def test_resolve_toc_drops_model_entries_not_present_in_structural_toc():
    """The model can only ever narrow the tree's real headings, never invent
    one: an entry in `model_toc` with no match in `structural_toc` is simply
    dropped, while a genuine match alongside it still survives."""
    from axial.envelope import _resolve_toc

    structural_toc = ["Introduction", "Chapter One", "Conclusion"]
    model_toc = ["Chapter One", "An Invented Chapter Not In The Tree"]

    assert _resolve_toc(structural_toc, model_toc) == ["Chapter One"]


def test_resolve_toc_preserves_a_duplicate_structural_heading():
    """When `structural_toc` itself carries a duplicate heading text (e.g.
    two distinct tree nodes that happen to share the same title), the
    intersection is built by walking `structural_toc` in order and testing
    set membership -- so a matching duplicate is preserved as-is, not
    deduplicated. Documenting the actual behavior: `_resolve_toc` never
    claims to deduplicate, only to reconcile against the model's answer."""
    from axial.envelope import _resolve_toc

    structural_toc = ["Chapter One", "Chapter One", "Chapter Two"]
    model_toc = ["Chapter One"]

    assert _resolve_toc(structural_toc, model_toc) == ["Chapter One", "Chapter One"]


def test_resolve_toc_returns_empty_when_structural_toc_is_empty():
    """#227: an empty `structural_toc` (e.g. a tree with no `section_header`-
    labelled top-level children) returns `[]` rather than falling back to the
    model's answer here -- `build_envelope` itself falls back further to the
    model's own `parsed["toc"]`, preserving `validate_envelope_fields`'s
    non-empty guarantee downstream."""
    from axial.envelope import _resolve_toc

    assert _resolve_toc([], ["Introduction", "Conclusion"]) == []


def test_resolve_toc_falls_back_to_full_structural_toc_when_model_toc_is_empty():
    from axial.envelope import _resolve_toc

    structural_toc = ["Introduction", "Conclusion"]

    assert _resolve_toc(structural_toc, []) == structural_toc


def test_toc_candidates_for_prompt_excludes_front_matter_region_includes_chapters():
    """The candidate list presented to the model skips the same leading
    front-matter REGION `_head_of_tree_lines` skips (#225's
    `_front_matter_region_end`): a title-labelled block and a copyright/ISBN
    marker block both anchor the region, so neither reaches the candidate
    list, while the real chapters that follow do."""
    from axial.envelope import _toc_candidates_for_prompt

    tree = {
        "children": [
            {"text": "A Book About Nothing", "label": "title", "children": []},
            {
                "text": "Copyright © 2001 Fictional Press. ISBN 000-0-00-000000-0.",
                "label": "text",
                "children": [],
            },
            {
                "text": "Chapter One: Origins",
                "label": "section_header",
                "children": [
                    {
                        "text": (
                            "A long chapter body of real argumentative prose that goes "
                            "into detail about the origins of the phenomenon under "
                            "study, providing ample evidence for the reader to follow."
                        ),
                        "label": "text",
                    }
                ],
            },
            {
                "text": "Chapter Two: Consequences",
                "label": "section_header",
                "children": [
                    {
                        "text": (
                            "Another chapter body with plenty of substantive prose "
                            "describing the consequences of the phenomenon in "
                            "question, again offering more than enough material."
                        ),
                        "label": "text",
                    }
                ],
            },
        ]
    }

    candidates = _toc_candidates_for_prompt(tree)

    assert candidates == ["Chapter One: Origins", "Chapter Two: Consequences"]


def test_toc_candidates_for_prompt_excludes_a_section_header_labelled_front_matter_block():
    """Reviewer-flagged interaction: a front-matter block that itself carries
    a `section_header` label (e.g. a "Preface" heading) is exactly the shape
    `_toc_from_tree` would otherwise pick up as a candidate chapter -- it
    must still be excluded once it falls inside the front-matter region."""
    from axial.envelope import _toc_candidates_for_prompt, _toc_from_tree

    tree = {
        "children": [
            {
                "text": "Preface",
                "label": "section_header",
                "children": [
                    {
                        "text": (
                            "A long preface with acknowledgements and remarks about "
                            "the making of this book, going on for a good while to "
                            "establish genuine substantive front-matter content that "
                            "is not itself a genuine chapter."
                        ),
                        "label": "text",
                    }
                ],
            },
            {
                "text": "Chapter One: Origins",
                "label": "section_header",
                "children": [
                    {
                        "text": (
                            "A chapter body of real argumentative prose, long enough "
                            "on its own to end the front-matter region here."
                        ),
                        "label": "text",
                    }
                ],
            },
        ]
    }

    # Sanity check: unfiltered, "Preface" WOULD be picked up as a candidate
    # (it carries the section_header label _toc_from_tree looks for) -- the
    # region skip is what removes it.
    assert "Preface" in _toc_from_tree(tree)

    candidates = _toc_candidates_for_prompt(tree)

    assert candidates == ["Chapter One: Origins"]


def test_toc_candidates_for_prompt_includes_all_top_level_headings_when_no_front_matter():
    """A tree with no title label, no copyright/ISBN marker, and no
    recognized preface/acknowledgements/foreword heading gives no positive
    evidence of any front matter at all -- `_front_matter_region_end` returns
    0, so every top-level heading surfaces as a candidate."""
    from axial.envelope import _toc_candidates_for_prompt

    tree = {
        "children": [
            {"text": "Chapter One", "label": "section_header", "children": []},
            {"text": "Chapter Two", "label": "section_header", "children": []},
        ]
    }

    assert _toc_candidates_for_prompt(tree) == ["Chapter One", "Chapter Two"]


def test_toc_candidates_for_prompt_skips_blank_heading_text():
    from axial.envelope import _toc_candidates_for_prompt

    tree = {
        "children": [
            {"text": "   ", "label": "section_header", "children": []},
            {"text": "Chapter One", "label": "section_header", "children": []},
        ]
    }

    assert _toc_candidates_for_prompt(tree) == ["Chapter One"]


# --- bounded toc-candidate block (#232) --------------------------------------


def test_bound_toc_candidates_leaves_a_real_scale_list_unchanged():
    """At or below `_TOC_CANDIDATES_MAX`, the list passes through whole,
    with no truncation flagged -- the bound is a pathological-input rail,
    never a routine trimmer (#232)."""
    from axial.envelope import _TOC_CANDIDATES_MAX, _bound_toc_candidates

    candidates = [f"Chapter {i}" for i in range(_TOC_CANDIDATES_MAX)]

    bounded, truncated = _bound_toc_candidates(candidates)

    assert bounded == candidates
    assert truncated is False


def test_bound_toc_candidates_truncates_whole_entries_past_the_bound():
    """Past `_TOC_CANDIDATES_MAX`, only the first N whole entries survive --
    never a partial heading -- and truncation is flagged so the caller can
    attach an explicit note."""
    from axial.envelope import _TOC_CANDIDATES_MAX, _bound_toc_candidates

    candidates = [f"Chapter {i}" for i in range(_TOC_CANDIDATES_MAX + 50)]

    bounded, truncated = _bound_toc_candidates(candidates)

    assert bounded == candidates[:_TOC_CANDIDATES_MAX]
    assert len(bounded) == _TOC_CANDIDATES_MAX
    assert truncated is True


def test_compose_prompt_appends_a_truncation_note_only_when_bounded():
    """`compose_prompt` attaches the truncation note only for a candidate
    list past `_TOC_CANDIDATES_MAX` -- never for one that fits (#232)."""
    from axial.envelope import _TOC_CANDIDATES_MAX, compose_prompt

    def _tree(n):
        return {
            "children": [
                {"text": f"Chapter {i}", "label": "section_header", "children": []}
                for i in range(n)
            ]
        }

    fits_prompt = compose_prompt(_tree(_TOC_CANDIDATES_MAX))
    over_prompt = compose_prompt(_tree(_TOC_CANDIDATES_MAX + 50))

    assert "truncat" not in fits_prompt.lower()
    assert "truncat" in over_prompt.lower()


# --- bibliography-by-aggregate exclusion (#222, PRD §7.3) -------------------


_SURNAMES = [
    "Voskuijlen",
    "Kharrazi",
    "Ostreicher",
    "Villanueva",
    "Aldrich",
    "Petrakis",
    "Bramwell",
    "Emenike",
    "Halloran",
    "Sunderajan",
    "Dellacroce",
    "Windham",
    "Achterberg",
    "Nkemelu",
    "Torvaldsen",
    "Marchetti",
    "Okonkwo",
    "Lindqvist",
    "Farrugia",
    "Boateng",
    "Steinorth",
    "Calloway",
    "Ibarrola",
    "Ferencz",
    "Vandermolen",
    "Aoyagi",
    "Kowalczyk",
    "Mbeki",
]


def _bibliography_wall_section(heading="Conclusion", n=28):
    return {
        "type": "prose",
        "order": "1",
        "text": heading,
        "label": "section_header",
        "children": [
            {
                "type": "prose",
                "order": f"1.{i}",
                "text": (
                    f"{_SURNAMES[i % len(_SURNAMES)]}, F. ({1970 + i}). "
                    f"Fictional Title {i}. City: Press."
                ),
                "label": "list_item",
            }
            for i in range(n)
        ],
    }


def test_is_bibliographic_aggregate_section_detects_a_citation_wall():
    """A section whose descendants are overwhelmingly single-citation
    bibliographic entries (each starting with an inverted-author-name plus a
    parenthetical year) is detected by the aggregate share signal, not by
    any single leaf's own per-block density (PRD §7.3)."""
    from axial.envelope import _is_bibliographic_aggregate_section

    section = _bibliography_wall_section()
    assert _is_bibliographic_aggregate_section(section) is True


def test_is_bibliographic_aggregate_section_leaves_ordinary_prose_alone():
    """Conservative by construction (§7.8 never-drop-on-uncertainty): a
    section whose descendants are ordinary argument sentences that merely
    cite a source in passing -- not bare citation-entry leaves -- must never
    be flagged, however many sentences happen to contain a citation."""
    from axial.envelope import _is_bibliographic_aggregate_section

    section = {
        "type": "prose",
        "order": "1",
        "text": "Conclusion",
        "label": "section_header",
        "children": [
            {
                "type": "prose",
                "order": "1.1",
                "text": (
                    "In sum, the argument holds, echoing the reading in "
                    "Okafor, D. (2003) but extending it well beyond the "
                    "original case."
                ),
                "label": "text",
            },
            {
                "type": "prose",
                "order": "1.2",
                "text": "A second ordinary sentence with no citation at all.",
                "label": "text",
            },
            {
                "type": "prose",
                "order": "1.3",
                "text": "A third ordinary sentence, likewise citation-free.",
                "label": "text",
            },
        ],
    }
    assert _is_bibliographic_aggregate_section(section) is False


def test_is_bibliographic_aggregate_section_requires_a_minimum_leaf_count():
    """A single bibliographic-looking leaf is not (by itself) "overwhelming"
    evidence of a mis-sectioned bibliography -- the aggregate share needs a
    minimum population to mean anything, guarding a small, ordinary section
    against a false positive on one coincidental leaf."""
    from axial.envelope import _is_bibliographic_aggregate_section

    section = _bibliography_wall_section(n=1)
    assert _is_bibliographic_aggregate_section(section) is False


def test_matched_section_blocks_excludes_a_detected_bibliography_section():
    """The exclusion happens inside `_matched_section_blocks` itself, before
    `compose_prompt`'s evidence-floor sum ever sees the section (PRD §7.3)."""
    from axial.envelope import _matched_section_blocks

    tree = {"children": [_bibliography_wall_section()]}

    blocks = _matched_section_blocks(tree)

    assert blocks == []


def test_head_of_tree_lines_skips_a_leading_front_matter_prefix():
    """The widened head-of-tree slice steps over a leading title-page /
    copyright-ISBN / publisher-boilerplate prefix on a content basis (label
    plus recognizable copyright-page markers), not by expecting the router
    to route it away -- both `title` and copyright/ISBN text are PROSE by
    the shared router (PRD §7.3, #222)."""
    from axial.envelope import _head_of_tree_lines

    tree = {
        "children": [
            {"type": "prose", "order": "0", "text": "A FICTIONAL TITLE PAGE", "label": "title"},
            {
                "type": "prose",
                "order": "1",
                "text": "Copyright © 2001 Fictional Press. All rights reserved. ISBN 000-0-00-000000-0.",
                "label": "text",
            },
            {
                "type": "prose",
                "order": "2",
                "text": "The Marigold-9 body prose marker opens the real argument of the source.",
                "label": "text",
            },
        ]
    }

    lines = _head_of_tree_lines(tree)

    joined = "\n".join(lines)
    assert "The Marigold-9 body prose marker" in joined
    assert "FICTIONAL TITLE PAGE" not in joined
    assert "Fictional Press" not in joined


def test_head_of_tree_lines_front_matter_skip_is_bounded():
    """The prefix-skip budget is a bounded tunable (PRD §7.3, #222): a run of
    front-matter-marked blocks that together exceed
    `_FRONT_MATTER_PREFIX_SKIP_CHARS` stops being skipped once the budget is
    exhausted, so a pathological source can never have its entire head-of-
    tree slice consumed as "front matter"."""
    from axial.envelope import _FRONT_MATTER_PREFIX_SKIP_CHARS, _head_of_tree_lines

    filler = "Copyright © notice filler text. " * 100  # a single oversized front-matter block
    assert len(filler) > _FRONT_MATTER_PREFIX_SKIP_CHARS
    tree = {
        "children": [
            {"type": "prose", "order": "0", "text": filler, "label": "text"},
        ]
    }

    lines = _head_of_tree_lines(tree)

    # The budget is exhausted by this single oversized block, so it is not
    # skipped -- it becomes the first (only) line instead of vanishing.
    assert lines == [filler]


def test_head_of_tree_lines_does_not_skip_prose_that_merely_contains_a_boilerplate_word():
    """Reviewer finding (#222 stage-2): the prefix skip must never fire on a
    bare occurrence of a common word like "printed" inside a genuine
    argument sentence -- only a high-confidence structural marker (title
    label, ©, an ISBN number, "all rights reserved", a Library of Congress
    line, a bare-year copyright line, or reproduction-permission legalese)
    counts as front matter. A false-drop here would silently undermine the
    minimum-evidence / grounded-by-construction guarantee this feature
    exists to protect."""
    from axial.envelope import _head_of_tree_lines

    tree = {
        "children": [
            {
                "type": "prose",
                "order": "0",
                "text": (
                    "This book was printed in provincial presses across the "
                    "region, and argues that guild solidarity outlives its "
                    "founding grievance."
                ),
                "label": "text",
            },
        ]
    }

    lines = _head_of_tree_lines(tree)

    joined = "\n".join(lines)
    assert "guild solidarity outlives its founding grievance" in joined


def test_is_front_matter_prefix_block_ignores_bare_boilerplate_words():
    """A lone occurrence of "publisher", "copyright", or "printed" -- with no
    structural marker alongside it -- is not enough to flag a block as front
    matter (reviewer finding, #222 stage-2)."""
    from axial.envelope import _is_front_matter_prefix_block

    leaf = {
        "text": (
            "The publisher of this journal argues that copyright reform, "
            "not printed circulation, drives citation counts."
        ),
        "label": "text",
    }
    assert _is_front_matter_prefix_block(leaf) is False


def test_is_front_matter_prefix_block_flags_a_reproduction_permission_notice():
    """Positive control pinned directly against the #222 outer fixture's own
    publisher-boilerplate sentence (tests/fixtures/envelope/
    bibliography_aggregate_tree.json): classic reproduction-permission
    legalese is a high-confidence structural marker on its own, with no
    "printed"/"copyright"/"publisher" bare-word reliance."""
    from axial.envelope import _is_front_matter_prefix_block

    leaf = {
        "text": (
            "Printed and distributed by Quillbrook Fictional Press for "
            "educational use only; no portion of this fictional front "
            "matter may be reproduced without permission."
        ),
        "label": "text",
    }
    assert _is_front_matter_prefix_block(leaf) is True


# --- response parsing / validation ------------------------------------------


def test_parse_response_rejects_invalid_json():
    from axial.envelope import EnvelopeParseError, parse_response

    with pytest.raises(EnvelopeParseError):
        parse_response("not json at all")


def test_parse_response_accepts_a_markdown_fenced_response():
    """issue #72: deepseek-v4-flash sometimes wraps its JSON answer in a
    markdown fence despite the prompt's "no fences" instruction."""
    from axial.envelope import parse_response

    raw = f"```json\n{json.dumps({'thesis': 'This paper argues X.'})}\n```"

    assert parse_response(raw) == {"thesis": "This paper argues X."}


def test_parse_response_rejects_prose_with_a_snippet_in_the_message():
    """issue #72: parse errors must quote the raw response so failures are
    diagnosable from worker logs."""
    from axial.envelope import EnvelopeParseError, parse_response

    raw = "I cannot summarize this paper."

    with pytest.raises(EnvelopeParseError) as exc_info:
        parse_response(raw)

    assert raw in str(exc_info.value)


def test_parse_response_rejects_a_non_object_json_value():
    from axial.envelope import EnvelopeParseError, parse_response

    with pytest.raises(EnvelopeParseError):
        parse_response("[1, 2, 3]")


def test_validate_envelope_fields_accepts_a_well_formed_response():
    from axial.envelope import validate_envelope_fields

    validate_envelope_fields(
        {
            "thesis": "X",
            "toc": ["Introduction", "Conclusion"],
            "scope": "Y",
            "stated_argument": "Z",
        }
    )  # must not raise


@pytest.mark.parametrize(
    "field,value",
    [
        ("thesis", ""),
        ("thesis", None),
        ("scope", ""),
        ("stated_argument", ""),
    ],
)
def test_validate_envelope_fields_rejects_empty_required_strings(field, value):
    from axial.envelope import EnvelopeValidationError, validate_envelope_fields

    data = {
        "thesis": "X",
        "toc": ["A"],
        "scope": "Y",
        "stated_argument": "Z",
    }
    data[field] = value

    with pytest.raises(EnvelopeValidationError):
        validate_envelope_fields(data)


def test_validate_envelope_fields_rejects_empty_toc():
    from axial.envelope import EnvelopeValidationError, validate_envelope_fields

    data = {"thesis": "X", "toc": [], "scope": "Y", "stated_argument": "Z"}

    with pytest.raises(EnvelopeValidationError):
        validate_envelope_fields(data)


def test_validate_envelope_fields_rejects_non_list_toc():
    from axial.envelope import EnvelopeValidationError, validate_envelope_fields

    data = {"thesis": "X", "toc": "not a list", "scope": "Y", "stated_argument": "Z"}

    with pytest.raises(EnvelopeValidationError):
        validate_envelope_fields(data)


# --- envelope assembly / write-once -----------------------------------------


def test_build_envelope_carries_the_locked_shape(tmp_path):
    from axial.envelope import build_envelope

    path = tmp_path / "my_paper.pdf"
    parsed = {
        "thesis": "X",
        "toc": ["Introduction"],
        "scope": "Y",
        "stated_argument": "Z",
    }

    envelope = build_envelope(path, "source-123", parsed)

    assert envelope["source_id"] == "source-123"
    assert envelope["thesis"] == "X"
    assert envelope["toc"] == ["Introduction"]
    assert envelope["scope"] == "Y"
    assert envelope["stated_argument"] == "Z"
    assert envelope["title"] == "My Paper"
    assert envelope["author"] is None
    assert envelope["date"] is None


def test_write_envelope_creates_parent_directories(tmp_path):
    from axial.envelope import write_envelope

    out_path = tmp_path / "nested" / "dir" / "source-123.json"

    write_envelope({"source_id": "source-123"}, out_path)

    assert out_path.exists()
    assert json.loads(out_path.read_text(encoding="utf-8")) == {"source_id": "source-123"}


# --- run_envelope: cache-first, no-recompute --------------------------------


def test_run_envelope_missing_file_raises_missing_source_error(tmp_path):
    from axial.envelope import MissingSourceError, run_envelope

    missing = tmp_path / "does_not_exist.pdf"

    with pytest.raises(MissingSourceError) as exc_info:
        run_envelope(missing, envelopes_dir=tmp_path / "envelopes")

    assert missing.name in str(exc_info.value)


def test_run_envelope_second_run_short_circuits_with_zero_client_calls(monkeypatch, tmp_path):
    """A cache hit must return the stored envelope without constructing or
    calling an LLM client at all (PRD §10, 'no recompute')."""
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    fake_tree = _tree_with_sections()
    monkeypatch.setattr(envelope_mod, "extract", lambda path: fake_tree)

    stub_client = StubLLMClient()
    first = envelope_mod.run_envelope(source, client=stub_client, envelopes_dir=envelopes_dir)
    assert stub_client.call_count == 1
    assert first["thesis"]

    def _fail_if_constructed():
        raise AssertionError("get_client() must not be called on a cache hit")

    monkeypatch.setattr(envelope_mod, "get_client", _fail_if_constructed)

    poison_client = ExplodingLLMClient()
    second = envelope_mod.run_envelope(source, client=poison_client, envelopes_dir=envelopes_dir)

    assert second == first


def test_run_envelope_wraps_extraction_failures(monkeypatch, tmp_path):
    import axial.envelope as envelope_mod
    from axial.extract import ConversionError

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    def _boom(path):
        raise ConversionError(Path(path), "simulated failure")

    monkeypatch.setattr(envelope_mod, "extract", _boom)

    with pytest.raises(envelope_mod.ExtractionFailedError):
        envelope_mod.run_envelope(
            source, client=StubLLMClient(), envelopes_dir=tmp_path / "envelopes"
        )


def test_run_envelope_wraps_llm_client_selection_errors(monkeypatch, tmp_path):
    """A missing API key / unknown provider (`LLMConfigError`, raised by
    `get_client()`) must surface as a typed `EnvelopeError`, not a bare
    `ValueError`/traceback -- so the CLI's `except EnvelopeError` handler in
    `cli.py` renders a clean `error: ...` for a real-provider misconfiguration
    instead of crashing (see llm.py's LLMError hierarchy)."""
    import axial.envelope as envelope_mod
    from axial.llm import LLMConfigError

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    def _boom(*args, **kwargs):
        raise LLMConfigError("unknown LLM provider: 'bogus'")

    monkeypatch.setattr(envelope_mod, "get_client", _boom)

    with pytest.raises(envelope_mod.LLMFailedError) as exc_info:
        envelope_mod.run_envelope(source, client=None, envelopes_dir=tmp_path / "envelopes")

    assert isinstance(exc_info.value, envelope_mod.EnvelopeError)


def test_run_envelope_honors_the_configured_envelopes_dir_when_not_passed_explicitly(
    monkeypatch, tmp_path
):
    """`paths.envelopes_dir` in `config/pipeline.yaml` must actually be read
    and honored as the default output directory when `run_envelope` is
    called without an explicit `envelopes_dir` -- the config key is not
    dead. Mirrors how `get_client()` reads a `config_path`-relative file."""
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")

    configured_dir = tmp_path / "configured-envelopes"
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        f"paths:\n  envelopes_dir: {configured_dir.as_posix()}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    envelope_mod.run_envelope(source, client=StubLLMClient(), config_path=config_path)

    written = list(configured_dir.glob("*.json"))
    assert len(written) == 1, (
        f"expected the envelope to be written under the configured "
        f"envelopes_dir {configured_dir}, found: {written}"
    )


def test_run_envelope_writes_a_file_that_round_trips_the_locked_fields(monkeypatch, tmp_path):
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    envelope = envelope_mod.run_envelope(
        source, client=StubLLMClient(), envelopes_dir=envelopes_dir
    )

    written = list(envelopes_dir.glob("*.json"))
    assert len(written) == 1
    on_disk = json.loads(written[0].read_text(encoding="utf-8"))
    assert on_disk == envelope
    for field in (
        "source_id",
        "author",
        "title",
        "date",
        "thesis",
        "toc",
        "scope",
        "stated_argument",
    ):
        assert field in on_disk


# --- run_envelope: bounded re-ask on complete-but-unparseable JSON (#76) ---


def test_run_envelope_succeeds_when_first_completion_is_malformed_json(monkeypatch, tmp_path):
    """A complete-but-syntactically-broken completion (e.g. a missing comma)
    must not abort the pass: `run_envelope` re-asks and succeeds on the next
    completion."""
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    valid = StubLLMClient._CANNED_RESPONSE

    class _ScriptedClient:
        def __init__(self):
            self._responses = ['{"thesis": "broken"', valid]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    envelope = envelope_mod.run_envelope(source, client=client, envelopes_dir=envelopes_dir)

    assert client.call_count == 2
    assert envelope["thesis"]


def test_run_envelope_raises_envelope_parse_error_on_persistently_malformed_json(
    monkeypatch, tmp_path
):
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    class _AlwaysBrokenClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return '{"thesis": "still broken"'

    client = _AlwaysBrokenClient()

    with pytest.raises(envelope_mod.EnvelopeParseError):
        envelope_mod.run_envelope(source, client=client, envelopes_dir=envelopes_dir)


# --- run_envelope: bounded re-ask on a degenerate-but-valid envelope (#80) --


def test_run_envelope_reasks_and_succeeds_when_toc_is_first_empty(monkeypatch, tmp_path):
    """A valid-JSON response with an empty `toc` list (response noise, the
    same species as broken JSON) must not immediately raise
    `EnvelopeValidationError` -- it re-asks within complete_json's bounded
    budget and succeeds on a clean second response."""
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    degenerate = json.dumps(
        {
            "thesis": "a thesis",
            "toc": [],
            "scope": "a scope",
            "stated_argument": "an argument",
        }
    )
    clean = StubLLMClient._CANNED_RESPONSE

    class _ScriptedClient:
        def __init__(self):
            self._responses = [degenerate, clean]
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            response = self._responses[self.call_count]
            self.call_count += 1
            return response

    client = _ScriptedClient()
    envelope = envelope_mod.run_envelope(source, client=client, envelopes_dir=envelopes_dir)

    assert client.call_count == 2
    assert envelope["toc"]


def test_run_envelope_raises_envelope_validation_error_on_persistently_empty_toc(
    monkeypatch, tmp_path
):
    import axial.envelope as envelope_mod

    source = tmp_path / "paper.pdf"
    source.write_bytes(b"fake pdf bytes")
    envelopes_dir = tmp_path / "envelopes"

    monkeypatch.setattr(envelope_mod, "extract", lambda path: _tree_with_sections())

    degenerate = json.dumps(
        {
            "thesis": "a thesis",
            "toc": [],
            "scope": "a scope",
            "stated_argument": "an argument",
        }
    )

    class _AlwaysDegenerateClient:
        def __init__(self):
            self.call_count = 0

        def complete(self, prompt, pass_name=None):
            self.call_count += 1
            return degenerate

    client = _AlwaysDegenerateClient()

    with pytest.raises(envelope_mod.EnvelopeValidationError):
        envelope_mod.run_envelope(source, client=client, envelopes_dir=envelopes_dir)

    assert client.call_count == 3
