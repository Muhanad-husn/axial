"""Artifact classification: for each non-text artifact node (a table or
figure) in the extraction tree, one LLM call assigns exactly one
`artifact_role` from the domain schema's closed Appendix D taxonomy (PRD §5
stage 5, §7.2, §8 P0-5).

Unlike the envelope/chunk passes, this pass never reads or writes a stored
envelope -- it walks the extraction tree directly (via `extract`), collects
`type == "artifact"` nodes, and pairs each with its ENCLOSING top-level
section's own verbatim heading `text` for section provenance, exactly as
`axial.chunk`'s `_section_nodes` does for prose. A source with zero artifact
nodes yields zero records with zero LLM calls and no error.

Artifact records carry a stable, deterministic `artifact_id`
(`<source_id>_art_<order>`, using the node's own dotted `order` value
VERBATIM -- unlike `chunk.py`'s chunk_id, dots are never dash-replaced, since
this module's contract locks the dotted-digits shape directly) plus
`artifact_role`, `field`, `source_id`, and `section` (PRD §7.2). This slice
(issue #30 slice 01) emits artifact records to stdout only; routing to
`data/vault/artifacts/` is issue #32 slice 02, which also added `field`
classification here.

A role returned by the model that is absent from the schema's `artifact_role`
axis is a hard error (PRD §8 P0-5/P0-6): `TagNotInSchemaError` is reused
verbatim from `axial.tag` (the shared tag feature is now merged on this
branch), never redefined locally. `field` (one primary + zero-or-more
secondary, Appendix A) is classified and validated the same way, reusing
`axial.tag`'s shared `parse_multi_value_tag_response`/`validate_multi_value_tag`
pair rather than reinventing a field parser here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from axial.codebook import Codebook, CodebookError, load_codebook
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.extract import ExtractError, extract
from axial.llm import (
    ARTIFACTS_PASS_NAME,
    DEFAULT_PIPELINE_CONFIG_PATH,
    LLMClient,
    LLMError,
    get_client,
)
from axial.schema import Schema, SchemaError, load_schema
from axial.tag import (
    TagNotInSchemaError,
    parse_multi_value_tag_response,
    validate_multi_value_tag,
)

# Default domain directory for the artifacts pass, overridable via a
# `domain_dir` argument to `run_artifacts` (and the CLI's `--domain` flag).
DEFAULT_DOMAIN_DIR = Path("config/domains/syria")

_ARTIFACT_ROLE_AXIS = "artifact_role"
FIELD_AXIS = "field"

# PRD §8 P0-5: the one artifact_role whose note is retained in the pool but
# flagged non-retrievable (see src/axial/vault.py's write path). Reused from
# here since this module owns the artifact_role domain vocabulary.
DISCARD_ROLE = "discard"

_ARTIFACT_PROMPT_TEMPLATE = """\
You are classifying a single non-text artifact (a table or figure) drawn \
from the source section titled "{section}" into exactly one artifact_role \
from the closed taxonomy below, and identifying its field (one primary tag \
plus zero or more secondary tags) from the closed field vocabulary below. \
Respond with ONLY a JSON object (no prose, no markdown fences) with exactly \
two keys: "artifact_role" (a single string naming one of the role ids \
listed below), and "field" (an object `{{"primary": <field id>, \
"secondary": [...]}}`, zero or more secondary field ids).

Roles:

{roles}

Field vocabulary:

