"""Unit tests for `axial.router` (issue #167, PRD §7.8): the shared
label -> route classification, its fail-open-to-prose default, and the
`list_item` back-matter rule. Co-located per house convention (`src/axial/`,
not `tests/`) -- the outer, locked acceptance test lives at
`tests/test_source_router.py`.
"""

from __future__ import annotations

import pytest

from axial.router import (
    APPARATUS,
    ARTIFACT,
    CONTENT_APPARATUS_CITATION_THRESHOLD,
    CONTENT_APPARATUS_REASON,
    PROSE,
    apparatus_reason,
    is_content_apparatus_candidate,
    iter_routed_blocks,
    route_for,
)

# --- route_for: the fixed label -> route mapping (§7.8) --------------------


@pytest.mark.parametrize("label", ["text", "section_header", "title"])
def test_route_for_prose_labels(label):
    assert route_for(label) == PROSE


@pytest.mark.parametrize("label", ["table", "picture", "caption"])
def test_route_for_artifact_labels(label):
    assert route_for(label) == ARTIFACT


@pytest.mark.parametrize("label", ["document_index", "footnote", "page_header", "page_footer"])
def test_route_for_apparatus_labels(label):
    assert route_for(label) == APPARATUS


# --- fail-open to prose: unknown/absent/empty label -------------------------


def test_route_for_unknown_label_fails_open_to_prose():
    assert route_for("some_never_before_seen_label") == PROSE


def test_route_for_none_label_fails_open_to_prose():
    assert route_for(None) == PROSE


def test_route_for_empty_label_fails_open_to_prose():
    assert route_for("") == PROSE


def test_route_for_whitespace_only_label_fails_open_to_prose():
    assert route_for("   ") == PROSE


# --- the list_item back-matter rule -----------------------------------------


def test_list_item_in_body_is_prose_by_default():
    assert route_for("list_item") == PROSE
    assert route_for("list_item", in_back_matter_section=False) == PROSE


def test_list_item_in_back_matter_section_is_apparatus():
    assert route_for("list_item", in_back_matter_section=True) == APPARATUS


# --- apparatus_reason: non-empty, informative reasons -----------------------


@pytest.mark.parametrize(
    "label", ["document_index", "footnote", "page_header", "page_footer", "list_item"]
)
def test_apparatus_reason_is_non_empty_for_every_apparatus_label(label):
    reason = apparatus_reason(label)
    assert isinstance(reason, str) and reason.strip()


def test_apparatus_reason_distinguishes_document_index_and_footnote():
    # The outer test's skip-record assertions don't lock exact wording, but a
    # reader inspecting the sidecar needs the reasons to differ per label.
    assert apparatus_reason("document_index") != apparatus_reason("footnote")


def test_apparatus_reason_falls_back_to_non_empty_for_unknown_label():
    reason = apparatus_reason("some_future_apparatus_label")
    assert isinstance(reason, str) and reason.strip()


# --- iter_routed_blocks: the tree-walk helper --------------------------------


def test_iter_routed_blocks_yields_route_per_leaf_with_text():
    node = {
        "type": "prose",
        "order": "1.1",
        "text": "ordinary paragraph",
        "label": "text",
    }
    results = list(iter_routed_blocks(node))
    assert results == [(node, PROSE)]


def test_iter_routed_blocks_skips_nodes_with_no_text():
    node = {"type": "prose", "order": "1.1", "label": "text"}
    assert list(iter_routed_blocks(node)) == []


def test_iter_routed_blocks_recurses_into_children():
    child_a = {"type": "prose", "order": "1.1", "text": "first", "label": "text"}
    child_b = {"type": "prose", "order": "1.2", "text": "second", "label": "caption"}
    parent = {
        "type": "prose",
        "order": "1",
        "text": "Heading",
        "label": "section_header",
        "children": [child_a, child_b],
    }
    results = list(iter_routed_blocks(parent))
    assert results == [
        (parent, PROSE),
        (child_a, PROSE),
        (child_b, ARTIFACT),
    ]


def test_iter_routed_blocks_threads_in_back_matter_section_to_every_descendant():
    child = {"type": "prose", "order": "1.1", "text": "a reference entry", "label": "list_item"}
    parent = {
        "type": "prose",
        "order": "1",
        "text": "References",
        "label": "section_header",
        "children": [child],
    }
    results = list(iter_routed_blocks(parent, in_back_matter_section=True))
    assert results == [
        (parent, PROSE),  # section_header itself is always prose
        (child, APPARATUS),  # list_item, but enclosing section is back-matter
    ]


# --- content-apparatus pre-filter (issue #207, §7.8) -------------------------


def test_is_content_apparatus_candidate_flags_dense_citation_run():
    names = [
        ("Alpha", "K"),
        ("Beta", "L"),
        ("Gamma", "R"),
        ("Delta", "S"),
        ("Epsilon", "T"),
    ]
    assert len(names) >= CONTENT_APPARATUS_CITATION_THRESHOLD
    text = " ".join(
        f"{surname}, {initial}. (2001) Some Volume, Press, pp. 1-2." for surname, initial in names
    )
    assert is_content_apparatus_candidate(text)


def test_is_content_apparatus_candidate_never_fires_on_a_single_passing_citation():
    text = (
        "This chapter's argument builds directly on Omicron, F. (2015), whose "
        "account of frontier administration remains influential, but the present "
        "analysis reframes the causal mechanism entirely around local fiscal "
        "capacity instead of external enforcement."
    )
    assert not is_content_apparatus_candidate(text)


def test_is_content_apparatus_candidate_never_fires_on_ordinary_prose_with_no_citations():
    text = "The provincial council debated the reconstruction budget for three sessions."
    assert not is_content_apparatus_candidate(text)


def test_is_content_apparatus_candidate_false_for_empty_text():
    assert not is_content_apparatus_candidate("")


def test_content_apparatus_reason_is_distinct_from_every_label_driven_reason():
    label_driven_reasons = {
        apparatus_reason(label)
        for label in ("document_index", "footnote", "page_header", "page_footer", "list_item")
    }
    assert CONTENT_APPARATUS_REASON not in label_driven_reasons
    assert isinstance(CONTENT_APPARATUS_REASON, str) and CONTENT_APPARATUS_REASON.strip()
