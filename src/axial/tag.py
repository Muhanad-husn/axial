"""Tagging spine: for each prose chunk, one LLM call assigns every tagged
axis at once -- `role_in_argument` (issue #27 slice 01) and, when the
loaded schema declares it, `empirical_scope` (issue #28 slice 02) -- each a
single-value, closed-set axis whose vocabulary is loaded from the domain
schema, never hardcoded (PRD §5 stage 6, §7.1).

This pass runs the argumentative-chunking pass internally
(`axial.chunk.run_chunk`) rather than reimplementing it: chunk_id/section
provenance is computed exactly once, in chunk.py. For each resulting prose
chunk, `run_tag` composes one codebook-driven prompt (`axial.codebook.
load_codebook`) covering every axis it will assign, makes one LLM call with
a dedicated `pass_name="tag"` (`axial.llm.TAG_PASS_NAME`), parses the
model's single response into each axis's value, and validates every value
against the loaded schema (`axial.schema.load_schema`): any value absent
from its axis's tag set is a hard error, never a silent pass (PRD §7.1,
P0-6). When `empirical_scope` resolves to `"scope:country-case"`, the same
response must also carry a `country` drawn from the schema's `country_list`
(Appendix C/G) -- missing or out-of-list is a hard error too. Each emitted
record carries the chunk's provenance (chunk_id, section, chunk_text) plus
the `schema_version` it was tagged under, so a later schema change is
detectable per note.

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

# This slice tags two axes: role_in_argument (slice 01) and empirical_scope
# (slice 02, issue #28), both single cardinality. Other prose axes (field,
# claim_type, theory_school) are deferred to later slices
# (plans/tag/01-tag-spine-single.md, "Out of scope").
ROLE_IN_ARGUMENT_AXIS = "role_in_argument"
EMPIRICAL_SCOPE_AXIS = "empirical_scope"

# Axes this pass assigns, in prompt/extraction order. Only axes the loaded
# schema actually declares are tagged for a given domain -- so a minimal
# schema lacking empirical_scope (e.g. an inner unit test's fixture domain)
# is tagged on role_in_argument alone, never a hard error for an axis the
# schema doesn't define.
TAGGED_AXES = (ROLE_IN_ARGUMENT_AXIS, EMPIRICAL_SCOPE_AXIS)

# Appendix C/G: the one empirical_scope value that carries a `country` extra
# field, drawn from the schema's `country_list` (Appendix G).
COUNTRY_CASE_SCOPE_VALUE = "scope:country-case"

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

_MULTI_AXIS_TAG_PROMPT_TEMPLATE = """\
You are assigning tags for the CHUNK below, one axis at a time, choosing \
exactly one value per axis from that axis's closed controlled vocabulary. \
Respond with ONLY a JSON object (no prose, no markdown fences) with \
exactly one key per axis listed below ({axis_names!r}), each key's value \
being exactly one of that axis's tag ids (a single string, not a list). \
If the empirical_scope value you choose is "{country_case_scope}", also \
include a "country" key whose value is exactly one country from the \
country list below.

{axis_sections}

Country list (only required when empirical_scope is "{country_case_scope}"):

{country_list}

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


class CountryCaseMissingCountryError(TagError):
    """Raised when empirical_scope == 'scope:country-case' but the tag
    response carries no (or an empty) 'country' value (PRD Appendix C/G:
    'a country-case with a missing ... country exits non-zero with a clear
    error')."""

    def __init__(self):
        super().__init__(
            "empirical_scope 'scope:country-case' requires a 'country' value, but none was provided"
        )


class CountryNotInListError(TagError):
    """Raised when a scope:country-case record's 'country' is not a member
    of the schema's country_list (PRD Appendix G), naming the offending
    value so the CLI's error output is actionable."""

    def __init__(self, country: Any):
        self.country = country
        super().__init__(f"country {country!r} is not in the schema's country_list")


def list_prose_axes(schema: Schema) -> list[str]:
    """The schema's axis names whose `applies_to` includes `prose`, in the
    schema's own axis order."""
    return [name for name, axis in schema.axes.items() if "prose" in axis.applies_to]


def _tag_descriptions(axis_name: str, codebook: Codebook) -> str:
    """Render one axis's codebook entries -- each tag's definition plus its
    positive/negative example -- as the prompt-ready description block
    shared by `compose_tag_prompt` and `compose_multi_axis_tag_prompt`."""
    entries = codebook.axes.get(axis_name, {})
    descriptions = [
        f"- {tag_id}: {entry.definition}\n"
        f"  positive example: {entry.positive_example}\n"
        f"  negative example: {entry.negative_example}"
        for tag_id, entry in entries.items()
    ]
    return "\n".join(descriptions)


def compose_tag_prompt(chunk_text: str, axis_name: str, codebook: Codebook) -> str:
    """Compose a tagging prompt for `axis_name` from the codebook: each
    tag's definition plus its positive/negative example (PRD §7.1)."""
    return _TAG_PROMPT_TEMPLATE.format(
        axis_name=axis_name,
        tag_descriptions=_tag_descriptions(axis_name, codebook),
        chunk_text=chunk_text,
    )


