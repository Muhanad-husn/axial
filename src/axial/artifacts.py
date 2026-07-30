"""Artifact collection: for each non-text artifact node (a table or figure)
in the extraction tree, records its id/source/section provenance and, when
one is present in reading order, its attached caption (PRD §5 stage 5, §7.2,
§8 P0-5).

**No LLM call (issue #429).** This pass used to send every artifact to the
model for an `artifact_role` (Appendix D's six-way taxonomy) and a `field`
classification. Two independent runs over the same source disagreed on
`artifact_role` for 48.5% of artifacts and flipped the keep/discard bit on
13.1% of them; the artifact record carries no content beyond ids, section
and caption, so those two labels were the pass's entire output and neither
reproduced. The axis and the classification call are gone. `retrievable` is
now decided downstream, in `axial.vault.build_artifact_frontmatter`, by a
rule over caption presence rather than a model judgment -- caption presence
predicted the old keep/discard bit far better than the model did (4.7%
flip rate on captioned artifacts vs. 19.6% on uncaptioned ones).

Like before (unchanged, deterministic): this pass never reads or writes a
stored envelope -- it walks the extraction tree directly (via `extract`),
collects every block the shared source router (issue #167/#168,
`axial.router`) routes to ARTIFACT (table, picture, caption), and pairs each
with its ENCLOSING top-level section's own verbatim heading `text` for
section provenance, exactly as `axial.chunk`'s `_routed_section_body` does
for prose/apparatus. A `caption` block is never itself a standalone artifact
record -- its text attaches to the nearest preceding table/picture in
reading order (see `_attach_captions`), riding on that artifact's own record
rather than being lost or chunked. A source with zero artifact-routed blocks
yields zero records with zero I/O beyond the tree read.

Artifact records carry a stable, deterministic `artifact_id`
(`<source_id>_art_<order>`, using the node's own dotted `order` value
VERBATIM) plus `source_id`, `section`, and (when a caption attached)
`caption`. `artifact_role` and `field` are gone (issue #429); routing to
`data/vault/artifacts/` is `axial.vault.write_artifact_note`'s job.

The per-artifact input guard that used to skip an OCR-garbled node before
spending an LLM call on it (`axial.nonprose_guard.non_prose_skip_reason`) is
also gone: its whole rationale was avoiding a wasted model call, which no
longer exists, and skipping record production entirely on a garbled node's
own internal text would have silently dropped a genuinely captioned artifact
whenever that artifact's own extracted text happened to be noisy -- a table's
own cell dump is not a signal about its caption's usefulness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.envelope import (
    MissingSourceError as _EnvelopeMissingSourceError,
    compute_source_id,
)
from axial.chunk import _is_back_matter
from axial.extract import ExtractError, extract
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH
from axial.router import ARTIFACT, canonical_label, route_for
from axial.yaml_loader import SAFE_LOADER

# Default artifacts-pass checkpoint directory, mirroring `axial.tag.TAGS_DIR`
# exactly (issue #98) -- now doubling as the pass's only real output store,
# since there is no LLM call left to "resume".
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
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
    paths_config = document.get("paths", {}) or {}
    configured = paths_config.get("artifacts_dir")
    return Path(configured) if configured else ARTIFACTS_DIR


def artifacts_checkpoint_path(source_id: str, artifacts_dir: Path = ARTIFACTS_DIR) -> Path:
    """The resume path for `source_id`'s artifacts-pass checkpoint (one JSON
    artifact record per line, appended as each one is built), keyed by the
    content-hashed source_id -- mirrors `axial.tag.tags_checkpoint_path`
    exactly (issue #98)."""
    return artifacts_dir / f"{source_id}.jsonl"


class ArtifactsError(Exception):
    """Base class for all artifact-collection errors."""


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
    """Append one artifact record to `path` AS IT IS PRODUCED (issue #98,
    mirroring `axial.tag.append_tag_checkpoint`): heal any torn tail left by
    an earlier hard kill, then write+flush the JSON line -- so a mid-run
    failure leaves every already-built artifact record durably on disk for
    the resume run."""
    append_checkpoint_record(path, record)


def load_artifact_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Load already-built artifact records from an artifacts-pass checkpoint
    file (the inverse of `append_artifact_checkpoint`), mirroring
    `axial.tag.load_tag_checkpoint` exactly: a torn final line is healed
    (dropped, its artifact simply rebuilt on resume); a torn non-final line
    raises `ArtifactCheckpointCorruptError` naming the path and the
    offending 1-indexed line number. Returns an empty list when the file
    does not exist yet."""
    return load_checkpoint_records(path, ArtifactCheckpointCorruptError)


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
        if canonical_label(node.get("label")) != "caption"
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
    standalone entry (fallback), so this pass still records it (rather than
    chunking it or dropping it), and a later caption can attach to that
    standalone entry in turn.

    A SECOND caption attaching to an entry that already carries one is
    NEVER an overwrite (that would silently drop the first caption's text,
    violating this slice's own "caption text is never lost" invariant):
    its text is appended, newline-joined, onto the entry's existing
    caption -- both survive."""
    entries: list[dict[str, Any]] = []
    last_entry: dict[str, Any] | None = None
    for node, section in blocks:
        if canonical_label(node.get("label")) == "caption":
            caption_text = node.get("text", "")
            if last_entry is None:
                # Orphan caption: no prior artifact to attach to -- emit as
                # its own standalone entry rather than lose or crash on it.
                # Its own text is already this entry's primary content (the
                # entry's own `node`), so `caption` (attached-caption text)
                # stays None here -- it is set only when a FURTHER caption
                # attaches to this now-standalone entry (see below).
                last_entry = {"node": node, "section": section, "caption": None}
                entries.append(last_entry)
            elif last_entry["caption"]:
                # Never overwrite an already-attached caption -- append so
                # both texts survive.
                last_entry["caption"] = f"{last_entry['caption']}\n{caption_text}"
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
    skip-set can be computed BEFORE a node's record is built, not only
    after."""
    order = node.get("order", "")
    return f"{source_id}_art_{order}"


def build_artifact_record(
    source_id: str,
    node: dict,
    section: str,
    caption: str | None = None,
) -> dict[str, Any]:
    """Assemble the locked artifact record shape (issue #429): `artifact_id`
    (`<source_id>_art_<order>`, keeping the node's dotted `order` verbatim),
    `source_id`, `section`, plus `caption` (issue #168) when the tree carries
    one immediately adjacent -- omitted entirely (never `caption: null`/`""`)
    when this artifact has no attached caption. `artifact_role` and `field`
    are gone: they were the LLM classification's own output, and this pass
    makes no LLM call."""
    record: dict[str, Any] = {
        "artifact_id": artifact_id_for_node(source_id, node),
        "source_id": source_id,
        "section": section,
    }
    if caption:
        record["caption"] = caption
    return record


def run_artifacts(
    source_path: str | Path,
    artifacts_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Run the artifact-collection pass on `source_path`.

    Walks the extraction tree for every ARTIFACT-routed block (table,
    picture, caption -- see `_routed_artifact_blocks`), attaches each
    caption's text to its nearest preceding table/picture (`_attach_captions`,
    issue #168), and emits one record per genuine artifact (table/picture).
    A source with no genuine artifact yields zero records. Makes no LLM
    call (issue #429).

    Artifacts-pass checkpoint/resume (issue #98, mirroring `axial.tag.run_tag`'s
    `tags_dir` seam): OPT-IN, active only when `artifacts_dir` is supplied
    (`axial.run`'s `artifacts` pass threads one in). When active: each
    record is appended to `<artifacts_dir>/<source_id>.jsonl` as it is
    produced (write+flush per artifact); on a later run, an artifact whose
    `artifact_id` already appears there is reused verbatim rather than
    rebuilt -- records recombine in the tree's stable node order. Standalone
    `axial artifacts` passes none and so behaves exactly as before, rebuilding
    every record from the tree on every run (cheap, since there is no LLM
    call to save)."""
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

    checkpoint_path: Path | None = None
    already_recorded: dict[str, dict[str, Any]] = {}
    if artifacts_dir is not None:
        checkpoint_path = artifacts_checkpoint_path(source_id, artifacts_dir)
        already_recorded = {
            record["artifact_id"]: record for record in load_artifact_checkpoint(checkpoint_path)
        }

    records: list[dict[str, Any]] = []
    for entry in entries:
        node = entry["node"]
        section = entry["section"]
        caption = entry["caption"]
        artifact_id = artifact_id_for_node(source_id, node)

        checkpointed = already_recorded.get(artifact_id)
        if checkpointed is not None:
            records.append(checkpointed)
            continue

        record = build_artifact_record(source_id, node, section, caption)
        if checkpoint_path is not None:
            append_artifact_checkpoint(checkpoint_path, record)
        records.append(record)

    return records
