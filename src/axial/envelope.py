"""Structural-envelope pass: one LLM call per source over its intro/abstract/
conclusion, producing a reusable envelope (PRD §5 stage 3, §7.3, §8 P0-3).

The envelope -- `{source_id, author, title, date, thesis, toc[], scope,
stated_argument}` -- is written once to `data/envelopes/<source_id>.json`
and reused by every later stage for that source (chunking, tagging). This
module computes a stable `source_id` *before* any LLM call and checks the
cache first, so a source with an existing envelope short-circuits with zero
LLM client calls (PRD §10, "no recompute" -- verified behaviorally by
tests/test_envelope.py using the poison `explode` provider from
src/axial/llm.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.extract import ExtractError, extract
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    ENVELOPE_PASS_NAME,
    LLMClient,
    LLMError,
    get_client,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.router import PROSE, iter_routed_blocks

ENVELOPES_DIR = Path("data/envelopes")

_ENVELOPE_HEADINGS = ("introduction", "abstract", "conclusion")

_REQUIRED_STRING_FIELDS = ("thesis", "scope", "stated_argument")

# --- Evidence-floor tunables (PRD §7.3, #201) --------------------------------
#
# "The slice size is a stated tunable, not a magic constant, proven via
# inspection in the spirit of the chunk band [min, max] (§7.7) and the
# low-alpha threshold (§7.8)." -- specs/PRODUCT.md 7.3. Two named constants,
# mirroring that band shape: a floor that decides whether the heading-matched
# evidence counts as "little or no text", and a target size for the
# head-of-tree fallback slice used when it doesn't.

# A matched intro/abstract/conclusion section (or set of sections) whose
# combined own-plus-descendant text falls below this many characters is
# functionally empty -- e.g. a bare heading with no real body captured -- and
# is treated exactly like an unmatched heading heuristic (widen). Set well
# below the real fixture's genuine two-section evidence (~500 characters,
# tests/fixtures/envelope/thesis_paper_tree.json's Introduction+Conclusion),
# so a normal, well-matched source's evidence is never disturbed.
_EVIDENCE_FLOOR_CHARS = 200

# Target size of the head-of-tree widening fallback: a bounded prefix of the
# source's own prose, taken in tree order (PRD §7.3). Large enough to give
# the model several paragraphs of real source text to ground thesis/scope/
# stated_argument on -- roughly two chunk-worths per the chunk band's
# CHUNK_MAX (§7.7) -- while staying bounded so a large source doesn't blow
# out the once-per-source envelope prompt. A starting point, not a
# proven-final value (mirrors CHUNK_MIN/CHUNK_MAX's own framing).
_HEAD_OF_TREE_SLICE_CHARS = 6000

_PROMPT_TEMPLATE = """\
You are extracting a structural envelope from an academic source's \
introduction, abstract, and conclusion sections, or -- when those are not \
clearly labeled -- a representative excerpt of the source's own opening \
prose. Read the source text below and respond with ONLY a JSON object (no \
prose, no markdown fences) with exactly these keys:

- "thesis": the author's stated thesis, as a non-empty string.
- "toc": a non-empty JSON array of the source's section/chapter labels.
- "scope": the stated scope of the argument, as a non-empty string.
- "stated_argument": the argument as restated (e.g. in the conclusion), \
as a non-empty string.

Base your answer only on the supplied source text below. Do not infer the \
thesis, scope, or stated argument from the title, the filename, or any \
outside knowledge -- every field must come solely from the text provided.

Sections:

{sections}
"""


class EnvelopeError(Exception):
    """Base class for all structural-envelope errors."""


class MissingSourceError(EnvelopeError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"missing or unreadable source file: {path}")


class ExtractionFailedError(EnvelopeError):
    """Raised when the underlying structural extraction pass fails."""

    def __init__(self, cause: ExtractError):
        self.cause = cause
        super().__init__(str(cause))


class LLMFailedError(EnvelopeError):
    """Raised when the LLM client -- selection/config or the completion call
    itself -- fails (e.g. a missing API key, an unknown provider, or a
    provider transport error), so the CLI renders a clean `error: ...`
    instead of a bare traceback."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class EnvelopeParseError(EnvelopeError):
    """Raised when the model's response is not parseable as a JSON object."""


class EnvelopeValidationError(EnvelopeError):
    """Raised when a parsed model response is missing required envelope fields."""


