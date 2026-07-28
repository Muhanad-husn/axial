"""Phase A v1 slice 06 (issue #411): Materialize -- the vault writer
(`specs/PRODUCT.md` §7.17, P0-8).

D11: "Code writes one file per surviving name (no model): the name, its
aliases, and its member notes as links." This is the first point the founder
can open the graph view and look -- everything before it is invisible on
disk -- and it is **LLM-free by construction**: every merge decision was
already made by Reconcile (slice 05, `axial.merge_names`); this module only
joins already-persisted artifacts and writes files.

Three outputs (§7.17), one pass, run **once over the whole corpus**
(`plans/phase-a-v1/README.md`'s pipeline table: "Materialize | once over the
index"), not per source:

  1. **Prose notes** (`data/vault/prose/`) -- every chunk that has an
     interrogation answer record is (re)written carrying that record as
     frontmatter (Appendix H), replacing the retired tag/xref axis block.
     A note carries **no links** (D11): `names`/`citations` stay plain
     strings in the frontmatter's `answers` block.
  2. **Artifact notes** (`data/vault/artifacts/`) -- every persisted
     artifacts-pass record (`data/artifacts/<source_id>.jsonl`,
     `axial.artifacts.run_artifacts`) is written via the existing, untouched
     `axial.vault.write_artifact_note` (issue #429 already settled that
     shape; nothing here re-derives it).
  3. **Name pages** (`data/vault/names/`) -- one per node in Reconcile's
     alias map (`data/names/alias_map.json`), carrying `name`/`kind`/
     `aliases`/`member_count` in frontmatter and, in the body, every member
     note as an Obsidian link with its author, year and one-sentence claim
     (§7.17). Link direction is name-page -> note only.

**The figure/table join (Open Question, §10, spec line 807).** A name whose
`kind` is `figure`/`table` additionally links to the artifact note(s) it
names, found by a bounded, deterministic substring match: the canonical name
or one of its aliases appears in an artifact's caption, restricted to the
SAME source(s) the name's own member notes came from (never cross-source --
"Table 3" in one book must never resolve to "Table 3" in another). This is
not a model judgment and not fuzzy matching; it is a plain, case-insensitive
substring check over a small, source-scoped candidate set, with one boundary
rule: a match is refused when the character right after it is another digit,
so `"Figure 9.1"` never matches inside `"Figure 9.10"` (`_matches_with_digit_
boundary` -- measured on the real corpus, 2026-07-28: 10 of 292 links, 3.4%,
were exactly this prefix collision before the rule). Confirmed here, not
designed in the spec, exactly as the spec's own Open Questions section says
to.

**Cross-source locator collision, fixed upstream (issue #445).** 54 of 385
real figure/table names (14%) used to have member notes spanning more than
one source: the inventory (slice 04) keyed a locator like "Figure 4.1" by
its exact surface string, so identical numbering from unrelated books
collapsed into one node by construction. `axial.names.build_inventory` now
scopes a locator-shaped surface's identity by source when it actually spans
more than one ("Figure 4.1 (source_id)"), so a figure/table-kind node this
module sees is, by construction, always single-source. The canonical/alias
strings a scoped node carries no longer literally appear in that source's
own caption text (the caption never carries the "(source_id)" suffix), so
`materialize_names` strips it back off with `unscope_surface_form` before
calling `find_artifact_links` below -- that function's own source-scoped
substring match and digit-boundary rule are untouched.

**Determinism and re-run cost (§7.17, P0-8).** Prose and artifact notes are
a pure function of already-persisted upstream artifacts (chunks, envelope,
source_meta, answers, artifacts) that Reconcile never touches, so they are
unconditionally (re)written -- always byte-identical given unchanged input,
and never touched by the alias map at all. Name pages are compared against
their own current on-disk content before writing (a Reconcile re-run
changes a bounded few hundred names, per D11); a stale name page --
one whose canonical no longer survives the current alias map -- is deleted,
so the vault never accumulates orphans from a tightened merge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from axial.paths import (
    DEFAULT_PIPELINE_CONFIG_PATH,
    _read_configured_dir,
    default_vault_dir,
    name_page_path,
)
from axial.vault import (
    VaultError,
    bibliographic_value,
    read_source_meta,
    render_note,
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

# The two `kind` values §7.15's interrogation prompt uses for a figure/table
# name (D5) -- matched case-insensitively, since nothing enforces exact case
# on a free-text `kind` answer.
_FIGURE_TABLE_KINDS = frozenset({"figure", "table"})


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
    byte-identical given unchanged upstream artifacts -- there is nothing
    for a "write only if changed" check to save here, unlike the name pages
    below.

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
    artifacts` yet still materializes its prose notes and name pages."""
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


