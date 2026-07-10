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
from pathlib import Path
from typing import Any

import httpx

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


def _slugify(label: str) -> str:
    """A filesystem/id-safe slug for a section heading, used inside
    chunk_id. Falls back to "section" if the heading has no alphanumerics."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or "section"


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
    (`<source_id>_<section order>_<section slug>_<NNN>`) and `section` (the
    section's own verbatim heading), per PRD §8 P0-4.

    `section_order` (the section node's own `order` field, e.g. "1", "2") is
    folded into the id specifically so that two distinct top-level sections
    sharing the same heading text (extract.py opens a fresh section node per
    heading occurrence, unnested) never collide on chunk_id -- the heading
    slug alone is not unique across a real multi-chapter source.
    """
    slug = _slugify(section_label)
    order_key = section_order.replace(".", "-") if section_order else "0"
    records = []
    for index, chunk in enumerate(chunks, start=1):
        records.append(
            {
                "chunk_id": f"{source_id}_{order_key}_{slug}_{index:03d}",
                "section": section_label,
                "text": chunk["text"],
            }
        )
    return records


def run_chunk(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """Run the argumentative-chunking pass on `source_path`.

    Reads the stored envelope from `data/envelopes/<source_id>.json` (never
    recomputes it -- PRD §10), then for each prose section in the extraction
    tree, calls the LLM with the envelope plus the section's neighbours (not
    the isolated section) to decide chunk boundaries. A section with no
    chunkable prose yields zero chunks without an LLM call or an error.
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

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

    sections = _section_nodes(tree)

    all_records: list[dict[str, Any]] = []
    for index, section in enumerate(sections):
        body_lines = _section_body_lines(section)
        if not body_lines:
            continue  # no chunkable prose in this section -- zero chunks, no LLM call

        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc

        section_label = section.get("text", "")
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
        section_order = section.get("order", "")
        all_records.extend(build_chunk_records(source_id, section_order, section_label, chunks))

    return all_records