{fields}
"""


class ArtifactsError(Exception):
    """Base class for all artifact-classification errors."""


class MissingSourceError(ArtifactsError):
    """Raised when the source path does not exist or is not a file."""

    def __init__(self, cause: _EnvelopeMissingSourceError):
        self.cause = cause
        super().__init__(str(cause))


class ExtractionFailedError(ArtifactsError):
    """Raised when the underlying structural extraction pass fails."""

    def __init__(self, cause: ExtractError):
        self.cause = cause
        super().__init__(str(cause))


class SchemaLoadFailedError(ArtifactsError):
    """Raised when the domain schema fails to load."""

    def __init__(self, cause: SchemaError):
        self.cause = cause
        super().__init__(str(cause))


class CodebookLoadFailedError(ArtifactsError):
    """Raised when the domain codebook fails to load."""

    def __init__(self, cause: CodebookError):
        self.cause = cause
        super().__init__(str(cause))


class LLMFailedError(ArtifactsError):
    """Raised when the LLM client -- selection/config or the completion call
    itself -- fails, so the CLI renders a clean `error: ...` instead of a
    bare traceback."""

    def __init__(self, cause: LLMError | httpx.HTTPError):
        self.cause = cause
        super().__init__(str(cause))


class ArtifactParseError(ArtifactsError):
    """Raised when the model's classification response is not parseable
    into a single, non-empty `artifact_role` string."""


# `TagNotInSchemaError` is reused verbatim from `axial.tag` (imported above)
# -- not redefined here. Its constructor is `(axis_name, tag)`. Re-exported
# under this module's namespace (via the import above) so existing callers
# doing `from axial.artifacts import TagNotInSchemaError` keep working
# unchanged.


def _collect_descendant_artifacts(node: dict, section: str) -> list[tuple[dict, str]]:
    """Recurse into `node`'s descendants, pairing every `type == 'artifact'`
    node found with `section` (the enclosing top-level section's own
    verbatim heading)."""
    pairs: list[tuple[dict, str]] = []
    for child in node.get("children", []):
        if child.get("type") == "artifact":
            pairs.append((child, section))
        pairs.extend(_collect_descendant_artifacts(child, section))
    return pairs


def _artifact_nodes_with_section(tree: dict) -> list[tuple[dict, str]]:
    """Collect every `type == 'artifact'` node in the extraction tree, each
    paired with its enclosing top-level section's own verbatim heading text
    (mirroring `axial.chunk`'s `_section_nodes` idea). A top-level node with
    no heading/children (content preceding any heading) carries no section
    label; if it is itself an artifact, it is paired with an empty string
    rather than dropped."""
    pairs: list[tuple[dict, str]] = []
    for child in tree.get("children", []):
        if "children" in child and child.get("text"):
            section = child["text"]
            pairs.extend(_collect_descendant_artifacts(child, section))
        elif child.get("type") == "artifact":
            pairs.append((child, ""))
    return pairs


def build_artifact_record(
    source_id: str,
    node: dict,
    section: str,
    role: str,
    field: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the locked artifact record shape: `artifact_id`
    (`<source_id>_art_<order>`, keeping the node's dotted `order` verbatim),
    `artifact_role`, `source_id`, `section`, plus `field` (issue #32 slice
    02's `{"primary": ..., "secondary": [...]}` mapping) when given -- a
    schema lacking a `field` axis (e.g. a minimal test fixture domain) omits
    the key entirely rather than emitting `field: null`."""
    order = node.get("order", "")
    record: dict[str, Any] = {
        "artifact_id": f"{source_id}_art_{order}",
        "artifact_role": role,
        "source_id": source_id,
        "section": section,
    }
    if field is not None:
        record["field"] = field
    return record


def _format_role_entry(tag_id: str, entry: Any) -> str:
    lines = [f"- {tag_id}: {entry.definition}"]
    if entry.positive_example:
        lines.append(f"  positive example: {entry.positive_example}")
    if entry.negative_example:
        lines.append(f"  negative example: {entry.negative_example}")
    return "\n".join(lines)


def compose_artifact_prompt(section: str, codebook: Codebook) -> str:
    """Compose the artifact-classification prompt from the codebook's
    `artifact_role` and `field` entries (definition + examples), never from
    a hardcoded role/field list, so the prompt always reflects the domain's
    current codebook."""
    role_entries = codebook.axes.get(_ARTIFACT_ROLE_AXIS, {})
    roles = "\n".join(_format_role_entry(tag_id, entry) for tag_id, entry in role_entries.items())
    field_entries = codebook.axes.get(FIELD_AXIS, {})
    fields = "\n".join(_format_role_entry(tag_id, entry) for tag_id, entry in field_entries.items())
    return _ARTIFACT_PROMPT_TEMPLATE.format(section=section, roles=roles, fields=fields)


def parse_artifact_role(raw: str) -> str:
    """Parse the model's raw classification response into a single,
    non-empty `artifact_role` string. Accepts a top-level object with an
    `artifact_role` key."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArtifactParseError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "artifact_role" not in data:
        raise ArtifactParseError(f"expected a top-level 'artifact_role' key, got: {data!r}")

    role = data["artifact_role"]
    if not isinstance(role, str) or not role.strip():
        raise ArtifactParseError(f"expected 'artifact_role' to be a non-empty string, got {role!r}")
    return role


def validate_artifact_role(role: str, schema: Schema) -> None:
    """Validate `role` against the schema's `artifact_role` axis tag_ids,
    raising `TagNotInSchemaError` (a hard error, PRD §8 P0-5/P0-6) if it is
    absent. Reuses `axial.tag.TagNotInSchemaError`, whose constructor order
    is `(axis_name, tag)` -- note this differs from the local class this
    replaced, which took `(role, axis_name)`."""
    axis = schema.axes.get(_ARTIFACT_ROLE_AXIS)
    if axis is None or role not in axis.tag_ids:
        raise TagNotInSchemaError(_ARTIFACT_ROLE_AXIS, role)


def run_artifacts(
    source_path: str | Path,
    client: LLMClient | None = None,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[dict[str, Any]]:
    """Run the artifact-classification pass on `source_path`.

    Walks the extraction tree for `type == 'artifact'` nodes; a source with
    none yields zero records with zero LLM calls and no error. For each
    artifact node found, calls the LLM once (`pass_name="artifacts"`) with a
    prompt composed from the domain codebook's `artifact_role` entries, then
    validates the returned role against the domain schema's `artifact_role`
    axis -- an out-of-schema role is a hard error.
    """
    path = Path(source_path)
    try:
        source_id = compute_source_id(path)
    except _EnvelopeMissingSourceError as exc:
        raise MissingSourceError(exc) from exc

    try:
        tree = extract(path)
    except ExtractError as exc:
        raise ExtractionFailedError(exc) from exc

    pairs = _artifact_nodes_with_section(tree)
    if not pairs:
        return []

    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        raise SchemaLoadFailedError(exc) from exc

    try:
        codebook = load_codebook(domain_dir)
    except CodebookError as exc:
        raise CodebookLoadFailedError(exc) from exc

    if client is None:
        try:
            client = get_client(config_path=config_path)
        except LLMError as exc:
            raise LLMFailedError(exc) from exc

    records: list[dict[str, Any]] = []
    for node, section in pairs:
        prompt = compose_artifact_prompt(section, codebook)

        try:
            raw_response = client.complete(prompt, pass_name=ARTIFACTS_PASS_NAME)
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc

        role = parse_artifact_role(raw_response)
        validate_artifact_role(role, schema)

        # `field` classification (issue #32 slice 02): reuses `axial.tag`'s
        # shared primary+secondary parser/validator, never a reinvented
        # field parser here. Only tagged when the loaded schema actually
        # declares a `field` axis -- a minimal domain lacking one (e.g. an
        # inner unit test's fixture schema) is not a hard error.
        field_value: dict[str, Any] | None = None
        field_axis = schema.axes.get(FIELD_AXIS)
        if field_axis is not None:
            parsed_field = parse_multi_value_tag_response(raw_response, field_axis)
            validate_multi_value_tag(schema, FIELD_AXIS, parsed_field)
            field_value = {
                "primary": parsed_field["primary"],
                "secondary": parsed_field["secondary"],
            }

        records.append(build_artifact_record(source_id, node, section, role, field_value))

    return records
