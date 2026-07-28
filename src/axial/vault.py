"""Vault write: Obsidian note/frontmatter primitives (PRD §5 stage 7; §7.2;
§8 P0-5/P0-8), plus `run_vault_write` itself.

**`run_vault_write` stays retired.** Phase A v1 (D4/D5,
`plans/phase-a-v1/README.md`) deleted the tag pass and the cross-reference
pass this module used to drive internally. Its replacement -- prose notes
carrying the interrogation pass's answers as frontmatter, artifact notes, and
the name pages Reconcile's alias map drives -- is `axial.materialize` (slice
06, issue #411), a fresh whole-corpus pass over `data/answers/`,
`data/artifacts/` and `data/names/alias_map.json` rather than a per-source
loop, so `run_vault_write` itself is not resurrected: it still raises
`VaultWriteRetiredError` immediately, naming #411.

The note-writing PRIMITIVES below -- `render_note`, `build_frontmatter`,
`write_chunk_note`, `build_artifact_frontmatter`, `write_artifact_note`,
`read_source_meta` and friends -- are what `axial.materialize` builds on.
`build_frontmatter`/`write_chunk_note` gained an optional `answer_record`
(plus `chapter`) parameter for #411: given one, five more keys land in a
note's frontmatter (`source`, `chapter`, `frame_version`, `interrogated`,
`answers`, Appendix H); omitted, the pre-#411 shape is unchanged, which is
what keeps every other existing caller (`axial.query.reader`'s own tests,
`axial.distill`, `axial.eval.corpus_pin`, `axial.rename_source_ids`, all of
which call `render_note`/`write_chunk_note`/`write_artifact_note` directly,
independent of `run_vault_write`) compiling unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axial.paths import (
    DEFAULT_DOMAIN_DIR,
    artifact_note_path as _artifact_note_path,
    chunk_note_path as _note_path,
    default_vault_dir as _default_vault_dir,  # noqa: F401 -- re-exported; axial.gold,
    # axial.polity_canonical, axial.eval.corpus_pin import it from here, not axial.paths
)

# Imported as a module, not by-name: `SOURCE_META_DIR` is read at call time
# so a test that redirects it (src/axial/conftest.py's autouse isolation
# fixture) is honored here too, mirroring `axial.chunk`'s own CHUNKS_DIR
# resolution.
from axial import intake as _intake
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient

# The five source-level frontmatter fields (PRD §7.2), excluding `fields`, a
# schema-driven axis tag deferred to phase-3 tagging (issue #29) and retired
# with the tag pass entirely (issue #414). `author`, `title` and `date` are
# facts about the FILE, read at intake into the source-metadata record
# (§7.12/§7.13), which is their sole origin; `thesis` and `scope` are what
# the model concluded about the WORK, and stay in the envelope (§7.3).
RECORD_SOURCE_META_FIELDS = ("author", "title", "date")
ENVELOPE_SOURCE_META_FIELDS = ("thesis", "scope")
SOURCE_META_FIELDS = RECORD_SOURCE_META_FIELDS + ENVELOPE_SOURCE_META_FIELDS

# Frontmatter keys reused verbatim from `axial.artifacts`' own record shape
# (PRD §7.2) for every artifact note. `cited_by` (the cross-reference pass's
# output) is retired with `axial.xref` (issue #414, D5). `artifact_role` and
# `field` are retired with the artifacts pass's LLM call (issue #429): two
# independent runs disagreed on `artifact_role` for 48.5% of artifacts and
# flipped the keep/discard bit on 13.1% of them, so the axis is gone and
# `retrievable` below is a rule over caption presence instead.
ARTIFACT_FRONTMATTER_FIELDS = ("artifact_id", "source_id", "section")


class VaultError(Exception):
    """Base class for all vault-write errors."""


class VaultWriteRetiredError(VaultError):
    """Raised by every `run_vault_write` call (module docstring): the pass
    is retired pending issue #411 "Materialize", itself gated behind slices
    04 (name inventory) and 05 (Reconcile). Not a crash on a missing
    dependency -- a deliberate, named stub."""

    def __init__(self, source_path: str | Path):
        self.source_path = Path(source_path)
        super().__init__(
            f"vault write is retired pending issue #411 (Materialize): "
            f"{self.source_path} was not processed. The tag and cross-"
            f"reference passes this write used to depend on are gone "
            f"(issue #414, plans/phase-a-v1/README.md D4/D5); its "
            f"replacement -- prose notes carrying interrogation answers, "
            f"plus name pages -- lands in slice 06, after slices 04/05."
        )


def read_source_meta(source_id: str, source_meta_dir: Path) -> dict[str, Any]:
    """Read `source_id`'s persisted source-metadata record (§7.12), raising
    `VaultError` when it is absent or unreadable -- never returning an empty
    stand-in, which would silently re-emit the nulls #278 retires."""
    path = _intake.source_meta_path(source_id, source_meta_dir)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VaultError(
            f"no source-metadata record found at {path}; run intake on the source first "
            f"(`axial ingest`/`axial extract` writes it)"
        ) from exc
    if not isinstance(record, dict):
        raise VaultError(f"source-metadata record at {path} is not a JSON object")
    return record


