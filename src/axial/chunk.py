"""Chunking (charter #148): `run_chunk_recursive` (issue #165, slice 06;
retired the embedding mechanism and became the SOLE chunking mechanism as of
issue #191, spec-drift #191) is deterministic recursive descent over a
separator hierarchy (paragraph -> line -> sentence -> raw char), with ZERO
embedding-model or text-generating LLM calls anywhere in this path. A
deterministic two-sided band guard `[CHUNK_MIN, CHUNK_MAX]` wraps the
separator-hierarchy split. It reads ONLY the persisted structural tree
(`data/trees/<source_id>.json`, via `axial.extract`) -- no envelope. It
writes records to `data/chunks/<source_id>.jsonl` (PRD §7.7) -- the CLI
`chunk` subcommand's mechanism (see `src/axial/cli.py`).

`read_chunks` (issue #154, slice 04 of the chunk-redesign subproject) is the
downstream-facing reader for that same on-disk artifact: `tag.py`, `xref.py`,
and (through them) `vault.py` read chunk records from
`data/chunks/<source_id>.jsonl` via `read_chunks` instead of computing chunks
themselves. It raises `MissingChunkArtifactError` when the artifact does not
exist yet, telling the operator to run `axial chunk` first -- no downstream
pass ever recomputes chunk boundaries (PRD §8 P0-4b).

Source routing (issue #167, PRD §7.8): `run_chunk_recursive` decides
prose/non-prose not by node `type` alone. Each block in a kept section's body is
classified by its docling `label` via the shared `axial.router.route_for`
(through `_routed_section_body`'s `iter_routed_blocks` walk) into exactly one
of `prose` / `artifact` / `apparatus`. Only prose-routed text is chunked;
artifact-routed blocks (`table`, `picture`, `caption`) are excluded from
chunking but NOT recorded as a drop (they belong to the not-yet-built
artifact pass, slice 03); apparatus-routed blocks (`document_index`,
`footnote`, `page_header`/`page_footer`, a back-matter `list_item`) are
dropped and recorded to the `<source_id>.skips.jsonl` sidecar with a
route-specific reason, alongside the pre-existing garble backstop
(`_garbage_section_skip_reason`) -- the router-owned skip sidecar is now the
single source of skip truth (§7.8), not garbage-only.

`build_chunk_records` is the shared record-assembly helper: a stable,
deterministic `chunk_id` (`<source_id>_<section order>_<section slug>_<NNN>`,
derived from the source_id, the section node's already-unique `order` field,
the section's own verbatim heading, and the chunk's position within that
section -- no randomness, no timestamps) and `section` (the section's
verbatim heading text). The `order` component is required for uniqueness:
`extract.py`'s tree-builder opens a new top-level section node for every
heading in reading order without nesting, so a real source can have multiple
top-level sections sharing the same heading text (e.g. repeated
"Introduction"/"Notes"/"Conclusion" across chapters) -- the heading slug
alone would collide across them, but each section's `order` is unique by
construction.
"""

from __future__ import annotations

import json
import os
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from axial.checkpoint import load_checkpoint_records
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.extract import load_persisted_tree, tree_path
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.nonprose_guard import MAX_NON_ALPHA_RATIO, garble_only_skip_reason
from axial.router import APPARATUS, PROSE, apparatus_reason, iter_routed_blocks

CHUNKS_DIR = Path("data/chunks")


