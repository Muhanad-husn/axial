"""Stage 6: the analysis record, `axial brief run`, and persistence
(specs/PHASE-B.md §5 stage 6, §7.3, §8 P0-8/P0-9). Issue #257 lands
`run_brief` -- the whole-engine orchestrator behind `axial brief run` -- and
`build_record`/`persist_record`, the record spine. Issue #265 adds
`compute_source_usage` (§7.13), wired into `build_record` itself; issue #491
re-bases its denominator onto the names a run queried (`derive_names_queried`
replaces the struck `derive_filters_observed`). Issue #266 adds
`axial.answer.usage_report`, the cross-run aggregation `axial brief usage` is
built on. Issue #261 adds `axial.answer.render.render_markdown` (§7.10) and
`persist_markdown`, wired into `run_brief` alongside `persist_record`. Issue
#491 adds `axial.answer.run_report` (§7.15), written alongside them.
"""

from __future__ import annotations

from axial.answer.record import (
    AnswerError,
    BriefRunResult,
    build_record,
    persist_markdown,
    persist_record,
    run_brief,
)
from axial.answer.render import render_markdown
from axial.answer.run_report import (
    PassClock,
    build_run_report,
    format_run_report,
    persist_run_report,
)
from axial.answer.source_usage import compute_source_usage, derive_names_queried
from axial.answer.usage_report import (
    UsageReport,
    build_usage_report,
    format_usage_report,
    load_analysis_records,
)

__all__ = [
    "AnswerError",
    "BriefRunResult",
    "PassClock",
    "UsageReport",
    "build_record",
    "build_run_report",
    "build_usage_report",
    "compute_source_usage",
    "derive_names_queried",
    "format_run_report",
    "format_usage_report",
    "load_analysis_records",
    "persist_markdown",
    "persist_record",
    "persist_run_report",
    "render_markdown",
    "run_brief",
]
