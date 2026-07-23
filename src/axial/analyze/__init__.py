"""Stage-4 pre-pass: evidence assembly + inspect-before-spend (specs/PHASE-B.md
§5 stage 4, §7.5, §7.7). Issue #255 slice 01 lands `assemble_evidence`
(`axial.analyze.assembly`) and `run_examine` (`axial.analyze.examine`), the
library entry points behind `axial brief examine`. The stage-4 synthesis
call and claim graph (§7.4) are out of this slice's scope -- slice 02,
issue #256.
"""

from __future__ import annotations

from axial.analyze.assembly import EvidenceChunk, EvidenceSet, PolityCoverage, assemble_evidence
from axial.analyze.examine import ExamineResult, format_examine_report, run_examine

__all__ = [
    "EvidenceChunk",
    "EvidenceSet",
    "ExamineResult",
    "PolityCoverage",
    "assemble_evidence",
    "format_examine_report",
    "run_examine",
]
