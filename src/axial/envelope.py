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
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient, LLMError, get_client
from axial.model_json import ModelJsonError, complete_json, parse_model_json

ENVELOPES_DIR = Path("data/envelopes")

_ENVELOPE_HEADINGS = ("introduction", "abstract", "conclusion")

_REQUIRED_STRING_FIELDS = ("thesis", "scope", "stated_argument")

_PROMPT_TEMPLATE = """\
You are extracting a structural envelope from an academic source's \
introduction, abstract, and conclusion sections only. Read the sections \
below and respond with ONLY a JSON object (no prose, no markdown fences) \
with exactly these keys:

- "thesis": the author's stated thesis, as a non-empty string.
- "toc": a non-empty JSON array of the source's section/chapter labels.
- "scope": the stated scope of the argument, as a non-empty string.
- "stated_argument": the argument as restated (e.g. in the conclusion), \
as a non-empty string.

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


def compose_prompt(tree: dict) -> str:
    """Compose the envelope prompt from the source's intro/abstract/
    conclusion nodes only (heuristic over the extraction tree's section
    headings), never the whole tree."""
    sections = []
    for node in select_envelope_nodes(tree):
        heading = node.get("text", "")
        body_lines = [
            line for child in node.get("children", []) for line in _node_text_lines(child)
        ]
        sections.append(f"## {heading}\n" + "\n".join(body_lines))
    return _PROMPT_TEMPLATE.format(sections="\n\n".join(sections))


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
        raw_response = complete_json(client, prompt)
    except (LLMError, httpx.HTTPError) as exc:
        raise LLMFailedError(exc) from exc
    except ModelJsonError as exc:
        raise EnvelopeParseError(f"model response was not valid JSON: {exc}") from exc

    parsed = parse_response(raw_response)
    validate_envelope_fields(parsed)

    envelope = build_envelope(path, source_id, parsed)
    write_envelope(envelope, out_path)
    return envelope
