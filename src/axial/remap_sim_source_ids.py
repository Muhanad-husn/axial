"""One-off migration: remap stale `source_id` values in the committed
simulated eval cases (`evals/cases/sim/*.json`) to the ids the *rebuilt*
corpus actually uses.

Background. `compute_source_id` (axial.envelope) is `f"{path.stem}-{hash[:12]}"`
-- the raw filename stem plus a 12-char content hash, with no normalisation of
the stem. The dev corpus was deleted and is being rebuilt from the same
source bytes, so content hashes are unchanged, but the files were re-added
under their raw download filenames instead of the tidy stems the original
corpus used. Every `source_id` in `evals/cases/sim/*.json`'s
`required_citation_source_ids` therefore carries a stale stem while the
12-char hash suffix still identifies the right source.

This script builds a `hash-suffix -> current source_id` map by scanning a
raw-sources directory with the exact same `compute_source_id` primitive the
pipeline uses, then rewrites each case file's citation ids in place --
matching purely on the hash suffix, never the stem. Ids are read from
wherever a case states them: the flat `required_citation_source_ids` list,
and (issue #560) every `required_citation_legs[].any_of` entry. A case can
state either, both, or -- once re-authored -- only the leg form; either way
every id the file names gets remapped.

Deliberately excludes `evals/corpus_pin/*.json`: a corpus pin is a
point-in-time snapshot of a corpus that no longer exists (different chunk
ids, freshly generated tags once the rebuild finishes); rewriting its ids
would produce a pin describing a corpus that never existed. The pin is
retired as history; a fresh one is generated from the rebuilt corpus with
`axial pin write <name>` (issue #248, `axial.eval.corpus_pin`) once the
rebuild is done.

Not a product feature -- no `axial` subcommand, no permanent home. One-off,
to be deleted once the real remap has been run against the rebuilt corpus
(see docs/sim-academic/merge_gold_labels.py for the same precedent: a small
standalone script under version control for exactly as long as it's needed).

Usage (dry run by default; nothing is written without --apply):
    python -m axial.remap_sim_source_ids --sources-dir data/sources
    python -m axial.remap_sim_source_ids --sources-dir data/sources --apply
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from axial.cli import _print_encoding_safe
from axial.envelope import compute_source_id
from axial.intake import SUPPORTED_EXTENSIONS

CASES_DIR = Path("evals") / "cases" / "sim"

# `compute_source_id`'s own shape is `{stem}-{12 hex digits}`, anchored at
# the end so a stem that itself contains hyphens (routine in this corpus,
# e.g. "tilly-from-mobilization-to-revolution") is never mistaken for the
# hash.
_HASH_SUFFIX = re.compile(r"-([0-9a-f]{12})$")


def build_hash_map(sources_dir: Path) -> dict[str, str]:
    """Scan `sources_dir` for raw source files and return `{hash_suffix:
    current_source_id}`, computed with the same `compute_source_id`
    primitive the pipeline itself uses. Reads raw source files directly
    (never envelopes) -- a partially rebuilt corpus lands its raw files
    before the envelope pass has necessarily reached every one of them."""
    mapping: dict[str, str] = {}
    for path in sorted(sources_dir.iterdir()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        source_id = compute_source_id(path)
        mapping[source_id[-12:]] = source_id
    return mapping


def _hash_suffix(source_id: str) -> str | None:
    match = _HASH_SUFFIX.search(source_id)
    return match.group(1) if match else None


@dataclass
class FileReport:
    """One case file's migration plan: which old ids map to which new ids
    (only entries that actually change), and which old ids' hash suffix
    wasn't found anywhere in the scanned corpus at all."""

    path: Path
    remapped: dict[str, str] = field(default_factory=dict)
    unmapped: list[str] = field(default_factory=list)


