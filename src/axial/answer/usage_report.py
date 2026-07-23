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
- **Keyed on `source_id`, joined on `filters_observed`.** Per source, a
  pooled `usage_ratio` across every included record; per
  `(source_id, tag_filter)` pair, a pooled `usage_ratio` across only the
  records whose `filters_observed` contains that filter. A record whose
  `usage_ratio` is `None` (available_share 0, §7.13) is excluded from the
  pool it would otherwise join -- the record count travelling with each
  pooled figure always reflects only the observations actually pooled.

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
class PooledSourceFilter:
    """One `(source_id, tag_filter)` pair's usage_ratio, pooled across only
    the included records whose `filters_observed` contains that filter."""

    source_id: str
    filter_label: str
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
    filters: list[PooledSourceFilter]


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


def _filter_identity(entry: dict[str, Any]) -> tuple[str, tuple[tuple[str, str], ...]]:
    """The exact identity a `filters_observed` entry is grouped on:
    `(tool, sorted args items)` -- never args alone. Mirrors
    `axial.answer.source_usage.derive_filters_observed`'s own dedup key,
    since `query_by_tag`'s `polity` filter and `query_by_polity`'s `polity`
    arg share a key name but are different queries (§7.13)."""
    tool = entry.get("tool", "")
    args = entry.get("args") or {}
    return (tool, tuple(sorted(args.items())))


def _filter_label(entry: dict[str, Any]) -> str:
    """A human-readable label for one observed filter, e.g.
    `theory_school:world-systems`. `query_by_polity`'s `polity` arg is
    relabeled `polities_touched` in display only, so it never reads as
    `query_by_tag`'s own, differently-scoped `polity` filter (§7.13) --
    grouping itself uses `_filter_identity`, not this label."""
    tool = entry.get("tool", "")
    args = entry.get("args") or {}
    parts = []
    for key, value in sorted(args.items()):
        display_key = "polities_touched" if (tool == "query_by_polity" and key == "polity") else key
        parts.append(f"{display_key}:{value}")
    return ",".join(parts) if parts else "(no filter)"


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
            filters=[],
        )

    included = [record for record in records if record.get("corpus_pin") == selected_pin]
    excluded_pin_counts = {p: c for p, c in pin_counts.items() if p != selected_pin}

    ratios_by_source: dict[str, list[float]] = {}
    ratios_by_source_filter: dict[
        tuple[str, tuple[str, tuple[tuple[str, str], ...]]], list[float]
    ] = {}
    label_by_filter_key: dict[tuple[str, tuple[tuple[str, str], ...]], str] = {}

    for record in included:
        source_usage = record.get("source_usage") or {}
        source_entries = source_usage.get("sources") or []
        filters_observed = source_usage.get("filters_observed") or []

        filter_keys = []
        for entry in filters_observed:
            key = _filter_identity(entry)
            label_by_filter_key[key] = _filter_label(entry)
            filter_keys.append(key)

        for source_entry in source_entries:
            ratio = source_entry.get("usage_ratio")
            if ratio is None:
                continue
            source_id = source_entry["source_id"]
            ratios_by_source.setdefault(source_id, []).append(ratio)
            for filter_key in filter_keys:
                ratios_by_source_filter.setdefault((source_id, filter_key), []).append(ratio)

    sources = [
        PooledSource(
            source_id=source_id,
            pooled_usage_ratio=sum(ratios) / len(ratios),
            record_count=len(ratios),
        )
        for source_id, ratios in ratios_by_source.items()
    ]
    sources.sort(key=lambda entry: (-entry.pooled_usage_ratio, entry.source_id))

    filters = [
        PooledSourceFilter(
            source_id=source_id,
            filter_label=label_by_filter_key[filter_key],
            pooled_usage_ratio=sum(ratios) / len(ratios),
            record_count=len(ratios),
        )
        for (source_id, filter_key), ratios in ratios_by_source_filter.items()
    ]
    filters.sort(key=lambda entry: (-entry.pooled_usage_ratio, entry.source_id, entry.filter_label))

    return UsageReport(
        pin_id=selected_pin,
        included_record_count=len(included),
        excluded_pin_counts=excluded_pin_counts,
        unreadable_count=unreadable_count,
        sources=sources,
        filters=filters,
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
    lines.append("pooled usage_ratio by source, per observed tag filter:")
    if not report.filters:
        lines.append("  (no filter rows)")
    for entry in report.filters:
        lines.append(
            f"  {entry.source_id} @ {entry.filter_label}: "
            f"usage_ratio={entry.pooled_usage_ratio:.2f} over {entry.record_count} record(s)"
        )

    return "\n".join(lines)
