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


# --- Bibliography-by-aggregate exclusion (PRD §7.3, #222) -------------------
#
# docling sometimes mis-attaches a source's bibliography under an ordinary
# body-section heading ("Introduction", "Conclusion"), fragmented into
# individual one-citation leaf nodes. Each leaf, alone, carries far too few
# inverted-author-name matches to ever trip `axial.router`'s own per-block
# `is_content_apparatus_candidate` (that check is a DIFFERENT granularity --
# density within one block, §7.8) -- only a signal aggregated ACROSS a
# section's descendants can ever catch this, so the envelope needs its own.

# A bibliographic leaf's own opening: an inverted author name immediately
# followed by a parenthetical year, e.g. "Voskuijlen, R. (1991). ...". This
# is deliberately anchored at the START of the leaf's text (`^`) -- an
# ordinary argument sentence that merely cites a source in passing has its
# citation embedded mid-sentence, never leading the leaf, so this pattern
# does not fire on it (proven against the #222 control fixture, whose
# in-passing citations sit well past the first word).
_BIBLIOGRAPHIC_LEAF_RE = re.compile(
    r"^\s*[A-Z][A-Za-z\-']+,\s+[A-Z]\.?\s*(?:[A-Z]\.?\s*)?\(\d{4}\)"
)

# The minimum number of PROSE-routed descendant leaves a section must carry
# before its aggregate share is even evaluated -- guards a small, ordinary
# section against a false positive on one or two coincidentally-shaped
# leaves (mirrors `axial.router.CONTENT_APPARATUS_CITATION_THRESHOLD`'s own
# conservative starting point). A stated tunable, not a magic constant.
_BIBLIOGRAPHIC_SECTION_MIN_LEAVES = 5

# The share of a section's descendant leaves that must match
# `_BIBLIOGRAPHIC_LEAF_RE` before the section is treated as a mis-sectioned
# bibliography rather than argument prose. Proven via inspection against the
# #222 fixtures: the bibliography-aggregate fixture's "Conclusion" section is
# 28/28 (100%) matching leaves; the control fixture's Introduction/Conclusion
# sections are 0% (their in-passing citations sit mid-sentence, never
# matching the leading-anchor pattern above). 0.8 sits comfortably between
# the two, conservative per §7.8's never-drop-on-uncertainty principle. A
# stated tunable, not a magic constant.
_BIBLIOGRAPHIC_LEAF_SHARE_THRESHOLD = 0.8


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
    bibliographic = sum(1 for text in leaves if _BIBLIOGRAPHIC_LEAF_RE.match(text or ""))
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

# Bound on how many total characters of leading prefix may ever be skipped
# as front matter -- a stated tunable, not a magic constant, so a
# pathological source (e.g. one that is front-matter-labeled/marked from
# start to finish) can never have its ENTIRE head-of-tree slice consumed by
# the skip; it still starts counting real content once the budget runs out,
# even if that content still looks like boilerplate. Set to a quarter of
# `_HEAD_OF_TREE_SLICE_CHARS` -- generous for a real title/copyright/preface
# run (the #222 fixture's own front matter is ~310 characters, comfortably
# inside it) while leaving the model the bulk of the slice for real prose.
_FRONT_MATTER_PREFIX_SKIP_CHARS = _HEAD_OF_TREE_SLICE_CHARS // 4


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
    of the source's own prose, taken in tree order"). It also skips a
    leading front-matter / apparatus prefix (title page, copyright/ISBN,
    publisher boilerplate) before it starts counting toward `max_chars`:
    each candidate block is checked with `_is_front_matter_prefix_block`
    while still in the leading run, and skipped (not counted, not
    collected) as long as the total skipped so far stays within
    `_FRONT_MATTER_PREFIX_SKIP_CHARS`. The very first block that either
    doesn't look like front matter, or would push the skip past its bounded
    budget, ends the skip for good -- everything from there on (even a
    short block) is collected exactly as before (#222)."""
    lines: list[str] = []
    total = 0
    skipped_prefix_chars = 0
    skipping_prefix = True

    for leaf, route in iter_routed_blocks(tree, in_back_matter_section=False):
        if route != PROSE:
            continue
        text = leaf.get("text")
        if skipping_prefix:
            if (
                _is_front_matter_prefix_block(leaf)
                and skipped_prefix_chars + len(text) <= _FRONT_MATTER_PREFIX_SKIP_CHARS
            ):
                skipped_prefix_chars += len(text)
                continue
            skipping_prefix = False
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


def build_envelope(path: Path, source_id: str, parsed: dict[str, Any]) -> dict[str, Any]:
    """Assemble the locked envelope shape (PRD §7.3):
    {source_id, author, title, date, thesis, toc, scope, stated_argument}."""
    return {
        "source_id": source_id,
        "author": parsed.get("author"),
        "title": parsed.get("title") or _fallback_title(path),
        "date": parsed.get("date"),
        "thesis": parsed["thesis"],
        "toc": parsed["toc"],
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

    envelope = build_envelope(path, source_id, parsed)
    write_envelope(envelope, out_path)
    return envelope