def _load_artifacts_by_source(artifacts_dir: Path, source_ids: set[str]) -> dict[str, list[dict]]:
    """`source_id -> [artifact record, ...]`, read only for the given
    `source_ids` -- the figure/table join below only ever needs the sources
    a figure/table-kind name's own member notes came from, never the whole
    corpus's artifact records."""
    artifacts_dir = Path(artifacts_dir)
    by_source: dict[str, list[dict]] = {}
    for source_id in source_ids:
        path = artifacts_dir / f"{source_id}.jsonl"
        if not path.is_file():
            continue
        by_source[source_id] = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return by_source


def _is_figure_or_table(kind: Any) -> bool:
    return isinstance(kind, str) and kind.strip().casefold() in _FIGURE_TABLE_KINDS


def _bare_surface_forms(
    surface_forms: list[str], member_chunk_ids: list[str], source_id_by_chunk_id: dict[str, str]
) -> list[str]:
    """`surface_forms` (a node's canonical + aliases) plus, for each, the
    bare text `unscope_surface_form` recovers for every source the node's
    own members actually came from -- what an artifact caption would
    contain, since a caption never carries the "(source_id)" suffix issue
    #445's scoping adds. A form that was never scoped (the common case)
    comes back unchanged, so this is a superset, never a narrowing, of what
    `find_artifact_links` is asked to match."""
    needed_sources = {
        source_id_by_chunk_id[chunk_id]
        for chunk_id in member_chunk_ids
        if chunk_id in source_id_by_chunk_id
    }
    bare_forms = set(surface_forms)
    for form in surface_forms:
        for source_id in needed_sources:
            bare_forms.add(unscope_surface_form(form, source_id))
    return sorted(bare_forms)


def _matches_with_digit_boundary(form: str, caption: str) -> bool:
    """Whether `form` occurs in `caption` (both already casefolded) as a
    substring whose end is NOT immediately followed by another digit.

    A plain substring match alone lets `"figure 9.1"` match inside
    `"figure 9.10"`/`"figure 9.11"`/... -- measured on the real corpus
    (2026-07-28): 10 of 292 real figure/table links (3.4%) were exactly this
    prefix collision, `"Figure 9.1"` alone accounting for five and `"Map 1"`
    matching `"Map 12: Reconstruction Programmes in Aleppo"` the rest. This
    is a boundary rule, not a threshold: it does not soften or loosen the
    match, it only refuses the one case where a shorter numbered locator is
    a strict prefix of a longer, different one. Deliberately narrow -- it
    checks ONLY the digit that would extend the matched number, not a
    general word-boundary rule, because that is the only case actually
    measured; whether `"Table 3"` should also refuse to match inside
    `"Table 3 continued"` (a letter/space boundary, not a digit one) is not
    measured and is not this rule's job to guess at."""
    start = 0
    while True:
        index = caption.find(form, start)
        if index == -1:
            return False
        end = index + len(form)
        if end >= len(caption) or not caption[end].isdigit():
            return True
        start = index + 1  # retry: this occurrence was a numeric prefix, not a match


