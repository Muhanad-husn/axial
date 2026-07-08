"""Tagging spine: for each prose chunk, one LLM call assigns the
`role_in_argument` axis -- a single-value, closed-set axis whose vocabulary
is loaded from the domain schema, never hardcoded (PRD §5 stage 6, §7.1).

This pass runs the argumentative-chunking pass internally
(`axial.chunk.run_chunk`) rather than reimplementing it: chunk_id/section
provenance is computed exactly once, in chunk.py. For each resulting prose
chunk, `run_tag` composes a codebook-driven prompt (`axial.codebook.
load_codebook`) for the `role_in_argument` axis, makes one LLM call with a
dedicated `pass_name="tag"` (`axial.llm.TAG_PASS_NAME`), parses the model's
response into a single axis value, and validates it against the loaded
schema (`axial.schema.load_schema`): any value absent from the schema's
`role_in_argument` tag set is a hard error, never a silent pass (PRD §7.1,
P0-6). Each emitted record carries the chunk's provenance (chunk_id,
section, chunk_text) plus the `schema_version` it was tagged under, so a
later schema change is detectable per note.

A source whose chunking yields zero chunks yields zero tagged records
without ever calling the LLM for the tag pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from axial.chunk import ChunkError, run_chunk
from axial.codebook import Codebook, CodebookError, load_codebook
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    TAG_PASS_NAME,
    LLMClient,
    LLMError,
    get_client,
)
from axial.schema import Schema, SchemaError, load_schema

DEFAULT_DOMAIN_DIR = Path("config/domains/syria")

# This slice tags exactly one axis: role_in_argument (single cardinality).
# Other prose axes (field, claim_type, empirical_scope, theory_school) are
# deferred to later slices (plans/tag/01-tag-spine-single.md, "Out of scope").
ROLE_IN_ARGUMENT_AXIS = "role_in_argument"

_TAG_PROMPT_TEMPLATE = """\
You are assigning the {axis_name!r} tag for the CHUNK below, choosing \
exactly one value from this closed controlled vocabulary. Respond with \
ONLY a JSON object (no prose, no markdown fences) with exactly one key, \
{axis_name!r}, whose value is exactly one of the tag ids below (a single \
string, not a list).

Tag vocabulary:

{tag_descriptions}

Chunk:

{chunk_text}
"""


class TagError(Exception):
    """Base class for all tagging-pass errors."""


class SchemaLoadFailedError(TagError):
    """Raised when the domain schema fails to load."""

    def __init__(self, cause: SchemaError):
        self.cause = cause
        super().__init__(str(cause))


class CodebookLoadFailedError(TagError):
    """Raised when the domain codebook fails to load."""

    def __init__(self, cause: CodebookError):
        self.cause = cause
        super().__init__(str(cause))


class ChunkingFailedError(TagError):
    """Raised when the internal argumentative-chunking pass fails -- the tag
    pass never reimplements chunking, so any chunk.py error is wrapped and
    surfaced here instead."""

    def __init__(self, cause: ChunkError):
        self.cause = cause
        super().__init__(str(cause))


class LLMFailedError(TagError):
    """Raised when the LLM client -- selection/config or the completion call
    itself -- fails, so the CLI renders a clean `error: ...` instead of a
    bare traceback."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class TagParseError(TagError):
    """Raised when the model's tagging response is not parseable into an
    axis -> value assignment."""


class TagCardinalityError(TagError):
    """Raised when a single-cardinality axis's parsed response carries zero
    or multiple values instead of exactly one."""

    def __init__(self, axis_name: str, values: list[Any]):
        self.axis_name = axis_name
        self.values = values
        super().__init__(
            f"axis {axis_name!r} is single-cardinality: expected exactly one "
            f"value, got {len(values)}: {values!r}"
        )


class TagNotInSchemaError(TagError):
    """Raised when a tag value the model returned does not exist in the
    loaded schema's axis vocabulary (PRD §7.1, P0-6: "A tag not in the
    schema is a hard error, not a silent pass")."""

    def __init__(self, axis_name: str, tag: Any):
        self.axis_name = axis_name
        self.tag = tag
        super().__init__(f"tag {tag!r} is not in the schema's {axis_name!r} axis")


