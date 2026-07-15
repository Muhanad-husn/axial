"""Tagging spine: for each prose chunk, one LLM call assigns every tagged
axis at once -- `role_in_argument` and `empirical_scope` (issues #27/#28,
single cardinality) plus `field`, `claim_type`, and `theory_school` (issue
#29 slice 03, primary+secondary cardinalities) -- each a closed-set axis
whose vocabulary is loaded from the domain schema, never hardcoded (PRD §5
stage 6, §7.1).

This pass reads its chunk records from the on-disk chunk artifact
(`axial.chunk.read_chunks`, PRD §7.7) rather than computing chunks itself
(issue #154, slice 04 of the chunk-redesign subproject): chunk_id/section
provenance is computed exactly once, by `axial chunk` (see chunk.py), and
this pass never (re)derives chunk boundaries -- `read_chunks` raises a clear
error telling the operator to run `axial chunk` first when no artifact
exists yet. For each resulting prose chunk, `run_tag` composes one
codebook-driven prompt (`axial.codebook.load_codebook`) covering every axis
it will assign, makes one LLM call with a dedicated `pass_name="tag"`
(`axial.llm.TAG_PASS_NAME`), parses the model's single response into each
axis's value(s), and validates every value against the loaded schema
(`axial.schema.load_schema`): any value absent from its axis's tag set is a
hard error, never a silent pass (PRD §7.1, P0-6).

How each axis is parsed/validated is dispatched on the loaded schema's own
`Axis.cardinality` -- never on the axis's name -- so adding another axis of
an already-handled cardinality (e.g. a future single-cardinality axis, or
another `primary_plus_secondary` one) is a schema/codebook change, not a
code change (PRD §4):

  - `cardinality == "single"` (`role_in_argument`, `empirical_scope`):
    `parse_tag_response` / `validate_tag`, exactly as slices 01/02 built
    them. When `empirical_scope` resolves to `"scope:country-case"`, the
    same response must also carry a non-empty `polity` (Appendix C/G) --
    missing or empty is a hard error, but a value outside the schema's
    `polity_examples` is accepted verbatim and logged to stderr as a
    candidate addition, never fatal (spec-drift #77).
  - `cardinality in {"primary_plus_secondary", "primary_plus_optional_
    secondary"}` (`field`, `claim_type`, `theory_school`):
    `parse_multi_value_tag_response` / `validate_multi_value_tag`, one
    shared pair of functions covering both variants (Appendix A vs. B/E).
    A `subtags` list, when present, is validated against that specific
    primary tag's OWN declared subtags (read from the axis's `raw` --
    `_declared_subtags` -- never the axis's full subtag universe), and an
    axis-level `status` flag (e.g. theory_school's `candidate`), when the
    schema declares one, is always taken from the schema itself
    (`_axis_extras`), never trusted from the model's response.
  - `cardinality == "many"` (`polities_touched`, issue #194 slice 05,
    Appendix C/G): `parse_many_valued_tag_response` parses a JSON list of
    free-text strings -- no vocabulary check applies (`values: free_text`
    has no controlled vocabulary), so this cardinality never raises
    `TagNotInSchemaError`. An absent key is `[]` (a chunk may substantively
    engage no polity).

Any tag value absent from its axis's schema vocabulary is a hard error
naming the axis and the offending tag (`TagNotInSchemaError`, reused
unchanged for every vocabulary-checked cardinality). Each emitted record
carries the chunk's provenance (chunk_id, section, chunk_text) plus the
`schema_version` it was tagged under, so a later schema change is
detectable per note.

A source whose chunking yields zero chunks yields zero tagged records
without ever calling the LLM for the tag pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

import yaml

from axial.chunk import ChunkError, MissingSourceError as _ChunkMissingSourceError, read_chunks
from axial.checkpoint import (
    append_checkpoint_record,
    heal_torn_checkpoint_tail as _shared_heal_torn_checkpoint_tail,
    load_checkpoint_records,
)
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.codebook import Codebook, CodebookError, load_codebook
from axial.llm import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    TAG_PASS_NAME,
    ContentRefusedError,
    LLMClient,
    LLMError,
    get_client,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.nonprose_guard import garble_only_skip_reason
from axial.schema import Axis, Schema, SchemaError, load_schema

DEFAULT_DOMAIN_DIR = Path("config/domains/syria")


def _default_domain_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Read `paths.domain_dir` from `config/pipeline.yaml` (mirrors
    `axial.envelope._default_envelopes_dir`'s exact structure for
    `paths.envelopes_dir`), so a config-declared domain directory is
    actually honored rather than only the hardcoded `DEFAULT_DOMAIN_DIR`
    default. An absent file/key falls back to `DEFAULT_DOMAIN_DIR`."""
    if not config_path.is_file():
        return DEFAULT_DOMAIN_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("domain_dir")
    return Path(configured) if configured else DEFAULT_DOMAIN_DIR


TAGS_DIR = Path("data/tags")


