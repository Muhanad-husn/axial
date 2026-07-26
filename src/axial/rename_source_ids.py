"""One-off migration: rewrite the derived corpus under `data/` to the
`source_id`s produced by *renamed* raw source files.

Background. `compute_source_id` (axial.envelope) is `f"{path.stem}-{hash[:12]}"`
-- the raw filename stem plus a 12-char content hash, with no normalisation
or length bound on the stem. The corpus was ingested from libgen/Z-Library
downloads, whose filenames run to 181 characters, so the longest `chunk_id`
reached 268 characters -- past Windows' documented 260-char MAX_PATH. Four
separate defects (PRs #377, #394, #395, #396) came out of that one fact. The
fix is upstream: rename the raw source PDFs to short citekeys
(`white-2011.pdf`). Renaming a file does not change its bytes, so every
`content_hash` is unchanged and only the readable stem half of each id moves.

This script makes the already-built derived corpus match the renamed
sources. It builds `old_source_id -> new_source_id` by matching *only* on
the shared 12-char content-hash suffix -- never on the stem, which is the
one thing the rename changes -- deriving the new ids with the same
`compute_source_id` primitive the pipeline uses. The mapping must be a
clean bijection between the hashes present in `data/sources/` and those
present in the derived corpus; anything else raises and writes nothing.

What it touches:

  * renames `<source_id>.<ext>` files under `data/{trees,envelopes,
    source_meta,chunks,tags,xref,artifacts}` (including `.skips.jsonl`),
  * renames the vault notes under `data/vault/{prose,artifacts}` -- via
    `axial.paths.chunk_note_path`/`artifact_note_path`, so the writer stays
    the single source of truth for a note's on-disk path, and reading each
    note's id from its YAML frontmatter, never from its filename (a note's
    filename may have been shortened by the MAX_PATH budget; its
    frontmatter id is always the true full id),
  * rewrites every `source_id`/`chunk_id`/`artifact_id` *inside* those
    files, plus `evals/cases/sim/*.json`'s `required_citation_source_ids`
    and the benchmark analysis logs under
    `data/logs/2026-07-25-brief-benchmark-slice1/analyses/`, whose `grounds`
    carry chunk_ids that would otherwise stop resolving against the vault.

Deliberately excludes `evals/corpus_pin/`: a pin is a point-in-time snapshot
of a corpus, and rewriting one would produce a pin describing a corpus that
never existed. The pin is regenerated from the renamed corpus afterwards
(`axial pin write <name>`, `axial.eval.corpus_pin`) -- the same reason
`remap_sim_source_ids` leaves it alone. The current pin is instead used as
ground truth in the other direction: every renamed source's full
`content_hash` is asserted against it before anything is written, which is
exactly the check that the rename changed names and nothing else.

Idempotent: after a successful `--apply` the derived corpus already carries
the new ids, so the mapping is the identity and a second run writes
nothing. A destination file that already exists is never overwritten -- the
run fails loudly instead. A *partially* applied run (interrupted mid-way)
leaves old and new filenames side by side, which surfaces as
`AmbiguousHashError` naming the hash; that one is resolved by hand.

Not a product feature -- no `axial` subcommand, no permanent home. One-off,
to be deleted once the rename has been run (same precedent as
`axial.remap_sim_source_ids` and docs/sim-academic/merge_gold_labels.py).

Usage (dry run by default; nothing is written without --apply):
    python -m axial.rename_source_ids
    python -m axial.rename_source_ids --apply
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from axial.cli import _print_encoding_safe
from axial.envelope import compute_source_id, content_digest
from axial.intake import SUPPORTED_EXTENSIONS
from axial.paths import artifact_note_path, chunk_note_path, default_sources_dir, default_vault_dir
from axial.vault import render_note

DATA_DIR = Path("data")
CASES_DIR = Path("evals") / "cases" / "sim"
PIN_PATH = Path("evals") / "corpus_pin" / "sim-2026-07-25.json"
ANALYSES_LOG_DIR = Path("data") / "logs" / "2026-07-25-brief-benchmark-slice1" / "analyses"

# The `data/` subdirectories whose files are named `<source_id>.<ext>`.
DERIVED_DIRS = ("trees", "envelopes", "source_meta", "chunks", "tags", "xref", "artifacts")

# `compute_source_id`'s own shape, `{stem}-{12 hex digits}`, anchored
# immediately before a filename's first extension (which must also handle
# `<source_id>.skips.jsonl`). The anchor is what keeps a stem that itself
# contains hyphens -- routine here, e.g. "Andreas Wimmer - Waves of War..."
# -- from being mistaken for the hash.
_FILENAME_ID = re.compile(r"^(.+-[0-9a-f]{12})\.")


class RenameMigrationError(RuntimeError):
    """Base for every condition that makes the migration refuse to run."""


class AmbiguousHashError(RenameMigrationError):
    def __init__(self, hash12: str, source_ids: list[str]):
        super().__init__(
            f"content-hash prefix {hash12} is claimed by {len(source_ids)} source ids, "
            f"so the mapping is not a bijection: {source_ids}"
        )
        self.hash12 = hash12
        self.source_ids = source_ids


class UnmatchedOldSourceIdError(RenameMigrationError):
    def __init__(self, source_ids: list[str]):
        super().__init__(
            f"{len(source_ids)} derived source id(s) have no raw source file with a "
            f"matching content-hash suffix: {source_ids}"
        )
        self.source_ids = source_ids


class UnmatchedNewSourceError(RenameMigrationError):
    def __init__(self, source_ids: list[str]):
        super().__init__(
            f"{len(source_ids)} raw source file(s) have no derived data with a matching "
            f"content-hash suffix: {source_ids}"
        )
        self.source_ids = source_ids


class DestinationExistsError(RenameMigrationError):
    def __init__(self, src: Path, dest: Path):
        super().__init__(f"refusing to overwrite existing {dest} while renaming {src}")
        self.src = src
        self.dest = dest


class MalformedNoteError(RenameMigrationError):
    def __init__(self, path: Path, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class ContentHashMismatchError(RenameMigrationError):
    def __init__(self, problems: list[str]):
        super().__init__(
            "renamed sources do not match the corpus pin's content hashes:\n  "
            + "\n  ".join(problems)
        )
        self.problems = problems


# ---------------------------------------------------------------- mapping


def _id_from_filename(name: str) -> str | None:
    """The `source_id` a derived filename is named for, or None when the
    filename is not `<source_id>.<ext>` at all (`data/tags` also holds
    `_quarantine_log.jsonl` and `theory_school_candidates.jsonl`, which are
    corpus-wide logs, not per-source files)."""
    match = _FILENAME_ID.match(name)
    return match.group(1) if match else None


def scan_sources(sources_dir: Path) -> dict[str, tuple[str, str]]:
    """`{hash12: (new_source_id, full_content_hash)}` for every supported
    raw source file, computed with the same `compute_source_id` /
    `content_digest` primitives the pipeline uses."""
    found: dict[str, tuple[str, str]] = {}
    by_hash: dict[str, list[str]] = defaultdict(list)
    for path in sorted(sources_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        source_id = compute_source_id(path)
        by_hash[source_id[-12:]].append(source_id)
        found[source_id[-12:]] = (source_id, content_digest(path))
    for hash12, ids in sorted(by_hash.items()):
        if len(ids) > 1:
            raise AmbiguousHashError(hash12, sorted(ids))
    return found


def scan_derived_ids(data_dir: Path) -> dict[str, str]:
    """`{hash12: old_source_id}` recovered from the derived corpus' own
    per-source filenames -- the only place the pre-rename ids still exist
    once the raw files have been renamed."""
    by_hash: dict[str, set[str]] = defaultdict(set)
    for name in DERIVED_DIRS:
        directory = data_dir / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            source_id = _id_from_filename(path.name)
            if source_id is not None:
                by_hash[source_id[-12:]].add(source_id)
    mapping: dict[str, str] = {}
    for hash12, ids in sorted(by_hash.items()):
        if len(ids) > 1:
            raise AmbiguousHashError(hash12, sorted(ids))
        mapping[hash12] = ids.pop()
    return mapping


def build_id_map(sources_dir: Path, data_dir: Path) -> dict[str, str]:
    """`{old_source_id: new_source_id}`, matched purely on the shared
    12-char content-hash suffix. Raises unless the two sides are a clean
    bijection."""
    new_by_hash = {hash12: entry[0] for hash12, entry in scan_sources(sources_dir).items()}
    old_by_hash = scan_derived_ids(data_dir)

    missing = [old for hash12, old in sorted(old_by_hash.items()) if hash12 not in new_by_hash]
    if missing:
        raise UnmatchedOldSourceIdError(missing)
    extra = [new for hash12, new in sorted(new_by_hash.items()) if hash12 not in old_by_hash]
    if extra:
        raise UnmatchedNewSourceError(extra)

    return {old: new_by_hash[hash12] for hash12, old in sorted(old_by_hash.items())}


def verify_content_hashes(sources_dir: Path, pin_path: Path) -> None:
    """Assert every renamed source's full `content_hash` against the corpus
    pin's `sources[].content_hash`, matched by the 12-char hash suffix. The
    pin's own snapshot id is stale by the time this runs, but its
    content-hash column is ground truth, and it is exactly the right check
    that the rename changed names and nothing else."""
    payload = json.loads(pin_path.read_text(encoding="utf-8"))
    pinned = {entry["content_hash"][:12]: entry["content_hash"] for entry in payload["sources"]}
    scanned = scan_sources(sources_dir)

    problems = []
    for hash12, (source_id, digest) in sorted(scanned.items()):
        expected = pinned.get(hash12)
        if expected is None:
            problems.append(f"{source_id}: no pinned source with content-hash prefix {hash12}")
        elif expected != digest:
            problems.append(f"{source_id}: content_hash {digest} != pinned {expected}")
    for hash12 in sorted(set(pinned) - set(scanned)):
        problems.append(f"pinned source {pinned[hash12]} has no raw file in {sources_dir}")
    if problems:
        raise ContentHashMismatchError(problems)


# ------------------------------------------------------------ id rewriting


def _encoded_forms(old: str, new: str) -> list[tuple[str, str]]:
    """The literal forms an id takes inside a JSON document: itself, plus
    its JSON-escaped form when the two differ (four source stems carry
    diacritics -- "Ugur Umit Ungor", "Sinisa Malesevic" -- and the pipeline
    writes JSON with the default `ensure_ascii=True`, so those ids appear on
    disk as `\\uXXXX` escapes)."""
    forms = [(old, new)]
    escaped = (json.dumps(old)[1:-1], json.dumps(new)[1:-1])
    if escaped[0] != old:
        forms.append(escaped)
    return forms


def substitute_ids_in_text(text: str, id_map: dict[str, str]) -> str:
    """Replace every old `source_id` in `text` with its new one. Because
    `chunk_id` and `artifact_id` are both `<source_id>` plus a suffix, this
    one substitution rewrites all three id kinds at once, and -- unlike
    parsing and re-serialising -- leaves every byte of formatting,
    indentation and key order untouched. A raw `source_id` carries its own
    12-hex content hash, so it cannot plausibly occur inside prose."""
    for old, new in id_map.items():
        if old == new:
            continue
        for old_form, new_form in _encoded_forms(old, new):
            if old_form in text:
                text = text.replace(old_form, new_form)
    return text


def _owning_source_id(id_: str, id_map: dict[str, str]) -> str | None:
    """The old `source_id` a `chunk_id`/`artifact_id` was built from --
    `<source_id>_<...>` in both cases (PRD §7.7,
    `axial.artifacts.artifact_id_for_node`)."""
    for old in id_map:
        if id_ == old or id_.startswith(old + "_"):
            return old
    return None


def remap_ids(value: Any, id_map: dict[str, str]) -> Any:
    """Recursively rewrite every id-shaped string in a parsed structure --
    used for vault note frontmatter, where PyYAML's line folding can split a
    long id across two lines and a text substitution would miss it."""
    if isinstance(value, str):
        old = _owning_source_id(value, id_map)
        return value if old is None else id_map[old] + value[len(old) :]
    if isinstance(value, list):
        return [remap_ids(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: remap_ids(item, id_map) for key, item in value.items()}
    return value


def split_note(path: Path, text: str) -> tuple[dict[str, Any], str]:
    """Split a note's `---`-delimited YAML frontmatter from its body,
    keeping the body verbatim so a rewritten note differs from the original
    only in its frontmatter."""
    if not text.startswith("---\n"):
        raise MalformedNoteError(path, "missing opening '---' frontmatter delimiter")
    end = text.find("\n---\n", 3)
    if end == -1:
        raise MalformedNoteError(path, "missing closing '---' frontmatter delimiter")
    try:
        parsed = yaml.safe_load(text[4 : end + 1])
    except yaml.YAMLError as exc:
        raise MalformedNoteError(path, f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(parsed, dict):
        raise MalformedNoteError(path, "frontmatter is not a mapping")
    return parsed, text[end + 5 :]


# ---------------------------------------------------------------- planning


@dataclass
class FilePlan:
    """One file to rename and/or rewrite in place. `dest == src` means the
    filename is already right and only the ids inside it change."""

    src: Path
    dest: Path


@dataclass
class NotePlan:
    """One vault note to move and rewrite. `src` is where the note is now (a
    filename possibly shortened by the MAX_PATH budget); `dest` comes from
    `chunk_note_path`/`artifact_note_path` applied to the *new* id."""

    src: Path
    dest: Path
    old_id: str
    new_id: str


@dataclass
class MigrationPlan:
    id_map: dict[str, str] = field(default_factory=dict)
    files: dict[str, list[FilePlan]] = field(default_factory=dict)
    notes: dict[str, list[NotePlan]] = field(default_factory=dict)


def plan_derived_files(data_dir: Path, id_map: dict[str, str]) -> dict[str, list[FilePlan]]:
    """Plan the `<source_id>.<ext>` renames. Files in these directories that
    are not named for a source (the corpus-wide logs in `data/tags`) keep
    their names but are still rewritten inside, since they carry chunk_ids
    that would otherwise stop resolving."""
    planned: dict[str, list[FilePlan]] = {}
    for name in DERIVED_DIRS:
        directory = data_dir / name
        if not directory.is_dir():
            continue
        entries = []
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            old_id = _id_from_filename(path.name)
            new_id = id_map.get(old_id) if old_id else None
            dest = path if new_id is None else directory / (new_id + path.name[len(old_id) :])
            entries.append(FilePlan(src=path, dest=dest))
        planned[str(directory)] = entries
    return planned


def plan_notes(
    vault_dir: Path, subdir: str, id_field: str, note_path: Any, id_map: dict[str, str]
) -> list[NotePlan]:
    """Plan one vault subdirectory's note moves, reading each note's id from
    its frontmatter (never its filename) and building the destination with
    the writer's own `note_path` function."""
    directory = vault_dir / subdir
    entries = []
    for path in sorted(directory.glob("*.md")):
        frontmatter, _body = split_note(path, path.read_text(encoding="utf-8"))
        old_id = frontmatter.get(id_field)
        if not isinstance(old_id, str) or not old_id:
            raise MalformedNoteError(path, f"missing or non-string {id_field!r} in frontmatter")
        old_source_id = _owning_source_id(old_id, id_map)
        if old_source_id is None:
            raise MalformedNoteError(path, f"{id_field} {old_id!r} matches no known source_id")
        new_source_id = id_map[old_source_id]
        new_id = new_source_id + old_id[len(old_source_id) :]
        entries.append(
            NotePlan(
                src=path,
                dest=note_path(vault_dir, new_source_id, new_id),
                old_id=old_id,
                new_id=new_id,
            )
        )
    return entries