def _all_ids(payload: dict) -> list[str]:
    """Every source id a case states, whether in the flat
    `required_citation_source_ids` list or nested inside a
    `required_citation_legs[].any_of` (issue #560). Duplicates across the
    two forms are harmless -- `plan_file` just maps each occurrence, and
    `apply_file`'s text substitution rewrites every occurrence regardless of
    how many times an id is named."""
    ids: list[str] = list(payload.get("required_citation_source_ids") or [])
    for leg in payload.get("required_citation_legs") or []:
        if isinstance(leg, dict):
            ids.extend(leg.get("any_of") or [])
    return ids


def plan_file(path: Path, hash_map: dict[str, str]) -> FileReport:
    """Compute a `FileReport` for one case file without writing anything."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    ids = _all_ids(payload)
    report = FileReport(path=path)
    for old_id in ids:
        suffix = _hash_suffix(old_id)
        new_id = hash_map.get(suffix) if suffix else None
        if new_id is None:
            report.unmapped.append(old_id)
        elif new_id != old_id:
            report.remapped[old_id] = new_id
    return report


def apply_file(report: FileReport) -> bool:
    """Rewrite `report.path` in place, substituting each remapped id's exact
    quoted JSON-string form. Everything else in the file -- key order,
    indentation, line endings -- is left untouched, since this never
    re-serializes the JSON; it only substitutes the changed string literals
    in the original text. Returns whether the file's bytes actually
    changed."""
    if not report.remapped:
        return False
    text = report.path.read_text(encoding="utf-8")
    new_text = text
    for old_id, new_id in report.remapped.items():
        new_text = new_text.replace(json.dumps(old_id), json.dumps(new_id))
    if new_text == text:
        return False
    report.path.write_text(new_text, encoding="utf-8")
    return True


def migrate(cases_dir: Path, sources_dir: Path, apply: bool) -> list[FileReport]:
    """Plan (and, under `apply=True`, write) the remap for every
    `<cases_dir>/*.json` case file. Idempotent: a case file whose ids
    already match the current corpus produces an empty `remapped` dict and
    is never written."""
    hash_map = build_hash_map(sources_dir)
    reports = []
    for path in sorted(cases_dir.glob("*.json")):
        report = plan_file(path, hash_map)
        reports.append(report)
        if apply:
            apply_file(report)
    return reports


def format_report(reports: list[FileReport]) -> str:
    """Render a full `migrate` outcome: what changed (or would change), and
    a loud warning block for every id whose hash suffix has no match in the
    scanned corpus -- never silently dropped or left unmentioned."""
    lines: list[str] = []
    changed = [r for r in reports if r.remapped]
    unmapped_total = [(r.path, old_id) for r in reports for old_id in r.unmapped]

    if changed:
        for r in changed:
            lines.append(f"{r.path}: {len(r.remapped)} id(s) remapped")
            for old_id, new_id in r.remapped.items():
                lines.append(f"  {old_id} -> {new_id}")
    else:
        lines.append("no ids to remap (already up to date)")

    if unmapped_total:
        lines.append("")
        lines.append(
            f"WARNING: {len(unmapped_total)} id(s) have no match in the scanned corpus "
            "(source not yet rebuilt, or genuinely gone):"
        )
        for path, old_id in unmapped_total:
            lines.append(f"  {path}: {old_id}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources-dir",
        type=Path,
        required=True,
        help="raw source files directory to scan for current source_ids (e.g. data/sources)",
    )
    parser.add_argument(
        "--cases-dir",
        type=Path,
        default=CASES_DIR,
        help="directory of sim case JSON files to remap (default: evals/cases/sim)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write changes; default is dry-run (report only, nothing written)",
    )
    args = parser.parse_args(argv)

    reports = migrate(args.cases_dir, args.sources_dir, args.apply)
    # Source filenames carry diacritics ("Uğur Ümit Üngör"), which crash a
    # cp1252 stdout on Windows -- same failure PR #379 fixed for run_pass.
    _print_encoding_safe(format_report(reports))
    if not args.apply:
        _print_encoding_safe("\ndry run: no files written (rerun with --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