def _default_tags_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Resolve the tag-checkpoint directory, mirroring
    `axial.envelope._default_envelopes_dir` / `axial.chunk._default_chunks_dir`
    exactly: honor `config/pipeline.yaml`'s `paths.tags_dir` when declared,
    else fall back to the module-level `TAGS_DIR` default (`data/tags`,
    resolved relative to the current working directory). An absent file/key
    falls back to `TAGS_DIR`."""
    if not config_path.is_file():
        return TAGS_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("tags_dir")
    return Path(configured) if configured else TAGS_DIR


def tags_checkpoint_path(source_id: str, tags_dir: Path = TAGS_DIR) -> Path:
    """The resume path for `source_id`'s tag-pass checkpoint (one JSON tagged
    record per line, appended as each chunk is tagged), keyed by the
    content-hashed source_id so an edited file never reuses a stale tag set
    (issue #81 point 2)."""
    return tags_dir / f"{source_id}.jsonl"


def _heal_torn_checkpoint_tail(path: Path) -> None:
    """Truncate a torn tail left by a hard kill mid-`append_tag_checkpoint`
    (issue #81 hardening) -- thin wrapper around the shared
    `axial.checkpoint.heal_torn_checkpoint_tail`, kept as a module-level name
    here since it predates the shared extraction and existing callers/tests
    reach it via `axial.tag`."""
    _shared_heal_torn_checkpoint_tail(path)


def append_tag_checkpoint(path: Path, record: dict[str, Any]) -> None:
    """Append one tagged record to `path` AS IT IS PRODUCED (issue #81 point
    2): heal any torn tail left by an earlier hard kill, then write+flush the
    JSON line -- so a mid-tag failure leaves every already-tagged chunk
    durably on disk for the resume run. Delegates to the shared
    `axial.checkpoint.append_checkpoint_record` (issue #98 extraction)."""
    append_checkpoint_record(path, record)


def load_tag_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load already-tagged records from a tag-pass checkpoint file (the
    inverse of `append_tag_checkpoint`), skipping blank lines. Returns an
    empty list when the file does not exist yet (the first, never-interrupted
    run).

    Hardening (issue #81): a hard process kill (OOM kill, Stop-Process) mid-
    `append_tag_checkpoint` can leave the file's LAST line partially flushed
    -- since each append writes and flushes exactly one line before
    returning, a kill can only ever tear the line currently in flight, which
    is always the last one. That torn final line is dropped silently (its
    chunk simply re-tags on the resume run) rather than raising -- a torn
    checkpoint would otherwise permanently poison that source's resume,
    strictly worse than no checkpoint at all. A torn line that is NOT the
    last one is genuine corruption unrelated to a kill mid-append (e.g. disk
    corruption or a manual edit), and still raises loudly
    (`TagCheckpointCorruptError`, naming the path and the offending
    1-indexed line number). Delegates the mechanics to the shared
    `axial.checkpoint.load_checkpoint_records` (issue #98 extraction)."""
    return load_checkpoint_records(path, TagCheckpointCorruptError)


ROLE_IN_ARGUMENT_AXIS = "role_in_argument"
EMPIRICAL_SCOPE_AXIS = "empirical_scope"
POLITIES_TOUCHED_AXIS = "polities_touched"
FIELD_AXIS = "field"
CLAIM_TYPE_AXIS = "claim_type"
THEORY_SCHOOL_AXIS = "theory_school"

# Axes this pass assigns, in prompt/extraction order. Only axes the loaded
# schema actually declares are tagged for a given domain -- so a minimal
# schema lacking one of these (e.g. an inner unit test's fixture domain) is
# tagged on the rest alone, never a hard error for an axis the schema
# doesn't define.
TAGGED_AXES = (
    ROLE_IN_ARGUMENT_AXIS,
    EMPIRICAL_SCOPE_AXIS,
    POLITIES_TOUCHED_AXIS,
    FIELD_AXIS,
    CLAIM_TYPE_AXIS,
    THEORY_SCHOOL_AXIS,
)

# Cardinalities handled by the shared multi-value parser/validator (issue
# #29 slice 03): one primary tag plus either zero-or-more secondary tags
# (Appendix A) or an optional single secondary tag (Appendix B/E). Which
# axis has which cardinality is schema data (`Axis.cardinality`), never
# branched on by axis name.
MULTI_VALUE_CARDINALITIES = {"primary_plus_secondary", "primary_plus_optional_secondary"}

# The many-valued free-text cardinality (Appendix C/G, issue #194 slice 05):
# `polities_touched` today, but dispatched on `Axis.cardinality == "many"`,
# never on the axis's name -- see `parse_many_valued_tag_response`.
MANY_VALUED_CARDINALITY = "many"

# Appendix C/G: the one empirical_scope value that carries a `polity` extra
# field, drawn from the schema's `polity_examples` (Appendix G) -- examples,
# not a closed menu (spec-drift #77 / issue #194 slice 05).
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
You are assigning tags for the CHUNK below, one axis at a time, from each \
axis's closed controlled vocabulary. Respond with ONLY a JSON object (no \
prose, no markdown fences) with exactly one key per axis listed below \
({axis_names!r}). A single-cardinality axis's value is exactly one tag id \
(a single string, not a list). A primary+secondary axis's value is an \
object `{{"primary": <tag id>, "secondary": [...]}}` (zero or more \
secondary tags) or `{{"primary": <tag id>, "secondary": <tag id or \
omitted>}}` (at most one optional secondary tag) -- see each axis's own \
instructions below for which. Where an axis's own tags declare subtags, \
also include a `"subtags"` list of any that apply, each one of that \
specific primary tag's own declared subtags. A many-valued free-text axis's \
value is a JSON list of strings (empty list `[]` when none apply) -- see \
its own instructions below.

If the empirical_scope value you choose is "{country_case_scope}", also \
include a "polity" key whose value is the specific polity this chunk is \
about, named faithfully as free text -- NOT restricted to a closed menu. \
The polity examples below are illustrations, not an exhaustive list: name \
the true polity even when it is absent from the examples, historical, \
defunct, or supra-national (an empire, a mandate, a former union). \
Emitting a value outside the examples is expected and correct, never a \
mistake to avoid.

{axis_sections}

Polity examples (illustrative only, not a closed menu -- only required \
when empirical_scope is "{country_case_scope}"):

{polity_examples}

Chunk:

{chunk_text}
"""

# Prompt text for a many-valued free-text axis (currently only
# `polities_touched`), read from the axis's own schema-declared cardinality
# (`"many"`) rather than its name -- so a future second `many`-cardinality
# axis would render identically, never a name-specific branch.
_MANY_VALUED_AXIS_SECTION_TEMPLATE = """\
Axis {axis_name!r} (cardinality: many, free text, no closed vocabulary) -- \
a many-valued list of every polity this CHUNK substantively *engages*: the \
chunk reasons about it, compares it, or draws evidence from it -- an \
incidental mention in passing does not qualify ("engaged, not \
name-dropped"). Name each polity faithfully, under the same rules as the \
"polity" field above -- historical, defunct, or supra-national referents \
are legitimate and expected when that is what the chunk actually engages. \
An empty list `[]` is a valid answer when the chunk substantively engages \
no polity."""


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
    """Raised when reading the on-disk chunk artifact fails -- e.g. no
    source file, or no chunk artifact yet (`axial.chunk.
    MissingChunkArtifactError`, telling the operator to run `axial chunk`
    first). The tag pass never (re)computes chunk boundaries itself, so any
    `axial.chunk.ChunkError` from `read_chunks` is wrapped and surfaced here
    instead."""

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
    loaded schema's axis vocabulary (PRD §7.1, P0-6).

    Carries the controlled `vocabulary` legal for the FAILING POSITION and an
    optional human-readable `position` label (issue #102): a subtag failure's
    legal set is that specific primary's own declared subtags, NOT the axis's
    primary vocabulary, so the bounded correction re-ask can show the model
    the right options to correct against. Both are optional so every existing
    raise site (and the locked error message) is unchanged when they are
    omitted."""

    def __init__(
        self,
        axis_name: str,
        tag: Any,
        *,
        vocabulary: set[str] | None = None,
        position: str | None = None,
    ):
        self.axis_name = axis_name
        self.tag = tag
        self.vocabulary = vocabulary
        self.position = position
        super().__init__(f"tag {tag!r} is not in the schema's {axis_name!r} axis")


class CountryCaseMissingPolityError(TagError):
    """Raised when empirical_scope == 'scope:country-case' but the tag
    response carries no (or an empty) 'polity' value (PRD Appendix C/G:
    'a missing or empty value stays the hard error it is today')."""

    def __init__(self):
        super().__init__(
            "empirical_scope 'scope:country-case' requires a 'polity' value, but none was provided"
        )


class TagCheckpointCorruptError(TagError):
    """Raised by `load_tag_checkpoint` when a NON-final line of a tag
    checkpoint file is not valid JSON (issue #81 hardening). A torn FINAL
    line is tolerated (a hard process kill can only ever tear the line
    currently being appended, always the last one -- see
    `load_tag_checkpoint`'s docstring); a torn line anywhere else is genuine
    corruption unrelated to a kill mid-append, and is a loud, diagnosable
    error naming the checkpoint path and the offending 1-indexed line
    number, rather than a silent partial load."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt tag checkpoint {path}: line {line_no} is not valid JSON: {cause}"
        )


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
    schema: Schema,
    polity_examples: list[str] | None = None,
) -> str:
    """Compose a single tagging prompt covering every axis in `axis_names`,
    so one LLM call (`pass_name=TAG_PASS_NAME`) can assign all of them at
    once instead of one call per axis (issue #28 slice 02). Each axis's
    section names its own `schema`-declared cardinality (single vs.
    primary+secondary vs. many, issues #29 slice 03 / #194 slice 05) so the
    model knows which shape to answer in -- read from the schema, never
    branched on the axis's name. Also surfaces `polity_examples` (Appendix
    C/G: illustrations, not a closed menu) so the model knows what a
    faithfully-named polity looks like when it assigns `empirical_scope:
    "scope:country-case"`."""
    sections = []
    for axis_name in axis_names:
        axis = schema.axes[axis_name]
        if axis.cardinality == "many":
            sections.append(_MANY_VALUED_AXIS_SECTION_TEMPLATE.format(axis_name=axis_name))
        else:
            sections.append(
                f"Axis {axis_name!r} (cardinality: {axis.cardinality}) "
                f"vocabulary:\n\n{_tag_descriptions(axis_name, codebook)}"
            )
    return _MULTI_AXIS_TAG_PROMPT_TEMPLATE.format(
        axis_names=list(axis_names),
        country_case_scope=COUNTRY_CASE_SCOPE_VALUE,
        axis_sections="\n\n".join(sections),
        polity_examples=", ".join(polity_examples or []),
        chunk_text=chunk_text,
    )


def _reject_blank_tag(value: Any, field: str) -> None:
    """Raise `TagParseError`, naming `field`, when `value` is an empty or
    whitespace-only string -- the same species of response noise as broken
    JSON (#76) or `secondary: []` (#58), never a candidate tag on its own.
    Any non-blank value (including a genuine out-of-vocabulary string) is
    left untouched here: schema-vocabulary validation is `validate_tag`'s
    job alone, entirely separate from this degeneracy check (issue #80)."""
    if isinstance(value, str) and not value.strip():
        raise TagParseError(f"{field} tag value is empty/whitespace-only: {value!r}")


def reject_degenerate_tag_values(raw: str, axes_to_tag: list[str], schema: Schema) -> None:
    """Validator passed to `complete_json` for the tag pass (issue #80):
    re-parses `raw` with the exact same per-axis parsers `run_tag` itself
    uses (`parse_tag_response` / `parse_multi_value_tag_response`), but only
    to reject an empty/whitespace-only tag string -- primary, each secondary
    entry, each subtag, or a single-cardinality axis's value -- as a
    re-askable `TagParseError` naming the offending field. Runs BEFORE
    `run_tag`'s own parse+validate flow, inside `complete_json`'s bounded
    re-ask budget, so a degenerate response never reaches `run_tag`'s own
    parsing at all; a non-degenerate response is parsed again there (cheap,
    and keeps this validator fully decoupled from `run_tag`'s bookkeeping).

    When a single-cardinality axis's value resolves to
    `COUNTRY_CASE_SCOPE_VALUE`, also runs `parse_polity_response` -- the
    exact parser `run_tag` itself later uses for the polity extra -- so a
    country-case response missing/blank `polity` is the same re-askable
    degeneracy as a blank tag, rather than surfacing only after this
    validator returns, outside `complete_json`'s re-ask budget (issue #92).
    A transient omission gets the bounded re-ask; PERSISTENT absence still
    surfaces `CountryCaseMissingPolityError` unchanged once re-asks are
    exhausted, since `complete_json` propagates the final attempt's
    exception unchanged -- preserving the #77-adjudicated hard error.

    A many-valued free-text axis (`cardinality == "many"`, e.g.
    `polities_touched`, issue #194 slice 05) is parsed via `parse_many_
    valued_tag_response` and each entry checked the same blank-string way
    -- but never against a vocabulary, since a free-text axis has none.

    Deliberately never calls `validate_tag`/`validate_multi_value_tag`: a
    genuine non-empty out-of-vocabulary tag must stay immediately fatal
    (`TagNotInSchemaError`, the P0-6 schema-gap signal), never smoothed over
    by a re-ask here."""
    for axis_name in axes_to_tag:
        axis = schema.axes[axis_name]
        if axis.cardinality in MULTI_VALUE_CARDINALITIES:
            parsed = parse_multi_value_tag_response(raw, axis)
            _reject_blank_tag(parsed["primary"], f"{axis_name}.primary")
            secondary = parsed.get("secondary")
            secondary_values = (
                secondary
                if isinstance(secondary, list)
                else ([secondary] if secondary is not None else [])
            )
            for index, value in enumerate(secondary_values):
                _reject_blank_tag(value, f"{axis_name}.secondary[{index}]")
            for index, value in enumerate(parsed.get("subtags") or []):
                _reject_blank_tag(value, f"{axis_name}.subtags[{index}]")
        elif axis.cardinality == MANY_VALUED_CARDINALITY:
            for index, value in enumerate(parse_many_valued_tag_response(raw, axis_name)):
                _reject_blank_tag(value, f"{axis_name}[{index}]")
        else:
            value = parse_tag_response(raw, axis_name)
            _reject_blank_tag(value, axis_name)
            if value == COUNTRY_CASE_SCOPE_VALUE:
                parse_polity_response(raw, axis_name)


# Keys ignored when hunting for the lone remaining candidate entry in an
# object-shaped single-axis value (`_value_echo_entry`) -- the same "extras"
# a country-case empirical_scope response may carry alongside its value,
# plus the primary+secondary shape's own `secondary`/`subtags` (issue #88
# point 3).
_AUXILIARY_TAG_OBJECT_KEYS = frozenset({"polity", "secondary", "subtags"})


def _value_echo_entry(raw_value: dict[str, Any]) -> str | None:
    """After excluding `_AUXILIARY_TAG_OBJECT_KEYS`, return the lone
    remaining entry's value when exactly one such entry ECHOES its own key as
    its string value (`{X: X}`) -- the observed "value-as-key" dialect (e.g.
    `{'scope:country-case': 'scope:country-case', 'polity': ...}`, issue
    #88 point 3): the model echoes the tag id back as both key and value
    instead of naming it under `'primary'` or `'value'`. Deliberately
    narrower than "any lone string entry": a lone entry whose key and value
    DIFFER (e.g. free-form `{'reasoning': 'some prose'}`) is never a
    candidate here -- accepting it would let prose parse cleanly only to die
    fatally at `validate_tag` outside `complete_json`'s re-ask budget,
    converting today's re-askable `TagParseError` into a source-killer
    (review finding on issue #88). Returns `None` (never a silent pick) when
    zero or more than one such echoing candidate remains, so the caller
    raises `TagParseError` instead."""
    candidates = [
        key
        for key, value in raw_value.items()
        if key not in _AUXILIARY_TAG_OBJECT_KEYS and isinstance(value, str) and value == key
    ]
    return candidates[0] if len(candidates) == 1 else None


def parse_tag_response(raw: str, axis_name: str) -> str:
    """Parse the model's raw tagging response into a single axis value.

    Accepts a top-level JSON object with `axis_name` as a key, whose value
    is either a bare string (the common case) or a single-element list.
    Zero or multiple values is a cardinality error, not a silent pick.

    Also accepts an object-shaped value -- the dialects deepseek-v4-flash
    modally answers with for a single-cardinality axis instead of a bare
    string, most often for `empirical_scope` on `scope:country-case` chunks
    (issue #62, widened by issue #88) -- resolved in this priority order:

      1. a string `'primary'` (issue #62's original shape, from the shared
         multi-axis prompt's primary+secondary object dialect);
      2. else a string `'value'` (issue #88 point 2: `{'value':
         'scope:country-case', 'polity': ...}`);
      3. else, after excluding auxiliary keys (`'polity'`, `'secondary'`,
         `'subtags'`), exactly ONE remaining entry whose string value ECHOES
         its own key (`{X: X}`) (issue #88 point 3, the "value-as-key"
         dialect: `{'scope:country-case': 'scope:country-case', 'polity':
         ...}`) -- narrower than "any lone string entry" on purpose: a lone
         entry whose key and value differ (e.g. free-form `{'reasoning':
         'some prose'}`) is never a candidate, since that would let real
         prose parse cleanly here only to die fatally at `validate_tag`
         outside the re-ask budget;
      4. else `TagParseError` -- a genuine multi-candidate (or non-echoing)
         object is never a silent pick.

    Whichever path resolves the value, a non-empty `secondary` (list or
    scalar) still raises `TagCardinalityError`, since a second value
    asserted on a single axis must never be silently dropped; unrelated
    extra keys (e.g. a nested `polity`) are otherwise ignored here.
    """
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or axis_name not in data:
        keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
        raise TagParseError(f"expected a top-level {axis_name!r} key, got: {keys}")

    raw_value = data[axis_name]

    if isinstance(raw_value, dict):
        primary = raw_value.get("primary")
        value_key = raw_value.get("value")
        if isinstance(primary, str):
            extracted = primary
        elif isinstance(value_key, str):
            extracted = value_key
        else:
            extracted = _value_echo_entry(raw_value)
            if extracted is None:
                raise TagParseError(
                    f"expected {axis_name!r} value to be a string, got an object "
                    f"without a string 'primary', 'value', or exactly one other "
                    f"self-echoing entry ({{X: X}}): {raw_value!r}"
                )
        secondary = raw_value.get("secondary")
        secondary_values = (
            secondary if isinstance(secondary, list) else ([secondary] if secondary else [])
        )
        if secondary_values:
            raise TagCardinalityError(axis_name, [extracted, *secondary_values])
        return extracted

    values = raw_value if isinstance(raw_value, list) else [raw_value]

    if len(values) != 1:
        raise TagCardinalityError(axis_name, values)

    value = values[0]
    if not isinstance(value, str):
        raise TagParseError(
            f"expected {axis_name!r} value to be a string, got {type(value).__name__}: {value!r}"
        )

    return value


def _normalize_axis_prefixed_value(axis_name: str, value: Any, vocabulary: set[str]) -> Any:
    """Normalize a string `value` of the form `"<axis_name>:<suffix>"` to
    its bare `<suffix>` -- but ONLY when the raw value is NOT already a
    member of `vocabulary` and the stripped suffix IS (issue #96: the live
    model recurringly echoes the axis's own name as a prefix, e.g.
    `field:ideology` for the `field` axis's `ideology` value).

    Deliberately narrow, so this never smooths over a genuine schema gap or
    reaches into an axis whose vocabulary is ITSELF prefix-shaped:

      - a value already in `vocabulary` (e.g. `empirical_scope`'s own
        `"scope:general"`, or `role_in_argument`'s own `"role:setup"`) is
        returned untouched -- the first condition never even fires;
      - a value prefixed with anything other than exactly `"<axis_name>:"`
        (e.g. `"scope:general"` under the `field` axis) is returned
        untouched;
      - a value whose stripped suffix is ALSO not in `vocabulary` (e.g.
        `"field:ethnicity"`) is returned untouched, so it still fails
        validation and still raises `TagNotInSchemaError` naming the
        original, unnormalized value;
      - a non-string value is returned untouched (only strings can carry a
        `"prefix:"` shape at all).
    """
    if not isinstance(value, str) or value in vocabulary:
        return value
    prefix = f"{axis_name}:"
    if value.startswith(prefix):
        suffix = value[len(prefix) :]
        if suffix in vocabulary:
            return suffix
    return value


def validate_tag(schema: Schema, axis_name: str, value: Any) -> Any:
    """Validate that `value` exists in the loaded schema's `axis_name` tag
    set; raises `TagNotInSchemaError` (naming the axis + offending tag) if
    not (PRD §7.1, P0-6).

    Before that check, normalizes `value` per `_normalize_axis_prefixed_
    value` (issue #96): a value of the form `"<axis_name>:<suffix>"` whose
    raw form is out-of-vocabulary but whose stripped suffix IS in-vocabulary
    is rewritten to that suffix first, so e.g. `field.primary ==
    "field:ideology"` validates (and is returned) as `"ideology"`. Returns
    the value to use going forward -- the normalized form when normalization
    applied, otherwise `value` unchanged -- so every caller must use the
    return value rather than assuming the passed-in `value` survives
    verbatim."""
    axis = schema.axes.get(axis_name)
    if axis is not None:
        value = _normalize_axis_prefixed_value(axis_name, value, axis.tag_ids)
    if axis is None or value not in axis.tag_ids:
        raise TagNotInSchemaError(
            axis_name, value, vocabulary=(axis.tag_ids if axis is not None else None)
        )
    return value


def _axis_declares_subtags(axis: Axis) -> bool:
    """Whether `axis`'s own vocabulary structurally supports per-tag
    `subtags` at all -- a list of `{id, ...}` tag objects (e.g. claim_type),
    as opposed to a flat scalar list (field) or grouped mapping
    (theory_school). Read from the schema, never the axis's name."""
    return any(isinstance(entry, dict) for entry in axis.raw.get("values") or [])


def _declared_subtags(axis: Axis, primary: str) -> set[str]:
    """The `primary` tag's own declared `subtags` list, read from the
    axis's `raw` values (empty if that entry declares none, or if the
    axis's vocabulary isn't a list of `{id, ...}` tag objects at all --
    e.g. `field`'s flat scalar list). Never the axis's full subtag universe
    (Appendix B: "sub-tags refine, they do not multiply the count")."""
    for entry in axis.raw.get("values") or []:
        if isinstance(entry, dict) and entry.get("id") == primary:
            return set(entry.get("subtags") or [])
    return set()


def parse_multi_value_tag_response(raw: str, axis: Axis) -> dict[str, Any]:
    """Parse the model's raw tagging response for one primary+secondary axis
    (`axis.cardinality` one of `MULTI_VALUE_CARDINALITIES`), shared by every
    axis of either cardinality (issue #29 slice 03) -- never one parser per
    axis.

    Per seam decision 9 (tests/test_tag.py), the raw response nests the
    axis's value in exactly the shape the final record exposes:
    `{axis.name: {"primary": <str>, "secondary": [...] | <str> | omitted,
    "subtags": [...] (optional)}}`. `"primary_plus_secondary"` (Appendix A)
    always yields a `secondary` list (zero or more, defaulting to `[]` when
    omitted); `"primary_plus_optional_secondary"` (Appendix B/E) yields
    `secondary` as `None` or a single scalar string, never a list -- but since
    the shared tagging prompt shows the list shape for the sibling
    cardinality, a model may still answer with a list here, so `[]` is
    normalized to `None` and a single-element list to its lone element before
    anything longer than that is rejected as a genuine cardinality violation.
    When the axis's own vocabulary structurally declares subtags at all
    (`_axis_declares_subtags`), `subtags` defaults to `[]` if the model
    omitted it, so e.g. `claim_type.subtags` is always a list."""
    axis_name = axis.name
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or axis_name not in data:
        keys = sorted(data.keys()) if isinstance(data, dict) else type(data).__name__
        raise TagParseError(f"expected a top-level {axis_name!r} key, got: {keys}")

    axis_value = data[axis_name]
    if isinstance(axis_value, str) and axis.cardinality == "primary_plus_optional_secondary":
        # Issue #105: a bare, unambiguous string for a
        # primary_plus_optional_secondary axis is a known model dialect for
        # "just the primary, no secondary" -- coerce it to the object shape
        # BEFORE the shape check below, so it flows through the same
        # vocabulary validation as every other value (an out-of-vocab bare
        # string still fails vocabulary validation downstream, and still
        # triggers the #102 correction re-ask -- coercion never bypasses
        # that check, it only fixes the shape ahead of it).
        axis_value = {"primary": axis_value}

    if not isinstance(axis_value, dict) or "primary" not in axis_value:
        raise TagParseError(
            f"expected {axis_name!r} value to be an object with a 'primary' "
            f"key, got {type(axis_value).__name__}: {axis_value!r}"
        )

    primary = axis_value["primary"]
    if not isinstance(primary, str):
        raise TagParseError(
            f"expected {axis_name!r}.primary to be a string, got "
            f"{type(primary).__name__}: {primary!r}"
        )

    raw_secondary = axis_value.get("secondary")
    if axis.cardinality == "primary_plus_secondary":
        secondary: Any = raw_secondary if raw_secondary is not None else []
        if not isinstance(secondary, list):
            secondary = [secondary]
    else:
        secondary = raw_secondary
        if isinstance(secondary, list):
            if len(secondary) == 0:
                secondary = None
            elif len(secondary) == 1:
                secondary = secondary[0]
        if secondary is not None and not isinstance(secondary, str):
            raise TagParseError(
                f"expected {axis_name!r}.secondary, when present, to be a "
                f"single string, got {type(secondary).__name__}: {secondary!r}"
            )

    parsed: dict[str, Any] = {"primary": primary, "secondary": secondary}
    if "subtags" in axis_value:
        raw_subtags = axis_value["subtags"]
        parsed["subtags"] = raw_subtags if isinstance(raw_subtags, list) else [raw_subtags]
    elif _axis_declares_subtags(axis):
        parsed["subtags"] = []

    return parsed


def validate_multi_value_tag(schema: Schema, axis_name: str, parsed: dict[str, Any]) -> None:
    """Validate a parsed primary+secondary axis value against the loaded
    schema: `primary` and every `secondary`/`subtags` entry must exist in
    the schema (`TagNotInSchemaError`, naming axis + offending tag), with
    subtags checked against that specific primary's OWN declared subtags
    (`_declared_subtags`), not the axis's full subtag universe.

    Normalizes `primary`, each `secondary` entry, and each `subtags` entry
    in place on `parsed` (issue #96, mirroring `validate_tag`'s own
    normalization): an axis-name-prefixed value that is out-of-vocabulary
    raw but in-vocabulary once the `"<axis_name>:"` prefix is stripped is
    rewritten before validation, so callers reading `parsed` afterward (both
    `run_tag`'s own record assembly and `axial.artifacts`, which reuses this
    validator for its own `field` classification) see the normalized value,
    never the raw prefixed one."""
    parsed["primary"] = validate_tag(schema, axis_name, parsed["primary"])

    secondary = parsed.get("secondary")
    if isinstance(secondary, list):
        parsed["secondary"] = [validate_tag(schema, axis_name, value) for value in secondary]
    elif secondary is not None:
        parsed["secondary"] = validate_tag(schema, axis_name, secondary)

    if "subtags" in parsed:
        declared = _declared_subtags(schema.axes[axis_name], parsed["primary"])
        normalized_subtags = []
        for subtag in parsed["subtags"]:
            normalized = _normalize_axis_prefixed_value(axis_name, subtag, declared)
            if normalized not in declared:
                raise TagNotInSchemaError(
                    axis_name,
                    subtag,
                    vocabulary=declared,
                    position=f"as a subtag of the primary {parsed['primary']!r}",
                )
            normalized_subtags.append(normalized)
        parsed["subtags"] = normalized_subtags


def parse_many_valued_tag_response(raw: str, axis_name: str) -> list[str]:
    """Parse the model's raw tagging response for one many-valued free-text
    axis (`Axis.cardinality == "many"`, e.g. `polities_touched`, issue #194
    slice 05 / Appendix C/G): a JSON list of strings under `axis_name`.

    No vocabulary validation applies here -- a free-text axis (`values:
    free_text`) has no controlled vocabulary to check membership against,
    unlike every other tagged axis this pass parses.

    An ABSENT `axis_name` key is treated as `[]` rather than a parse error
    (the spec's own "empty is allowed" rule: a chunk may substantively
    engage no polity at all) -- but a PRESENT key that is not a list, or a
    list containing a non-string entry, is a genuine shape error
    (`TagParseError`), the same species of malformation every other parser
    in this module raises on."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise TagParseError(
            f"expected a top-level JSON object, got {type(data).__name__}: {data!r}"
        )

    if axis_name not in data:
        return []

    values = data[axis_name]
    if not isinstance(values, list):
        raise TagParseError(
            f"expected {axis_name!r} value to be a list of strings, got "
            f"{type(values).__name__}: {values!r}"
        )
    for value in values:
        if not isinstance(value, str):
            raise TagParseError(
                f"expected every {axis_name!r} entry to be a string, got "
                f"{type(value).__name__}: {value!r} (full list: {values!r})"
            )
    return values


def _axis_extras(axis: Axis) -> dict[str, Any]:
    """Axis-level extra metadata attached to every record's per-axis
    object -- currently only `theory_school`'s schema-declared `status`
    flag (Appendix E) -- read from the schema itself, never trusted from
    the model's response, and never branched on the axis's name (any axis
    whose `raw` declares a `status` gets it the same way)."""
    extras: dict[str, Any] = {}
    if "status" in axis.raw:
        extras["status"] = axis.raw["status"]
    return extras


def parse_polity_response(raw: str, axis_name: str | None = None) -> str:
    """Parse the model's raw tagging response for its `polity` extra field
    (Appendix C/G, required when `empirical_scope == "scope:country-case"`).
    A missing or empty `polity` key is a hard error
    (`CountryCaseMissingPolityError`), not a silent pass. When the
    top-level `polity` is
    absent/empty and `axis_name` is given, also accepts `polity` nested
    inside `data[axis_name]` (e.g. `{"empirical_scope": {"primary": ...,
    "polity": ...}}`), since deepseek-v4-flash sometimes answers
    `empirical_scope` in the object dialect the shared prompt shows for
    primary+secondary axes and nests `polity` there instead of as a
    top-level sibling key (issue #62); the caller (`run_tag`) passes the
    scope axis's own name, so this parser never hardcodes it."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise TagParseError(f"model response was not valid JSON: {exc}") from exc

    polity: Any = data.get("polity") if isinstance(data, dict) else None

    if not polity and axis_name is not None and isinstance(data, dict):
        axis_value = data.get(axis_name)
        if isinstance(axis_value, dict):
            polity = axis_value.get("polity")

    if not polity:
        raise CountryCaseMissingPolityError()

    if not isinstance(polity, str):
        raise TagParseError(
            f"expected 'polity' value to be a string, got {type(polity).__name__}: {polity!r}"
        )
    return polity


def log_polity_not_in_list(schema: Schema, polity: str) -> None:
    """Log a non-fatal diagnostic to stderr when `polity` is not a member
    of the loaded schema's `polity_examples` (Appendix G).

    Spec-drift #77 (adjudicated 2026-07-10): a controlled polity list is no
    longer enforced in v0 -- any non-empty `polity` is accepted verbatim --
    but an out-of-list value is surfaced as a candidate addition for later
    review, never raised. Mirrors `axial.extract`'s `_log_fallback`
    convention: stderr only, stdout stays pure JSON.
    """
    if polity not in schema.polity_examples:
        print(
            f"polity {polity!r} is not in the schema's polity_examples; "
            f"logging as a candidate addition",
            file=sys.stderr,
        )


def build_tagged_record(
    chunk_record: dict[str, Any],
    role_in_argument: str,
    schema_version: str,
    empirical_scope: str | None = None,
    polity: str | None = None,
    multi_value_axes: dict[str, dict[str, Any]] | None = None,
    many_valued_axes: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Assemble a tagged record carrying the chunk's provenance (chunk_id,
    section, chunk_text) plus the role_in_argument value and the schema
    version it was tagged under (PRD §7.1). When `empirical_scope` is given
    it is added too (issue #28 slice 02); when `polity` is also given (only
    meaningful for a `scope:country-case` record) it is added as well. A
    non-country-case record must not carry a `polity` field at all.
    `multi_value_axes` (issue #29 slice 03) maps each primary+secondary
    axis name to its already-parsed-and-validated nested object
    (`{"primary": ..., "secondary": ..., ...}`), added under that same axis
    name -- one key per axis the schema declared and the pass tagged, no
    per-axis branching here either. `many_valued_axes` (issue #194 slice
    05) maps each many-valued free-text axis name (currently only
    `polities_touched`) to its already-parsed list of strings, added under
    that same axis name the same way -- always the list the parser
    produced (possibly `[]`), never omitted when the axis was tagged."""
    record: dict[str, Any] = {
        "chunk_id": chunk_record["chunk_id"],
        "section": chunk_record["section"],
        "chunk_text": chunk_record["text"],
        "role_in_argument": role_in_argument,
        "schema_version": schema_version,
    }
    if empirical_scope is not None:
        record["empirical_scope"] = empirical_scope
    if polity is not None:
        record["polity"] = polity
    for axis_name, axis_value in (multi_value_axes or {}).items():
        record[axis_name] = axis_value
    for axis_name, axis_values in (many_valued_axes or {}).items():
        record[axis_name] = axis_values
    return record


# Appended to a pass's own base prompt to form the P0-6 bounded correction
# re-ask (issue #102). Shows the invalid value, the controlled vocabulary
# legal for the FAILING POSITION (a subtag failure shows that primary's own
# declared subtags, not the axis's primary vocabulary), and the instruction to
# return a valid value or the literal NONE. Deliberately avoids the chunk-pass
# and xref-pass prompt markers so a recorded run still counts it as a
# tag-pass-family call, not a chunk/xref one.
_CORRECTION_REASK_NOTICE = """\

CORRECTION REQUIRED. Your previous answer used {invalid!r} for the {axis!r} \
axis{position}, but that value is NOT in its controlled vocabulary. Choose one \
value strictly from this controlled vocabulary:

{vocabulary}

Reply with the FULL JSON object again -- every key exactly as instructed \
above -- replacing only the invalid value with a valid one drawn from that \
vocabulary, or the single word NONE if, and only if, none of them applies.
"""


def compose_correction_prompt(base_prompt: str, exc: TagNotInSchemaError) -> str:
    """Build the bounded correction re-ask prompt (issue #102): the pass's own
    `base_prompt` plus a correction notice naming the invalid value, the
    failing position, and the controlled vocabulary legal there (from
    `exc.vocabulary`, populated at every schema-vocabulary raise site). The
    model must return a valid value or an explicit NONE -- the code never
    guesses or normalizes the value itself."""
    if exc.vocabulary:
        vocab_text = "\n".join(f"- {value}" for value in sorted(exc.vocabulary))
    else:
        vocab_text = "(that axis's controlled vocabulary, as listed above)"
    position = f" {exc.position}" if exc.position else ""
    notice = _CORRECTION_REASK_NOTICE.format(
        invalid=exc.tag,
        axis=exc.axis_name,
        position=position,
        vocabulary=vocab_text,
    )
    return base_prompt + notice


def apply_correction_reask(
    client: LLMClient,
    pass_name: str,
    raw_response: str,
    base_prompt: str,
    validate: Any,
) -> Any:
    """Run `validate(raw_response)`; on an out-of-vocabulary `TagNotInSchemaError`
    issue EXACTLY ONE bounded correction re-ask and re-validate that one
    correction (issue #102, PRD §7.1 / P0-6).

    `validate(raw)` parses+validates a raw tag/artifact response, raising
    `TagNotInSchemaError` on a schema-vocabulary miss and returning its own
    parsed result otherwise. The correction re-ask is a SINGLE
    `client.complete(correction_prompt, pass_name=pass_name)` call -- distinct
    from `complete_json`'s JSON/degeneracy re-ask budget -- whose prompt shows
    the failing position's controlled vocabulary and asks for a valid value or
    an explicit NONE. If the correction is still out-of-vocabulary (a literal
    NONE is in no axis's vocabulary, so it fails re-validation the same way),
    the re-validation's `TagNotInSchemaError` propagates unchanged: the P0-6
    hard error, never a silent pass and never a code-side guess. The corrected
    value can only ever come from the model's own re-ask response, re-checked
    through the identical vocabulary validation.

    Only `TagNotInSchemaError` triggers the re-ask; any other error `validate`
    raises (parse/cardinality/missing-polity) propagates unchanged, exactly
    as before this layer existed. Transport errors from `client.complete` are
    not caught here -- the caller wraps them into its own typed LLM error."""
    try:
        return validate(raw_response)
    except TagNotInSchemaError as exc:
        correction_prompt = compose_correction_prompt(base_prompt, exc)
        corrected_raw = client.complete(correction_prompt, pass_name=pass_name)
        return validate(corrected_raw)


def _parse_and_validate_tags(
    raw_response: str, axes_to_tag: list[str], schema: Schema
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, list[str]], str | None]:
    """Parse+validate every tagged axis from one raw tag-pass response,
    dispatched on each axis's schema-declared cardinality (never its name).
    Returns `(single_axis_values, multi_value_axes, many_valued_axes,
    polity)`. Raises `TagNotInSchemaError` on any schema-vocabulary miss
    (the signal `apply_correction_reask` catches for its single bounded
    re-ask), and the same parse/cardinality/missing-polity errors as before
    for other malformations -- a many-valued free-text axis (`cardinality
    == "many"`, issue #194 slice 05) never raises `TagNotInSchemaError`,
    since it has no vocabulary to validate against. Factored out of
    `run_tag`'s per-chunk body (issue #102) so the identical parse+validate
    can run on both the original answer and the bounded correction re-ask's
    answer."""
    values: dict[str, str] = {}
    multi_value_axes: dict[str, dict[str, Any]] = {}
    many_valued_axes: dict[str, list[str]] = {}
    polity: str | None = None
    for axis_name in axes_to_tag:
        axis = schema.axes[axis_name]
        if axis.cardinality in MULTI_VALUE_CARDINALITIES:
            parsed = parse_multi_value_tag_response(raw_response, axis)
            validate_multi_value_tag(schema, axis_name, parsed)
            parsed.update(_axis_extras(axis))
            multi_value_axes[axis_name] = parsed
        elif axis.cardinality == MANY_VALUED_CARDINALITY:
            many_valued_axes[axis_name] = parse_many_valued_tag_response(raw_response, axis_name)
        else:
            value = parse_tag_response(raw_response, axis_name)
            value = validate_tag(schema, axis_name, value)
            values[axis_name] = value
            if axis_name == EMPIRICAL_SCOPE_AXIS and value == COUNTRY_CASE_SCOPE_VALUE:
                polity = parse_polity_response(raw_response, axis_name)
                log_polity_not_in_list(schema, polity)
    return values, multi_value_axes, many_valued_axes, polity


class TaggedRecords(list):
    """A `list` of tagged records that also surfaces `quarantine_count`
    (issue #120): a plain `list` subclass so every existing call site
    (`list(result)`, iteration, `json.dumps(records)`) keeps working
    unchanged, while `run_tag`'s caller can additionally read
    `result.quarantine_count` for how many chunks this run quarantined."""

    def __init__(self, records: list[dict[str, Any]], quarantine_count: int = 0):
        super().__init__(records)
        self.quarantine_count = quarantine_count


# Content-caused failure classes this pass quarantines a single chunk for
# instead of aborting the whole source (issue #120): a `ContentRefusedError`
# survives the #116 fallback reroute (content_filter), or a `ModelJsonError`
# survives `complete_json`'s bounded retry budget (malformed_json). Each is a
# content-shaped failure -- retrying the identical prompt against the same
# model cannot change the outcome -- unlike a transient `OpenRouterError`/
# `httpx.HTTPError`, which must keep propagating unchanged (never quarantined,
# see `run_tag`'s per-chunk loop and the locked outer test).
#
# A persisting `TagNotInSchemaError` (out-of-vocab, after the #102 correction
# re-ask already ran) is DELIBERATELY NOT included here (founder ruling,
# descoped from #120): it stays the P0-6 hard error, source-fatal, exactly as
# before this issue -- see tests/test_tag_axis_prefix.py / test_tag_vocab_reask.py.
QUARANTINE_REASON_CONTENT_FILTER = "content_filter"
QUARANTINE_REASON_MALFORMED_JSON = "malformed_json"


def _quarantine_chunk(
    chunk_record: dict[str, Any], reason: str, checkpoint_path: Path | None
) -> None:
    """Log and checkpoint chunk_record's quarantine (issue #120): a stderr
    line naming the chunk and reason, then -- when a checkpoint is active --
    a `{"chunk_id": ..., "quarantine_reason": ...}` record appended via the
    same write+flush-per-record path ordinary tagged records use
    (`append_tag_checkpoint`), so a resume run recognizes and skips it
    (`run_tag`'s checkpoint-load split below) without ever re-calling the
    model."""
    chunk_id = chunk_record["chunk_id"]
    print(f"tag: quarantining chunk {chunk_id}: {reason}", file=sys.stderr)
    if checkpoint_path is not None:
        append_tag_checkpoint(checkpoint_path, {"chunk_id": chunk_id, "quarantine_reason": reason})


def run_tag(
    source_path: str | Path,
    client: LLMClient | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path | None = None,
    tags_dir: Path | None = None,
    chunks_dir: Path | None = None,
) -> TaggedRecords:
    """Run the tagging pass on `source_path`.

    Reads its chunk records from the on-disk chunk artifact
    (`axial.chunk.read_chunks`, never recomputed -- issue #154), then for
    each resulting prose chunk makes one LLM call (`pass_name=TAG_PASS_NAME`)
    to assign every axis the loaded schema declares among `TAGGED_AXES`,
    validating each result against the loaded domain schema. Each axis is
    parsed/validated by its own schema-declared `cardinality` (`single` vs.
    one of `MULTI_VALUE_CARDINALITIES`), never by axis name -- see the
    module docstring. When `empirical_scope` resolves to
    `"scope:country-case"`, the same response's `polity` is also required
    (non-empty, or `CountryCaseMissingPolityError`); a value outside the
    schema's `polity_examples` (Appendix C/G) is accepted verbatim and logged
    to stderr as a candidate addition, never fatal (spec-drift #77). A
    source whose chunk artifact holds zero chunks yields zero tagged
    records without ever calling the LLM for the tag pass.

    `domain_dir`, when omitted, is resolved from `config_path`'s
    `paths.domain_dir` (falling back to `DEFAULT_DOMAIN_DIR` when absent --
    `_default_domain_dir`, mirroring `_default_envelopes_dir`); an explicit
    `domain_dir` always overrides config (issue #38).

    Tag-pass checkpoint/resume (issue #81 point 2/3): OPT-IN, active only when
    a `tags_dir` is supplied (the `axial vault write` composition threads one
    in; standalone `axial tag` passes none and so behaves exactly as before,
    re-tagging every run -- the reuse feature is deliberately scoped to vault
    write). When active: each tagged record is appended to
    `<tags_dir>/<source_id>.jsonl` as it is produced (write+flush per chunk);
    on a later run, chunks whose `chunk_id` already appears there are reused
    verbatim and NOT re-sent to the model, only the missing ones are tagged,
    and checkpointed + fresh records recombine in the chunker's stable order.
    A mid-tag failure therefore leaves every already-tagged chunk on disk, so
    the retry resumes instead of restarting. `chunks_dir`, when supplied, is
    where `read_chunks` looks for the on-disk chunk artifact (defaults to the
    same `data/chunks/` resolution `axial chunk` itself writes to).
    """
    if domain_dir is None:
        domain_dir = _default_domain_dir(config_path)

    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        raise SchemaLoadFailedError(exc) from exc

    try:
        codebook = load_codebook(domain_dir)
    except CodebookError as exc:
        raise CodebookLoadFailedError(exc) from exc

    try:
        source_id = compute_source_id(Path(source_path))
    except _EnvelopeMissingSourceError as exc:
        raise ChunkingFailedError(_ChunkMissingSourceError(exc)) from exc

    try:
        chunk_records = read_chunks(source_id, chunks_dir=chunks_dir, config_path=config_path)
    except ChunkError as exc:
        raise ChunkingFailedError(exc) from exc

    # Tag-pass checkpoint/resume (issue #81 point 2/3), opt-in via `tags_dir`.
    # The checkpoint is keyed by the content-hashed source_id -- already
    # computed above to read the chunk artifact.
    checkpoint_path: Path | None = None
    already_tagged: dict[str, dict[str, Any]] = {}
    already_quarantined: dict[str, str] = {}
    if tags_dir is not None:
        checkpoint_path = tags_checkpoint_path(source_id, tags_dir)
        for record in load_tag_checkpoint(checkpoint_path):
            # A checkpoint record carrying `quarantine_reason` (issue #120)
            # is NOT an ordinary tagged record -- split it into its own
            # skip-set so a resume run recognizes and skips it (no LLM call,
            # no re-quarantine) instead of treating it as cached tag output.
            reason = record.get("quarantine_reason")
            if reason is not None:
                already_quarantined[record["chunk_id"]] = reason
            else:
                already_tagged[record["chunk_id"]] = record

    # Only tag axes the loaded schema actually declares (TAGGED_AXES'
    # comment above): a minimal domain missing empirical_scope is tagged on
    # role_in_argument alone.
    axes_to_tag = [axis_name for axis_name in TAGGED_AXES if axis_name in schema.axes]

    tagged_records: list[dict[str, Any]] = []
    quarantine_count = 0
    for chunk_record in chunk_records:
        # Resume: a chunk already quarantined by an earlier run (issue #120)
        # is skipped outright -- no LLM call, no re-quarantine, and it never
        # becomes a tagged record.
        quarantine_reason = already_quarantined.get(chunk_record["chunk_id"])
        if quarantine_reason is not None:
            print(
                f"tag: skipping quarantined chunk {chunk_record['chunk_id']} "
                f"(reason: {quarantine_reason})",
                file=sys.stderr,
            )
            continue

        # Resume: a chunk already checkpointed by an earlier run is reused
        # verbatim and never re-sent to the model -- records recombine in the
        # chunker's stable order (issue #81 point 2), so note writing is
        # identical to a never-interrupted run.
        checkpointed = already_tagged.get(chunk_record["chunk_id"])
        if checkpointed is not None:
            tagged_records.append(checkpointed)
            continue

        # Input guard (issue #169, source-router slice 04: demoted from
        # primary gate to garble-only backstop). The chunk artifact this
        # pass reads is now prose-only and size-bounded by the router +
        # chunk band (source-router slices 02-03), so a large chunk here is
        # legitimate prose, not back-matter -- size must never skip it. Only
        # the non-alpha arm remains, catching prose genuinely garbled enough
        # to have slipped type classification: no LLM call, no tagged
        # record, no checkpoint write for this chunk. The skip is a
        # deterministic function of the chunk's text, so it re-applies on
        # every resume without ever reaching the model.
        skip_reason = garble_only_skip_reason(chunk_record["text"])
        if skip_reason is not None:
            print(
                f"tag: skipping chunk {chunk_record['chunk_id']}: {skip_reason}",
                file=sys.stderr,
            )
            continue

        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc

        # One LLM call per chunk assigns every tagged axis at once (issue
        # #28 slice 02) -- never one call per axis.
        prompt = compose_multi_axis_tag_prompt(
            chunk_record["text"],
            axes_to_tag,
            codebook,
            schema,
            polity_examples=schema.polity_examples,
        )

        try:
            raw_response = complete_json(
                client,
                prompt,
                pass_name=TAG_PASS_NAME,
                validate=lambda raw: reject_degenerate_tag_values(raw, axes_to_tag, schema),
            )
        except ContentRefusedError as exc:
            # Content-caused, never transient (issue #120): a moderation
            # refusal surviving the #116 fallback reroute cannot be fixed by
            # retrying the identical prompt against the same model -- caught
            # narrowly here (before the broader LLMError clause below, since
            # `ContentRefusedError` subclasses it) so only this specific class
            # is quarantined; every other `LLMError`/`httpx.HTTPError` still
            # propagates exactly as today. Quarantine is scoped to when the
            # checkpoint is active (`tags_dir` supplied) -- mirroring every
            # other checkpoint-only behavior in this pass (issue #81's own
            # "opt-in" docstring above): a standalone `axial tag` run with no
            # checkpoint has nowhere to durably record the quarantine, so it
            # keeps today's hard-error contract unchanged.
            if checkpoint_path is None:
                raise LLMFailedError(exc) from exc
            _quarantine_chunk(chunk_record, QUARANTINE_REASON_CONTENT_FILTER, checkpoint_path)
            quarantine_count += 1
            continue
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc
        except ModelJsonError as exc:
            # Malformed JSON that persisted through `complete_json`'s entire
            # bounded retry budget (issue #120) -- content-shaped, not
            # transient, so this specific chunk is quarantined rather than
            # aborting the whole source (checkpoint-scoped, see above).
            if checkpoint_path is None:
                raise TagParseError(f"model response was not valid JSON: {exc}") from exc
            _quarantine_chunk(chunk_record, QUARANTINE_REASON_MALFORMED_JSON, checkpoint_path)
            quarantine_count += 1
            continue

        # Shared, data-driven cardinality dispatch (issue #29 slice 03): each
        # axis is parsed/validated by its own schema-declared `cardinality`,
        # never by its name. An out-of-vocabulary value triggers exactly ONE
        # bounded correction re-ask (issue #102, P0-6): the model is shown the
        # failing position's controlled vocabulary and must return a valid
        # value or an explicit NONE; still-out-of-vocab after that single
        # re-ask propagates `TagNotInSchemaError` as the hard error. Polity /
        # parse / cardinality errors propagate unchanged (never re-asked
        # here). `client` is already resolved above, so the correction re-ask
        # reuses it; any transport failure it raises wraps to `LLMFailedError`.
        try:
            values, multi_value_axes, many_valued_axes, polity = apply_correction_reask(
                client,
                TAG_PASS_NAME,
                raw_response,
                prompt,
                lambda raw: _parse_and_validate_tags(raw, axes_to_tag, schema),
            )
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc

        record = build_tagged_record(
            chunk_record,
            values[ROLE_IN_ARGUMENT_AXIS],
            schema.version,
            empirical_scope=values.get(EMPIRICAL_SCOPE_AXIS),
            polity=polity,
            multi_value_axes=multi_value_axes,
            many_valued_axes=many_valued_axes,
        )
        # Persist this chunk's tagged record before moving to the next one
        # (write+flush per chunk), so a failure on a later chunk leaves every
        # already-tagged chunk durably checkpointed for the resume run.
        if checkpoint_path is not None:
            append_tag_checkpoint(checkpoint_path, record)
        tagged_records.append(record)

    return TaggedRecords(tagged_records, quarantine_count)
