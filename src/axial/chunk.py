"""Argumentative chunking: for each prose section, one LLM call decides chunk
boundaries with the stored envelope plus the section's surrounding sections
in context -- never the isolated section (PRD §5 stage 4, §8 P0-4).

Unlike the envelope pass (`axial.envelope`), this pass never writes the
envelope: it reads `data/envelopes/<source_id>.json` (written once by
`axial envelope`), reusing `axial.envelope.compute_source_id`/`envelope_path`/
`_default_envelopes_dir` so the source_id and on-disk location are computed
exactly once, in exactly one place (PRD §10, "no recompute"). If no stored
envelope exists yet, this pass raises a typed error telling the caller to run
`axial envelope` first -- it never falls back to recomputing one.

Chunk records carry a stable, deterministic `chunk_id` (`<source_id>_<section
order>_<section slug>_<NNN>`, derived from the source_id, the section node's
already-unique `order` field, the section's own verbatim heading, and the
chunk's position within that section -- no randomness, no timestamps) and
`section` (the section's verbatim heading text), satisfying PRD §8 P0-4's
"stable chunk_ids" and "preserve section provenance". The `order` component
is required for uniqueness: `extract.py`'s tree-builder opens a new
top-level section node for every heading in reading order without nesting,
so a real source can have multiple top-level sections sharing the same
heading text (e.g. repeated "Introduction"/"Notes"/"Conclusion" across
chapters) -- the heading slug alone would collide across them, but each
section's `order` is unique by construction. This slice emits chunk records
to stdout only; vault persistence is slice 06.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.checkpoint import (
    append_checkpoint_record,
    load_checkpoint_records,
)
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
    envelope_path,
    _default_envelopes_dir,
)
from axial.extract import ExtractError, extract
from axial.llm import (
    CHUNK_PASS_NAME,
    DEFAULT_PIPELINE_CONFIG_PATH,
    LLMClient,
    LLMError,
    get_client,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json

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


def append_chunk_checkpoint(path: Path, record: dict[str, Any]) -> None:
    """Append one chunk record to `path` AS IT IS PRODUCED (issue #104): heal
    any torn tail left by an earlier hard kill, then append the JSON line,
    flushed before returning. Creates parent directories as needed. Reuses
    `axial.checkpoint.append_checkpoint_record` -- the same primitive
    `axial.tag.append_tag_checkpoint` builds on -- so chunk and tag
    checkpoints stay consistent (atomic/append-safe, crash-tolerant)."""
    append_checkpoint_record(path, record)


def load_chunk_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load chunk records already persisted to a chunk-pass checkpoint file
    (the inverse of `append_chunk_checkpoint`), skipping blank lines. Returns
    an empty list when the file does not exist yet.

    Hardening (issue #104, mirroring `axial.tag.load_tag_checkpoint`): a torn
    FINAL line (a hard kill mid-append) is healed (dropped) rather than
    poisoning the resume -- its records simply reappear in the "not yet
    checkpointed" gap and are re-produced on the resume run. A torn line
    that is NOT the last one raises `ChunkCheckpointCorruptError`, naming the
    checkpoint path and the offending 1-indexed line number. Reuses the same
    shared `axial.checkpoint.load_checkpoint_records` primitive
    `axial.tag.load_tag_checkpoint` builds on."""
    return load_checkpoint_records(path, ChunkCheckpointCorruptError)


_CHUNK_PROMPT_TEMPLATE = """\
You are deciding argumentative chunk boundaries for the TARGET SECTION below, \
given this source's structural envelope and its surrounding sections for \
context. Chunks should reflect argumentative units (a claim and its \
support), not fixed sizes. Respond with ONLY a JSON object (no prose, no \
markdown fences) with exactly one key, "chunks": a non-empty JSON array of \
objects, each with a "text" key holding one argumentative chunk of prose \
taken from the TARGET SECTION only -- never from the surrounding sections, \
which are given only for context, not to be chunked themselves.

Envelope:
- stated_argument: {stated_argument}
- thesis: {thesis}
- scope: {scope}

Surrounding sections (context only -- do not chunk these):

{neighbours}

Target section (chunk this one):

{target}
"""

_NO_NEIGHBOURS_PLACEHOLDER = "(none)"


class ChunkError(Exception):
    """Base class for all argumentative-chunking errors."""


class MissingSourceError(ChunkError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class MissingEnvelopeError(ChunkError):
    """Raised when no stored envelope exists yet for the source (PRD §7.3,
    "produced once in stage 3; consumed by stages 4 and 6") -- the chunk
    pass never recomputes one; the caller must run `axial envelope` first."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"no stored envelope found at {path}; run `axial envelope` on the source first"
        )


class ExtractionFailedError(ChunkError):
    """Raised when the underlying structural extraction pass fails."""

    def __init__(self, cause: ExtractError):
        self.cause = cause
        super().__init__(str(cause))


class LLMFailedError(ChunkError):
    """Raised when the LLM client -- selection/config or the completion call
    itself -- fails, so the CLI renders a clean `error: ...` instead of a
    bare traceback."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkParseError(ChunkError):
    """Raised when the model's chunking response is not parseable into a
    non-empty array of chunk-text objects."""


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


def _prose_text_lines(node: dict) -> list[str]:
    """Collect a node's own text plus all descendants' text, in order --
    prose nodes only (never artifact nodes like tables/pictures), since this
    pass produces prose chunks (PRD §5 stage 4, "Output: prose chunks")."""
    lines = []
    if node.get("type") == "prose":
        text = node.get("text")
        if text:
            lines.append(text)
    for child in node.get("children", []):
        lines.extend(_prose_text_lines(child))
    return lines


def _section_body_lines(node: dict) -> list[str]:
    """A section node's body text lines (excluding its own heading)."""
    return [line for child in node.get("children", []) for line in _prose_text_lines(child)]


def _section_text(node: dict) -> str:
    """A section's heading plus body, formatted for inclusion in a prompt."""
    heading = node.get("text", "")
    body = "\n".join(_section_body_lines(node))
    return f"## {heading}\n{body}" if body else f"## {heading}"


# Input-guard thresholds for non-prose section bodies (issue #118, mirroring
# axial.xref's #111 guard, xref.py:54-55): an OCR'd index/bibliography-shaped
# section becomes one very large, mostly-non-alphabetic block with no
# argumentative structure that can stall the LLM. Heuristics, not hard rules.
# Duplicated here rather than imported from axial.xref because axial.xref
# already imports from axial.chunk (run_chunk, ChunkError) -- importing the
# guard back from xref would create an import cycle. Issue #132 will lift
# this and xref's copy into one shared helper.
_CHUNK_MAX_SECTION_CHARS = 30000
_CHUNK_MAX_NON_ALPHA_RATIO = 0.4


def _non_prose_skip_reason(text: str) -> str | None:
    """Return a human-readable reason to skip `text` from the chunk pass as
    non-prose back-matter (issue #118, mirroring xref.py's `_non_prose_skip_reason`,
    #111), or None to process it normally."""
    char_count = len(text)
    if char_count > _CHUNK_MAX_SECTION_CHARS:
        return f"exceeds size limit ({char_count} chars > {_CHUNK_MAX_SECTION_CHARS})"
    if char_count:
        non_alpha_ratio = sum(1 for c in text if not c.isalpha()) / char_count
        if non_alpha_ratio > _CHUNK_MAX_NON_ALPHA_RATIO:
            return f"high non-alpha ratio ({non_alpha_ratio:.1%})"
    return None


def compose_chunk_prompt(
    target: dict, prev_section: dict | None, next_section: dict | None, envelope: dict[str, Any]
) -> str:
    """Compose the chunking prompt for `target` from the target section's own
    text, its neighbouring sections' actual text (never just an envelope
    paraphrase), and the stored envelope's contents -- never the isolated
    section (PRD §5 stage 4, §8 P0-4)."""
    neighbour_texts = []
    if prev_section is not None:
        neighbour_texts.append(_section_text(prev_section))
    if next_section is not None:
        neighbour_texts.append(_section_text(next_section))
    neighbours = "\n\n".join(neighbour_texts) if neighbour_texts else _NO_NEIGHBOURS_PLACEHOLDER

    return _CHUNK_PROMPT_TEMPLATE.format(
        stated_argument=envelope.get("stated_argument", ""),
        thesis=envelope.get("thesis", ""),
        scope=envelope.get("scope", ""),
        neighbours=neighbours,
        target=_section_text(target),
    )


def parse_response(raw: str) -> list[dict[str, Any]]:
    """Parse the model's raw chunking response into a list of chunk-text
    objects (each with at least a "text" key). Accepts a top-level object
    with a "chunks" array, or a bare top-level array. Array entries that are
    bare strings are normalized to {"text": <string>} before validation."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise ChunkParseError(f"model response was not valid JSON: {exc}") from exc

    if isinstance(data, dict):
        if "chunks" not in data:
            raise ChunkParseError(
                f"expected a top-level 'chunks' key, got keys: {sorted(data.keys())}"
            )
        chunks = data["chunks"]
    else:
        chunks = data

    if not isinstance(chunks, list):
        raise ChunkParseError(
            f"expected chunk data to be a JSON array, got {type(chunks).__name__}: {chunks!r}"
        )

    normalized = [{"text": chunk} if isinstance(chunk, str) else chunk for chunk in chunks]

    for chunk in normalized:
        if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
            raise ChunkParseError(
                f"expected each chunk to be an object with a string 'text' key, got {chunk!r}"
            )

    return normalized


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


def run_chunk(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    chunks_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the argumentative-chunking pass on `source_path`.

    Reads the stored envelope from `data/envelopes/<source_id>.json` (never
    recomputes it -- PRD §10), then for each prose section in the extraction
    tree, calls the LLM with the envelope plus the section's neighbours (not
    the isolated section) to decide chunk boundaries. A section with no
    chunkable prose yields zero chunks without an LLM call or an error.

    Chunk-pass checkpoint (issue #81 point 1, made per-section-incremental by
    issue #104): OPT-IN, active only when a `chunks_dir` is supplied (the
    `axial vault write` composition threads one in; standalone `axial chunk`
    passes none and so behaves exactly as before, recomputing every run --
    the reuse feature is deliberately scoped to vault write, not the
    standalone pass whose own contract re-runs each time). When active: each
    section's chunk records are appended to `<chunks_dir>/<source_id>.jsonl`
    (one record per line) as soon as that section completes -- write+flush
    per section, mirroring `axial.tag.run_tag`'s per-chunk checkpoint -- so a
    mid-pass hard failure at section N leaves sections 0..N-1's records
    durably persisted instead of losing them (issue #104's primary fix: the
    prior all-or-nothing `write_chunk_checkpoint(...)` call after the whole
    loop lost every already-produced record on a mid-pass failure). On a
    later run, a section whose `section_order` already appears in the
    checkpoint is skipped entirely -- no LLM call -- and only the remaining
    sections are processed, their records appended and combined with the
    checkpointed ones in the chunker's own section order. When every
    chunkable section is already checkpointed, the checkpointed records are
    returned verbatim with zero chunking LLM calls (mirroring the envelope
    pass's "no recompute" reuse) -- extraction/envelope-read still run (they
    are needed to know which sections exist), but both are already cheap,
    cache-backed reads with no LLM cost of their own.
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    checkpoint_path = (
        chunks_checkpoint_path(source_id, chunks_dir) if chunks_dir is not None else None
    )
    checkpointed_records: list[dict[str, Any]] = []
    done_section_orders: set[str] = set()
    if checkpoint_path is not None and checkpoint_path.exists():
        checkpointed_records = load_chunk_checkpoint(checkpoint_path)
        if checkpointed_records and not any("section_order" in r for r in checkpointed_records):
            # Legacy (pre-#104) checkpoint: written once, atomically, only
            # after the whole pass succeeded (the old, now-removed
            # write_chunk_checkpoint) -- none of its records carry
            # section_order, so treat it as complete, exactly like the old
            # short-circuit, zero LLM calls. Without this, an old-format
            # checkpoint's empty done_section_orders would make every
            # section look unfinished, re-chunking the whole source AND
            # appending duplicate records on top of the legacy lines.
            return checkpointed_records
        done_section_orders = {
            record["section_order"] for record in checkpointed_records if "section_order" in record
        }

    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)

    env_path = envelope_path(source_id, envelopes_dir)
    if not env_path.exists():
        raise MissingEnvelopeError(env_path)
    envelope = json.loads(env_path.read_text(encoding="utf-8"))

    try:
        tree = extract(path)
    except ExtractError as exc:
        raise ExtractionFailedError(exc) from exc

    # Drop clear back-matter sections (bibliography/index/references/contents/
    # copyright/lists) before the loop, so they are never chunked, never sent
    # to the LLM (not even as a neighbour's context), and never written as
    # notes (issue #113). Filtering up front -- rather than skipping inside the
    # loop -- also keeps a dropped section out of the prev/next neighbour
    # context of the sections that are kept. Chunk ids are keyed by each
    # section's own `order` field, not its position, so kept sections'
    # checkpoint keys are unchanged.
    sections = [node for node in _section_nodes(tree) if not _is_back_matter(node.get("text", ""))]

    all_records: list[dict[str, Any]] = list(checkpointed_records)
    for index, section in enumerate(sections):
        body_lines = _section_body_lines(section)
        if not body_lines:
            continue  # no chunkable prose in this section -- zero chunks, no LLM call

        section_order = section.get("order", "")
        if checkpoint_path is not None and section_order in done_section_orders:
            continue  # already checkpointed by an earlier run -- no LLM call

        section_label = section.get("text", "")

        # Input guard (issue #118, mirroring xref.py's #111 guard): skip a
        # section whose own body is non-prose back-matter (a huge OCR'd
        # index/bibliography) -- no LLM call, no chunk records, no checkpoint
        # write for this section. The skip is a deterministic function of the
        # section's text, so it re-applies on every resume without ever
        # reaching the model. This only skips the section's own turn as the
        # chunking target -- it may still appear as neighbour context in an
        # adjacent section's prompt (PRD §5 stage 4 / §8 P0-4), unrelated to
        # issue #113's separate back-matter title filter above.
        skip_reason = _non_prose_skip_reason("\n".join(body_lines))
        if skip_reason is not None:
            print(f"chunk: skipping section {section_label}: {skip_reason}", file=sys.stderr)
            continue

        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc

        prev_section = sections[index - 1] if index > 0 else None
        next_section = sections[index + 1] if index < len(sections) - 1 else None

        prompt = compose_chunk_prompt(section, prev_section, next_section, envelope)

        try:
            raw_response = complete_json(client, prompt, pass_name=CHUNK_PASS_NAME)
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc
        except ModelJsonError as exc:
            raise ChunkParseError(f"model response was not valid JSON: {exc}") from exc

        chunks = parse_response(raw_response)
        section_records = build_chunk_records(source_id, section_order, section_label, chunks)

        # Persist this section's records before moving to the next section
        # (write+flush per section), so a failure on a later section leaves
        # every already-completed section durably checkpointed (issue #104's
        # primary fix).
        if checkpoint_path is not None:
            for record in section_records:
                append_chunk_checkpoint(checkpoint_path, record)
        all_records.extend(section_records)

    return all_records
