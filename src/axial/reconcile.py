"""Reconcile: safe garbage-collection for orphaned derived artifacts (issue
#291, plans/reconcile/01-orphan-gc.md, walking skeleton).

`source_id` is a content hash (`axial.envelope.compute_source_id`, `<stem>-
<sha12>`), so renaming or re-saving a source file mints a fresh id and
strands every derived artifact the OLD id produced -- its tree, envelope,
chunks, tags, artifacts, xref records, and vault notes all keep living on
disk under the dead id. Nothing else in this codebase cleans that up.

`axial reconcile gc` builds the **live** keep-set by running
`compute_source_id()` over every file in `data/sources/`, scans the seven
derived surfaces through the SAME path seam each producer already uses
(`_default_chunks_dir` and siblings), and attributes every file it finds to
a source_id. A file whose id is not in the keep set is an orphan. Dry run
(no flags) is the default and removes nothing; `--apply` shows the same
list, asks for confirmation (or auto-confirms under `--yes`), and only then
removes the orphans and writes a paths/ids-only removal log under
`data/logs/reconcile/` (DEC-23: never source text). A file that cannot be
confidently attributed (the vault-note wrinkle -- a note is named by
`chunk_id`/`artifact_id`, not `source_id`) is reported *unattributed* and
left in place -- when in doubt, keep.

Six of the seven derived surfaces are named directly by source_id
(`<source_id>.json`/`.jsonl`); the seventh, the vault, is named by
`chunk_id`/`artifact_id`. A vault note is attributed by its frontmatter
`source_id` when present and readable; failing that, by the longest
already-known source_id that prefixes its filename (every `chunk_id`/
`artifact_id` carries its source_id as a leading `<source_id>_...`
component). A note whose frontmatter cannot be parsed at all, or whose
filename matches no known id, is unattributed -- never guessed, never
removed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from axial.artifacts import _default_artifacts_dir
from axial.chunk import _default_chunks_dir
from axial.envelope import _default_envelopes_dir, compute_source_id
from axial.extract import TREES_DIR
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_vault_dir
from axial.query.reader import MalformedNoteError, _read_frontmatter
from axial.tag import _default_tags_dir
from axial.xref import _default_xref_dir

SOURCES_DIR = Path("data/sources")
RECONCILE_LOG_DIR = Path("data/logs/reconcile")

# A source_id is always `<stem>-<12 lowercase hex chars>`
# (`axial.envelope.compute_source_id`). A derived-dir filename whose stem
# doesn't end this way is not source-scoped at all -- e.g.
# `data/tags/theory_school_candidates.jsonl` -- and is never attributed to
# a source, orphan or otherwise (never even reported).
_SOURCE_ID_RE = re.compile(r".+-[0-9a-f]{12}$")

# The chunk pass's skip-sidecar suffix (`axial.chunk.chunks_skips_sidecar_
# path`, `<source_id>.skips.jsonl`): stripped so the sidecar attributes to
# the SAME source_id as its main `<source_id>.jsonl`, never a distinct one.
_CHUNK_SKIPS_SUFFIX = ".skips"


class ReconcileError(Exception):
    """Base class for all reconcile errors."""


@dataclass(frozen=True)
class DerivedDirs:
    """The derived-dir surfaces reconcile scans -- an explicit constant,
    one field per surface, not a plugin registry (over-engineering
    tripwire named in the slice plan). `data/source_meta/` (issue #285)
    becomes an eighth surface once it lands; add its field and scan row
    then, not now."""

    trees: Path
    envelopes: Path
    chunks: Path
    tags: Path
    artifacts: Path
    xref: Path
    vault: Path


def default_derived_dirs(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> DerivedDirs:
    """Resolve every derived dir through the exact seam its own producer
    uses, so the scan honors `config/pipeline.yaml` wherever the producer
    does and stays plain-cwd-relative wherever it doesn't. `trees` has no
    config override anywhere in this codebase today (`axial.extract`
    exposes only the bare `TREES_DIR` constant) -- mirrored here as-is,
    not invented for this slice."""
    return DerivedDirs(
        trees=TREES_DIR,
        envelopes=_default_envelopes_dir(config_path),
        chunks=_default_chunks_dir(config_path),
        tags=_default_tags_dir(config_path),
        artifacts=_default_artifacts_dir(config_path),
        xref=_default_xref_dir(config_path),
        vault=default_vault_dir(config_path),
    )


def live_source_ids(sources_dir: Path = SOURCES_DIR) -> set[str]:
    """The live keep-set: `compute_source_id()` for every file directly
    under `sources_dir` (never recursing). Empty when the dir is absent or
    holds no files -- `data/sources/` is read-only to this tool either
    way, never scanned for removal."""
    if not sources_dir.is_dir():
        return set()
    return {compute_source_id(path) for path in sources_dir.iterdir() if path.is_file()}


def _flat_dir_source_id(path: Path) -> str | None:
    """The source_id one of the six directly-source_id-named derived-dir
    files attributes to: its filename stem, with a chunk-pass `.skips`
    sidecar suffix stripped first. `None` for a non-source-scoped file
    sharing the dir (e.g. `theory_school_candidates.jsonl`)."""
    stem = path.stem
    if stem.endswith(_CHUNK_SKIPS_SUFFIX):
        stem = stem[: -len(_CHUNK_SKIPS_SUFFIX)]
    return stem if _SOURCE_ID_RE.fullmatch(stem) else None


def _iter_flat_dir_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file())


def _iter_vault_notes(vault_dir: Path) -> list[Path]:
    notes: list[Path] = []
    for sub in ("prose", "artifacts"):
        subdir = vault_dir / sub
        if not subdir.is_dir():
            continue
        notes.extend(sorted(path for path in subdir.iterdir() if path.suffix == ".md"))
    return notes


def attribute_vault_note(path: Path, known_ids: set[str]) -> str | None:
    """Attribute one vault note to a source_id (the slice's one load-
    bearing decision): its frontmatter `source_id` when the note parses
    and carries one; otherwise the longest `known_ids` entry that prefixes
    the filename stem (every `chunk_id`/`artifact_id` carries its
    source_id as a leading `<source_id>_...` component). Returns `None` --
    unattributed -- when the frontmatter can't be parsed at all, or no
    known id prefixes the filename: never guessed, never removed."""
    try:
        frontmatter, _body = _read_frontmatter(path)
    except MalformedNoteError:
        return None

    source_id = frontmatter.get("source_id")
    if isinstance(source_id, str) and source_id.strip():
        return source_id.strip()

    stem = path.stem
    candidates = [sid for sid in known_ids if stem == sid or stem.startswith(sid + "_")]
    if not candidates:
        return None
    return max(candidates, key=len)


@dataclass(frozen=True)
class ScanResult:
    """One reconcile scan's outcome: the live keep-set, orphaned files
    grouped by their (dead) source_id, and vault notes that could not be
    confidently attributed to any source_id (reported, never removed)."""

    keep_set: set[str]
    orphans: dict[str, list[Path]]
    unattributed: list[Path]

    @property
    def orphan_count(self) -> int:
        return sum(len(paths) for paths in self.orphans.values())


def scan_orphans(
    sources_dir: Path = SOURCES_DIR,
    dirs: DerivedDirs | None = None,
) -> ScanResult:
    """The reconcile spine's read-only half: live-id set -> derived-dir
    scan -> attribute -> orphan diff. Never mutates anything on disk."""
    if dirs is None:
        dirs = default_derived_dirs()

    keep_set = live_source_ids(sources_dir)

    flat_dirs = (dirs.trees, dirs.envelopes, dirs.chunks, dirs.tags, dirs.artifacts, dirs.xref)
    known_ids = set(keep_set)
    flat_files: list[tuple[Path, str]] = []
    for directory in flat_dirs:
        for path in _iter_flat_dir_files(directory):
            source_id = _flat_dir_source_id(path)
            if source_id is None:
                continue
            known_ids.add(source_id)
            flat_files.append((path, source_id))

    orphans: dict[str, list[Path]] = {}
    unattributed: list[Path] = []

    for path, source_id in flat_files:
        if source_id not in keep_set:
            orphans.setdefault(source_id, []).append(path)

    for path in _iter_vault_notes(dirs.vault):
        source_id = attribute_vault_note(path, known_ids)
        if source_id is None:
            unattributed.append(path)
        elif source_id not in keep_set:
            orphans.setdefault(source_id, []).append(path)

    return ScanResult(keep_set=keep_set, orphans=orphans, unattributed=unattributed)


def format_scan_report(result: ScanResult) -> str:
    """Render a scan for the operator: orphans grouped by source_id, paths
    only (DEC-23), plus any unattributed vault notes left in place."""
    lines: list[str] = []
    if not result.orphans:
        lines.append("reconcile gc: no orphaned derived artifacts found")
    else:
        lines.append(
            f"reconcile gc: {result.orphan_count} orphaned file(s) "
            f"across {len(result.orphans)} source_id(s)"
        )
        for source_id in sorted(result.orphans):
            lines.append(f"orphaned source_id: {source_id}")
            for path in sorted(result.orphans[source_id]):
                lines.append(f"  {path}")

    if result.unattributed:
        lines.append(f"unattributed, left in place ({len(result.unattributed)}):")
        for path in sorted(result.unattributed):
            lines.append(f"  {path}")

    return "\n".join(lines)


def _default_confirm(prompt: str) -> bool:
    """The real, interactive confirm: never exercised by the outer CLI
    acceptance test (which always passes `--yes`) -- only reachable from a
    real `--apply` run with no `--yes`."""
    answer = input(f"{prompt}\nremove these orphans? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


def write_removal_log(
    result: ScanResult,
    log_dir: Path = RECONCILE_LOG_DIR,
    when: datetime | None = None,
) -> Path:
    """Write the removal log BEFORE anything is removed (DEC-19): one
    JSONL file per run under `log_dir`, a run-header record carrying the
    keep-set followed by one record per removed path and its orphaned
    source_id. Paths and source_ids only -- no source text (DEC-23)."""
    if when is None:
        when = datetime.now(timezone.utc)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{when.strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    with log_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "run", "keep_set": sorted(result.keep_set)}) + "\n")
        for source_id in sorted(result.orphans):
            for path in sorted(result.orphans[source_id]):
                handle.write(
                    json.dumps({"type": "removed", "path": str(path), "source_id": source_id})
                    + "\n"
                )
    return log_path


def remove_orphans(
    result: ScanResult, log_dir: Path = RECONCILE_LOG_DIR
) -> tuple[list[Path], Path]:
    """Write the removal log, then remove every orphaned path in `result`.
    Never called on an empty orphan set (`run_gc` checks first), so a
    no-orphan run never writes a log at all."""
    log_path = write_removal_log(result, log_dir=log_dir)
    removed: list[Path] = []
    for source_id in sorted(result.orphans):
        for path in sorted(result.orphans[source_id]):
            path.unlink(missing_ok=True)
            removed.append(path)
    return removed, log_path


@dataclass(frozen=True)
class GcResult:
    """`run_gc`'s outcome: the underlying scan, whether removal actually
    ran, whether the operator declined, and (only when it ran) the
    removed paths and the log path."""

    scan: ScanResult
    applied: bool
    aborted: bool
    removed: list[Path]
    log_path: Path | None


def run_gc(
    *,
    apply: bool = False,
    yes: bool = False,
    confirm: Callable[[str], bool] | None = None,
    sources_dir: Path = SOURCES_DIR,
    dirs: DerivedDirs | None = None,
    log_dir: Path = RECONCILE_LOG_DIR,
) -> GcResult:
    """The whole reconcile spine: live-id set -> derived-dir scan ->
    attribute -> orphan diff -> dry-run list -> consent -> remove + log.

    Dry run (`apply=False`, the default) never removes anything. Under
    `apply=True` with an empty orphan set this is a no-op: no confirm
    call, no log write. Otherwise, `yes=True` auto-confirms (the CLI's
    `--yes`, and the only consent path the outer acceptance test ever
    drives); `yes=False` calls `confirm` (defaulting to a real interactive
    prompt) with the rendered scan report, and declining removes nothing.
    """
    scan = scan_orphans(sources_dir=sources_dir, dirs=dirs)

    if not apply or not scan.orphans:
        return GcResult(scan=scan, applied=False, aborted=False, removed=[], log_path=None)

    if not yes:
        confirm_fn = confirm or _default_confirm
        if not confirm_fn(format_scan_report(scan)):
            return GcResult(scan=scan, applied=False, aborted=True, removed=[], log_path=None)

    removed, log_path = remove_orphans(scan, log_dir=log_dir)
    return GcResult(scan=scan, applied=True, aborted=False, removed=removed, log_path=log_path)


def format_gc_report(result: GcResult) -> str:
    """Render a full `run_gc` outcome for the CLI: the scan listing plus
    what happened to it (nothing, on a dry run; removed + logged; or
    aborted on operator decline)."""
    lines = [format_scan_report(result.scan)]
    if not result.scan.orphans:
        return "\n".join(lines)

    if result.aborted:
        lines.append("aborted: nothing removed")
    elif result.applied:
        lines.append(
            f"removed {len(result.removed)} orphaned file(s); log written to {result.log_path}"
        )
    else:
        lines.append("dry run: nothing removed (rerun with --apply to remove)")
    return "\n".join(lines)
