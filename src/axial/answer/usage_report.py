"""Cross-run source-usage aggregation (specs/PHASE-B.md §7.13, §8 P0-13,
issue #266): `axial brief usage` reads every analysis record already
written under `data/analyses/` and pools the per-run `source_usage` field
issue #265's `compute_source_usage` (`axial.answer.source_usage`) wrote
onto each one -- it never recomputes usage from the vault.

Two rules define what gets pooled (§7.13 "Design for the aggregate", the
slice-02 plan):

- **Corpus pin partitions the report.** Records are pooled only with
  records sharing the same `corpus_pin` (§7.12) -- runs on different pins
  are not comparable. Records on other pins are counted and named, never
  silently dropped. The pin defaults to whichever pin the most records
  share; `--pin` overrides it.
- **Keyed on `source_id`, joined on `names_queried`.** Per source, a pooled
  `usage_ratio` across every included record; per `(source_id, name query)`
  pair, a pooled `usage_ratio` across only the records whose
  `names_queried` contains that query. A record whose `usage_ratio` is
  `None` (available_share 0, §7.13) is excluded from the pool it would
  otherwise join -- the record count travelling with each pooled figure
  always reflects only the observations actually pooled.

  **The join moved from tag filters to names** (issue #491): `query_by_tag`
  and `query_by_polity` are struck with the facets they filtered (D1), so
  `filters_observed` could never carry a row again. The grouping rule is
  unchanged -- an entry's identity is still `(tool, sorted args)`, never
  args alone, because `get_name`, `name_neighbors`, `who_cites` and
  `who_argues_against` all take a canonical name under the same arg key and
  are different queries. This is what makes "a source that draws several
  times its available share whenever queries touch a given name" visible
  (P0-13).

Pooling is a plain arithmetic mean of the per-run `usage_ratio` values --
the simplest mechanism that makes the promotion-condition inspection
(§7.13) checkable; nothing here asserts a threshold on the result (P0-13:
"gates nothing").

Zero model calls: this module only reads JSON already on disk and does
arithmetic -- it never imports `axial.llm`, never touches the vault.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PooledSource:
    """One source's usage_ratio pooled across every included record."""

    source_id: str
    pooled_usage_ratio: float
    record_count: int


@dataclass(frozen=True)
class PooledSourceName:
    """One `(source_id, name query)` pair's usage_ratio, pooled across only
    the included records whose `names_queried` contains that query."""

    source_id: str
    name_label: str
    pooled_usage_ratio: float
    record_count: int


@dataclass(frozen=True)
class UsageReport:
    """The whole cross-run report: which pin it covers, how many records
    were included/excluded/unreadable, and the two pooled breakdowns."""

    pin_id: str | None
    included_record_count: int
    excluded_pin_counts: dict[str, int]
    unreadable_count: int
    sources: list[PooledSource]
    names: list[PooledSourceName]


def load_analysis_records(analyses_dir: Path) -> tuple[list[dict[str, Any]], int]:
    """Every parseable `<analyses_dir>/*.json` record, plus a count of files
    that failed to parse. A missing directory yields zero records rather
    than raising -- an empty/never-run `data/analyses/` is a normal state
    this report handles, not an error (P0-13's own empty-corpus scenario).
    A malformed record is counted and skipped, never a crash -- the report
    "gates nothing", including on its own inputs."""
    records: list[dict[str, Any]] = []
    unreadable = 0
    if not analyses_dir.is_dir():
        return records, unreadable
    for path in sorted(analyses_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            unreadable += 1
            continue
        if not isinstance(data, dict):
            unreadable += 1
            continue
        records.append(data)
    return records, unreadable


def _name_identity(entry: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...]]:
    """The exact identity a `names_queried` entry is grouped on:
    `(tool, sorted args items)` -- never args alone. Mirrors
    `axial.answer.source_usage.derive_names_queried`'s own dedup key, since
    the four name-layer traversals all take a canonical name under the same
    arg key and are different queries (§7.13)."""
    tool = entry.get("tool", "")
    args = entry.get("args") or {}
    return (tool, tuple(sorted((str(k), str(v)) for k, v in args.items())))


def _name_label(entry: dict[str, Any]) -> str:
    """A human-readable label for one name query, e.g.
    `get_name(canonical=Charles Tilly)`. The tool is part of the label
    because it is part of the identity: reaching a name through `who_cites`
    is a different query from reading its page."""
    tool = entry.get("tool", "")
    args = entry.get("args") or {}
    rendered = ",".join(f"{key}={value}" for key, value in sorted(args.items()))
    return f"{tool}({rendered})" if rendered else f"{tool}()"


def _select_pin(pin_counts: dict[str, int], requested: str | None) -> str | None:
    """The pin to report on: `requested` (`--pin`) if given, else whichever
    pin the most records share (§7.13 plan), ties broken alphabetically for
    determinism. `None` when there are no records at all."""
    if requested is not None:
        return requested
    if not pin_counts:
        return None
    return max(sorted(pin_counts), key=lambda pin: pin_counts[pin])


