"""Source router (issue #167, PRD §7.8 / §5 step 2b / §8 P0-4): the single,
shared classification that maps a docling structural `label` (§7.4) to
exactly one of three routes -- `PROSE`, `ARTIFACT`, `APPARATUS` -- so that no
downstream pass (chunk, artifact, tag, cross-reference) re-derives the
prose/non-prose decision for itself (§7.8 "one shared classification"). The
router reads the persisted tree only; it triggers no re-extraction and calls
no model.

**Routes and the `label` -> route mapping (§7.8):**
- **prose** -- `text`, `section_header`, `title`, and an in-body `list_item`.
  The only blocks that ever reach the chunk stage (§7.7).
- **artifact** -- `table`, `picture`, `caption`. Routed to the artifact pass
  (§5 stage 5); never chunked. (`caption` is typed `prose` in the raw tree
  today -- routing on `label`, not `type`, is what reclassifies it.)
- **apparatus** -- `document_index` (TOC/index), `footnote`
  (endnotes/footnotes), `page_header`, `page_footer`, and a `list_item` whose
  enclosing section is back-matter. **Dropped:** not chunked, not
  artifact-noted; each drop is recorded with a reason (§7.8 "single source of
  skip truth").

**Unknown label fails open to prose.** A block whose `label` is absent,
empty, or not in the mapping routes to prose, never silently dropped (§7.8) --
a misclassified block surfaces as visible prose to be caught and corrected,
rather than vanishing.

**`list_item` under back-matter.** A `list_item` is prose BY DEFAULT (in-body
lists are chunked); it is apparatus ONLY when its enclosing section is
back-matter (e.g. a bibliography/reference list rendered as list items).
`route_for` takes that context as the `in_back_matter_section` keyword --
callers decide "is this list_item's enclosing section back-matter" (typically
via `axial.chunk._is_back_matter` on the section's own heading) and pass the
answer in; the router itself never inspects the tree structure to find an
"enclosing section" -- that is the tree-walk caller's job (see
`iter_routed_blocks` below).
"""

from __future__ import annotations

from collections.abc import Iterator

PROSE = "prose"
ARTIFACT = "artifact"
APPARATUS = "apparatus"

# §7.8's fixed label -> route mapping. `list_item` is deliberately absent from
# every one of these sets -- its route depends on `in_back_matter_section`
# (see `route_for`), not on a fixed label lookup.
_PROSE_LABELS = frozenset({"text", "section_header", "title"})
_ARTIFACT_LABELS = frozenset({"table", "picture", "caption"})
_APPARATUS_LABELS = frozenset({"document_index", "footnote", "page_header", "page_footer"})

# Route-specific, human-readable reasons for the router-owned skip sidecar
# (§7.8 "each drop is recorded with a reason"; issue #167 plan's own worked
# examples). `list_item` here names the back-matter-list_item apparatus case
# specifically (never the fixed-label lookup above).
_APPARATUS_REASONS = {
    "document_index": "apparatus: table of contents",
    "footnote": "apparatus: endnotes",
    "page_header": "apparatus: running head",
    "page_footer": "apparatus: running head",
    "list_item": "apparatus: back-matter list item",
}


def route_for(label: str | None, *, in_back_matter_section: bool = False) -> str:
    """The single shared classification (§7.8): map a docling structural
    `label` to `PROSE` / `ARTIFACT` / `APPARATUS`.

    `label` is normalized by stripping surrounding whitespace only -- docling
    labels are already lowercase, stable tokens (see `extract.py`'s
    `_leaf_node`), so no further normalization is warranted. An absent, empty,
    or unrecognized label fails open to `PROSE` (§7.8's hard requirement:
    never silently drop on an unknown label).

    `list_item` is prose by default; it resolves to apparatus only when
    `in_back_matter_section` is true, per §7.8's own worked example. The
    caller supplies that context -- see `iter_routed_blocks`.
    """
    normalized = (label or "").strip()
    if not normalized:
        return PROSE
    if normalized == "list_item":
        return APPARATUS if in_back_matter_section else PROSE
    if normalized in _ARTIFACT_LABELS:
        return ARTIFACT
    if normalized in _APPARATUS_LABELS:
        return APPARATUS
    # Covers both the known prose labels AND any unrecognized label --
    # fail-open to prose (§7.8).
    return PROSE


def apparatus_reason(label: str | None) -> str:
    """The route-specific reason string for an apparatus-routed `label`
    (§7.8 "each drop is recorded with a reason"). Only meaningful for a label
    that `route_for` actually resolves to `APPARATUS`; callers should only
    call this once they already know the route. Falls back to a generic
    (still non-empty) reason for any apparatus label this module doesn't yet
    have a bespoke phrase for, so a future apparatus label addition never
    regresses to an empty reason string.
    """
    normalized = (label or "").strip()
    return _APPARATUS_REASONS.get(normalized, f"apparatus: {normalized or 'unknown label'}")


def iter_routed_blocks(
    node: dict, *, in_back_matter_section: bool = False
) -> Iterator[tuple[dict, str]]:
    """Walk `node` and its descendants (inclusive of `node` itself), yielding
    `(leaf_node, route)` for every node carrying non-empty `text` -- the
    per-block routing a section-body tree walk needs (mirrors
    `axial.chunk._prose_text_lines`'s own recursive shape, but yields a route
    per block instead of collecting prose text unconditionally).

    `in_back_matter_section` is the ONE piece of enclosing-section context
    the router needs (§7.8's `list_item` rule) and is threaded unchanged to
    every descendant -- the tree today never nests one section inside
    another (`extract.py`'s tree-builder opens sections only at the top
    level), so a single boolean covers every descendant's "enclosing
    section" for this walk's purposes.
    """
    route = route_for(node.get("label"), in_back_matter_section=in_back_matter_section)
    if node.get("text"):
        yield node, route
    for child in node.get("children", []):
        yield from iter_routed_blocks(child, in_back_matter_section=in_back_matter_section)