def find_artifact_links(
    surface_forms: list[str],
    member_chunk_ids: list[str],
    source_id_by_chunk_id: dict[str, str],
    artifacts_by_source: dict[str, list[dict]],
) -> list[str]:
    """`artifact_id`s this figure/table name resolves to (module docstring):
    every artifact, in a source one of `member_chunk_ids` actually came
    from, whose caption contains one of `surface_forms` as a substring
    (case-insensitive), refusing a match whose end is immediately followed
    by another digit (`_matches_with_digit_boundary` -- "Figure 9.1" must
    never match inside "Figure 9.10"). Sorted, deduplicated; `[]` when no
    caption matches -- a figure/table name with no resolvable artifact
    still gets a name page, just with no `Artifacts:` section."""
    needed_sources = {
        source_id_by_chunk_id[chunk_id]
        for chunk_id in member_chunk_ids
        if chunk_id in source_id_by_chunk_id
    }
    folded_forms = [form.casefold() for form in surface_forms]
    matches: set[str] = set()
    for source_id in needed_sources:
        for record in artifacts_by_source.get(source_id, []):
            caption = record.get("caption")
            if not caption:
                continue
            folded_caption = caption.casefold()
            if any(_matches_with_digit_boundary(form, folded_caption) for form in folded_forms):
                matches.add(record["artifact_id"])
    return sorted(matches)


# ---------------------------------------------------------------------------
# 3. Name pages -- one per Reconcile alias-map node (D11, §7.17)
# ---------------------------------------------------------------------------


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


def member_chunk_ids_for_node(
    node: dict[str, Any], inventory: dict[str, dict[str, Any]]
) -> list[str]:
    """Every chunk_id that named this node's canonical OR any of its
    aliases (§7.17's "member notes"), unioned and sorted -- deduplicated,
    since a note can name both a canonical and one of its own aliases in
    the same `names[]` answer."""
    chunk_ids: set[str] = set()
    for surface_form in (node["canonical"], *node.get("aliases", [])):
        entry = inventory.get(surface_form)
        if entry:
            chunk_ids.update(entry["chunk_ids"])
    return sorted(chunk_ids)


def build_name_frontmatter(
    canonical: str, kind: str | None, aliases: list[str], member_count: int
) -> dict[str, Any]:
    """§7.17's exact name-page frontmatter: `name`, `kind`, `aliases`,
    `member_count`."""
    return {"name": canonical, "kind": kind, "aliases": list(aliases), "member_count": member_count}


def _render_claim(value: Any) -> str:
    """One member line's claim, rendered for the name-page body: the free
    `claim` answer verbatim when it is one, else a plain marker for D7's
    explicit abstention or a missing answer -- never a guess."""
    if value is None:
        return "(no claim recorded)"
    if is_abstention(value):
        return "(not stated in the passage)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class MemberLine:
    chunk_id: str
    author: Any
    year: Any
    claim: Any


def render_name_page_body(
    canonical: str, aliases: list[str], members: list[MemberLine], artifact_ids: list[str]
) -> str:
    """§7.17's name-page body: the aliases, then (for a figure/table name
    whose surface resolved one) the artifact link(s), then every member
    note as an Obsidian link with its author, year and one-sentence claim
    -- "readable without opening anything". Link direction is name-page ->
    note/artifact only (D11): nothing here is written back onto a note."""
    lines = [f"# {canonical}", ""]
    if aliases:
        lines.append("**Aliases:** " + ", ".join(aliases))
        lines.append("")
    if artifact_ids:
        lines.append("**Artifacts:**")
        for artifact_id in artifact_ids:
            lines.append(f"- [[{artifact_id}]]")
        lines.append("")
    lines.append("**Member notes:**")
    if not members:
        lines.append("(none)")
    else:
        for member in members:
            lines.append(
                f"- [[{member.chunk_id}]] — {member.author} ({member.year}): "
                f"{_render_claim(member.claim)}"
            )
    return "\n".join(lines) + "\n"