def build_plan(
    *,
    sources_dir: Path,
    data_dir: Path,
    vault_dir: Path,
    cases_dir: Path,
    analyses_dir: Path,
    pin_path: Path,
) -> MigrationPlan:
    """Compute the whole migration without writing anything. Verifies the
    renamed sources against the corpus pin first: a mapping built on hash
    suffixes is only as trustworthy as the claim that the bytes did not
    change, so that claim is checked before any plan is built."""
    verify_content_hashes(sources_dir, pin_path)
    id_map = build_id_map(sources_dir, data_dir)

    plan = MigrationPlan(id_map=id_map)
    plan.files = plan_derived_files(data_dir, id_map)
    for directory, pattern in ((cases_dir, "*.json"), (analyses_dir, "**/*.json")):
        if directory.is_dir():
            plan.files[str(directory)] = [
                FilePlan(src=path, dest=path) for path in sorted(directory.glob(pattern))
            ]

    for subdir, id_field, note_path in (
        ("prose", "chunk_id", chunk_note_path),
        ("artifacts", "artifact_id", artifact_note_path),
    ):
        if (vault_dir / subdir).is_dir():
            plan.notes[str(vault_dir / subdir)] = plan_notes(
                vault_dir, subdir, id_field, note_path, id_map
            )
    return plan


