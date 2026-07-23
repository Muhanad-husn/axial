"""Stage 6: the analysis record, `axial brief run`, and persistence
(specs/PHASE-B.md §5 stage 6, §7.3, §8 P0-8/P0-9). Issue #257 lands
`run_brief` -- the whole-engine orchestrator behind `axial brief run` -- and
`build_record`/`persist_record`, the record spine. Issue #265 adds
`compute_source_usage` (§7.13), wired into `build_record` itself. Issue #266
adds `axial.answer.usage_report`, the cross-run aggregation `axial brief
usage` is built on. Markdown rendering (§7.10) is a separate, later slice.
"""

from __future__ import annotations

from axial.answer.record import (
    AnswerError,
    BriefRunResult,
    MissingVaultSchemaVersionError,
    build_record,
    persist_record,
    run_brief,
    vault_schema_version,
)
from axial.answer.source_usage import compute_source_usage, derive_filters_observed
from axial.answer.usage_report import (
    UsageReport,
    build_usage_report,
    format_usage_report,
    load_analysis_records,
)

__all__ = [
    "AnswerError",
    "BriefRunResult",
    "MissingVaultSchemaVersionError",
    "UsageReport",
    "build_record",
    "build_usage_report",
    "compute_source_usage",
    "derive_filters_observed",
    "format_usage_report",
    "load_analysis_records",
    "persist_record",
    "run_brief",
    "vault_schema_version",
]
