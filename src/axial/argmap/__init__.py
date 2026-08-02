"""The argument map (issue #572): positions (this package) and, in later
PRs, relations, the door, the landing, and the corridor. See
`axial.argmap.build` for the position layer's build pipeline and
`specs/PHASE-B.md`'s argument-map section for the artifact contract."""

from axial.argmap.build import (
    BAG_DISTANCE_THRESHOLD,
    EXTRACT_SLICE,
    MERGE_DISTANCE_THRESHOLD,
    PASS_NAME,
    WORKERS,
    CorruptReadsLedgerError,
    ExtractJob,
    MapError,
    Passage,
    assign_position_ids,
    author_spread,
    bag_passages,
    build_jobs,
    compute_corpus_pin,
    extract_positions_for_slice,
    merge_positions,
    render_claims_blind,
    run_extraction,
    run_map_build,
    select_passages,
)

__all__ = [
    "BAG_DISTANCE_THRESHOLD",
    "EXTRACT_SLICE",
    "MERGE_DISTANCE_THRESHOLD",
    "PASS_NAME",
    "WORKERS",
    "CorruptReadsLedgerError",
    "ExtractJob",
    "MapError",
    "Passage",
    "assign_position_ids",
    "author_spread",
    "bag_passages",
    "build_jobs",
    "compute_corpus_pin",
    "extract_positions_for_slice",
    "merge_positions",
    "render_claims_blind",
    "run_extraction",
    "run_map_build",
    "select_passages",
]