def compute_source_id(path: Path) -> str:
    """Compute a stable, deterministic source_id from `path`'s content,
    before any LLM call. Combines the filename stem (for readability) with a
    short content hash (so distinct files never collide and edited/re-saved
    files under the same name get a fresh id, avoiding stale-cache reuse).
    """
    if not path.is_file():
        raise MissingSourceError(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"{path.stem}-{digest}"


def envelope_path(source_id: str, envelopes_dir: Path = ENVELOPES_DIR) -> Path:
    """The write-once path for `source_id`'s envelope JSON."""
    return envelopes_dir / f"{source_id}.json"


def _default_envelopes_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.envelopes_dir` from `config/pipeline.yaml` (the same
    pipeline-config file `llm.get_client` reads its `llm:` block from), so
    the config-declared path is actually honored rather than only the
    hardcoded `ENVELOPES_DIR` default. An absent file/key falls back to
    `ENVELOPES_DIR`."""
    if not config_path.is_file():
        return ENVELOPES_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("envelopes_dir")
    return Path(configured) if configured else ENVELOPES_DIR


def _is_envelope_heading(node: dict) -> bool:
    """A section node's own heading text matches introduction/abstract/
    conclusion, case-insensitively (substring match, so e.g. "1. Introduction"
    or "Abstract and Summary" both count)."""
    text = node.get("text")
    if not text:
        return False
    lowered = text.strip().lower()
    return any(heading in lowered for heading in _ENVELOPE_HEADINGS)


def select_envelope_nodes(tree: dict) -> list[dict]:
    """Select only the top-level section nodes whose heading matches
    introduction/abstract/conclusion -- never the whole source (PRD §5
    stage 3, "from intro/abstract/conclusion")."""
    return [child for child in tree.get("children", []) if _is_envelope_heading(child)]


# The docling label(s) that mark a top-level chapter/section heading for
# structural `toc` derivation (issue #227). Chosen against
# tests/fixtures/envelope/structural_toc_tree.json's own three real
# chapters, each labelled `section_header`.
_TOC_HEADING_LABELS = ("section_header",)


def _toc_from_tree(tree: dict) -> list[str]:
    """The source's own table of contents, read directly off the
    extraction tree: the `text` of every top-level child labelled
    `_TOC_HEADING_LABELS`, in tree order (PRD §7.3, §5 stage 3 -- `toc` is a
    real property of the source's own structure, not an LLM guess, #227).
    Blank/whitespace-only heading text is skipped. Independent of whatever
    the front-matter-region skip (#225) does to the envelope PROMPT's own
    evidence -- this reads the tree directly, so a swept-from-the-prompt TOC
    page can never cost the source its real chapter list."""
    return [
        text
        for child in tree.get("children", [])
        if (child.get("label") or "").strip().lower() in _TOC_HEADING_LABELS
        and (text := (child.get("text") or "").strip())
    ]


# --- Bibliography-by-aggregate exclusion (PRD §7.3, #222) -------------------
#
# docling sometimes mis-attaches a source's bibliography under an ordinary
# body-section heading ("Introduction", "Conclusion"), fragmented into
# individual one-citation leaf nodes. Each leaf, alone, carries far too few
# inverted-author-name matches to ever trip `axial.router`'s own per-block
# `is_content_apparatus_candidate` (that check is a DIFFERENT granularity --
# density within one block, §7.8) -- only a signal aggregated ACROSS a
# section's descendants can ever catch this, so the envelope needs its own.

# A bibliographic leaf's own opening. #222 shipped this anchored only on the
# tidy "Surname, Initial (Year)" shape of its own synthetic fixture; real
# OCR'd academic bibliographies (the Tilly source PRD §8 P0-3 names as the
# acceptance target) turned out far messier and matched that narrow pattern
# at only ~11-13% -- nowhere near the share threshold, so the detector was a
# no-op on the very source it was built for (found via
# tests/ingestion/test_envelope_bibliography_real_ocr.py, a hand-authored
# fixture mirroring the real shapes without reproducing any real book's
# text, DEC-23). This pattern recognizes THREE distinct real-world leaf
# openers instead of one, each still anchored at the START of the leaf's
# text (`^`) so an ordinary argument sentence that merely cites a source in
# passing -- its citation always embedded mid-sentence, never leading the
# leaf -- does not fire on it (proven against both the #222 control fixture
# and the real-OCR control fixture):
#   1. an inverted surname (single token, mixed case allowed, e.g.
#      "Voskuijlen, R." or "TILLY, CHARLES") OR a multi-word ALL-CAPS
#      surname (e.g. "PEREIRA DE QUEIROZ, MARIA ISAURA", "LE GOFF, T. J.
#      A."), each followed by a comma and a capitalized given name/initial --
#      the capital-after-comma requirement is itself a guard against
#      ordinary prose, whose word after a mid-sentence comma is almost
#      always lowercase;
#   2. a continuation-dash entry standing in for a repeated author, e.g.
#      "__ (1974b)." / "___ (1977).";
#   3. a corporate/institutional author in ALL CAPS with no inverted-name
#      comma at all, e.g. "NATIONAL ADVISORY COMMISSION ON CIVIL DISORDERS
#      (1968)." -- one to eight consecutive ALL-CAPS-ish tokens (this
#      alternative also incidentally catches OCR-garbled personal-name
#      entries printed in running caps with period-separated initials, e.g.
#      "KLAPP. ORRIN E. (1969).", since every token in that shape is itself
#      all-uppercase).
# Alternative 1's surname portion also tolerates a stray OCR-garbled glyph
# in place of a letter (e.g. "I<ETTLEWELL", "ROI<I<AN" for what OCR
# mis-read from a real surname).
_BIBLIOGRAPHIC_LEAF_OPENER_RE = re.compile(
    r"^\s*(?:"
    r"[A-Z][A-Za-z<>\[\]{}\-']+"
    r"|(?:[A-Z][A-Z<>\[\]{}\-']*\s+){1,3}[A-Z][A-Z<>\[\]{}\-']*"
    r"),\s+[A-Z]"
    r"|^\s*_{1,3}\s*\("
    r"|^\s*(?:[A-Z][A-Z.&]+\s+){1,8}\("
)

# The parenthetical publication year, e.g. "(1991)" or "(1974b)". Checked
# separately from the opener (rather than chained directly onto it) because
# real entries interpose a variable amount of text between the opener and
# the year -- multiple authors, "eds.", "and"-joined co-authors -- that the
# opener alone does not attempt to parse.
_BIBLIOGRAPHIC_LEAF_YEAR_RE = re.compile(r"\(\d{4}[a-z]?\)")

# How many leading characters of the leaf the parenthetical year must fall
# within for the opener match above to count as a genuine citation rather
# than a coincidental one (e.g. a leaf that opens with a capitalized name
# but only happens to mention an unrelated year much later in the
# sentence). Measured against the real-OCR fixture's own longest genuine
# lead-in (a four-author "eds." entry, ~75 characters from the leaf's start
# to its "(") plus headroom -- proven via inspection, not fixture-fitted to
# a single tidy shape (the #222 mistake this fix corrects). A stated
# tunable, not a magic constant.
_BIBLIOGRAPHIC_LEAF_YEAR_WINDOW_CHARS = 80

# The minimum number of PROSE-routed descendant leaves a section must carry
# before its aggregate share is even evaluated -- guards a small, ordinary
# section against a false positive on one or two coincidentally-shaped
# leaves (mirrors `axial.router.CONTENT_APPARATUS_CITATION_THRESHOLD`'s own
# conservative starting point). A stated tunable, not a magic constant.
_BIBLIOGRAPHIC_SECTION_MIN_LEAVES = 5

# The share of a section's descendant leaves that must match
# `_is_bibliographic_leaf` before the section is treated as a mis-sectioned
# bibliography rather than argument prose. Proven via inspection against
# BOTH the #222 tidy fixture (28/28, 100%) and the real-OCR fixture (18/18,
# 100%) AND the real Tilly source's own two mis-sectioned sections (31/31
# and 54/54, 100% each, `data/trees/tilly-from-mobilization-to-revolution-
# f908c910464c.json`) -- the widened opener now recognizes every one of
# these real-world shapes, so the threshold itself stays at the original,
# conservative 0.8 (comfortably below the ~100% every genuine bibliography
# actually clears) rather than being loosened to compensate for a narrow
# opener (#222's mistake). Both control fixtures' in-passing citations
# still sit at 0% share (never matching the leading-anchor opener), and a
# corpus-wide audit across every cached `data/trees/*.json` tree found no
# other source whose legitimate intro/conclusion prose crosses this
# threshold. A stated tunable, not a magic constant.
_BIBLIOGRAPHIC_LEAF_SHARE_THRESHOLD = 0.8


def _is_bibliographic_leaf(text: str | None) -> bool:
    """True when `text` opens like a bibliographic entry
    (`_BIBLIOGRAPHIC_LEAF_OPENER_RE`, one of three real-world citation
    shapes) AND carries a parenthetical publication year within the first
    `_BIBLIOGRAPHIC_LEAF_YEAR_WINDOW_CHARS` characters -- the combination
    guards against a leaf that merely opens with a capitalized name/acronym
    but is not actually a citation entry."""
    if not text:
        return False
    if not _BIBLIOGRAPHIC_LEAF_OPENER_RE.match(text):
        return False
    year_match = _BIBLIOGRAPHIC_LEAF_YEAR_RE.search(text)
    return bool(year_match and year_match.start() <= _BIBLIOGRAPHIC_LEAF_YEAR_WINDOW_CHARS)


def _section_body_leaves(node: dict) -> list[str]:
    """PROSE-routed descendant leaf texts under `node`'s children (§7.8's
    shared router) -- the exact population `_matched_section_blocks` turns
    into evidence, and the same population `_is_bibliographic_aggregate_section`
    evaluates its share over, so the two can never drift apart."""
    return [
        leaf.get("text")
        for child in node.get("children", [])
        for leaf, route in iter_routed_blocks(child, in_back_matter_section=False)
        if route == PROSE
    ]


def _is_bibliographic_aggregate_section(node: dict) -> bool:
    """True when `node` (a matched intro/abstract/conclusion section) is a
    mis-sectioned bibliography: its descendant leaves are overwhelmingly
    single-citation / bibliographic entries (PRD §7.3, "Bibliography-by-
    aggregate exclusion", #222). An aggregate signal across the section's
    descendants -- never a per-block density check (that's
    `axial.router.is_content_apparatus_candidate`, a different granularity,
    §7.8). Conservative: too few leaves to judge (below
    `_BIBLIOGRAPHIC_SECTION_MIN_LEAVES`) or too low a matching share (below
    `_BIBLIOGRAPHIC_LEAF_SHARE_THRESHOLD`) both return False -- when
    uncertain, the section stays prose."""
    leaves = _section_body_leaves(node)
    if len(leaves) < _BIBLIOGRAPHIC_SECTION_MIN_LEAVES:
        return False
    bibliographic = sum(1 for text in leaves if _is_bibliographic_leaf(text))
    return (bibliographic / len(leaves)) >= _BIBLIOGRAPHIC_LEAF_SHARE_THRESHOLD


def _prune_bibliographic_sections(tree: dict) -> dict:
    """Return a shallow-pruned copy of `tree` with any top-level matched
    envelope section that `_is_bibliographic_aggregate_section` flags having
    its children emptied out. `_matched_section_blocks` already excludes such
    a section from the matched-section evidence on its own; this pruning is
    for the *head-of-tree widen* (`_head_of_tree_lines`), which walks the
    WHOLE tree in order and would otherwise still surface the same excluded
    citation wall once the walk reaches it (#222) -- pruning keeps both
    paths' exclusion in sync without re-deriving the detector twice."""
    pruned_children = [
        {**child, "children": []}
        if _is_envelope_heading(child) and _is_bibliographic_aggregate_section(child)
        else child
        for child in tree.get("children", [])
    ]
    return {**tree, "children": pruned_children}


def _matched_section_blocks(tree: dict) -> list[str]:
    """Build one text block per matched intro/abstract/conclusion node: the
    section's own heading plus its PROSE-routed descendants' text (§7.8: the
    shared source router, `axial.router.route_for`, is the single
    prose/non-prose classification -- this function never re-derives it).
    Descendant blocks the router routes to ARTIFACT (e.g. `table`, `caption`)
    or APPARATUS (e.g. `document_index`, `footnote`, running heads) are
    dropped before they reach the §7.3 evidence floor or the prompt, exactly
    like `_head_of_tree_lines` below (issue #216). `in_back_matter_section`
    is always False here: a matched intro/abstract/conclusion section is
    front/body matter by construction, never back-matter, so an in-section
    `list_item` is legitimately prose. The node's own text is always the
    `## heading` line itself (`heading = node.get("text", "")`), so it is not
    also repeated as the first body line -- only descendants' PROSE text is
    appended below the heading, avoiding a verbatim duplicate line without
    dropping any content (the own text still appears once, in the heading)."""
    blocks = []
    for node in select_envelope_nodes(tree):
        if _is_bibliographic_aggregate_section(node):
            # PRD §7.3 "Bibliography-by-aggregate exclusion" (#222): excluded
            # from the matched-section evidence before the evidence-floor
            # check ever sees it -- never appended as a block at all.
            continue
        heading = node.get("text", "")
        body_lines = _section_body_leaves(node)
        block = f"## {heading}"
        if body_lines:
            block += "\n" + "\n".join(body_lines)
        blocks.append(block)
    return blocks


def _truncate_at_boundary(text: str, limit: int) -> str:
    """Truncate `text` to at most `limit` characters, preferring to cut at
    the nearest preceding whitespace boundary so a word isn't sliced
    mid-token. Falls back to a hard character cut when no boundary is close
    enough to the limit (e.g. one very long unbroken token), so the result
    is never longer than `limit` either way. Deterministic."""
    if len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    cut = text.rfind(" ", 0, limit)
    # Only honor the boundary if it doesn't throw away most of the budget
    # (e.g. a single 38k-char paragraph with no early space).
    if cut > limit // 2:
        return text[:cut]
    return text[:limit]


# --- Front-matter / apparatus prefix skip (PRD §7.3, #222) ------------------
#
# The head-of-tree widen reads real, PROSE-routed content (title page,
# copyright/ISBN, publisher boilerplate are all labelled `title`/`text` --
# the router does not drop them, §7.8), so a source whose head-of-tree opens
# with a run of front matter would otherwise hand the model boilerplate
# instead of argument prose. This is a CONTENT-basis skip, not a routing
# decision: it inspects the node's own `label` plus recognizable copyright-
# page markers, distinct from `axial.router.route_for`'s PROSE/ARTIFACT/
# APPARATUS classification.

# A docling `title` label is, on its own, a reliable front-matter signal --
# a title page is never the source's own argument prose.
_FRONT_MATTER_TITLE_LABEL = "title"

# High-confidence copyright-page structural markers only (reviewer finding,
# #222 stage-2): a bare occurrence of a common word like "copyright",
# "publisher", or "printed" is NOT sufficient on its own -- a genuine
# argument paragraph can easily contain one of those words in passing (e.g.
# "...printed in provincial presses...", "...the publisher of this
# journal..."), and silently dropping real prose on a lone-word match would
# undermine the very minimum-evidence / grounded-by-construction guarantee
# this feature exists to protect (never-drop-on-uncertainty, §7.8's own
# framing). Every alternative below is a STRUCTURAL copyright-page signal
# that essentially never appears inside body argument prose:
#   - the "©" symbol itself;
#   - "all rights reserved" (a fixed legal phrase, not a word in passing);
#   - "library of congress" (a cataloguing-in-publication line);
#   - an ISBN NUMBER (the word "isbn" followed by a real digit run, not the
#     bare word alone);
#   - a bare-year copyright line ("copyright 1998", "copyright (c) 1998" --
#     "copyright" immediately bound to a year, not the word alone);
#   - classic reproduction-permission legalese ("...may be reproduced
#     ... without ... permission...", the standard "no part of this
#     publication may be reproduced without permission" boilerplate found on
#     virtually every copyrighted book's imprint page).
_FRONT_MATTER_BOILERPLATE_RE = re.compile(
    r"©"
    r"|\ball rights reserved\b"
    r"|\blibrary of congress\b"
    r"|\bisbn\b[^a-zA-Z0-9]{0,20}\d{3,}"
    r"|\bcopyright\s*(?:\(c\)\s*)?\d{4}\b"
    r"|\breproduced\b[^.]{0,40}\bwithout\b[^.]{0,20}\bpermission\b",
    re.IGNORECASE,
)

# Bound on how many total characters of leading GENERIC front matter --
# a docling `title`-labelled block, a high-confidence copyright/ISBN marker
# block (`_FRONT_MATTER_BOILERPLATE_RE`), or an ambiguous SHORT fragment
# sitting between two such anchors (a bare page-number run, a one-line
# author/affiliation credit, a one-word "Tables"/"Figures" heading) -- may
# ever be skipped. Deliberately kept SMALL: this is NOT the tunable that
# bounds an explicitly heading-recognized front-matter SECTION, which is
# routinely much longer prose (see `_FRONT_MATTER_SECTION_SKIP_CHARS`
# below) -- proven via inspection against both the real Tilly source (its
# own title-page + copyright/ISBN + dedication + Contents/Tables fragments
# sum to 887 characters, `data/trees/tilly-from-mobilization-to-revolution-
# f908c910464c.json`) and the front-matter-region fixture (503 characters,
# `tests/fixtures/envelope/frontmatter_region_tree.json`) -- comfortable
# headroom over both while staying small enough that
# `tests/test_envelope.py::test_head_of_tree_lines_front_matter_skip_is_
# bounded`'s own single 3200-character oversized marker-matched block still
# exceeds it (that regression's own invariant: a single block that alone
# blows the budget is never skipped).
_FRONT_MATTER_PREFIX_SKIP_CHARS = 2000

# Bound on how many total characters an explicitly heading-recognized
# front-matter SECTION (`_FRONT_MATTER_SECTION_HEADING_KEYWORDS` --
# preface, acknowledgements/acknowledgments, foreword) may contribute to
# the skip, tracked separately from `_FRONT_MATTER_PREFIX_SKIP_CHARS`
# above: a genuine preface/acknowledgements run is routinely far longer
# than an ambiguous title-page fragment or a single copyright block, yet is
# unambiguously identified by its own heading rather than guessed at by
# length. Proven via inspection: the real Tilly source's own Preface
# section is 4388 characters (heading + body, `data/trees/tilly-from-
# mobilization-to-revolution-f908c910464c.json`); the front-matter-region
# fixture's own Preface is 1238 characters. Set with real headroom over the
# larger of the two while remaining an explicit, bounded cap -- an
# unusually long preface (e.g. `data/trees/mann-sources-of-social-power-
# v1-...json`'s own "Preface to the new edition", which runs past fifty
# thousand characters) still hits this bound and stops being skipped rather
# than consuming an unbounded share of the source.
_FRONT_MATTER_SECTION_SKIP_CHARS = 6000

# The maximum combined PROSE-routed character length (a top-level child's
# own heading text plus all its PROSE-routed descendant text) for that
# child to count as an ambiguous SHORT fragment -- a bare page-number run,
# a one-line author/affiliation credit, a one-word "Tables"/"Figures"
# heading -- rather than a genuine body paragraph. Chosen well above every
# such fragment actually observed across a corpus-wide survey of
# `data/trees/*.json` (typically 5-90 characters; the longest, a padded
# "CONTENTS" heading, reached 188) while staying well below a real short
# paragraph or abstract opening (this module's own `_EVIDENCE_FLOOR_CHARS`,
# 200, is the size below which even a MATCHED intro/abstract/conclusion
# section counts as "little or no text" at all -- a genuine paragraph is
# routinely several times that).
_FRONT_MATTER_FRAGMENT_CHARS = 200

# Front-matter SECTION heading keywords (case-insensitive substring match,
# checked ONLY against a `section_header`/`title`-labelled node's own
# heading text, never its descendants' body text -- so an ordinary argument
# paragraph that happens to mention "acknowledgements" in passing is never
# affected). Deliberately narrow: three genuinely verbose front-matter
# section types that `_FRONT_MATTER_FRAGMENT_CHARS`'s length-based fragment
# check alone cannot catch, because a real preface/acknowledgements/
# foreword routinely runs to several thousand characters (see
# `_FRONT_MATTER_SECTION_SKIP_CHARS` above). "prefaee" is the real,
# OCR-garbled spelling docling actually produced for the real Tilly
# source's own "Preface" heading (a single letter substitution, c -> e,
# found via inspection of `data/trees/tilly-from-mobilization-to-
# revolution-f908c910464c.json`) -- included literally, mirroring #222's
# own widening to real-OCR shapes, rather than a broad fuzzy prefix match
# (which would risk matching an unrelated chapter title like "Preferences
# and Rational Action"). A corpus-wide survey found no book whose
# Contents/Tables/Figures/dedication heading needed a keyword at all -- in
# every case that content was small enough for the length-based fragment
# check above to catch on its own.
_FRONT_MATTER_SECTION_HEADING_KEYWORDS = (
    "preface",
    "prefaee",
    "acknowledg",  # covers acknowledgement(s)/acknowledgment(s)
    "foreword",
)


def _is_front_matter_prefix_block(leaf: dict) -> bool:
    """True when `leaf` looks like leading front matter / apparatus on a
    content basis: either its own `label` is `title`, or its text carries a
    HIGH-CONFIDENCE copyright-page structural marker
    (`_FRONT_MATTER_BOILERPLATE_RE`) -- never a bare occurrence of a common
    word like "copyright", "publisher", or "printed" (reviewer finding,
    #222 stage-2: a genuine argument paragraph can easily contain one of
    those words in passing, and dropping it on that alone would be exactly
    the false-drop-on-uncertainty this feature must never commit). Proven
    against both directions: the existing `document_index`-skip fixture
    (no `title` label, no marker) must still surface its short prose line
    unskipped, and a genuine paragraph that merely contains "printed in"
    must also survive unskipped."""
    label = (leaf.get("label") or "").strip().lower()
    if label == _FRONT_MATTER_TITLE_LABEL:
        return True
    text = leaf.get("text") or ""
    return bool(_FRONT_MATTER_BOILERPLATE_RE.search(text))


def _prose_chars_in_subtree(node: dict) -> int:
    """Combined length of every PROSE-routed leaf's own text under `node`
    (inclusive of `node` itself), via the shared router (§7.8). This is the
    exact accounting the eventual per-leaf collection walk in
    `_head_of_tree_lines` applies, so a top-level child's measured size here
    matches what it would actually cost the widened slice if collected
    whole."""
    return sum(
        len(leaf.get("text") or "")
        for leaf, route in iter_routed_blocks(node, in_back_matter_section=False)
        if route == PROSE
    )


def _is_front_matter_section_heading(node: dict) -> bool:
    """True when `node` is itself a heading-labelled node (`section_header`
    or `title`) whose own heading text names a known VERBOSE front-matter
    section -- preface, acknowledgements/acknowledgments, or foreword
    (`_FRONT_MATTER_SECTION_HEADING_KEYWORDS`). Checked only against the
    node's OWN text, never a descendant's body text, so an ordinary
    argument paragraph that happens to mention one of these words in
    passing is never affected."""
    label = (node.get("label") or "").strip().lower()
    if label not in (_FRONT_MATTER_TITLE_LABEL, "section_header"):
        return False
    text = (node.get("text") or "").strip().lower()
    return any(keyword in text for keyword in _FRONT_MATTER_SECTION_HEADING_KEYWORDS)


def _subtree_has_front_matter_leaf(node: dict) -> bool:
    """True when any leaf within `node`'s own subtree (inclusive of `node`
    itself) is a front-matter-flagged leaf per `_is_front_matter_prefix_block`
    (a docling `title` label, or a high-confidence copyright/ISBN marker) --
    applied across a WHOLE top-level child, not just its own first line, so
    a marker buried under an ordinary heading (e.g. the legal boilerplate
    paragraph nested under a plain "First Edition" heading, as in the real
    Tilly source) still flags the whole child as front matter."""
    return any(
        _is_front_matter_prefix_block(leaf)
        for leaf, _route in iter_routed_blocks(node, in_back_matter_section=False)
    )


def _front_matter_region_end(children: list[dict]) -> int:
    """How many of `children` (a tree's top-level children, in reading
    order) form a leading front-matter REGION to skip whole, replacing the
    old "the first non-flagged block ends the skip for good" rule (the real
    Tilly defect this fixes): a real title page routinely opens with an
    untagged `section_header`/`text` block -- the book's own title, an
    author/affiliation line -- carrying no docling `title` label and no
    copyright marker, so a rule that ends the skip at the very first
    unflagged block never gets past it, and the whole front-matter/preface
    region leaks into the evidence.

    Walks `children` in order, classifying each as one of:

    - a high-confidence ANCHOR: a docling `title`-labelled block, a block
      carrying a high-confidence copyright/ISBN marker anywhere in its
      subtree (`_subtree_has_front_matter_leaf`), or a heading-recognized
      preface/acknowledgements/foreword section
      (`_is_front_matter_section_heading`) -- skipped regardless of its own
      length. A heading-recognized section is bounded by
      `_FRONT_MATTER_SECTION_SKIP_CHARS` (these routinely run long); a
      title-label/marker anchor is bounded by `_FRONT_MATTER_PREFIX_SKIP_CHARS`
      (these are routinely short);
    - an ambiguous SHORT FRAGMENT (`_prose_chars_in_subtree` at or under
      `_FRONT_MATTER_FRAGMENT_CHARS`) that still has real, longer content
      somewhere later in `children` -- e.g. a bare page-number run or a
      one-line "Tables" heading sitting between two anchors -- skipped the
      same way, bounded by `_FRONT_MATTER_PREFIX_SKIP_CHARS`;
    - anything else (a long, unrecognized block, or a short block with
      nothing substantial left after it -- the tree's own tail) ENDS the
      region here.

    Returns 0 -- skip nothing -- unless at least one genuine ANCHOR was
    found among the skipped children: a source with no title label, no
    copyright/ISBN marker, and no recognized preface/acknowledgements/
    foreword heading anywhere in its leading run gives no positive evidence
    it has any front matter at all, so an ambiguous short leading fragment
    (e.g. a short one-line paper title, or a short opening abstract) is
    never swept on length alone -- guards a born-digital source that opens
    directly with its own short prose (never-drop-on-uncertainty, #222's own
    framing)."""
    if not children:
        return 0

    prose_chars = [_prose_chars_in_subtree(child) for child in children]
    # suffix_max[i] = the largest prose_chars value at or after index i (0
    # once nothing remains), used to answer "is there real, longer content
    # somewhere later" in O(1) per child rather than rescanning the tail.
    suffix_max = [0] * (len(children) + 1)
    for i in range(len(children) - 1, -1, -1):
        suffix_max[i] = max(prose_chars[i], suffix_max[i + 1])

    region_end = 0
    saw_anchor = False
    marker_budget_used = 0
    section_budget_used = 0

    for index, child in enumerate(children):
        chars = prose_chars[index]

        if _is_front_matter_section_heading(child):
            if section_budget_used + chars > _FRONT_MATTER_SECTION_SKIP_CHARS:
                break
            section_budget_used += chars
            saw_anchor = True
            region_end = index + 1
            continue

        if _subtree_has_front_matter_leaf(child):
            if marker_budget_used + chars > _FRONT_MATTER_PREFIX_SKIP_CHARS:
                break
            marker_budget_used += chars
            saw_anchor = True
            region_end = index + 1
            continue

        is_fragment = chars <= _FRONT_MATTER_FRAGMENT_CHARS
        has_more_ahead = suffix_max[index + 1] > _FRONT_MATTER_FRAGMENT_CHARS
        if not (is_fragment and has_more_ahead):
            break
        if marker_budget_used + chars > _FRONT_MATTER_PREFIX_SKIP_CHARS:
            break
        marker_budget_used += chars
        region_end = index + 1

    return region_end if saw_anchor else 0


def _head_of_tree_lines(tree: dict, max_chars: int = _HEAD_OF_TREE_SLICE_CHARS) -> list[str]:
    """Walk the tree in stable pre-order (root -> children, depth-first --
    the document's own reading order per `axial.extract._build_tree`) via the
    shared source router (`axial.router.iter_routed_blocks`, §7.8), keeping
    only PROSE-routed blocks -- a `document_index` (TOC), `table`, `caption`,
    `footnote`, or `page_header`/`page_footer` block routes to ARTIFACT/
    APPARATUS and is skipped, never diluting the "substantive" head-of-tree
    slice with non-prose front matter (issue #216). `in_back_matter_section`
    is always False: the head-of-tree region is by definition the START of
    the source, never back-matter, so an in-body `list_item` is legitimately
    prose. Collection stops once the length of the *joined* slice (i.e.
    `"\\n".join(lines)`, exactly what `compose_prompt` assembles) would reach
    `max_chars`. Each candidate line's cost includes the `"\\n"` separator
    that joins it to the previous line, so the accounting matches what
    actually lands in the prompt -- not merely the sum of the nodes' own text
    lengths. A single node whose own text would overrun the remaining budget
    is truncated (at a word boundary where possible, #201 finding 2) rather
    than appended whole. Together this means the length of
    `"\\n".join(_head_of_tree_lines(tree))` never exceeds `max_chars`,
    regardless of node count or fragmentation -- a large source (e.g. one
    huge un-split paragraph) can't blow the bound via a single node, and
    neither can a tree of thousands of tiny text nodes blow it via
    unaccounted-for join separators (#201 follow-up finding). Deterministic:
    the same tree always yields the same slice (PRD §7.3, "a bounded prefix
    of the source's own prose, taken in tree order").

    Before any of that, it skips a leading front-matter REGION (title page,
    copyright/ISBN block, publisher boilerplate, preface scaffolding) via
    `_front_matter_region_end`, computed once over `tree`'s top-level
    children: unlike the walk's own line-by-line collection, the region-skip
    decision operates at top-level-child granularity, because a real title
    page's own opening block routinely carries neither a docling `title`
    label nor a copyright marker (the real Tilly defect this replaces an
    earlier, narrower rule for) -- only the REGION shape (short, ambiguous
    fragments and verbose, heading-recognized sections sitting between
    genuine anchors) reveals it. The region is never entered at all unless
    at least one genuine anchor is found (see `_front_matter_region_end`),
    so a source with no front matter keeps its own opening prose untouched."""
    children = tree.get("children", [])
    region_end = _front_matter_region_end(children)
    remaining_tree = {"children": children[region_end:]}

    lines: list[str] = []
    total = 0

    for leaf, route in iter_routed_blocks(remaining_tree, in_back_matter_section=False):
        if route != PROSE:
            continue
        text = leaf.get("text")
        separator_cost = 1 if lines else 0
        remaining = max_chars - total - separator_cost
        if remaining <= 0:
            break
        if len(text) > remaining:
            truncated = _truncate_at_boundary(text, remaining)
            if truncated:
                lines.append(truncated)
                total += separator_cost + len(truncated)
            break
        lines.append(text)
        total += separator_cost + len(text)
        if total >= max_chars:
            break

    return lines


def _substantive_length(text: str) -> int:
    """Character count of `text` with all whitespace stripped out -- so a
    block that is entirely whitespace (e.g. a matched heading whose captured
    body is blank/space-padded) measures as zero, not as however many raw
    characters it happens to occupy (PRD §7.3, "never an empty or
    whitespace-only section block", #201 finding 1)."""
    return len("".join(text.split()))


def compose_prompt(tree: dict) -> str:
    """Compose the envelope prompt from the source's intro/abstract/
    conclusion nodes (heuristic over the extraction tree's section
    headings). When that heuristic selects little or no SUBSTANTIVE text
    (PRD §7.3, "evidence floor on the input" -- measured on whitespace-
    stripped content, so raw whitespace can't clear the floor), widen
    instead to a substantive head-of-tree slice of the source's own prose,
    so the model is never handed an empty, near-empty, or whitespace-only
    evidence block (#201)."""
    blocks = _matched_section_blocks(tree)
    if sum(_substantive_length(block) for block in blocks) < _EVIDENCE_FLOOR_CHARS:
        # A section already excluded from `blocks` above (bibliography-by-
        # aggregate, #222) must not resurface via the head-of-tree walk,
        # which reads the WHOLE tree in order -- prune its children first.
        lines = _head_of_tree_lines(_prune_bibliographic_sections(tree))
        evidence = "## Source text (head-of-tree excerpt)\n" + "\n".join(lines)
    else:
        evidence = "\n\n".join(blocks)
    return _PROMPT_TEMPLATE.format(sections=evidence)


def parse_response(raw: str) -> dict[str, Any]:
    """Parse the model's raw text response as a JSON object."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise EnvelopeParseError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EnvelopeParseError(
            f"expected the model response to be a JSON object, got {type(data).__name__}: {data!r}"
        )
    return data


def validate_envelope_fields(data: dict[str, Any]) -> None:
    """Validate the required envelope fields on a parsed model response,
    raising a typed error on malformed output (PRD §7.3's four required
    fields: thesis, toc, scope, stated_argument)."""
    for field in _REQUIRED_STRING_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EnvelopeValidationError(
                f"envelope field {field!r} must be a non-empty string, got {value!r}"
            )

    toc = data.get("toc")
    if not isinstance(toc, list) or not toc:
        raise EnvelopeValidationError(f"envelope field 'toc' must be a non-empty list, got {toc!r}")


def reject_degenerate_envelope(raw: str) -> None:
    """Validator passed to `complete_json` for the envelope pass (issue #80):
    re-runs the existing `parse_response` + `validate_envelope_fields` on
    `raw` -- the SAME checks behind `EnvelopeValidationError`, never
    duplicated -- so a valid-JSON-but-degenerate response (e.g. `toc: []`)
    is a re-askable failure within `complete_json`'s bounded budget instead
    of an instant abort. After the last attempt, `validate_envelope_fields`'s
    own `EnvelopeValidationError` propagates unchanged, exactly as before
    this validator existed."""
    validate_envelope_fields(parse_response(raw))


def _fallback_title(path: Path) -> str:
    """Best-effort title derived from the filename when the model response
    doesn't supply one -- no dedicated metadata-extraction pass exists yet."""
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def build_envelope(
    path: Path, source_id: str, parsed: dict[str, Any], structural_toc: list[str] | None = None
) -> dict[str, Any]:
    """Assemble the locked envelope shape (PRD §7.3):
    {source_id, author, title, date, thesis, toc, scope, stated_argument}.

    `toc` prefers `structural_toc` (`_toc_from_tree`'s tree-derived chapter
    list) whenever it is non-empty, falling back to the model's own
    `parsed["toc"]` only when the tree yields no identifiable top-level
    heading structure -- preserving `validate_envelope_fields`'s "toc must
    be a non-empty list" guarantee, since `parsed["toc"]` is already
    validated non-empty by the time it reaches here (#227)."""
    return {
        "source_id": source_id,
        "author": parsed.get("author"),
        "title": parsed.get("title") or _fallback_title(path),
        "date": parsed.get("date"),
        "thesis": parsed["thesis"],
        "toc": structural_toc if structural_toc else parsed["toc"],
        "scope": parsed["scope"],
        "stated_argument": parsed["stated_argument"],
    }


def write_envelope(envelope: dict[str, Any], path: Path) -> None:
    """Write the envelope JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_envelope(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, Any]:
    """Run the structural-envelope pass on `source_path`.

    `envelopes_dir` defaults to `config/pipeline.yaml`'s `paths.envelopes_dir`
    (falling back to `ENVELOPES_DIR` if the file/key is absent) when not
    given explicitly, so the config-declared path is actually honored.

    Computes the stable source_id first (no LLM call needed) and checks
    `data/envelopes/<source_id>.json` before doing anything else: a cache
    hit returns the stored envelope with zero client construction/use,
    guaranteeing "no recompute" (PRD §10).
    """
    path = Path(source_path)
    source_id = compute_source_id(path)

    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)

    out_path = envelope_path(source_id, envelopes_dir)
    if out_path.exists():
        return json.loads(out_path.read_text(encoding="utf-8"))

    try:
        tree = extract(path)
    except ExtractError as exc:
        raise ExtractionFailedError(exc) from exc

    prompt = compose_prompt(tree)

    try:
        if client is None:
            client = get_client(config_path=config_path)
        raw_response = complete_json(
            client, prompt, pass_name=ENVELOPE_PASS_NAME, validate=reject_degenerate_envelope
        )
    except (LLMError, httpx.HTTPError) as exc:
        raise LLMFailedError(exc) from exc
    except ModelJsonError as exc:
        raise EnvelopeParseError(f"model response was not valid JSON: {exc}") from exc

    parsed = parse_response(raw_response)
    validate_envelope_fields(parsed)

    envelope = build_envelope(path, source_id, parsed, structural_toc=_toc_from_tree(tree))
    write_envelope(envelope, out_path)
    return envelope