def compose_multi_axis_tag_prompt(
    chunk_text: str,
    axis_names: list[str],
    codebook: Codebook,
    country_list: list[str] | None = None,
) -> str:
    """Compose a single tagging prompt covering every axis in `axis_names`,
    so one LLM call (`pass_name=TAG_PASS_NAME`) can assign all of them at
    once instead of one call per axis (issue #28 slice 02). Also surfaces
    `country_list` so the model knows what to choose from when it assigns
    `empirical_scope: "scope:country-case"`."""
    sections = [
        f"Axis {axis_name!r} vocabulary:\n\n{_tag_descriptions(axis_name, codebook)}"
        for axis_name in axis_names
    ]
    return _MULTI_AXIS_TAG_PROMPT_TEMPLATE.format(
        axis_names=list(axis_names),
        country_case_scope=COUNTRY_CASE_SCOPE_VALUE,
        axis_sections="\n\n".join(sections),
        country_list=", ".join(country_list or []),
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

    value = values[0]
    if not isinstance(value, str):
        raise TagParseError(
            f"expected {axis_name!r} value to be a string, got {type(value).__name__}: {value!r}"
        )

    return value


def validate_tag(schema: Schema, axis_name: str, value: Any) -> None:
    """Validate that `value` exists in the loaded schema's `axis_name` tag
    set; raises `TagNotInSchemaError` (naming the axis + offending tag) if
    not (PRD §7.1, P0-6)."""
    axis = schema.axes.get(axis_name)
    if axis is None or value not in axis.tag_ids:
        raise TagNotInSchemaError(axis_name, value)


def parse_country_response(raw: str) -> str:
    """Parse the model's raw tagging response for its `country` extra field
    (Appendix C/G, required when `empirical_scope == "scope:country-case"`).
    A missing or empty `country` key is a hard error (`CountryCaseMissing
    CountryError`), not a silent pass."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or not data.get("country"):
        raise CountryCaseMissingCountryError()

    country = data["country"]
    if not isinstance(country, str):
        raise TagParseError(
            f"expected 'country' value to be a string, got {type(country).__name__}: {country!r}"
        )
    return country


def validate_country(schema: Schema, country: str) -> None:
    """Validate that `country` exists in the loaded schema's `country_list`
    (Appendix G); raises `CountryNotInListError` naming the offending value
    if not."""
    if country not in schema.country_list:
        raise CountryNotInListError(country)


def build_tagged_record(
    chunk_record: dict[str, Any],
    role_in_argument: str,
    schema_version: str,
    empirical_scope: str | None = None,
    country: str | None = None,
) -> dict[str, Any]:
    """Assemble a tagged record carrying the chunk's provenance (chunk_id,
    section, chunk_text) plus the role_in_argument value and the schema
    version it was tagged under (PRD §7.1). When `empirical_scope` is given
    it is added too (issue #28 slice 02); when `country` is also given (only
    meaningful for a `scope:country-case` record) it is added as well. A
    non-country-case record must not carry a `country` field at all."""
    record: dict[str, Any] = {
        "chunk_id": chunk_record["chunk_id"],
        "section": chunk_record["section"],
        "chunk_text": chunk_record["text"],
        "role_in_argument": role_in_argument,
        "schema_version": schema_version,
    }
    if empirical_scope is not None:
        record["empirical_scope"] = empirical_scope
    if country is not None:
        record["country"] = country
    return record


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
    (`pass_name=TAG_PASS_NAME`) to assign every axis the loaded schema
    declares among `TAGGED_AXES` (`role_in_argument` and, when present,
    `empirical_scope`), validating each result against the loaded domain
    schema. When `empirical_scope` resolves to `"scope:country-case"`, the
    same response's `country` is also required and validated against the
    schema's `country_list` (Appendix C/G). A source whose chunking yields
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

    # Only tag axes the loaded schema actually declares (TAGGED_AXES'
    # comment above): a minimal domain missing empirical_scope is tagged on
    # role_in_argument alone.
    axes_to_tag = [axis_name for axis_name in TAGGED_AXES if axis_name in schema.axes]

    tagged_records: list[dict[str, Any]] = []
    for chunk_record in chunk_records:
        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc

        # One LLM call per chunk assigns every tagged axis at once (issue
        # #28 slice 02) -- never one call per axis.
        prompt = compose_multi_axis_tag_prompt(
            chunk_record["text"], axes_to_tag, codebook, country_list=schema.country_list
        )

        try:
            raw_response = client.complete(prompt, pass_name=TAG_PASS_NAME)
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc

        values: dict[str, str] = {}
        for axis_name in axes_to_tag:
            value = parse_tag_response(raw_response, axis_name)
            validate_tag(schema, axis_name, value)
            values[axis_name] = value

        country: str | None = None
        if values.get(EMPIRICAL_SCOPE_AXIS) == COUNTRY_CASE_SCOPE_VALUE:
            country = parse_country_response(raw_response)
            validate_country(schema, country)

        tagged_records.append(
            build_tagged_record(
                chunk_record,
                values[ROLE_IN_ARGUMENT_AXIS],
                schema.version,
                empirical_scope=values.get(EMPIRICAL_SCOPE_AXIS),
                country=country,
            )
        )

    return tagged_records