# ---------------------------------------------------------------- applying


def apply_file(entry: FilePlan, id_map: dict[str, str]) -> None:
    """Rename the file first, then rewrite its contents: the new name is
    much shorter than the old one, and several current paths sit within a
    few characters of Windows' MAX_PATH, so nothing may lengthen a path
    mid-flight."""
    path = entry.src
    if entry.dest != entry.src:
        if entry.dest.exists():
            raise DestinationExistsError(entry.src, entry.dest)
        path.rename(entry.dest)
        path = entry.dest
    text = path.read_text(encoding="utf-8")
    rewritten = substitute_ids_in_text(text, id_map)
    if rewritten != text:
        path.write_text(rewritten, encoding="utf-8")


def apply_note(entry: NotePlan, id_map: dict[str, str]) -> None:
    """Rewrite one note's frontmatter ids and place it at its new path. The
    new note is written before the old one is removed, so an interruption
    can duplicate a note but never lose one."""
    text = entry.src.read_text(encoding="utf-8")
    frontmatter, body = split_note(entry.src, text)
    rewritten = render_note(remap_ids(frontmatter, id_map), body)
    if entry.dest == entry.src:
        if rewritten != text:
            entry.src.write_text(rewritten, encoding="utf-8")
        return
    if entry.dest.exists():
        raise DestinationExistsError(entry.src, entry.dest)
    entry.dest.parent.mkdir(parents=True, exist_ok=True)
    entry.dest.write_text(rewritten, encoding="utf-8")
    entry.src.unlink()