def bibliographic_value(source_meta: dict[str, Any], field: str) -> Any:
    """One §7.13 bibliographic field, rendered for the note's frontmatter.

    The record holds each field in exactly one of three distinguishable
    states, and all three survive into the note: a resolved value carries
    `{"value", "provenance"}` and renders as the value itself; the
    `unavailable` and `not_attempted` sentinels render as themselves. A key
    the record does not carry at all is `not_attempted` -- no read has run
    for it -- never a blank that reads like an empty answer."""
    value = source_meta.get(field, _intake.NOT_ATTEMPTED)
    if isinstance(value, dict):
        return value.get("value")
    return value


def build_source_meta_block(
    source_meta: dict[str, Any], envelope: dict[str, Any]
) -> dict[str, Any]:
    """The note's five-key `source_meta` block (PRD §7.2/§7.13), composed
    from two artifacts: `author`/`title`/`date` from the source-metadata
    record (§7.12 -- their sole origin, never the envelope and never the
    filename), `thesis`/`scope` from the envelope (§7.3). The key set and
    its order are unchanged; only where three of the five values come from
    is."""
    block = {field: bibliographic_value(source_meta, field) for field in RECORD_SOURCE_META_FIELDS}
    block.update({field: envelope.get(field) for field in ENVELOPE_SOURCE_META_FIELDS})
    return block


