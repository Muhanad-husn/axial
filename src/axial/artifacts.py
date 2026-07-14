"""Artifact classification: for each non-text artifact node (a table or
figure) in the extraction tree, one LLM call assigns exactly one
`artifact_role` from the domain schema's closed Appendix D taxonomy (PRD §5
stage 5, §7.2, §8 P0-5).

Unlike the envelope/chunk passes, this pass never reads or writes a stored
envelope -- it walks the extraction tree directly (via `extract`), collects
every block the shared source router (issue #167/#168, `axial.router`)
routes to ARTIFACT (table, picture, caption), and pairs each with its
ENCLOSING top-level section's own verbatim heading `text` for section
provenance, exactly as `axial.chunk`'s `_routed_section_body` does for
prose/apparatus. A `caption` block is never itself classified as a
standalone artifact -- its text attaches to the nearest preceding table/
picture in reading order (see `_attach_captions`), riding on that
artifact's own record rather than being lost or chunked. A source with zero
artifact-routed blocks yields zero records with zero LLM calls and no error.

Artifact records carry a stable, deterministic `artifact_id`
(`<source_id>_art_<order>`, using the node's own dotted `order` value
VERBATIM -- unlike `chunk.py`'s chunk_id, dots are never dash-replaced, since
this module's contract locks the dotted-digits shape directly) plus
`artifact_role`, `field`, `source_id`, `section`, and (when a caption
attached) `caption` (PRD §7.2, issue #168). This slice (issue #30 slice 01)
emits artifact records to stdout only; routing to `data/vault/artifacts/` is
issue #32 slice 02, which also added `field` classification here.

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
import sys
from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.codebook import Codebook, CodebookError, load_codebook
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.chunk import _is_back_matter
from axial.extract import ExtractError, extract
from axial.llm import (
    ARTIFACTS_PASS_NAME,
    DEFAULT_PIPELINE_CONFIG_PATH,
    LLMClient,
    LLMError,
    get_client,
)
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.nonprose_guard import non_prose_skip_reason
from axial.router import ARTIFACT, route_for
from axial.schema import Schema, SchemaError, load_schema
from axial.tag import (
    TagNotInSchemaError,
    apply_correction_reask,
    parse_multi_value_tag_response,
    validate_multi_value_tag,
)

# Default domain directory for the artifacts pass, overridable via a
# `domain_dir` argument to `run_artifacts` (and the CLI's `--domain` flag).
DEFAULT_DOMAIN_DIR = Path("config/domains/syria")

# Default artifacts-pass checkpoint directory, mirroring `axial.tag.TAGS_DIR`
# exactly (issue #98).
ARTIFACTS_DIR = Path("data/artifacts")


def _default_artifacts_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Resolve the artifacts-checkpoint directory, mirroring
    `axial.tag._default_tags_dir` exactly: honor `config/pipeline.yaml`'s
    `paths.artifacts_dir` when declared, else fall back to the module-level
    `ARTIFACTS_DIR` default (`data/artifacts`, resolved relative to the
    current working directory). An absent file/key falls back to
    `ARTIFACTS_DIR`."""
    if not config_path.is_file():
        return ARTIFACTS_DIR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("artifacts_dir")
    return Path(configured) if configured else ARTIFACTS_DIR


def artifacts_checkpoint_path(source_id: str, artifacts_dir: Path = ARTIFACTS_DIR) -> Path:
    """The resume path for `source_id`'s artifacts-pass checkpoint (one JSON
    classified-artifact record per line, appended as each artifact is
    classified), keyed by the content-hashed source_id -- mirrors
    `axial.tag.tags_checkpoint_path` exactly (issue #98)."""
    return artifacts_dir / f"{source_id}.jsonl"


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


class ArtifactCheckpointCorruptError(ArtifactsError):
    """Raised by `load_artifact_checkpoint` when a NON-final line of an
    artifacts checkpoint file is not valid JSON (issue #98, mirroring
    `axial.tag.TagCheckpointCorruptError`). A torn FINAL line is tolerated (a
    hard process kill can only ever tear the line currently being appended,
    always the last one); a torn line anywhere else is genuine corruption
    unrelated to a kill mid-append, and is a loud, diagnosable error naming
    the checkpoint path and the offending 1-indexed line number, rather than
    a silent partial load."""

    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(
            f"corrupt artifacts checkpoint {path}: line {line_no} is not valid JSON: {cause}"
        )