def build_usage_report(
    records: list[dict[str, Any]],
    *,
    pin: str | None = None,
    unreadable_count: int = 0,
) -> UsageReport:
    """Pool §7.13 `source_usage` across `records`, partitioned by
    `corpus_pin` (§7.12). Only records sharing the selected pin contribute
    to the two breakdowns; every other record is counted, by pin, and
    named in the report -- never silently dropped."""
    pin_counts: dict[str, int] = {}
    for record in records:
        pin_id = record.get("corpus_pin")
        if pin_id is None:
            continue
        pin_counts[pin_id] = pin_counts.get(pin_id, 0) + 1

    selected_pin = _select_pin(pin_counts, pin)
    if selected_pin is None:
        return UsageReport(
            pin_id=None,
            included_record_count=0,
            excluded_pin_counts={},
            unreadable_count=unreadable_count,
            sources=[],
            names=[],
        )

    included = [record for record in records if record.get("corpus_pin") == selected_pin]
    excluded_pin_counts = {p: c for p, c in pin_counts.items() if p != selected_pin}

    ratios_by_source: dict[str, list[float]] = {}
    ratios_by_source_name: dict[
        tuple[str, tuple[str, tuple[tuple[str, str], ...]]], list[float]
    ] = {}
    label_by_name_key: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}

    for record in included:
        source_usage = record.get("source_usage") or {}
        source_entries = source_usage.get("sources") or []
        names_queried = source_usage.get("names_queried") or []

        name_keys = []
        for entry in names_queried:
            key = _name_identity(entry)
            label_by_name_key[key] = _name_label(entry)
            name_keys.append(key)

        for source_entry in source_entries:
            ratio = source_entry.get("usage_ratio")
            if ratio is None:
                continue
            source_id = source_entry["source_id"]
            ratios_by_source.setdefault(source_id, []).append(ratio)
            for name_key in name_keys:
                ratios_by_source_name.setdefault((source_id, name_key), []).append(ratio)

    sources = [
        PooledSource(
            source_id=source_id,
            pooled_usage_ratio=sum(ratios) / len(ratios),
            record_count=len(ratios),
        )
        for source_id, ratios in ratios_by_source.items()
    ]
    sources.sort(key=lambda entry: (-entry.pooled_usage_ratio, entry.source_id))

    names = [
        PooledSourceName(
            source_id=source_id,
            name_label=label_by_name_key[name_key],
            pooled_usage_ratio=sum(ratios) / len(ratios),
            record_count=len(ratios),
        )
        for (source_id, name_key), ratios in ratios_by_source_name.items()
    ]
    names.sort(key=lambda entry: (-entry.pooled_usage_ratio, entry.source_id, entry.name_label))

    return UsageReport(
        pin_id=selected_pin,
        included_record_count=len(included),
        excluded_pin_counts=excluded_pin_counts,
        unreadable_count=unreadable_count,
        sources=sources,
        names=names,
    )


def format_usage_report(report: UsageReport) -> str:
    """Render `UsageReport` into a human-readable report. Format/wording is
    left to the implementer (mirroring `axial.chunk.format_examine_report`)
    -- only that every stated count/ratio is present and appears near its
    own label."""
    lines: list[str] = []

    if report.pin_id is None:
        lines.append("usage report: no analysis records to report on")
        if report.unreadable_count:
            lines.append(f"  {report.unreadable_count} record(s) were unreadable and excluded")
        return "\n".join(lines)

    lines.append(
        f"usage report: {report.included_record_count} record(s) on corpus_pin '{report.pin_id}'"
    )
    for other_pin in sorted(report.excluded_pin_counts):
        count = report.excluded_pin_counts[other_pin]
        lines.append(
            f"  excluded {count} record(s) on corpus_pin '{other_pin}' as not comparable (§7.12)"
        )
    if report.unreadable_count:
        lines.append(f"  excluded {report.unreadable_count} unreadable record(s)")

    lines.append("")
    lines.append("pooled usage_ratio by source (heaviest-weighing first):")
    if not report.sources:
        lines.append("  (no source rows)")
    for entry in report.sources:
        lines.append(
            f"  {entry.source_id}: usage_ratio={entry.pooled_usage_ratio:.2f} "
            f"over {entry.record_count} record(s)"
        )

    lines.append("")
    lines.append("pooled usage_ratio by source, per name query:")
    if not report.names:
        lines.append("  (no name rows)")
    for entry in report.names:
        lines.append(
            f"  {entry.source_id} @ {entry.name_label}: "
            f"usage_ratio={entry.pooled_usage_ratio:.2f} over {entry.record_count} record(s)"
        )

    return "\n".join(lines)
