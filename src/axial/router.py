"""Source router (issue #167, PRD §7.8 / §5 step 2b / §8 P0-4; issue #172):
the single, shared classification that maps a structural `label` -- either
docling's own token (§7.4) or, on the Unstructured fallback extraction path
(P0-2), `unstructured`'s PascalCase `element.category` spelling -- to exactly
one of three routes -- `PROSE`, `ARTIFACT`, `APPARATUS` -- so that no
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

**Label normalization (issue #172).** `route_for` and `apparatus_reason`
first resolve `label` to a canonical docling token via a shared alias table
(`_canonical_token`) before consulting the mapping above. Docling's own
tokens resolve to themselves; Unstructured's disjoint `element.category`
spellings (e.g. `Header`, `Table`, `ListItem`) resolve to the docling token
they mean (`page_header`, `table`, `list_item`), so both extraction paths
share the one classification. A label that is neither a docling token nor a
known Unstructured alias passes through unchanged and falls through to the
fail-open rule below -- the alias table is not a catch-all.

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

**Content-detected apparatus (issue #207, §7.8).** The label mapping above
only catches apparatus docling itself labels as apparatus. A reference
list/bibliography/endnote run mis-sectioned under an ordinary body heading
(e.g. "Chapter Two") is labelled `text` and routes to prose by the mapping
alone -- only its content reveals it. `is_content_apparatus_candidate` is
the cheap, deterministic pre-filter for that residual case: a dense run of
inverted-author-name citations past `CONTENT_APPARATUS_CITATION_THRESHOLD`.
Only a flagged candidate is ever sent to a bounded per-block model
classification call (owned by `axial.chunk`, which holds the `client=...`
DI seam); an unflagged block never incurs model spend. A confirmed
apparatus classification is recorded with the distinct `CONTENT_APPARATUS_REASON`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

PROSE = "prose"
ARTIFACT = "artifact"
APPARATUS = "apparatus"

# §7.8's fixed label -> route mapping. `list_item` is deliberately absent from
# every one of these sets -- its route depends on `in_back_matter_section`
# (see `route_for`), not on a fixed label lookup.
_PROSE_LABELS = frozenset({"text", "section_header", "title"})
_ARTIFACT_LABELS = frozenset({"table", "picture", "caption"})
_APPARATUS_LABELS = frozenset(
    {"document_index", "footnote", "page_header", "page_footer", "page_number"}
)

# Issue #172: normalized-key alias table resolving BOTH docling's own tokens
# (mapped to themselves) and the Unstructured fallback extractor's disjoint
# `element.category` spellings to the one canonical docling token §7.8's
# route mapping above is written in terms of. The lookup key is the raw
# label casefolded with separators (`-`, ` `) collapsed to `_` (see
# `_canonical_token`), so `"Header"`, `"header"`, and `"Page-Header"` all
# normalize before this table is consulted. Single source: every downstream
# route/reason decision runs on the resolved token, never on the raw label.
_LABEL_ALIASES = {
    # docling's own tokens, identity-mapped so this table is the one place
    # normalization happens for both extraction paths.
    "text": "text",
    "section_header": "section_header",
    "title": "title",
    "table": "table",
    "picture": "picture",
    "caption": "caption",
    "document_index": "document_index",
    "footnote": "footnote",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "list_item": "list_item",
    # Unstructured `element.category` aliases (verified in-sandbox against
    # the installed `unstructured` package).
    "header": "page_header",
    "footer": "page_footer",
    "tablechunk": "table",
    "image": "picture",
    "figure": "picture",
    "figurecaption": "caption",
    "listitem": "list_item",
    "narrativetext": "text",
    "uncategorizedtext": "text",
    "pagenumber": "page_number",
}

# Route-specific, human-readable reasons for the router-owned skip sidecar
# (§7.8 "each drop is recorded with a reason"; issue #167 plan's own worked
# examples). `list_item` here names the back-matter-list_item apparatus case
# specifically (never the fixed-label lookup above).
_APPARATUS_REASONS = {
    "document_index": "apparatus: table of contents",
    "footnote": "apparatus: endnotes",
    "page_header": "apparatus: running head",
    "page_footer": "apparatus: running head",
    "page_number": "apparatus: page number",
    "list_item": "apparatus: back-matter list item",
}


def _canonical_token(label: str | None) -> str:
    """Resolve a raw `label` (docling token or Unstructured `element.category`
    spelling) to the one canonical docling token `route_for`/`apparatus_reason`
    both classify on (issue #172). Shared by both so they can't drift.

    Strips surrounding whitespace, then -- if that leaves anything -- looks
    up a casefolded, separator-normalized key (`-`/` ` -> `_`) in
    `_LABEL_ALIASES`. A label that isn't a known docling token or
    Unstructured alias passes through unchanged (stripped only): it won't
    match any route set below, so it still falls open to `PROSE` (§7.8) --
    this table is a normalization step, never a catch-all.
    """
    stripped = (label or "").strip()
    if not stripped:
        return ""
    key = stripped.casefold().replace("-", "_").replace(" ", "_")
    return _LABEL_ALIASES.get(key, stripped)


def canonical_label(label: str | None) -> str:
    """Public wrapper over `_canonical_token` (issue #172): resolve a raw
    `label` -- docling token or Unstructured `element.category` spelling --
    to the one canonical docling token this module classifies on. Exposed so
    a caller that needs to compare against a specific canonical token (e.g.
    `axial.artifacts`'s caption test) shares this module's normalization
    rather than re-deriving it or reaching into the private `_canonical_token`.
    """
    return _canonical_token(label)


def route_for(label: str | None, *, in_back_matter_section: bool = False) -> str:
    """The single shared classification (§7.8): map a structural `label` --
    docling's own token or, on the Unstructured fallback path, its aliased
    `element.category` spelling (issue #172) -- to `PROSE` / `ARTIFACT` /
    `APPARATUS`.

    `label` is first resolved to a canonical docling token via
    `_canonical_token` (docling tokens pass through unchanged; Unstructured
    spellings normalize to the docling token they mean), and the route
    mapping below runs on that resolved token. An absent, empty, or
    genuinely unrecognized label fails open to `PROSE` (§7.8's hard
    requirement: never silently drop on an unknown label).

    `list_item` is prose by default; it resolves to apparatus only when
    `in_back_matter_section` is true, per §7.8's own worked example. The
    caller supplies that context -- see `iter_routed_blocks`.
    """
    normalized = _canonical_token(label)
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
    call this once they already know the route. Shares `_canonical_token`
    with `route_for` (issue #172) so an aliased Unstructured label (e.g.
    `Header`) still resolves to its docling reason. Falls back to a generic
    (still non-empty) reason for any apparatus label this module doesn't yet
    have a bespoke phrase for, so a future apparatus label addition never
    regresses to an empty reason string.
    """
    normalized = _canonical_token(label)
    return _APPARATUS_REASONS.get(normalized, f"apparatus: {normalized or 'unknown label'}")


# =============================================================================
# Content-detected apparatus (issue #207, §7.8 "Content-detected apparatus
# (the residual reference-list case)" / "Model-backed classification of
# flagged candidates"): a block the label mapping above routes to PROSE may
# still be a reference list / bibliography / endnote run mis-sectioned under
# an ordinary body heading (docling labels it "text"), so only the block's
# CONTENT reveals it as apparatus -- heading/title matching cannot catch it.
# This is a TWO-STAGE arm so clean prose never incurs model spend: a cheap
# deterministic pre-filter (`is_content_apparatus_candidate`, below) flags a
# candidate; only a flagged candidate is ever sent to the bounded per-block
# model classification call (that call itself lives in `axial.chunk`, which
# owns the `client=...` DI seam mirroring `axial.tag.run_tag`'s own).
# =============================================================================

# An inverted-author-name citation entry, e.g. "Omicron, F." or "Alpha, K.":
# a capitalized surname, a comma, then a capitalized initial/given-name
# token. Deliberately narrow -- not a general "any comma" heuristic -- so an
# ordinary sentence containing a comma never matches by accident.
_INVERTED_AUTHOR_NAME_RE = re.compile(r"[A-Z][a-z]+,\s+[A-Z]")

# Tunable starting point (framed like `axial.chunk.CHUNK_MIN` /
# `LOW_ALPHA_RATIO_THRESHOLD` -- a named constant with a comment, not a magic
# literal -- proven-able later via `axial chunk examine`): the minimum
# number of inverted-author-name matches a block's text must carry before
# the content arm flags it as a candidate. Chosen conservatively so a block
# that merely cites a source once or twice in passing (the ordinary-prose
# case §7.8 requires this arm never fire on) stays well under the
# threshold, while a real reference list -- which recurs far more densely --
# clears it easily.
CONTENT_APPARATUS_CITATION_THRESHOLD = 5

# The content-apparatus drop reason (§7.8: "its reason recorded ... with a
# distinct content-apparatus reason"), recorded to the router-owned skip
# sidecar -- deliberately different from every label-driven reason in
# `_APPARATUS_REASONS` above.
CONTENT_APPARATUS_REASON = "apparatus: content-detected citation list"


def is_content_apparatus_candidate(text: str) -> bool:
    """The cheap, deterministic pre-filter (§7.8): True when `text` carries
    at least `CONTENT_APPARATUS_CITATION_THRESHOLD` inverted-author-name
    citation entries -- a dense run of bibliographic citations, styled like
    a reference list. Conservative by construction: ordinary analytical
    prose that cites a source once or twice in passing never reaches the
    threshold and is never flagged. Only a block this pre-filter flags is
    ever sent to the bounded model classification call (§7.8's
    "Model-backed classification of flagged candidates") -- every unflagged
    block routes exactly as its `label` already dictates, at zero model
    spend."""
    if not text:
        return False
    return len(_INVERTED_AUTHOR_NAME_RE.findall(text)) >= CONTENT_APPARATUS_CITATION_THRESHOLD


def iter_routed_blocks(
    node: dict, *, in_back_matter_section: bool = False
) -> Iterator[tuple[dict, str]]:
    """Walk `node` and its descendants (inclusive of `node` itself), yielding
    `(leaf_node, route)` for every node carrying non-empty `text` -- the
    per-block routing a section-body tree walk needs (the same per-leaf
    recursive shape `axial.chunk._routed_section_body` walks, but yielding a
    route per block instead of collecting prose text unconditionally).

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
