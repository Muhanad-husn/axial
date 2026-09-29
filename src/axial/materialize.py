"""Phase A v1 slice 06 (issue #411): Materialize -- the vault writer
(`specs/PRODUCT.md` §7.17, P0-8). Name pages, and everything here that
wrote them, were retired by DEC-75 (issue #853): the final output never
read a page, only `chunk_id`s and the relational store.

This module only joins already-persisted artifacts and writes files, and is
**LLM-free by construction**.

Two outputs (§7.17), one pass, run **once over the whole corpus**
(`plans/phase-a-v1/README.md`'s pipeline table: "Materialize | once over the
index"), not per source, plus the relational store built from the same
inputs:

  1. **Prose notes** (`data/vault/prose/`) -- every chunk that has an
     interrogation answer record is (re)written carrying that record as
     frontmatter (Appendix H), replacing the retired tag/xref axis block.
     A note carries **no links**: `names`/`citations` stay plain strings in
     the frontmatter's `answers` block.
  2. **Artifact notes** (`data/vault/artifacts/`) -- every persisted
     artifacts-pass record (`data/artifacts/<source_id>.jsonl`,
     `axial.artifacts.run_artifacts`) is written via the existing, untouched
     `axial.vault.write_artifact_note` (issue #429 already settled that
     shape; nothing here re-derives it).
  3. **The relational store** (`data/vault/notes.db`, `build_note_store`
     below, DEC-62) -- the notes and their typed relations, including
     `note_names` (which name each note names), read by `find_names`/
     `get_name` (`axial.query.names`) in place of the retired name pages.

**Determinism and re-run cost (§7.17, P0-8).** Prose and artifact notes are
a pure function of already-persisted upstream artifacts (chunks, envelope,
source_meta, answers, artifacts) that Reconcile never touches, so they are
unconditionally (re)written -- always byte-identical given unchanged input.
The store is rewritten atomically on every run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from axial.back_matter import is_evidence_back_matter
from axial.checkpoint import load_checkpoint_records
from axial.chunk import (
    ChunkError,
    _default_chunks_dir,
    read_chunks,
)
from axial.envelope import _default_envelopes_dir, envelope_path
from axial.interrogate import (
    _default_answers_dir,
    chapter_for_section,
    is_abstention,
    load_answer_checkpoint,
)
from axial.intake import SOURCE_META_DIR
from axial.merge_names import DEFAULT_ALIAS_MAP_PATH
from axial.names import DEFAULT_INVENTORY_PATH, load_answer_records, unscope_surface_form
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, _read_configured_dir, default_vault_dir
from axial.position_pages import write_position_pages
from axial.query import store as note_store
from axial.query.names import _build_name_layer, as_string_list, fold_surface_form
from axial.query.reader import (
    NOT_IN_PASSAGE,
    MalformedChunkIdError,
    source_id_from_chunk_id,
    stated_position,
)
from axial.vocabulary import VOCABULARY_DIR
from axial.wikidata import load_qids
from axial.vault import (
    VaultError,
    bibliographic_value,
    read_source_meta,
    write_artifact_note,
    write_chunk_note,
)

# `data/artifacts/` is the artifacts pass's own checkpoint directory
# (`axial.artifacts.ARTIFACTS_DIR`); duplicated here as a bare default path
# rather than imported, mirroring `axial.query.reader`'s own stated reason
# for a small deliberate duplicate (that module docstring): `axial.artifacts`
# imports `axial.extract`'s docling-backed extraction stack to define one
# path constant, which this LLM-free, extraction-free pass has no other
# reason to pull in.
DEFAULT_ARTIFACTS_DIR = Path("data/artifacts")


class MaterializeError(Exception):
    """Base class for all materialize errors."""


class MissingAliasMapError(MaterializeError):
    """Raised when `data/names/alias_map.json` does not exist yet -- running
    this pass before Reconcile (`axial names merge`) is a misconfigured
    invocation, not an empty vault."""

    def __init__(self, path: Path):
        self.path = path
        super().__init__(f"no alias map found at {path}; run `axial names merge` first")


class MissingNoteContextError(MaterializeError):
    """Raised when a source with answer records is missing the chunk
    artifact, envelope, or source-metadata record its notes depend on --
    those are upstream prerequisites of interrogation itself, so their
    absence here is a misconfigured pipeline, not a partial vault."""

    def __init__(self, source_id: str, what: str, remedy: str):
        self.source_id = source_id
        super().__init__(f"{source_id!r} is missing its {what}; run `{remedy}` for it first")


def _default_artifacts_dir(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Path:
    """Honour `paths.artifacts_dir` when config declares it, else
    `DEFAULT_ARTIFACTS_DIR` -- mirrors `axial.artifacts._default_artifacts_dir`
    exactly, without importing that module (see module docstring)."""
    return _read_configured_dir(config_path, "artifacts_dir", DEFAULT_ARTIFACTS_DIR)


def _read_json(path: Path, source_id: str, what: str, remedy: str) -> dict[str, Any]:
    if not path.is_file():
        raise MissingNoteContextError(source_id, what, remedy)
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 1. Prose notes -- a pure function of chunks + envelope + source_meta +
#    answers, none of which Reconcile ever touches.
# ---------------------------------------------------------------------------


def materialize_notes(
    *,
    answers_dir: Path,
    chunks_dir: Path,
    envelopes_dir: Path,
    source_meta_dir: Path,
    vault_dir: Path,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, int]:
    """(Re)write one prose note per chunk that has an interrogation answer
    record, for every source under `answers_dir` (§7.17). Unconditional
    write: the inputs here (chunks, envelope, source_meta, the answer
    itself) are never changed by Reconcile, so this is always
    byte-identical given unchanged upstream artifacts.

    A chunk with no answer record (a failed or garble-skipped note, §7.15)
    is not written -- there is no interrogation answer for its frontmatter
    to carry -- and counted separately rather than silently dropped."""
    sources = 0
    written = 0
    skipped_no_answer = 0
    for path in sorted(Path(answers_dir).glob("*.jsonl")):
        source_id = path.stem
        sources += 1
        answers_by_chunk_id = {
            record["chunk_id"]: record
            for record in load_answer_checkpoint(path)
            if "answers" in record
        }

        try:
            chunk_records = read_chunks(source_id, chunks_dir=chunks_dir, config_path=config_path)
        except ChunkError as exc:
            raise MissingNoteContextError(source_id, "chunk artifact", "axial chunk") from exc
        envelope = _read_json(
            envelope_path(source_id, envelopes_dir), source_id, "envelope", "axial envelope"
        )
        try:
            source_meta = read_source_meta(source_id, source_meta_dir)
        except VaultError as exc:
            raise MissingNoteContextError(
                source_id, "source-metadata record", "axial ingest"
            ) from exc

        for chunk_record in chunk_records:
            answer_record = answers_by_chunk_id.get(chunk_record["chunk_id"])
            if answer_record is None:
                skipped_no_answer += 1
                continue
            record = {
                "chunk_id": chunk_record["chunk_id"],
                "section": chunk_record.get("section"),
                "chunk_text": chunk_record["text"],
            }
            chapter = chapter_for_section(envelope.get("toc"), chunk_record.get("section"))
            write_chunk_note(
                record,
                envelope,
                source_meta,
                vault_dir,
                source_id=source_id,
                chapter=chapter,
                answer_record=answer_record,
            )
            written += 1

    return {
        "sources": sources,
        "notes_written": written,
        "notes_skipped_no_answer": skipped_no_answer,
    }


# ---------------------------------------------------------------------------
# 2. Artifact notes -- unchanged shape (issue #429), just called from here
# ---------------------------------------------------------------------------


def materialize_artifact_notes(*, artifacts_dir: Path, vault_dir: Path) -> dict[str, int]:
    """Write one artifact note per persisted artifacts-pass record
    (`data/artifacts/<source_id>.jsonl`), via the existing, untouched
    `axial.vault.write_artifact_note`. `artifacts_dir` absent or empty
    yields zero notes, not an error: a corpus that has not run `axial
    artifacts` yet still materializes its prose notes and its store."""
    sources = 0
    written = 0
    artifacts_dir = Path(artifacts_dir)
    if not artifacts_dir.is_dir():
        return {"artifact_sources": 0, "artifact_notes_written": 0}
    for path in sorted(artifacts_dir.glob("*.jsonl")):
        sources += 1
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            write_artifact_note(json.loads(line), vault_dir)
            written += 1
    return {"artifact_sources": sources, "artifact_notes_written": written}


# `load_alias_map`/`load_inventory` (below) are shared with `build_note_store`
# (DEC-62); everything else that once lived in this section -- the
# figure/table artifact join, `member_chunk_ids_for_node`, and the name-page
# writer itself -- went with the name pages (DEC-75, issue #853).


def load_alias_map(path: Path) -> list[dict[str, Any]]:
    """Reconcile's own `{version, generated_at, nodes: [...]}` shape
    (`axial.merge_names.write_alias_map`); raises `MissingAliasMapError`
    when it does not exist yet."""
    path = Path(path)
    if not path.is_file():
        raise MissingAliasMapError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("nodes", [])


def load_inventory(path: Path) -> dict[str, dict[str, Any]]:
    """`surface_form -> {kind, count, chunk_ids}`, read from slice 04's
    lossless inventory (`axial.names.write_inventory`'s exact shape). `{}`
    when the file does not exist -- a node whose surfaces are all absent
    from it simply has no member notes, rather than this pass crashing."""
    path = Path(path)
    if not path.is_file():
        return {}
    inventory: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            inventory[row["surface"]] = {
                "kind": row.get("kind"),
                "count": row.get("count"),
                "chunk_ids": row.get("chunk_ids") or [],
            }
    return inventory


# ---------------------------------------------------------------------------
# 3. The relational store -- the notes and their typed relations (DEC-62)
# ---------------------------------------------------------------------------

# A source id is `<author>-[...-]<year>-<hash>` (issue #268's rename): the
# publication year is the rightmost token that is four digits and nothing
# else, so `mann-v1-2012-5f90ead66c93` reads 2012 and the twelve-hex-digit
# content hash can never be mistaken for one.
_YEAR_TOKEN = re.compile(r"^\d{4}$")


def _publication_year(source_id: str) -> int | None:
    for token in reversed(source_id.split("-")):
        if _YEAR_TOKEN.match(token):
            return int(token)
    return None


def _text(value: Any) -> str | None:
    """A free-text answer as a TEXT column: the corpus's own string, `None`
    when it answered nothing, and JSON for the occasional record where a
    field the frame asks for as a string came back as a list or an object.
    Nothing is dropped and nothing raises on the way into the store."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _store_claim(value: Any) -> str | None:
    """A note's `claim` answer as the store holds it: the corpus's own text
    when it answered with text, `None` when the record carries no claim at
    all, the bare abstention marker for D7's abstention in any of its shapes,
    and JSON for anything else -- so `axial.query.names._render_claim` reads
    back exactly what this wrote."""
    if value is None or isinstance(value, str):
        return value
    if is_abstention(value):
        return NOT_IN_PASSAGE
    return _text(value)


def _source_of(chunk_id: str) -> str:
    """The `source_id` a chunk_id parses to, or `""` when it does not --
    the same placement the reader's own member grouping gives an unparsed
    member, so `note_names`'s source count never disagrees with it."""
    try:
        return source_id_from_chunk_id(chunk_id)
    except MalformedChunkIdError:
        return ""


def _target_phrase_index(folded: dict[str, list[tuple[str, str]]]) -> dict[str, list[str]]:
    """`folded surface phrase -> [canonical, ...]` over every surface form of
    two or more tokens the name layer carries (its own `folded` map, so the
    #642 transliteration fold applies here exactly as it does everywhere
    else).

    **Two tokens is the measured floor, not a knob**
    (`data/logs/2026-08-04-relational-join-ceiling/` §1): matching
    single-token surfaces against free-text targets lifts the apparent join
    rate from 44% to 93% and is almost entirely noise from the corpus's own
    one-word canonicals -- "the notion of Free French rule" resolving to the
    canonical `Rule`, "many of his contemporaries" to `His`. A phrase is a
    name; a word is not."""
    index: dict[str, set[str]] = {}
    for phrase, pairs in folded.items():
        if len(phrase.split()) < 2:
            continue
        index.setdefault(phrase, set()).update(canonical for canonical, _surface in pairs)
    return {phrase: sorted(canonicals) for phrase, canonicals in index.items()}


def _resolve_target(target: str, phrases: dict[str, list[str]], longest: int) -> list[str]:
    """Every canonical whose folded surface form appears inside `target` as a
    whole-word phrase -- the conservative join. Walks the target's own word
    n-grams rather than scanning the index, which is the same answer at a
    fraction of the cost (49,555 substring scans per target against a few
    hundred dictionary lookups)."""
    tokens = fold_surface_form(target).split()
    found: set[str] = set()
    for size in range(2, min(len(tokens), longest) + 1):
        for start in range(len(tokens) - size + 1):
            found.update(phrases.get(" ".join(tokens[start : start + size]), ()))
    return sorted(found)


class _CorruptResidueDecisionsError(Exception):
    """Raised by `_resolved_opposition_edges` on a non-torn-tail corrupt line
    in the semantic residue resolver's own decision log. A twin of
    `axial.argmap.residue.ResidueDecisionsCorruptError`, defined here rather
    than imported: `axial.argmap.residue` already imports `_resolve_target`/
    `_target_phrase_index` from this module, so importing back from it here
    would be a materialize <-> argmap.residue cycle for one exception
    class."""

    def __init__(self, path: Path, line_no: int, cause: Exception) -> None:
        super().__init__(f"corrupt residue decision log at {path}:{line_no}: {cause}")


def _resolved_opposition_edges(
    decisions_path: Path | None, positions_path: Path | None
) -> list[tuple]:
    """`note_opposed_position` rows (issue #651), folded from the semantic
    residue resolver's own content-keyed decision log (`axial.argmap.
    residue.run_residue_sample` decides and appends to it; this is the only
    place it is ever read back into the store -- the pass never writes the
    store directly).

    One row per `(chunk_id, target, position_id)` the log actually matched.
    `mode` is `"both"` when the blocked and unblocked arms independently
    matched the same triple, else whichever single arm did (module
    docstring on `axial.query.store`: the two arms resolve mostly different
    targets, not a nested subset, so this is a real distinction, not
    bookkeeping). `self_referential` is a plain `source_id` membership check
    against the matched position's own `sources` -- issue #651's own
    scoping ("a source_id comparison at assembly is enough, no new
    mechanism"), not a chunk-level check, since the decision record carries
    no finer join than the note's source.

    `[]` when either path is `None`, or the decision log or the position
    file does not exist yet -- a corpus with no argument map, or one with a
    map but no residue pass run against it, materializes exactly as it did
    before this table existed: no rows, no error."""
    if decisions_path is None or positions_path is None:
        return []
    decisions_path = Path(decisions_path)
    positions_path = Path(positions_path)
    if not decisions_path.is_file() or not positions_path.is_file():
        return []

    positions_by_id = {
        position["position_id"]: position
        for position in (
            json.loads(line)
            for line in positions_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    records = load_checkpoint_records(decisions_path, _CorruptResidueDecisionsError)
    # Content-keyed (issue #486): the last record on disk under a given key
    # is the live one -- the same fold `axial.argmap.residue.load_decisions`
    # does over this exact file.
    by_key = {record["key"]: record for record in records if "key" in record}

    modes_by_triple: dict[tuple[str, str, str], set[str]] = {}
    source_by_pair: dict[tuple[str, str], str | None] = {}
    for record in by_key.values():
        chunk_id = record.get("chunk_id")
        target = record.get("target")
        if not chunk_id or not target:
            continue
        source_by_pair[(chunk_id, target)] = record.get("source_id")
        mode = record.get("mode") or ""
        for position_id in record.get("matches") or []:
            modes_by_triple.setdefault((chunk_id, target, position_id), set()).add(mode)

    rows: list[tuple] = []
    for (chunk_id, target, position_id), modes in sorted(modes_by_triple.items()):
        mode_label = "both" if len(modes) > 1 else next(iter(modes))
        source_id = source_by_pair.get((chunk_id, target))
        position = positions_by_id.get(position_id)
        self_referential = 1 if position and source_id in (position.get("sources") or ()) else 0
        rows.append((chunk_id, source_id, target, position_id, mode_label, self_referential))
    return rows


def build_note_store(
    *,
    alias_map_path: Path,
    inventory_path: Path,
    answers_dir: Path,
    source_meta_dir: Path,
    envelopes_dir: Path,
    vault_dir: Path,
    residue_decisions_path: Path | None = None,
) -> dict[str, int]:
    """Build the vault's relational store (DEC-62, `axial.query.store`) from
    already-persisted artifacts: the answer records, the lossless inventory,
    Reconcile's alias map, and the source metadata. No model call, no
    re-extraction, no second source of truth -- `note_names` is built
    straight off the same alias map and inventory the retired name pages
    used to read (DEC-75, issue #853), never derived from a page.

    `chapter` is the one column here that is not already sitting in the
    answer record: it is `chapter_for_section` read off the source's own
    envelope, the same call `materialize_notes` makes for the prose note, so
    the two can never disagree about which chapter a section resolves to.
    The envelope is loaded once per source (issue #648's comment measured 31
    sources, ~2-6KB each) and cached across that source's notes, never once
    per note.

    `arguing_against` is resolved here too: each free-text target keeps a
    row with the canonical it resolves to, or one row with `NULL` when it
    resolves to nothing, which is the honest majority (56%) and must stay
    countable.

    **`notes.back_matter` (issue #661)** is set once here, from each note's
    own `section` via `axial.back_matter.is_evidence_back_matter` -- the
    same broader rule `axial.gold` already applies to its own sampling
    frame, reused rather than re-derived. Every store read that returns a
    note as citable evidence filters on this column so an acknowledgments
    or endnotes page, though still written and still interrogated, can
    never again be retrieved, assembled or cited as evidence for a claim.

    **`note_opposed_position` (issue #651)** is folded in from
    `residue_decisions_path` when given -- the semantic residue resolver's
    own content-keyed decision log (`axial.argmap.residue`), a SIBLING of
    that pass's own `positions.jsonl` in the same pinned map directory
    (`_resolved_opposition_edges` reads both from the one path). `None`
    (the default) or a decision log that has not been written yet both mean
    the same thing here -- no rows, no error -- so a vault materialized
    before a residue pass ever ran looks exactly as it always has.

    Written atomically over any existing store."""
    positions_path = (
        Path(residue_decisions_path).parent / "positions.jsonl"
        if residue_decisions_path is not None
        else None
    )
    opposed_positions = _resolved_opposition_edges(residue_decisions_path, positions_path)
    nodes = load_alias_map(alias_map_path)
    inventory = load_inventory(inventory_path)
    layer = _build_name_layer(Path(alias_map_path).parent)
    phrases = _target_phrase_index(layer.folded)
    longest = max((len(phrase.split()) for phrase in phrases), default=0)

    notes: list[tuple] = []
    citations: list[tuple] = []
    opposition: list[tuple] = []
    source_ids: set[str] = set()
    # `(chunk_id, surface) -> kind`, the label THIS note gave that name --
    # first answer wins, so a note naming one surface twice under two kinds
    # is read the same way on every run.
    kind_by_occurrence: dict[tuple[str, str], str | None] = {}
    # `source_id -> toc`, loaded once per source and reused across every one
    # of its notes -- `load_answer_records` groups records by source (one
    # `<source_id>.jsonl` at a time), so this is never re-read mid-source.
    toc_by_source: dict[str, Any] = {}

    for record in load_answer_records(answers_dir):
        if "answers" not in record:
            continue
        chunk_id = record["chunk_id"]
        source_id = record.get("source_id")
        if source_id:
            source_ids.add(source_id)
            if source_id not in toc_by_source:
                envelope = _read_json(
                    envelope_path(source_id, envelopes_dir), source_id, "envelope", "axial envelope"
                )
                toc_by_source[source_id] = envelope.get("toc")
        section = record.get("section")
        chapter = chapter_for_section(toc_by_source.get(source_id), section) if source_id else None
        answers = record["answers"]
        position = stated_position(answers)
        notes.append(
            (
                chunk_id,
                source_id,
                _text(section),
                chapter,
                _store_claim(answers.get("claim")),
                position if isinstance(position, str) else None,
                1 if is_evidence_back_matter(section if isinstance(section, str) else "") else 0,
            )
        )
        for entry in answers.get("names") or []:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                kind_by_occurrence.setdefault((chunk_id, entry["name"]), _text(entry.get("kind")))
        for entry in answers.get("citations") or []:
            if isinstance(entry, dict) and isinstance(entry.get("cited"), str):
                citations.append(
                    (
                        chunk_id,
                        source_id,
                        entry["cited"],
                        _text(entry.get("stance")),
                        _text(entry.get("about")),
                    )
                )
        targets = answers.get("arguing_against")
        if is_abstention(targets):
            continue
        for target in dict.fromkeys(as_string_list(targets)):
            resolved = _resolve_target(target, phrases, longest)
            if not resolved:
                opposition.append((chunk_id, source_id, target, None))
            for canonical in resolved:
                opposition.append((chunk_id, source_id, target, canonical))

    # Issue #856: the QIDs `axial names wikidata` wrote beside the index.
    qids = load_qids(Path(alias_map_path).parent / "index.json")
    names: list[tuple] = []
    note_names: list[tuple] = []
    for node in sorted(nodes, key=lambda node: node["canonical"]):
        canonical = node["canonical"]
        names.append(
            (canonical, _text(node.get("kind")), fold_surface_form(canonical), qids.get(canonical))
        )
        kinds: dict[str, str | None] = {}
        for surface in (canonical, *node.get("aliases", [])):
            entry = inventory.get(surface)
            if not entry:
                continue
            for chunk_id in entry["chunk_ids"]:
                kind = kind_by_occurrence.get(
                    (chunk_id, surface),
                    kind_by_occurrence.get(
                        (chunk_id, unscope_surface_form(surface, _source_of(chunk_id)))
                    ),
                )
                if kinds.setdefault(chunk_id, kind) is None and kind is not None:
                    kinds[chunk_id] = kind
        note_names.extend(
            (chunk_id, _source_of(chunk_id), canonical, kinds[chunk_id])
            for chunk_id in sorted(kinds)
        )

    sources: list[tuple] = []
    for source_id in sorted(source_ids):
        try:
            record = read_source_meta(source_id, source_meta_dir)
        except VaultError as exc:
            raise MissingNoteContextError(
                source_id, "source-metadata record", "axial ingest"
            ) from exc
        sources.append(
            (
                source_id,
                *(
                    None if value is None else str(value)
                    for value in (
                        bibliographic_value(record, "author"),
                        bibliographic_value(record, "title"),
                        bibliographic_value(record, "date"),
                    )
                ),
                _publication_year(source_id),
            )
        )

    return note_store.write_store(
        note_store.store_path(vault_dir),
        sources=sources,
        notes=sorted(notes, key=lambda row: row[0]),
        names=names,
        note_names=note_names,
        note_arguing_against=opposition,
        note_citations=citations,
        note_opposed_position=opposed_positions,
    )


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def run_materialize(
    *,
    alias_map_path: Path | None = None,
    inventory_path: Path | None = None,
    answers_dir: Path | None = None,
    chunks_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    source_meta_dir: Path | None = None,
    artifacts_dir: Path | None = None,
    vault_dir: Path | None = None,
    residue_decisions_path: Path | None = None,
    map_dir: Path | None = None,
    vocabulary_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, Any]:
    """Materialize the whole vault in one pass (§7.17): prose notes, artifact
    notes, then the relational store, in that order. No model call anywhere.
    Every directory defaults to the same config-then-fallback resolution
    every other pass uses; passing one overrides just that directory,
    the seam a test uses to point the whole pass at a fixture tree.

    Writes no `names/` directory (DEC-75, issue #853 retired the name pages
    that used to live there).

    `residue_decisions_path` (issue #651, default `None`) opts into folding
    the semantic residue resolver's decision log into the store's
    `note_opposed_position` table -- see `build_note_store`'s own docstring.
    Not auto-discovered from the corpus pin: computing that pin hashes every
    raw source file (`axial.argmap.build.compute_corpus_pin`), a cost every
    ordinary materialize run would otherwise pay just to check whether a
    residue pass happens to exist. An operator who has run one passes its
    path explicitly (`axial names materialize --residue-decisions-path`).

    `map_dir` (issue #854) is one built map, `data/map/<pin>/`: when given,
    its positions are written as pages under `<vault_dir>/positions/`
    (`axial.position_pages`), their categories read from `vocabulary_dir`
    (default `data/vocabulary`). Explicit for the same reason as
    `residue_decisions_path`: resolving the pin hashes every raw source."""
    answers_dir = (
        Path(answers_dir) if answers_dir is not None else _default_answers_dir(config_path)
    )
    chunks_dir = Path(chunks_dir) if chunks_dir is not None else _default_chunks_dir(config_path)
    envelopes_dir = (
        Path(envelopes_dir) if envelopes_dir is not None else _default_envelopes_dir(config_path)
    )
    source_meta_dir = Path(source_meta_dir) if source_meta_dir is not None else SOURCE_META_DIR
    artifacts_dir = (
        Path(artifacts_dir) if artifacts_dir is not None else _default_artifacts_dir(config_path)
    )
    vault_dir = Path(vault_dir) if vault_dir is not None else default_vault_dir(config_path)
    alias_map_path = Path(alias_map_path) if alias_map_path is not None else DEFAULT_ALIAS_MAP_PATH
    inventory_path = Path(inventory_path) if inventory_path is not None else DEFAULT_INVENTORY_PATH

    notes_result = materialize_notes(
        answers_dir=answers_dir,
        chunks_dir=chunks_dir,
        envelopes_dir=envelopes_dir,
        source_meta_dir=source_meta_dir,
        vault_dir=vault_dir,
        config_path=config_path,
    )
    artifacts_result = materialize_artifact_notes(artifacts_dir=artifacts_dir, vault_dir=vault_dir)
    store_result = build_note_store(
        alias_map_path=alias_map_path,
        inventory_path=inventory_path,
        answers_dir=answers_dir,
        source_meta_dir=source_meta_dir,
        envelopes_dir=envelopes_dir,
        vault_dir=vault_dir,
        residue_decisions_path=residue_decisions_path,
    )

    pages_result = {"position_pages_written": 0, "position_pages_isolated": 0}
    if map_dir is not None:
        pages_result = write_position_pages(
            map_dir=Path(map_dir),
            vocabulary_dir=Path(vocabulary_dir) if vocabulary_dir is not None else VOCABULARY_DIR,
            vault_dir=vault_dir,
        )

    return {
        "vault_dir": str(vault_dir),
        **notes_result,
        **artifacts_result,
        **store_result,
        **pages_result,
    }