def materialize_names(
    *,
    alias_map_path: Path,
    inventory_path: Path,
    answers_dir: Path,
    source_meta_dir: Path,
    artifacts_dir: Path,
    vault_dir: Path,
) -> dict[str, int]:
    """Write one name page per Reconcile alias-map node (§7.17, D11). A page
    is (re)written only when its rendered content differs from what is
    already on disk, and a name page whose canonical no longer survives the
    current alias map is deleted -- so re-running against an unchanged
    alias map touches nothing, and a tightened merge rewrites only the
    affected pages, never the prose notes (acceptance criterion 4)."""
    nodes = load_alias_map(alias_map_path)
    inventory = load_inventory(inventory_path)

    claim_by_chunk_id: dict[str, Any] = {}
    source_id_by_chunk_id: dict[str, str] = {}
    for record in load_answer_records(answers_dir):
        if "answers" not in record:
            continue
        chunk_id = record.get("chunk_id")
        source_id_by_chunk_id[chunk_id] = record.get("source_id")
        claim_by_chunk_id[chunk_id] = record["answers"].get("claim")

    figure_table_sources: set[str] = set()
    for node in nodes:
        if _is_figure_or_table(node.get("kind")):
            for chunk_id in member_chunk_ids_for_node(node, inventory):
                source_id = source_id_by_chunk_id.get(chunk_id)
                if source_id is not None:
                    figure_table_sources.add(source_id)
    artifacts_by_source = _load_artifacts_by_source(artifacts_dir, figure_table_sources)

    author_year_cache: dict[str, tuple[Any, Any]] = {}

    def _author_year(source_id: str | None) -> tuple[Any, Any]:
        if source_id is None:
            return None, None
        if source_id not in author_year_cache:
            try:
                record = read_source_meta(source_id, source_meta_dir)
            except VaultError as exc:
                raise MissingNoteContextError(
                    source_id, "source-metadata record", "axial ingest"
                ) from exc
            author_year_cache[source_id] = (
                bibliographic_value(record, "author"),
                bibliographic_value(record, "date"),
            )
        return author_year_cache[source_id]

    names_dir = Path(vault_dir) / "names"
    names_dir.mkdir(parents=True, exist_ok=True)
    existing = {path for path in names_dir.glob("*.md")}
    kept: set[Path] = set()
    used_filenames: set[str] = set()

    written = 0
    unchanged = 0
    for node in sorted(nodes, key=lambda n: n["canonical"]):
        canonical = node["canonical"]
        kind = node.get("kind")
        aliases = list(node.get("aliases", []))
        member_ids = member_chunk_ids_for_node(node, inventory)

        members = [
            MemberLine(
                chunk_id,
                *_author_year(source_id_by_chunk_id.get(chunk_id)),
                claim_by_chunk_id.get(chunk_id),
            )
            for chunk_id in member_ids
        ]

        artifact_ids: list[str] = []
        if _is_figure_or_table(kind):
            artifact_ids = find_artifact_links(
                _bare_surface_forms([canonical, *aliases], member_ids, source_id_by_chunk_id),
                member_ids,
                source_id_by_chunk_id,
                artifacts_by_source,
            )

        frontmatter = build_name_frontmatter(canonical, kind, aliases, len(member_ids))
        body = render_name_page_body(canonical, aliases, members, artifact_ids)
        text = render_note(frontmatter, body)

        path = name_page_path(vault_dir, canonical, used_filenames)
        kept.add(path)
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            unchanged += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        written += 1

    orphaned = sorted(existing - kept)
    for path in orphaned:
        path.unlink()

    return {
        "name_pages": len(nodes),
        "name_pages_written": written,
        "name_pages_unchanged": unchanged,
        "name_pages_deleted": len(orphaned),
    }


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
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, Any]:
    """Materialize the whole vault in one pass (§7.17): prose notes, artifact
    notes, then name pages, in that order. No model call anywhere (D11).
    Every directory defaults to the same config-then-fallback resolution
    every other pass uses; passing one overrides just that directory,
    the seam a test uses to point the whole pass at a fixture tree."""
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
    names_result = materialize_names(
        alias_map_path=alias_map_path,
        inventory_path=inventory_path,
        answers_dir=answers_dir,
        source_meta_dir=source_meta_dir,
        artifacts_dir=artifacts_dir,
        vault_dir=vault_dir,
    )

    return {
        "vault_dir": str(vault_dir),
        **notes_result,
        **artifacts_result,
        **names_result,
    }
