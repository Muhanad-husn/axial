"""Stage 6: the analysis record, `axial brief run`, and persistence
(specs/PHASE-B.md §5 stage 6, §7.3, §8 P0-8/P0-9). Issue #257 lands
`run_brief` -- the whole-engine orchestrator behind `axial brief run` -- and
`build_record`/`persist_record`, the record spine. Markdown rendering
(§7.10) and the source-usage disclosure (§7.13) are separate, later slices.
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

__all__ = [
    "AnswerError",
    "BriefRunResult",
    "MissingVaultSchemaVersionError",
    "build_record",
    "persist_record",
    "run_brief",
    "vault_schema_version",
]