def _default_chunks_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Resolve the chunk-checkpoint directory, mirroring
    `axial.envelope._default_envelopes_dir`'s structure exactly: honor
    `config/pipeline.yaml`'s `paths.chunks_dir` when declared, else fall back
    to the module-level `CHUNKS_DIR` default (`data/chunks`, resolved relative
    to the current working directory -- the same cwd-relative convention the
    envelope/vault dirs already use, so an isolated staging root's checkpoints
    never alias the real `data/` tree). An absent file/key falls back to
    `CHUNKS_DIR`."""
    if not config_path.is_file():
        return CHUNKS_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("chunks_dir")
    return Path(configured) if configured else CHUNKS_DIR


def chunks_checkpoint_path(source_id: str, chunks_dir: Path = CHUNKS_DIR) -> Path:
    """The reuse-once path for `source_id`'s chunk-pass checkpoint (one JSON
    chunk record per line), keyed by the content-hashed source_id so an edited
    file (a new source_id) never reuses stale chunks (issue #81 point 1)."""
    return chunks_dir / f"{source_id}.jsonl"


def chunks_skips_sidecar_path(source_id: str, chunks_dir: Path = CHUNKS_DIR) -> Path:
    """The companion sidecar path for `source_id`'s router-owned skip log
    (issue #153's garble backstop, generalized by issue #167/PRD §7.8 to also
    carry apparatus drops -- the single source of skip truth), alongside its
    chunk checkpoint (`chunks_checkpoint_path`): one JSON object per line,
    exactly `{"section", "section_order", "reason"}`. `run_chunk_recursive`
    rewrites this cleanly on every call -- created only when there is >= 1
    skip, removed when a rerun has none -- mirroring the main JSONL's own
    overwrite-cleanly contract so a rerun on the same source bytes stays
    idempotent. `axial chunk examine` (a separate, later, read-only
    invocation) reads it to report sections skipped as garbage without
    re-deriving the guard."""
    return chunks_dir / f"{source_id}.skips.jsonl"


def load_chunk_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load chunk records already persisted to `path` (`run_chunk_recursive`'s
    own on-disk artifact, or -- historically -- the retired chunk-pass
    checkpoint), skipping blank lines. Returns an empty list when the file
    does not exist yet. The underlying read for `read_chunks` (below).

    Hardening (issue #104, mirroring `axial.tag.load_tag_checkpoint`): a torn
    FINAL line (a hard kill mid-write) is healed (dropped) rather than
    poisoning the read. A torn line that is NOT the last one raises
    `ChunkCheckpointCorruptError`, naming the path and the offending
    1-indexed line number. Reuses the same shared
    `axial.checkpoint.load_checkpoint_records` primitive
    `axial.tag.load_tag_checkpoint` builds on."""
    return load_checkpoint_records(path, ChunkCheckpointCorruptError)


class ChunkError(Exception):
    """Base class for all argumentative-chunking errors."""


class MissingSourceError(ChunkError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkCheckpointCorruptError(ChunkError):
    """Raised by `load_chunk_checkpoint` when a NON-final line of a chunk
    checkpoint file is not valid JSON (issue #104, mirroring
    `axial.tag.TagCheckpointCorruptError`). A torn FINAL line is healed
    (dropped) instead -- see `load_chunk_checkpoint`'s docstring; a torn line
    anywhere else is genuine corruption unrelated to a hard-kill mid-append,
    so it still raises loudly."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt chunk checkpoint {path}: line {line_no} is not valid JSON: {cause}"
        )


class MissingChunkArtifactError(ChunkError):
    """Raised by `read_chunks` when no on-disk chunk artifact exists yet for
    the source (PRD §7.7, §8 P0-4b): downstream passes (`tag`, `xref`, and
    `vault write` through them) never recompute chunk boundaries themselves
    -- the caller must run `axial chunk` first."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no chunk artifact found at {path}; run `axial chunk` on the source first"
        )


class ChunkArtifactCorruptError(ChunkError):
    """Raised by `examine_chunks` (issue #153) when a line of a chunk
    artifact -- the main `<source_id>.jsonl` or its `<source_id>.skips.jsonl`
    sidecar -- is not valid JSON. Modeled on `ChunkCheckpointCorruptError`,
    but unconditional (examine is a diagnostic read, not a resumable
    checkpoint, so there is no "torn final line" healing case to special-case
    here): any malformed line raises loudly, carrying the offending file's
    path and its 1-indexed line number so the operator can go fix it."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt chunk artifact {path}: line {line_no} is not valid JSON: {cause}"
        )


def read_chunks(
    source_id: str,
    *,
    chunks_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """Read the on-disk chunk artifact (PRD §7.7) `source_id` already has at
    `data/chunks/<source_id>.jsonl`, written by `axial chunk`
    (`run_chunk_recursive`). Resolves the path with the SAME helpers the
    writer uses (`_default_chunks_dir` / `chunks_checkpoint_path`), so reader
    and writer always agree on where the artifact lives. Returns the chunk
    records in file (section-then-position) order -- the order
    `run_chunk_recursive` wrote them in.

    Raises `MissingChunkArtifactError` if the artifact does not exist yet:
    this is a pure reader, never a recompute path (issue #154, PRD §8
    P0-4b) -- no downstream pass ever (re)derives chunk boundaries itself."""
    if chunks_dir is None:
        chunks_dir = _default_chunks_dir(config_path)
    path = chunks_checkpoint_path(source_id, chunks_dir)
    if not path.exists():
        raise MissingChunkArtifactError(path)
    return load_chunk_checkpoint(path)


_SLUG_MAX_LEN = 80


def _slugify(label: str) -> str:
    """A filesystem/id-safe slug for a section heading, used inside
    chunk_id. Falls back to "section" if the heading has no alphanumerics.

    Capped at `_SLUG_MAX_LEN` chars (issue #94): an unbounded slug -- e.g. a
    section heading that restates a paper's full title -- pushes the note
    filename (`<chunk_id>.md`, `axial.vault._note_path`) past Windows'
    260-char MAX_PATH. The cut trims back to the nearest hyphen boundary
    within the cap where one exists, so the slug never ends mid-word; a
    trailing hyphen left behind by that trim is stripped. Uniqueness is
    unaffected: `build_chunk_records` folds the section's own `order` into
    chunk_id, which already disambiguates sections whose slugs coincide."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    if len(slug) > _SLUG_MAX_LEN:
        truncated = slug[:_SLUG_MAX_LEN]
        cut = truncated.rfind("-")
        if cut > 0:
            truncated = truncated[:cut]
        slug = truncated.rstrip("-")
    return slug or "section"


# Clear non-content back-matter / boilerplate section titles that must never
# be chunked or written as vault notes (issue #113). Conservative + exact:
# only unambiguous titles match after normalization; endnotes ("Notes"),
# appendix, preface, and anything ambiguous are KEPT. OCR-mangled titles
# (e.g. tilly's index came through as the garbled section "lad ex") won't
# match here -- that residual is backstopped by the xref input guard (#111).
_BACK_MATTER_TITLES = frozenset(
    {
        "index",
        "general index",
        "subject index",
        "name index",
        "author index",
        "index of names",
        "bibliography",
        "select bibliography",
        "references",
        "reference list",
        "works cited",
        "cited works",
        "table of contents",
        "contents",
        "copyright",
        "list of figures",
        "list of tables",
        "list of illustrations",
        "list of maps",
        "list of abbreviations",
    }
)


def _is_back_matter(title: str) -> bool:
    """True if `title` is a clear non-content back-matter/boilerplate section
    (issue #113): an exact match, after normalization (lowercase, whitespace
    collapsed, surrounding punctuation stripped), against `_BACK_MATTER_TITLES`.
    Conservative by design -- a title that is merely similar (an appendix, an
    endnotes section, a chapter) is KEPT, since a false keep is cheap while a
    false drop loses real content."""
    normalized = re.sub(r"\s+", " ", title.lower()).strip(" .:-–—")
    return normalized in _BACK_MATTER_TITLES


def _section_nodes(tree: dict) -> list[dict]:
    """Top-level nodes that represent a section: opened by a heading, so
    they carry both a verbatim `text` and a `children` list. These are the
    chunking units for this pass (PRD §5 stage 4) -- a top-level node with no
    `children` key (content preceding any heading) carries no section label
    to report provenance for, so it is not a chunking unit here."""
    return [
        child for child in tree.get("children", []) if "children" in child and child.get("text")
    ]


def _routed_section_body(section: dict) -> tuple[list[str], list[dict[str, Any]]]:
    """Route every block in `section`'s body (its `children`, excluding the
    section's own heading) through the shared source router (issue #167, PRD
    §7.8) via `axial.router.iter_routed_blocks`, and split the result into
    `(prose_lines, apparatus_drops)`:

    - `prose_lines` -- ordered text of every prose-routed block (`text`,
      `section_header`, `title`, an in-body `list_item`), chunked as today.
    - `apparatus_drops` -- one router-owned skip record
      (`chunks_skips_sidecar_path`'s `{"section", "section_order", "reason"}`
      shape) per apparatus-routed block (`document_index`, `footnote`,
      `page_header`/`page_footer`, or a back-matter `list_item`): dropped,
      never chunked, each with a route-specific reason
      (`axial.router.apparatus_reason`).

    Artifact-routed blocks (`table`, `picture`, `caption`) contribute to
    NEITHER list -- excluded from chunking, but not a "drop" (§7.8: they are
    routed to the not-yet-built artifact pass, slice 03, not lost).

    `in_back_matter_section` (the router's own `list_item` rule, §7.8) is
    derived here from THIS section's own heading via `_is_back_matter` --
    the same title-based check `run_chunk_recursive` already uses to filter
    whole back-matter sections before this function ever sees them, so it is
    always `False` in the wiring below today; it stays correct in isolation
    (and for any future caller that stops pre-filtering whole sections) since
    it is derived independently, right here, from this section's own text.
    """
    section_label = section.get("text", "")
    section_order = section.get("order", "")
    in_back_matter_section = _is_back_matter(section_label)

    prose_lines: list[str] = []
    apparatus_drops: list[dict[str, Any]] = []
    for child in section.get("children", []):
        for node, route in iter_routed_blocks(child, in_back_matter_section=in_back_matter_section):
            if route == PROSE:
                text = node.get("text")
                if text:
                    prose_lines.append(text)
            elif route == APPARATUS:
                apparatus_drops.append(
                    {
                        "section": section_label,
                        "section_order": node.get("order", section_order),
                        "reason": apparatus_reason(node.get("label")),
                    }
                )
            # route == ARTIFACT: excluded from chunking, not a drop (§7.8).
    return prose_lines, apparatus_drops


def build_chunk_records(
    source_id: str, section_order: str, section_label: str, chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Assemble chunk records carrying a stable, deterministic `chunk_id`
    (`<source_id>_<section order>_<section slug>_<NNN>`), `section` (the
    section's own verbatim heading), and `section_order` (the section node's
    own verbatim `order` field, e.g. "1", "2" -- issue #104: the per-section
    checkpoint's own provenance, letting a resume tell which sections are
    already durably persisted without re-deriving it by parsing chunk_id),
    per PRD §8 P0-4.

    `section_order` is also folded into chunk_id specifically so that two
    distinct top-level sections sharing the same heading text (extract.py
    opens a fresh section node per heading occurrence, unnested) never
    collide on chunk_id -- the heading slug alone is not unique across a
    real multi-chapter source.
    """
    slug = _slugify(section_label)
    order_key = section_order.replace(".", "-") if section_order else "0"
    records = []
    for index, chunk in enumerate(chunks, start=1):
        records.append(
            {
                "chunk_id": f"{source_id}_{order_key}_{slug}_{index:03d}",
                "section": section_label,
                "section_order": section_order,
                "text": chunk["text"],
            }
        )
    return records


# =============================================================================
# Band constants + shared errors (PRD §5 stage 4 / §7.7 / §8 P0-4)
# =============================================================================

# Band constants (character counts, matching PRD §7.7's "text length"):
# sensible STARTING POINTS anchored on PRD §7.7's "what the vault stores and
# works downstream today (~1-3k characters per chunk)" -- NOT proven-final
# values. Proving/tuning these is the operational `axial chunk examine` loop
# (slice 03), which reads real corpus chunk-size distributions off the
# on-disk artifact; this slice ships a working default, not a tuned one.
CHUNK_MIN = 1000
CHUNK_MAX = 3000


class MissingTreeError(ChunkError):
    """Raised when no persisted structural tree exists yet for the source
    (PRD §5 stage 4, "the stage reads the persisted structural tree only") --
    this chunk stage never runs docling/Unstructured itself; the
    caller must run `axial extract` first."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no persisted tree found at {path}; run `axial extract` on the source first"
        )


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def segment_sentences(text: str) -> list[str]:
    """A deterministic, dependency-free sentence segmenter: split on
    whitespace immediately following a sentence-ending punctuation mark
    (`.`, `!`, `?`).

    In-slice decision: no abbreviation/decimal-number handling, and no
    heavier NLP dependency (e.g. nltk's punkt, spaCy) -- disproportionate to
    this slice's 80/20 bar. An occasional over-split (e.g. "Dr. Smith" -> two
    pieces) only ever makes a candidate unit SMALLER, which the MIN-side band
    guard already tolerates and corrects (small pieces merge forward); it
    never produces an oversized, unsplittable unit, which is the failure
    mode that actually matters for the band guarantee.
    """
    stripped = text.strip()
    if not stripped:
        return []
    return [piece.strip() for piece in _SENTENCE_SPLIT_RE.split(stripped) if piece.strip()]


def _group_char_len(group: list[str]) -> int:
    return len(" ".join(group))


def _hard_split_by_chars(text: str, chunk_max: int) -> list[str]:
    """Last-resort fallback for a single "sentence" that alone exceeds
    `chunk_max` (e.g. a run-on with no internal sentence-ending punctuation
    for the segmenter to find): split it on raw character boundaries so the
    MAX-side guarantee ("no record exceeds CHUNK_MAX -- no exception") holds
    even in this degenerate case."""
    if not text:
        return []
    return [text[i : i + chunk_max] for i in range(0, len(text), chunk_max)]


def _enforce_min(groups: list[list[str]], chunk_min: int) -> list[list[str]]:
    """MIN-side band guard (PRD §5 stage 4 / §8 P0-4): a below-`chunk_min`
    chunk merges forward into the next one, within this call's own section
    only (callers never pass groups spanning two sections). Merging
    repeats until the accumulated group reaches `chunk_min`, so only the
    LAST group in the returned list can end up below `chunk_min` -- exactly
    the documented exception (a section's last chunk, or a whole section
    shorter than `chunk_min`, may remain below it)."""
    if not groups:
        return []
    merged: list[list[str]] = [list(groups[0])]
    for group in groups[1:]:
        if _group_char_len(merged[-1]) < chunk_min:
            merged[-1].extend(group)
        else:
            merged.append(list(group))
    return merged


def _garbage_section_skip_reason(
    text: str, max_non_alpha_ratio: float = MAX_NON_ALPHA_RATIO
) -> str | None:
    """The non-alpha arm ONLY of the shared `axial.nonprose_guard` heuristic
    (PRD §5 stage 4 / §7.7 / §8 P0-4: "size never triggers a skip" for this
    chunk stage -- an oversized but legitimate section is SPLIT, never
    skipped). Delegates to `axial.nonprose_guard.garble_only_skip_reason`
    (issue #169, source-router slice 04, which lifted this stage's own
    "non-alpha arm ONLY" precedent into the shared module so `axial.chunk`,
    `axial.tag`, and `axial.xref` share one definition instead of three
    copies) rather than `non_prose_skip_reason` directly, since that
    function's size arm would skip on size too; this stage's own MAX-side
    band guard (`_recursive_split_text`) is what handles size instead."""
    return garble_only_skip_reason(text, max_non_alpha_ratio=max_non_alpha_ratio)


_BLANK_PAGE_NOTICE_NORMALIZED = "this page intentionally left blank"


def _fragment_floor_reason(text: str) -> str | None:
    """Post-split fragment floor (issue #193, PRD §7.8 "Post-split fragment
    floor (#193)"): classify one emitted candidate chunk as unambiguous
    non-content boilerplate, or `None` when it must be kept.

    Runs AFTER the section splitter and the band guard, on individual
    emitted chunks (not at the section level, unlike
    `_garbage_section_skip_reason`) -- the leaking crumbs this floor targets
    are section *tails* whose parent section is legitimate prose, so a
    section-level filter never sees them (§7.8's own root-cause note).

    Drops exactly two unambiguous shapes, in order:
    - a **blank-page notice**: `text`, lowercased and whitespace-collapsed
      (`re.sub(r"\\s+", " ", text).strip().lower()`), equals
      `"this page intentionally left blank"` exactly.
    - a **no-alphabetic-content fragment**: `text` contains zero alphabetic
      characters (`not any(c.isalpha() for c in text)`) -- only digits,
      punctuation, whitespace, or symbols (e.g. `"6"`, `"200..."`, `"13)."`).

    Protection invariant (first-class, not a side effect, §7.8 "Genuine
    short prose is protected"): any chunk containing an alphabetic word is
    KEPT (`None`) -- length alone never triggers a drop. An empty string
    also returns `None` (nothing to drop; the splitter never emits blank
    pieces in practice, but this keeps the helper total and safe)."""
    if not text:
        return None

    normalized = re.sub(r"\s+", " ", text).strip().lower()
    if normalized == _BLANK_PAGE_NOTICE_NORMALIZED:
        return "fragment floor: blank-page notice"

    if not any(c.isalpha() for c in text):
        return "fragment floor: no alphabetic content"

    return None


def _resolve_chunk_inputs(source_path: str | Path) -> tuple[str, dict]:
    """Shared first step for the chunk stage (issue #165, slice 06):
    compute `source_id` and load its persisted structural tree, raising
    `MissingSourceError` / `MissingTreeError` before any chunking work.
    Never runs extraction itself -- reads only the persisted tree
    (`axial.extract.load_persisted_tree`)."""
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    tp = tree_path(source_id)
    if not tp.exists():
        raise MissingTreeError(tp)
    tree = load_persisted_tree(tp)
    return source_id, tree


def _write_chunk_sections(
    source_id: str,
    tree: dict,
    join_body: Callable[[list[str]], str],
    split_section: Callable[[str], list[str]],
    chunks_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """The per-section routing/writing orchestrator the chunk stage uses
    (issue #165, slice 06): walk the tree's top-level sections (skipping
    back-matter), route each section's body through the shared source
    router (`_routed_section_body`, issue #167/PRD §7.8), join the routed
    prose lines with `join_body` (`run_chunk_recursive`'s `"\n\n".join`),
    skip a garbage section exactly as before, split the joined body with
    `split_section` (the recursive/structural splitter), assemble records
    via the shared `build_chunk_records` (`chunk_id` scheme / field set /
    section-then-position order, PRD §7.7), and write them plus the
    `.skips.jsonl` sidecar."""
    if chunks_dir is None:
        chunks_dir = _default_chunks_dir(config_path)
    out_path = chunks_checkpoint_path(source_id, chunks_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sections = [node for node in _section_nodes(tree) if not _is_back_matter(node.get("text", ""))]

    skips_path = chunks_skips_sidecar_path(source_id, chunks_dir)
    skip_records: list[dict[str, Any]] = []

    all_records: list[dict[str, Any]] = []
    out_lines: list[str] = []
    for section in sections:
        body_lines, apparatus_drops = _routed_section_body(section)
        skip_records.extend(apparatus_drops)
        if not body_lines:
            continue  # no chunkable prose in this section -- zero records

        section_label = section.get("text", "")
        section_order = section.get("order", "")
        body_text = join_body(body_lines)

        skip_reason = _garbage_section_skip_reason(body_text)
        if skip_reason is not None:
            print(f"chunk: skipping section {section_label!r}: {skip_reason}", file=sys.stderr)
            skip_records.append(
                {
                    "section": section_label,
                    "section_order": section_order,
                    "reason": skip_reason,
                }
            )
            continue

        chunk_texts = split_section(body_text)

        # Post-split fragment floor (issue #193, PRD §7.8): drop any
        # candidate that is unambiguous non-content boilerplate (a
        # blank-page notice or a zero-alphabetic-content fragment) before it
        # ever reaches the on-disk artifact, recording each drop to the
        # router-owned skip sidecar. Length alone never triggers a drop --
        # any chunk carrying an alphabetic word survives.
        kept_chunk_texts: list[str] = []
        for chunk_text in chunk_texts:
            fragment_floor_reason = _fragment_floor_reason(chunk_text)
            if fragment_floor_reason is not None:
                skip_records.append(
                    {
                        "section": section_label,
                        "section_order": section_order,
                        "reason": fragment_floor_reason,
                    }
                )
                continue
            kept_chunk_texts.append(chunk_text)

        section_records = build_chunk_records(
            source_id,
            section_order,
            section_label,
            [{"text": chunk_text} for chunk_text in kept_chunk_texts],
        )
        for record in section_records:
            out_lines.append(json.dumps(record) + "\n")
        all_records.extend(section_records)

    # Atomic (issue #185): accumulate the full artifact in memory, write it
    # to a sibling temp file, then `os.replace` it over `out_path` ONCE.
    # `open("w")` on `out_path` directly would truncate the prior complete
    # artifact at the start of the run, so a hard kill mid-run left a torn
    # file already in place of the good one; `os.replace` is a single
    # filesystem rename, so a reader always sees either the complete prior
    # file or the complete new one.
    out_tmp_path = out_path.with_name(out_path.name + ".tmp")
    out_tmp_path.write_text("".join(out_lines), encoding="utf-8")
    os.replace(out_tmp_path, out_path)

    if skip_records:
        skips_tmp_path = skips_path.with_name(skips_path.name + ".tmp")
        skips_tmp_path.write_text(
            "".join(json.dumps(record) + "\n" for record in skip_records), encoding="utf-8"
        )
        os.replace(skips_tmp_path, skips_path)
    elif skips_path.exists():
        # A rerun on the same source bytes with zero skips this time must
        # not leave a stale sidecar from an earlier run (idempotency).
        skips_path.unlink()

    return all_records


# =============================================================================
# Recursive/structural chunk stage (issue #165, slice 06 of the
# chunk-redesign subproject; the SOLE chunk mechanism as of issue #191, PRD
# §5 stage 4 / §7.7 / §8 P0-4)
# =============================================================================
#
# Deterministic recursive descent over a separator hierarchy -- paragraph
# (`\n\n`) -> line (`\n`) -> sentence (`segment_sentences`) -> raw char
# (`_hard_split_by_chars`) -- with ZERO embedding-model or text-generating
# LLM calls anywhere in this path. Writes the §7.7 artifact
# (`build_chunk_records`) via the shared per-section routing/writing
# orchestrator (`_write_chunk_sections`).


def _split_level_paragraph(text: str) -> list[str]:
    """Level 0 of the recursive separator hierarchy: split on a blank-line
    paragraph break (`\n\n`, one per docling prose block once
    `run_chunk_recursive` joins them -- see this module's own docstring/the
    slice plan's pre-flight decision)."""
    return [piece.strip() for piece in text.split("\n\n") if piece.strip()]


def _split_level_line(text: str) -> list[str]:
    """Level 1 of the recursive separator hierarchy: split on a bare line
    break (`\n`) -- what a paragraph-level split falls through to when a
    piece has no `\n\n` inside it but does have internal line breaks."""
    return [piece.strip() for piece in text.split("\n") if piece.strip()]


# The separator hierarchy's first two levels (paragraph, line); the third
# level (sentence) reuses `segment_sentences` directly -- no wrapper needed,
# its signature already matches (`str -> list[str]`). The fourth and last
# level (char) is the unconditional base case in `_recursive_split_text`
# below, not tried via this list (`_hard_split_by_chars` also needs
# `chunk_max`, a different signature).
_RECURSIVE_SEPARATOR_LEVELS: tuple[Callable[[str], list[str]], ...] = (
    _split_level_paragraph,
    _split_level_line,
    segment_sentences,
)


def _recursive_split_text(text: str, chunk_max: int, level: int = 0) -> list[str]:
    """Deterministic recursive/structural split (plan 06, issue #165): try
    the separator hierarchy paragraph (`\n\n`) -> line (`\n`) -> sentence in
    order (`_RECURSIVE_SEPARATOR_LEVELS`); a piece that is still over
    `chunk_max` after a level's split falls through to the NEXT level for
    just that piece (never restarting from the top for the whole text). A
    level whose split does not actually divide the text (zero or one
    resulting piece -- the separator was not found) is skipped, falling
    straight through to the next level on the SAME text. When every level
    is exhausted (no sentence-ending punctuation found either -- a run-on
    with no internal structure at all), falls back to a raw character split
    (`_hard_split_by_chars`), the unconditional base case. Guarantees every
    returned piece's length <= `chunk_max`, with NO exception. Empty/blank
    input yields an empty list, mirroring `segment_sentences`."""
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= chunk_max:
        return [stripped]

    if level < len(_RECURSIVE_SEPARATOR_LEVELS):
        pieces = _RECURSIVE_SEPARATOR_LEVELS[level](stripped)
        if len(pieces) > 1:
            result: list[str] = []
            for piece in pieces:
                result.extend(_recursive_split_text(piece, chunk_max, level + 1))
            return result
        # This level's separator was not found (or found nothing to split
        # on) -- fall through to the next level on the SAME text.
        return _recursive_split_text(stripped, chunk_max, level + 1)

    # Deepest level: no sentence boundary either -- raw char split is the
    # unconditional last resort so the MAX-side guarantee never has an
    # exception.
    return _hard_split_by_chars(stripped, chunk_max)


def _enforce_max_recursive(groups: list[list[str]], chunk_max: int) -> list[list[str]]:
    """The MAX-side safety net, run again AFTER `_enforce_min`'s forward
    merge ("enforce max, then min, then max again" -- a MIN-side merge can
    itself push a group back over `chunk_max`). Re-joins any over-band
    merged group's pieces and re-runs `_recursive_split_text` on the joined
    text -- zero embedding calls."""
    result: list[list[str]] = []
    for group in groups:
        joined = " ".join(group)
        if len(joined) <= chunk_max:
            result.append(group)
        else:
            result.extend([piece] for piece in _recursive_split_text(joined, chunk_max))
    return result


def _recursive_section_chunks(
    text: str, chunk_min: int = CHUNK_MIN, chunk_max: int = CHUNK_MAX
) -> list[str]:
    """Chunk one prose section's body text via the recursive/structural
    mechanism (issue #165, slice 06): split on the separator hierarchy for
    the unconditional MAX-side guarantee (`_recursive_split_text`), then
    coalesce below-`chunk_min` pieces forward with `_enforce_min` --
    treating each split piece as a singleton group -- then re-run the
    MAX-side split as a safety net (`_enforce_max_recursive`) since a
    MIN-side merge can itself push a group over `chunk_max`. Zero
    embedding/LLM calls anywhere in this function."""
    pieces = _recursive_split_text(text, chunk_max)
    if not pieces:
        return []

    groups: list[list[str]] = [[piece] for piece in pieces]
    groups = _enforce_min(groups, chunk_min)
    groups = _enforce_max_recursive(groups, chunk_max)

    return [" ".join(group) for group in groups]


def run_chunk_recursive(
    source_path: str | Path,
    chunks_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    chunk_min: int = CHUNK_MIN,
    chunk_max: int = CHUNK_MAX,
) -> list[dict[str, Any]]:
    """Run the recursive/structural chunk stage on `source_path` (issue
    #165, slice 06; the SOLE chunk mechanism as of issue #191): read the
    persisted structural tree via the shared per-section routing/writing
    orchestrator (`_resolve_chunk_inputs` / `_write_chunk_sections`),
    joining each section's routed body lines with `\n\n` (so a real docling
    paragraph break exists for the hierarchy's top level to find) and
    splitting via `_recursive_section_chunks`'s deterministic separator
    hierarchy.

    Constructs no embedding model, makes no `encode` call, and touches no
    embedding cache on disk -- zero embedding-model cost by construction.
    Also makes no text-generating LLM call -- this whole module never has.

    Writes the §7.7 artifact shape (`build_chunk_records`'s `chunk_id`
    scheme, field set, section-then-position order) to
    `data/chunks/<source_id>.jsonl`, so `axial chunk examine` and every
    other downstream consumer of `read_chunks` works on it unchanged.

    Raises `MissingSourceError` / `MissingTreeError` -- this mechanism
    never runs extraction itself.
    """
    source_id, tree = _resolve_chunk_inputs(source_path)

    def _join_body(body_lines: list[str]) -> str:
        return "\n\n".join(body_lines)

    def _split_section(body_text: str) -> list[str]:
        return _recursive_section_chunks(body_text, chunk_min, chunk_max)

    return _write_chunk_sections(
        source_id,
        tree,
        _join_body,
        _split_section,
        chunks_dir=chunks_dir,
        config_path=config_path,
    )


# --- `axial chunk examine` (issue #153, PRD §7.7 / §8 P0-4b) ---------------
#
# Read-only inspection over the on-disk chunk artifact(s) produced by
# `run_chunk_recursive` above: total/per-source counts, the size
# distribution, boundary sanity, and garbage-skip reporting (from the
# `.skips.jsonl` sidecar). Pure file I/O + arithmetic -- constructs no
# embedder and no LLM client, so it costs zero LLM/embedding spend and can
# run any time after a chunk run exists.

EXAMINE_SAMPLE_SIZE = 5


@dataclass
class ExamineSkip:
    """One garbage-skipped section, read verbatim from a source's
    `.skips.jsonl` sidecar (see `chunks_skips_sidecar_path`)."""

    source_id: str
    section: str
    section_order: str
    reason: str


@dataclass
class ExamineSample:
    """One sampled chunk text, shown with its own identifying fields so an
    eyeball sample can be traced back to its record (PRD §7.7)."""

    source_id: str
    chunk_id: str
    section: str
    text: str


@dataclass
class ExamineStats:
    """Aggregate chunk-quality stats over every chunk artifact under a
    chunks dir (`examine_chunks`'s return value), formatted for display by
    `format_examine_report`."""

    total: int
    per_source: dict[str, int] = field(default_factory=dict)
    min_size: float = 0
    max_size: float = 0
    mean_size: float = 0
    median_size: float = 0
    above_max: int = 0
    below_min: int = 0
    split_sections: int = 0
    skips: list[ExamineSkip] = field(default_factory=list)
    samples: list[ExamineSample] = field(default_factory=list)


def examine_chunks(
    chunks_dir: Path,
    chunk_min: int = CHUNK_MIN,
    chunk_max: int = CHUNK_MAX,
    sample_size: int = EXAMINE_SAMPLE_SIZE,
) -> ExamineStats:
    """Read every `<source_id>.jsonl` chunk artifact under `chunks_dir`
    (excluding `*.skips.jsonl` sidecars -- those are read separately, per
    source, for garbage-skip reporting) and aggregate the stats `axial
    chunk examine` reports: total + per-source counts, the size
    distribution (min/max/mean/median over `text` lengths), boundary
    sanity (chunks above `chunk_max`, chunks below `chunk_min`, sections
    split into multiple chunks -- grouped by (source_id, section_order)),
    sections skipped as garbage with their reasons, and a chunk-text
    sample. Pure read: never opens any chunks-dir file for writing.
    Returns all-zero/empty stats when `chunks_dir` has no chunk artifacts
    (including when it does not exist at all).

    Raises `ChunkArtifactCorruptError` if any line of a main `.jsonl`
    artifact or a `.skips.jsonl` sidecar is not valid JSON -- examine is a
    diagnostic tool, so corruption is surfaced loudly rather than silently
    skipped (mirroring `load_chunk_checkpoint`'s non-final-line behavior)."""
    per_source: dict[str, int] = {}
    sizes: list[int] = []
    above_max = 0
    below_min = 0
    section_counts: dict[tuple[str, str], int] = {}
    skips: list[ExamineSkip] = []
    samples: list[ExamineSample] = []

    if chunks_dir.is_dir():
        jsonl_paths = sorted(
            p for p in chunks_dir.glob("*.jsonl") if not p.name.endswith(".skips.jsonl")
        )
    else:
        jsonl_paths = []

    for path in jsonl_paths:
        source_id = path.stem
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ChunkArtifactCorruptError(path, line_no, exc) from exc
                count += 1
                text = record.get("text", "")
                size = len(text)
                sizes.append(size)
                if size > chunk_max:
                    above_max += 1
                if size < chunk_min:
                    below_min += 1
                section_order = str(record.get("section_order", ""))
                key = (source_id, section_order)
                section_counts[key] = section_counts.get(key, 0) + 1
                if len(samples) < sample_size:
                    samples.append(
                        ExamineSample(
                            source_id=source_id,
                            chunk_id=str(record.get("chunk_id", "")),
                            section=str(record.get("section", "")),
                            text=text,
                        )
                    )
        per_source[source_id] = count

        skips_path = chunks_skips_sidecar_path(source_id, chunks_dir)
        if skips_path.is_file():
            with skips_path.open("r", encoding="utf-8") as handle:
                for line_no, line in enumerate(handle, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        skip_record = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise ChunkArtifactCorruptError(skips_path, line_no, exc) from exc
                    skips.append(
                        ExamineSkip(
                            source_id=source_id,
                            section=str(skip_record.get("section", "")),
                            section_order=str(skip_record.get("section_order", "")),
                            reason=str(skip_record.get("reason", "")),
                        )
                    )

    total = len(sizes)
    split_sections = sum(1 for group_count in section_counts.values() if group_count > 1)

    if sizes:
        min_size: float = min(sizes)
        max_size: float = max(sizes)
        mean_size = statistics.mean(sizes)
        median_size = statistics.median(sizes)
    else:
        min_size = max_size = mean_size = median_size = 0

    return ExamineStats(
        total=total,
        per_source=per_source,
        min_size=min_size,
        max_size=max_size,
        mean_size=mean_size,
        median_size=median_size,
        above_max=above_max,
        below_min=below_min,
        split_sections=split_sections,
        skips=skips,
        samples=samples,
    )


def format_examine_report(
    stats: ExamineStats, chunk_min: int = CHUNK_MIN, chunk_max: int = CHUNK_MAX
) -> str:
    """Render `ExamineStats` into a human-readable report (PRD §7.7).
    Format/wording is left to the implementer (mirroring `run_chunk_
    embedding`'s stderr skip messages) -- only that every listed number is
    present, matches the fixture, and appears near its own label."""
    lines: list[str] = []

    lines.append(
        f"chunk examine: {stats.total} total chunk(s) across {len(stats.per_source)} source(s)"
    )
    for source_id in sorted(stats.per_source):
        lines.append(f"  {source_id}: {stats.per_source[source_id]} chunk(s)")

    lines.append("")
    lines.append(
        "size distribution (chars): "
        f"min={stats.min_size} max={stats.max_size} "
        f"mean={float(stats.mean_size):.1f} median={float(stats.median_size):.1f}"
    )

    lines.append("")
    lines.append(
        f"boundary sanity: {stats.above_max} chunk(s) above max (CHUNK_MAX={chunk_max}), "
        f"{stats.below_min} chunk(s) below min (CHUNK_MIN={chunk_min}), "
        f"{stats.split_sections} section(s) split into multiple chunks"
    )

    lines.append("")
    lines.append(f"sections skipped as garbage: {len(stats.skips)}")
    for skip in stats.skips:
        lines.append(
            f"  [{skip.source_id}] {skip.section!r} (order {skip.section_order}): {skip.reason}"
        )

    lines.append("")
    lines.append("chunk-text sample:")
    if not stats.samples:
        lines.append("  (no chunks to sample)")
    for sample in stats.samples:
        preview = sample.text if len(sample.text) <= 200 else sample.text[:200] + "..."
        lines.append(f"  [{sample.source_id}] {sample.chunk_id} {sample.section!r}: {preview}")

    return "\n".join(lines)