def apply_plan(plan: MigrationPlan) -> None:
    for entries in plan.files.values():
        for entry in entries:
            apply_file(entry, plan.id_map)
    for note_entries in plan.notes.values():
        for note in note_entries:
            apply_note(note, plan.id_map)


# --------------------------------------------------------------- reporting


def format_plan(plan: MigrationPlan) -> str:
    lines = [f"source id mappings ({len(plan.id_map)}):"]
    unchanged = 0
    for old, new in plan.id_map.items():
        if old == new:
            unchanged += 1
            continue
        lines.append(f"  {old}")
        lines.append(f"    -> {new}")
    if unchanged:
        lines.append(f"  ({unchanged} id(s) already renamed, unchanged)")

    lines.append("")
    lines.append("files (rename + id rewrite):")
    for label, entries in plan.files.items():
        renamed = sum(1 for entry in entries if entry.dest != entry.src)
        lines.append(f"  {label}: {len(entries)} file(s), {renamed} renamed")

    lines.append("")
    lines.append("vault notes (rename + frontmatter id rewrite):")
    for label, note_entries in plan.notes.items():
        renamed = sum(1 for note in note_entries if note.dest != note.src)
        lines.append(f"  {label}: {len(note_entries)} note(s), {renamed} renamed")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources-dir",
        type=Path,
        default=default_sources_dir(),
        help="raw source files, already renamed to their new short names",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="derived corpus root")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes; default is dry-run (report only, nothing written)",
    )
    args = parser.parse_args(argv)

    try:
        plan = build_plan(
            sources_dir=args.sources_dir,
            data_dir=args.data_dir,
            vault_dir=default_vault_dir(),
            cases_dir=CASES_DIR,
            analyses_dir=ANALYSES_LOG_DIR,
            pin_path=PIN_PATH,
        )
    except RenameMigrationError as exc:
        # Source filenames carry diacritics, which crash a cp1252 stdout on
        # Windows -- the same failure PR #379 fixed for run_pass.
        _print_encoding_safe(f"REFUSING TO MIGRATE: {exc}")
        return 1

    _print_encoding_safe(format_plan(plan))
    if not args.apply:
        _print_encoding_safe("\ndry run: nothing written (rerun with --apply to write)")
        return 0

    apply_plan(plan)
    _print_encoding_safe("\napplied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