def list_prose_axes(schema: Schema) -> list[str]:
    """The schema's axis names whose `applies_to` includes `prose`, in the
    schema's own axis order."""
    return [name for name, axis in schema.axes.items() if "prose" in axis.applies_to]


def compose_tag_prompt(chunk_text: str, axis_name: str, codebook: Codebook) -> str:
    """Compose a tagging prompt for `axis_name` from the codebook: each
    tag's definition plus its positive/negative example (PRD §7.1)."""
    entries = codebook.axes.get(axis_name, {})
    descriptions = [
        f"- {tag_id}: {entry.definition}\n"
        f"  positive example: {entry.positive_example}\n"
        f"  negative example: {entry.negative_example}"
        for tag_id, entry in entries.items()
    ]
    return _TAG_PROMPT_TEMPLATE.format(
        axis_name=axis_name,
        tag_descriptions="\n".join(descriptions),
        chunk_text=chunk_text,
    )


def parse_tag_response(raw: str, axis_name: str) -> str:
    """Parse the model's raw tagging response into a single axis value.

    Accepts a top-level JSON object with `axis_name` as a key, whose value
    is either a bare string (the common case) or a single-element list.
    Zero or multiple values is a cardinality error, not a silent pick.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or axis_name not in data:
        keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
        raise TagParseError(f"expected a top-level {axis_name!r} key, got: {keys}")

    raw_value = data[axis_name]
    values = raw_value if isinstance(raw_value, list) else [raw_value]

    if len(values) != 1:
        raise TagCardinalityError(axis_name, values)

    return values[0]


def validate_tag(schema: Schema, axis_name: str, value: Any) -> None:
    """Validate that `value` exists in the loaded schema's `axis_name` tag
    set; raises `TagNotInSchemaError` (naming the axis + offending tag) if
    not (PRD §7.1, P0-6)."""
    axis = schema.axes.get(axis_name)
    if axis is None or value not in axis.tag_ids:
        raise TagNotInSchemaError(axis_name, value)


def build_tagged_record(
    chunk_record: dict[str, Any], role_in_argument: str, schema_version: str
) -> dict[str, Any]:
    """Assemble a tagged record carrying the chunk's provenance (chunk_id,
    section, chunk_text) plus the role_in_argument value and the schema
    version it was tagged under (PRD §7.1)."""
    return {
        "chunk_id": chunk_record["chunk_id"],
        "section": chunk_record["section"],
        "chunk_text": chunk_record["text"],
        "role_in_argument": role_in_argument,
        "schema_version": schema_version,
    }


def run_tag(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
) -> list[dict[str, Any]]:
    """Run the tagging pass on `source_path`.

    Runs the argumentative-chunking pass internally (never reimplemented),
    then for each resulting prose chunk makes one LLM call
    (`pass_name=TAG_PASS_NAME`) to assign `role_in_argument`, validating the
    result against the loaded domain schema. A source whose chunking yields
    zero chunks yields zero tagged records without ever calling the LLM for
    the tag pass.
    """
    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        raise SchemaLoadFailedError(exc) from exc

    try:
        codebook = load_codebook(domain_dir)
    except CodebookError as exc:
        raise CodebookLoadFailedError(exc) from exc

    try:
        chunk_records = run_chunk(
            source_path, client=client, envelopes_dir=envelopes_dir, config_path=config_path
        )
    except ChunkError as exc:
        raise ChunkingFailedError(exc) from exc

    tagged_records: list[dict[str, Any]] = []
    for chunk_record in chunk_records:
        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc

        prompt = compose_tag_prompt(chunk_record["text"], ROLE_IN_ARGUMENT_AXIS, codebook)

        try:
            raw_response = client.complete(prompt, pass_name=TAG_PASS_NAME)
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc

        value = parse_tag_response(raw_response, ROLE_IN_ARGUMENT_AXIS)
        validate_tag(schema, ROLE_IN_ARGUMENT_AXIS, value)

        tagged_records.append(build_tagged_record(chunk_record, value, schema.version))

    return tagged_records
