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


def _node_text_lines(node: dict) -> list[str]:
    """Collect a node's own text plus all descendants' text, in order."""
    lines = []
    text = node.get("text")
    if text:
        lines.append(text)
    for child in node.get("children", []):
        lines.extend(_node_text_lines(child))
    return lines


def _matched_section_blocks(tree: dict) -> list[str]:
    """Build one text block per matched intro/abstract/conclusion node: the
    section's own direct text plus its children's, not its children's alone
    (PRD §7.3, "full text of the selected sections")."""
    blocks = []
    for node in select_envelope_nodes(tree):
        heading = node.get("text", "")
        body_lines = _node_text_lines(node)
        blocks.append(f"## {heading}\n" + "\n".join(body_lines))
    return blocks


def _head_of_tree_lines(tree: dict, max_chars: int = _HEAD_OF_TREE_SLICE_CHARS) -> list[str]:
    """Walk the tree in stable pre-order (root -> children, depth-first --
    the document's own reading order per `axial.extract._build_tree`),
    collecting every node's own text, stopping once the accumulated length
    reaches `max_chars` (rounding up to the line that crosses the threshold
    rather than truncating a sentence mid-way). Deterministic: the same tree
    always yields the same slice (PRD §7.3, "a bounded prefix of the
    source's own prose, taken in tree order")."""
    lines: list[str] = []
    total = 0

    def _walk(node: dict) -> bool:
        nonlocal total
        text = node.get("text")
        if text:
            lines.append(text)
            total += len(text)
            if total >= max_chars:
                return True
        for child in node.get("children", []):
            if _walk(child):
                return True
        return False

    _walk(tree)
    return lines


def compose_prompt(tree: dict) -> str:
    """Compose the envelope prompt from the source's intro/abstract/
    conclusion nodes (heuristic over the extraction tree's section
    headings). When that heuristic selects little or no text (PRD §7.3,
    "evidence floor on the input"), widen instead to a substantive
    head-of-tree slice of the source's own prose, so the model is never
    handed an empty or near-empty evidence block (#201)."""
    blocks = _matched_section_blocks(tree)
    if sum(len(block) for block in blocks) < _EVIDENCE_FLOOR_CHARS:
        lines = _head_of_tree_lines(tree)
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
