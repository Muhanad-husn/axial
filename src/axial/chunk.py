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
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import httpx
import yaml

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


def write_chunk_checkpoint(records: list[dict[str, Any]], path: Path) -> None:
    """Persist a source's chunk records to `path`, one JSON record per line,
    creating parent directories as needed (issue #81 point 1). Written once,
    after the chunking pass produces the records.

    Hardening (issue #81): written atomically -- the full content goes to a
    temp file in the same directory first, then swapped onto `path` via
    `os.replace` (an atomic rename on both POSIX and Windows) -- so a hard
    process kill (OOM kill, Stop-Process) mid-write can never leave a
    partial/torn file visible under the final name. Unlike the tag
    checkpoint's append-and-tolerate-a-torn-tail strategy, this file is
    written once as a whole and is load-bearing for chunk_ids (a torn one
    would corrupt every downstream chunk_id lookup), so "never partially
    visible" is the simpler, correct guarantee here rather than "tolerate and
    heal"."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def load_chunk_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load chunk records from a chunk-pass checkpoint file (the inverse of
    `write_chunk_checkpoint`), skipping blank lines."""
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


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
    chunks_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the argumentative-chunking pass on `source_path`.

    Reads the stored envelope from `data/envelopes/<source_id>.json` (never
    recomputes it -- PRD §10), then for each prose section in the extraction
    tree, calls the LLM with the envelope plus the section's neighbours (not
    the isolated section) to decide chunk boundaries. A section with no
    chunkable prose yields zero chunks without an LLM call or an error.

    Chunk-pass checkpoint (issue #81 point 1): OPT-IN, active only when a
    `chunks_dir` is supplied (the `axial vault write` composition threads one
    in; standalone `axial chunk` passes none and so behaves exactly as before,
    recomputing every run -- the reuse feature is deliberately scoped to vault
    write, not the standalone pass whose own contract re-runs each time). When
    active: once the source's chunk records are produced they are persisted to
    `<chunks_dir>/<source_id>.jsonl` (one record per line); a later run that
    finds this file reuses it verbatim and makes NO chunking LLM call
    (mirroring the envelope pass's "no recompute" reuse). Keyed by the
    content-hashed source_id, so an edited file gets a fresh id and never
    reuses stale chunks -- the reuse-once check runs before any envelope read
    or extraction, so a hit short-circuits the whole pass with zero work.
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    checkpoint_path = (
        chunks_checkpoint_path(source_id, chunks_dir) if chunks_dir is not None else None
    )
    if checkpoint_path is not None and checkpoint_path.exists():
        return load_chunk_checkpoint(checkpoint_path)

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

    if checkpoint_path is not None:
        write_chunk_checkpoint(all_records, checkpoint_path)
    return all_records