def build_frontmatter(
    record: dict[str, Any],
    envelope: dict[str, Any],
    source_meta: dict[str, Any],
    *,
    chapter: str | None = None,
    answer_record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a chunk note's frontmatter mapping: `chunk_id`, `section`,
    `chunk_text`, and `source_meta` (the five source-level fields, PRD §7.2,
    composed by `build_source_meta_block` from the source-metadata record
    and the envelope) -- always present, unchanged from before issue #411.

    Retired (issue #414, D4/D5): the tag-pass axis block (`schema_version`,
    `role_in_argument`, `field`/`claim_type`/`theory_school`,
    `empirical_scope`, `polities_touched`) and `artifact_refs` (the
    cross-reference pass's backlink list).

    Their replacement (issue #411, Appendix H): when `answer_record` (one
    line of `data/answers/<source_id>.jsonl`, `axial.interrogate.
    build_answer_record`'s shape) is given, five more keys are added --
    `source` (a display label, `"<author> — <title>"`), `chapter` (the
    caller's own `chapter_for_section` lookup -- passed in rather than
    recomputed here, so this module never has to import `axial.interrogate`
    for one lookup), `frame_version`, `interrogated` (`{pass, model, at}`),
    and `answers` (the record's own answers dict, verbatim -- plain strings
    and lists, never `[[wikilinks]]`: D11 keeps every link in the name page,
    not the note). Omitted entirely, not `null`, when no answer record is
    given -- the pre-#411 shape survives unchanged for any caller that does
    not yet have one."""
    source_meta_block = build_source_meta_block(source_meta, envelope)
    frontmatter: dict[str, Any] = {"chunk_id": record["chunk_id"]}
    if answer_record is not None:
        frontmatter["source"] = (
            f"{source_meta_block.get('author')} — {source_meta_block.get('title')}"
        )
    frontmatter["section"] = record["section"]
    frontmatter["chunk_text"] = record["chunk_text"]
    frontmatter["source_meta"] = source_meta_block
    if answer_record is not None:
        frontmatter["chapter"] = chapter
        frontmatter["frame_version"] = answer_record.get("frame_version")
        frontmatter["interrogated"] = {
            "pass": answer_record.get("pass"),
            "model": answer_record.get("model"),
            "at": answer_record.get("answered_at"),
        }
        frontmatter["answers"] = answer_record.get("answers", {})
    return frontmatter


def render_note(frontmatter: dict[str, Any], body: str) -> str:
    """Render a note's full text: a `---`-delimited YAML frontmatter block
    followed by the body (standard Obsidian/Jekyll convention).

    `default_style='"'` forces every scalar (including multi-line chunk
    text) into a single double-quoted line with embedded newlines escaped
    as `\\n`. Without it, PyYAML's default folded/plain scalar style can
    fold a long chunk_text value across multiple lines, and if that value
    itself contains a line that is exactly `---` (a plausible Markdown
    horizontal rule or table border in real docling/Unstructured output),
    the folded output would place that embedded `---` on its own line
    inside the frontmatter block -- indistinguishable from the closing
    delimiter to a splitter that scans for the first bare `---` line
    (exactly what the locked outer test's frontmatter parser does). Forcing
    double-quoted scalars guarantees no `---` line can ever appear inside
    the frontmatter body itself.
    """
    frontmatter_yaml = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True, default_style='"'
    )
    return f"---\n{frontmatter_yaml}---\n{body}"


# Note filename budgeting (Windows' 260-char MAX_PATH) is shared with the
# read side (`axial.query.reader.get_chunk`/`get_artifact` must locate a
# note by the SAME rule this writer used, or a budgeted note becomes
# unreachable by its own real id) -- so `_note_path`/`_artifact_note_path`
# and the budgeting internals they call are `axial.paths.chunk_note_path`/
# `artifact_note_path` imported above, not defined here. A real 31-source
# Phase A ingestion rerun measured two long-titled sources losing 165/484
# (~34%) and 59/483 (~12%) of their notes to `FileNotFoundError` from
# oversized chunk_id/artifact_id-derived paths -- not a rare outlier, but
# most section slugs of ordinary length for a long-titled source.


def write_chunk_note(
    record: dict[str, Any],
    envelope: dict[str, Any],
    source_meta: dict[str, Any],
    vault_dir: Path,
    *,
    source_id: str,
    chapter: str | None = None,
    answer_record: dict[str, Any] | None = None,
) -> Path:
    """Write one chunk's note under `<vault_dir>/prose/`, named by
    `record['chunk_id']` (shortened only on the filesystem, per
    `_note_path`, when the full chunk_id would push the path over Windows'
    MAX_PATH -- `chunk_id` itself is unchanged everywhere else). Creates
    parent directories as needed. `source_meta` is the source's persisted
    source-metadata record (§7.12), the origin of the note's
    `author`/`title`/`date`. `source_id` is the source's own
    `compute_source_id` value, needed only for the filename-budget
    fallback. `chapter`/`answer_record` (issue #411) are forwarded verbatim
    to `build_frontmatter` -- see its docstring."""
    frontmatter = build_frontmatter(
        record, envelope, source_meta, chapter=chapter, answer_record=answer_record
    )
    body = f"# {record['section']}\n\n{record['chunk_text']}\n"
    note_text = render_note(frontmatter, body)

    path = _note_path(vault_dir, source_id, record["chunk_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_text, encoding="utf-8")
    return path


def build_artifact_frontmatter(record: dict[str, Any]) -> dict[str, Any]:
    """Assemble one artifact note's frontmatter mapping: `artifact_id`,
    `source_id`, `section` reused verbatim from the artifact record
    (`axial.artifacts.build_artifact_record`'s shape), plus a `retrievable`
    boolean.

    `retrievable` (issue #429) is `True` iff the record carries a non-empty
    `caption` -- a rule over caption presence, not a model judgment. The
    artifact record carries no content beyond ids/section/caption, so there
    is nothing in an uncaptioned artifact note to protect by keeping it
    retrievable; the retired `artifact_role`/`discard` axis measured 48.5%
    disagreement across two runs and a 13.1% keep/discard flip rate, while
    caption presence alone predicted that same bit far better (4.7% flip
    rate on captioned artifacts vs. 19.6% on uncaptioned ones).

    `caption` (issue #168) is included only when the record itself carries
    one -- see below.

    Retired (issue #414, D5): `cited_by`, the cross-reference pass's
    backlink list. Retired (issue #429): `artifact_role`, `field` -- the
    LLM classification's own output, gone with the call that produced it."""
    frontmatter = {field: record.get(field) for field in ARTIFACT_FRONTMATTER_FIELDS}
    caption = record.get("caption")
    frontmatter["retrievable"] = bool(caption)
    # `caption` (issue #168): the text of a caption block attached to this
    # artifact by `axial.artifacts.run_artifacts`/`_attach_captions`, when
    # present -- omitted entirely (never `caption: null`) when this artifact
    # has no attached caption, mirroring `axial.artifacts.build_artifact_record`'s
    # own conditional-`caption`-inclusion pattern, so a pre-#168 artifact
    # record (no `caption` key at all) still produces a byte-for-byte
    # unchanged frontmatter.
    if caption:
        frontmatter["caption"] = caption
    return frontmatter


def write_artifact_note(record: dict[str, Any], vault_dir: Path) -> Path:
    """Write one artifact's note under `<vault_dir>/artifacts/`, named by
    `record['artifact_id']` (shortened only on the filesystem, per
    `_artifact_note_path`, when the full artifact_id would push the path
    over Windows' MAX_PATH -- `artifact_id` itself is unchanged everywhere
    else), creating parent directories as needed -- a surface separate from
    `<vault_dir>/prose/` (PRD §8 P0-8). `record['source_id']` (always
    present, `axial.artifacts.build_artifact_record`'s shape) is needed
    only for the filename-budget fallback."""
    frontmatter = build_artifact_frontmatter(record)
    body = f"# {record['section']}\n\nArtifact `{record['artifact_id']}`.\n"
    note_text = render_note(frontmatter, body)

    path = _artifact_note_path(vault_dir, record["source_id"], record["artifact_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(note_text, encoding="utf-8")
    return path


def run_vault_write(
    source_path: str | Path,
    client: LLMClient | None = None,
    envelopes_dir: Path | None = None,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    domain_dir: str | Path = DEFAULT_DOMAIN_DIR,
    chunks_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    source_meta_dir: Path | None = None,
) -> None:
    """Retired (module docstring): always raises `VaultWriteRetiredError`
    naming issue #411. Every parameter is accepted, unused, purely so
    existing call sites (`axial.ingest.run_ingest`, `axial.drive`,
    `axial.run`'s `vault-write` pass, `axial vault write`) keep calling this
    function the same way they always have and get one clear, typed error
    back instead of an `ImportError`/`AttributeError` from a half-deleted
    pipeline."""
    del (
        client,
        envelopes_dir,
        vault_dir,
        config_path,
        domain_dir,
        chunks_dir,
        artifacts_dir,
        source_meta_dir,
    )
    raise VaultWriteRetiredError(source_path)