def append_artifact_checkpoint(path: Path, record: dict[str, Any]) -> None:
    """Append one classified-artifact record to `path` AS IT IS PRODUCED
    (issue #98, mirroring `axial.tag.append_tag_checkpoint`): heal any torn
    tail left by an earlier hard kill, then write+flush the JSON line -- so a
    mid-artifacts-pass failure leaves every already-classified artifact
    durably on disk for the resume run."""
    append_checkpoint_record(path, record)


def load_artifact_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load already-classified artifact records from an artifacts-pass
    checkpoint file (the inverse of `append_artifact_checkpoint`), mirroring
    `axial.tag.load_tag_checkpoint` exactly: a torn final line is healed
    (dropped, its artifact simply re-classified on resume); a torn non-final
    line raises `ArtifactCheckpointCorruptError` naming the path and the
    offending 1-indexed line number. Returns an empty list when the file
    does not exist yet."""
    return load_checkpoint_records(path, ArtifactCheckpointCorruptError)


# `TagNotInSchemaError` is reused verbatim from `axial.tag` (imported above)
# -- not redefined here. Its constructor is `(axis_name, tag)`. Re-exported
# under this module's namespace (via the import above) so existing callers
# doing `from axial.artifacts import TagNotInSchemaError` keep working
# unchanged.


def _reject_blank_artifact_value(value: Any, field: str) -> None:
    """Raise `ArtifactParseError`, naming `field`, when `value` is an empty
    or whitespace-only string -- the same species of response noise as
    broken JSON, never a candidate tag on its own (issue #90, mirroring
    `axial.tag._reject_blank_tag` from issue #80). Any non-blank value
    (including a genuine out-of-vocabulary string) is left untouched here:
    schema-vocabulary validation is `validate_artifact_role`/
    `validate_multi_value_tag`'s job alone, entirely separate from this
    degeneracy check."""
    if isinstance(value, str) and not value.strip():
        raise ArtifactParseError(f"{field} tag value is empty/whitespace-only: {value!r}")


def reject_degenerate_artifact_values(raw: str, schema: Schema) -> None:
    """Validator passed to `complete_json` for the artifacts pass (issue
    #90, mirroring `axial.tag.reject_degenerate_tag_values` from issue #85/
    #80): re-parses `raw` with the exact same parsers `run_artifacts` itself
    uses (`parse_artifact_role` / `parse_multi_value_tag_response`), but
    only to reject an empty/whitespace-only value -- the `artifact_role`
    string itself, or the `field` axis's primary/each secondary entry when
    the loaded schema declares a `field` axis -- as a re-askable
    `ArtifactParseError`. Runs BEFORE `run_artifacts`'s own parse+validate
    flow, inside `complete_json`'s bounded re-ask budget, so a degenerate
    response (e.g. `field.primary == ""`) never reaches
    `validate_artifact_role`/`validate_multi_value_tag` -- and hence never
    raises a raw, unwrapped `TagNotInSchemaError` for tag `''` -- at all; a
    non-degenerate response is parsed again there (cheap, and keeps this
    validator fully decoupled from `run_artifacts`'s bookkeeping).

    Deliberately never calls `validate_artifact_role`/
    `validate_multi_value_tag`: a genuine non-empty out-of-vocabulary value
    must stay immediately fatal (`TagNotInSchemaError`, the P0-6
    schema-gap signal), never smoothed over by a re-ask here."""
    # `parse_artifact_role` already rejects a missing/non-string/blank role
    # as `ArtifactParseError` on its own -- reused verbatim, not duplicated.
    parse_artifact_role(raw)

    field_axis = schema.axes.get(FIELD_AXIS)
    if field_axis is not None:
        parsed = parse_multi_value_tag_response(raw, field_axis)
        _reject_blank_artifact_value(parsed["primary"], f"{FIELD_AXIS}.primary")
        secondary = parsed.get("secondary")
        secondary_values = (
            secondary
            if isinstance(secondary, list)
            else ([secondary] if secondary is not None else [])
        )
        for index, value in enumerate(secondary_values):
            _reject_blank_artifact_value(value, f"{FIELD_AXIS}.secondary[{index}]")


def _routed_artifact_blocks(tree: dict) -> list[tuple[dict, str]]:
    """Collect every ARTIFACT-routed block (table, picture, caption) in the
    extraction tree, in reading order, each paired with its enclosing
    top-level section's own verbatim heading text (issue #168, PRD §7.8) --
    the same section-scoped recursive walk `axial.chunk._routed_section_body`
    uses, classifying each node via the shared `axial.router.route_for`, but
    for the artifact pass's own collection rather than chunking.

    Deliberately does NOT reuse `axial.router.iter_routed_blocks` directly:
    that helper only yields a node carrying non-empty `text` (the right gate
    for chunk.py, which has nothing to chunk otherwise), but a real docling
    `TableItem` routinely carries an EMPTY `text` (its content lives in table
    cells, not a `text` attribute -- confirmed against
    tests/fixtures/extract/prose_and_table_tree.json's own table node) and
    must still be collected as an artifact. This walk mirrors
    `iter_routed_blocks`'s recursive shape exactly, just without that
    text-presence gate.

    A node whose extraction `type` is already `'artifact'` (docling's own
    `TableItem`/`PictureItem` classification, see `extract.py`'s `_classify`)
    is ALWAYS included here regardless of its own `label` -- a back-compat
    carve-out so a genuine artifact never silently vanishes on an
    unrecognized-label edge case; every other block (in particular a
    caption, `type == 'prose'`, `label == 'caption'`) routes purely by the
    shared router's label mapping. Apparatus-routed blocks (`document_index`,
    `footnote`, page heads/feet, a back-matter `list_item`) are never
    collected.

    A top-level node with no heading/children (content preceding any
    heading) carries no section label (`""`); its own ARTIFACT-routed
    descendants (including itself) are paired with that empty string rather
    than dropped, mirroring the previous `type == 'artifact'`-only scan's
    behavior for this edge case."""
    pairs: list[tuple[dict, str]] = []

    def _walk(node: dict, section: str, in_back_matter_section: bool) -> None:
        route = route_for(node.get("label"), in_back_matter_section=in_back_matter_section)
        if route == ARTIFACT or node.get("type") == "artifact":
            pairs.append((node, section))
        for child in node.get("children", []):
            _walk(child, section, in_back_matter_section)

    for child in tree.get("children", []):
        if "children" in child and child.get("text"):
            section = child["text"]
            in_back_matter_section = _is_back_matter(section)
            for grandchild in child.get("children", []):
                _walk(grandchild, section, in_back_matter_section)
        else:
            _walk(child, "", False)
    return pairs


def _artifact_nodes_with_section(tree: dict) -> list[tuple[dict, str]]:
    """Genuine artifact nodes only (table/picture) -- excludes caption
    blocks, which attach to their artifact instead of standing alone (see
    `_attach_captions`). A thin filter over `_routed_artifact_blocks`, kept
    as its own function since existing unit tests target it by name."""
    return [
        (node, section)
        for node, section in _routed_artifact_blocks(tree)
        if node.get("label") != "caption"
    ]


def _attach_captions(blocks: list[tuple[dict, str]]) -> list[dict[str, Any]]:
    """Pair each genuine artifact (table/picture) with its reading-order-
    adjacent caption's text, if any (issue #168 plan: "a caption attaches to
    the nearest figure/table in reading order"). `blocks` is
    `_routed_artifact_blocks`'s own output (ARTIFACT-routed nodes in document
    order, table/picture and caption alike). Returns one entry per artifact
    record to build: `{"node": ..., "section": ..., "caption": <text> |
    None}` -- a caption block never becomes its own entry when it can attach
    to a preceding one.

    Simple reading-order rule (80/20): a caption attaches to the last entry
    produced so far. An ORPHAN caption -- reached before any entry exists at
    all -- never crashes and is never silently lost: it becomes its own
    standalone entry (fallback), so this pass still classifies it (rather
    than chunking it or dropping it), and a later caption can attach to that
    standalone entry in turn."""
    entries: list[dict[str, Any]] = []
    last_entry: dict[str, Any] | None = None
    for node, section in blocks:
        if node.get("label") == "caption":
            caption_text = node.get("text", "")
            if last_entry is None:
                # Orphan caption: no prior artifact to attach to -- emit as
                # its own standalone entry rather than lose or crash on it.
                last_entry = {"node": node, "section": section, "caption": None}
                entries.append(last_entry)
            else:
                last_entry["caption"] = caption_text
            continue
        last_entry = {"node": node, "section": section, "caption": None}
        entries.append(last_entry)
    return entries


def artifact_id_for_node(source_id: str, node: dict) -> str:
    """The stable, deterministic `artifact_id` for `node`
    (`<source_id>_art_<order>`, keeping the node's dotted `order` verbatim)
    -- factored out of `build_artifact_record` (issue #98) so the checkpoint
    skip-set can be computed BEFORE a node is classified, not only after."""
    order = node.get("order", "")
    return f"{source_id}_art_{order}"


def build_artifact_record(
    source_id: str,
    node: dict,
    section: str,
    role: str,
    field: dict[str, Any] | None = None,
    caption: str | None = None,
) -> dict[str, Any]:
    """Assemble the locked artifact record shape: `artifact_id`
    (`<source_id>_art_<order>`, keeping the node's dotted `order` verbatim),
    `artifact_role`, `source_id`, `section`, plus `field` (issue #32 slice
    02's `{"primary": ..., "secondary": [...]}` mapping) when given -- a
    schema lacking a `field` axis (e.g. a minimal test fixture domain) omits
    the key entirely rather than emitting `field: null`.

    `caption` (issue #168): the text of the caption block attached to this
    artifact via `_attach_captions`, when the tree carries one immediately
    adjacent -- omitted entirely (never `caption: null`/`""`) when this
    artifact has no attached caption, mirroring `field`'s own conditional
    inclusion, so every pre-#168 caller/test keeps the record shape it
    already asserts."""
    record: dict[str, Any] = {
        "artifact_id": artifact_id_for_node(source_id, node),
        "artifact_role": role,
        "source_id": source_id,
        "section": section,
    }
    if field is not None:
        record["field"] = field
    if caption:
        record["caption"] = caption
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
        data = parse_model_json(raw)
    except ModelJsonError as exc:
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
        raise TagNotInSchemaError(
            _ARTIFACT_ROLE_AXIS, role, vocabulary=(axis.tag_ids if axis is not None else None)
        )


def _classify_artifact_response(raw: str, schema: Schema) -> tuple[str, dict[str, Any] | None]:
    """Parse+validate one raw artifacts-pass response into its `artifact_role`
    and (when the schema declares a `field` axis) its `field` value, reusing
    `axial.tag`'s shared primary+secondary parser/validator for `field`.
    Raises `TagNotInSchemaError` on any schema-vocabulary miss (the signal
    `apply_correction_reask` catches for its single bounded re-ask, issue
    #102), and `ArtifactParseError` on a malformed response as before.
    Factored out of `run_artifacts`'s per-node body so the identical
    classification runs on both the original answer and the correction
    re-ask's answer."""
    role = parse_artifact_role(raw)
    validate_artifact_role(role, schema)

    field_value: dict[str, Any] | None = None
    field_axis = schema.axes.get(FIELD_AXIS)
    if field_axis is not None:
        parsed_field = parse_multi_value_tag_response(raw, field_axis)
        validate_multi_value_tag(schema, FIELD_AXIS, parsed_field)
        field_value = {
            "primary": parsed_field["primary"],
            "secondary": parsed_field["secondary"],
        }
    return role, field_value


def run_artifacts(
    source_path: str | Path,
    client: LLMClient | None = None,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    artifacts_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the artifact-classification pass on `source_path`.

    Walks the extraction tree for every ARTIFACT-routed block (table,
    picture, caption -- see `_routed_artifact_blocks`), attaches each
    caption's text to its nearest preceding table/picture (`_attach_captions`,
    issue #168); a source with no genuine artifact yields zero records with
    zero LLM calls and no error. For each artifact found, calls the LLM once
    (`pass_name="artifacts"`) with a prompt composed from the domain
    codebook's `artifact_role` entries, then validates the returned role
    against the domain schema's `artifact_role` axis -- an out-of-schema role
    is a hard error. A caption is never itself sent to the model as a
    distinct artifact to classify.

    Artifacts-pass checkpoint/resume (issue #98, mirroring `axial.tag.run_tag`'s
    `tags_dir` seam): OPT-IN, active only when `artifacts_dir` is supplied
    (`axial vault write`'s composition threads one in, into BOTH its own
    direct call and the one nested inside `axial.xref.run_xref` -- see
    `axial.vault.run_vault_write`'s docstring for why the second call site
    matters too). Standalone `axial artifacts`/`axial xref` pass none and so
    behave exactly as before, re-classifying every run. When active: each
    classified record is appended to `<artifacts_dir>/<source_id>.jsonl` as
    it is produced (write+flush per artifact); on a later run, artifacts
    whose `artifact_id` already appears there are reused verbatim and NOT
    re-sent to the model -- only the missing ones are classified, and
    checkpointed + fresh records recombine in the tree's stable node order.
    A mid-pass failure therefore leaves every already-classified artifact on
    disk, so the retry resumes instead of restarting.
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

    entries = _attach_captions(_routed_artifact_blocks(tree))
    if not entries:
        return []

    try:
        schema = load_schema(domain_dir)
    except SchemaError as exc:
        raise SchemaLoadFailedError(exc) from exc

    try:
        codebook = load_codebook(domain_dir)
    except CodebookError as exc:
        raise CodebookLoadFailedError(exc) from exc

    # Artifacts-pass checkpoint/resume (issue #98), opt-in via `artifacts_dir`.
    checkpoint_path: Path | None = None
    already_classified: dict[str, dict[str, Any]] = {}
    if artifacts_dir is not None:
        checkpoint_path = artifacts_checkpoint_path(source_id, artifacts_dir)
        already_classified = {
            record["artifact_id"]: record for record in load_artifact_checkpoint(checkpoint_path)
        }

    records: list[dict[str, Any]] = []
    for entry in entries:
        node = entry["node"]
        section = entry["section"]
        caption = entry["caption"]
        # Resume: an artifact already checkpointed by an earlier run is
        # reused verbatim and never re-sent to the model -- records
        # recombine in the tree's stable node order (issue #98, mirroring
        # `run_tag`'s own resume convention).
        artifact_id = artifact_id_for_node(source_id, node)
        checkpointed = already_classified.get(artifact_id)
        if checkpointed is not None:
            records.append(checkpointed)
            continue

        # Input guard (issue #132, mirroring xref's #111 / chunk's #118
        # guard, now via the shared `axial.nonprose_guard` helper): skip an
        # artifact node whose own extracted `text` is non-prose/OCR-garbled
        # back-matter -- no LLM call, no classified record, no checkpoint
        # write for this artifact. `node["text"]` is the one per-iteration
        # textual payload `axial.extract._leaf_node` populates on any node
        # (prose or artifact) that exposes one, so it is the artifacts
        # pass's own analogue of the tag/chunk/xref passes' chunk text. The
        # skip is a deterministic function of that text, so it re-applies on
        # every resume without ever reaching the model.
        skip_reason = non_prose_skip_reason(node.get("text", ""))
        if skip_reason is not None:
            print(f"artifacts: skipping artifact {artifact_id}: {skip_reason}", file=sys.stderr)
            continue

        if client is None:
            try:
                client = get_client(config_path=config_path)
            except LLMError as exc:
                raise LLMFailedError(exc) from exc

        prompt = compose_artifact_prompt(section, codebook)

        try:
            raw_response = complete_json(
                client,
                prompt,
                pass_name=ARTIFACTS_PASS_NAME,
                validate=lambda raw: reject_degenerate_artifact_values(raw, schema),
            )
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc
        except ModelJsonError as exc:
            raise ArtifactParseError(f"model response was not valid JSON: {exc}") from exc

        # An out-of-vocabulary artifact_role or field value triggers exactly
        # ONE bounded correction re-ask (issue #102, P0-6), identical to the
        # tag pass: the model is shown the failing position's controlled
        # vocabulary and must return a valid value or an explicit NONE;
        # still-out-of-vocab after that single re-ask propagates
        # `TagNotInSchemaError` as the hard error. `_classify_artifact_response`
        # runs the exact same role/field parse+validate on either answer.
        try:
            role, field_value = apply_correction_reask(
                client,
                ARTIFACTS_PASS_NAME,
                raw_response,
                prompt,
                lambda raw: _classify_artifact_response(raw, schema),
            )
        except (LLMError, httpx.HTTPError) as exc:
            raise LLMFailedError(exc) from exc

        record = build_artifact_record(source_id, node, section, role, field_value, caption)
        # Persist this artifact's classified record before moving to the
        # next one (write+flush per artifact), so a failure on a later
        # artifact leaves every already-classified one durably checkpointed
        # for the resume run.
        if checkpoint_path is not None:
            append_artifact_checkpoint(checkpoint_path, record)
        records.append(record)

    return records
