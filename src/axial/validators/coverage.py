"""Stage-5 coverage/confidence validator (specs/PHASE-B.md §7.7, §7.9, §5
stage 5, issue #260).

Two independent, model-free pieces live here, mirroring the split the
plan draws between "computed deterministically" content and the release
gate that reads it (plans/analysis-validators/03-coverage-and-confidence.md):

1. **`compute_coverage_map`** -- the §7.7 computation itself: for every
   polity a claim graph touches, `{corpus_chunk_count, evidence_chunk_count,
   coverage_band}`, built from `axial.query.reader.coverage_count` (the
   whole-vault denominator) and this run's own claim grounds (the
   numerator). Never asked of a model. Exposed to the founder through the
   `axial brief coverage <brief_id>` inspection affordance so the
   `coverage_bands` config cut points can be proven against the real corpus
   before they gate anything (mirrors `axial chunk examine` proving the
   Phase-A chunk band, PRODUCT.md §7.7).

2. **`validate_coverage_and_confidence`** -- the release gate (§7.9): a
   PURE presence/coherence check over a persisted §7.3 record's OWN
   `coverage_map` and `confidence` fields, exactly as `validate_attribution`
   checks a record's own `claims[].kind`/`grounds` -- it never recomputes or
   repairs the record, only reports pass/fail with reasons. It blocks
   release on any of:
   - a polity a claim touches has no entry in `record["coverage_map"]`
     (`missing_coverage_entry`);
   - `confidence` is absent, or its `overall_band` is null/blank, or its
     `rationale` is empty (`missing_confidence_disclosure`);
   - `confidence.overall_band` is the top band (`high`) while
     `coverage_map` contains a `thin` polity -- an unjustified confidence
     disclosure (`confidence_exceeds_coverage`).

Takes no `LLMClient` at all: nothing here can make a model call, so the
`explode` provider installed in tests never fires by construction, not by
a check that happens not to trip it.

Out of scope for this slice (plans/analysis-validators/03-coverage-and-
confidence.md, README.md): the calibration metric (§10, rung3-gates slice
02), settling the confidence vocabulary (§7.4 Open Questions -- this module
reads whatever `overall_band` the record carries), per-claim confidence
scoring, and tuning the band cut points against the real corpus (the
inspection affordance makes that provable; the proving pass itself is
founder-run operational work).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.reader import ChunkNotFoundError, coverage_count, get_chunk

# The §7.4 three-band confidence vocabulary's top band -- the one a
# `thin` polity in the coverage map may never be disclosed alongside.
TOP_CONFIDENCE_BAND = "high"

# The §7.7 band vocabulary's bottom band -- the one that triggers the
# confidence-vs-coverage check.
THIN_COVERAGE_BAND = "thin"

# The coverage_bands config block's code-level fallback (issue #260): a
# stated starting hypothesis over a ~17k-chunk vault, in the spirit of the
# Phase-A chunk band (PRODUCT.md §7.7) -- used only when
# `config/pipeline.yaml` (or its `coverage_bands` key) is absent, mirroring
# `axial.retrieve.loop.DEFAULT_STEP_BUDGET`'s own fallback convention.
# `thin` is below `moderate_floor`, `moderate` is [moderate_floor,
# dense_floor), `dense` is `dense_floor` and above. Tuning these against the
# real corpus is explicitly out of this slice's scope -- see the module
# docstring.
DEFAULT_MODERATE_FLOOR = 20
DEFAULT_DENSE_FLOOR = 100

# The closed reason vocabulary this validator ever reports.
REASON_MISSING_COVERAGE_ENTRY = "missing_coverage_entry"
REASON_MISSING_CONFIDENCE_DISCLOSURE = "missing_confidence_disclosure"
REASON_CONFIDENCE_EXCEEDS_COVERAGE = "confidence_exceeds_coverage"


def _resolve_coverage_bands(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> tuple[int, int]:
    """Read `coverage_bands.{moderate_floor,dense_floor}` from
    `config/pipeline.yaml`, falling back to the module defaults when the
    file or either key is absent -- a config change, never a code change,
    tunes the cut points (plan inner-loop: "Overriding coverage_bands in
    config changes the band with no code change")."""
    if not config_path.is_file():
        return DEFAULT_MODERATE_FLOOR, DEFAULT_DENSE_FLOOR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    bands_config = document.get("coverage_bands") or {}
    moderate_floor = int(bands_config.get("moderate_floor", DEFAULT_MODERATE_FLOOR))
    dense_floor = int(bands_config.get("dense_floor", DEFAULT_DENSE_FLOOR))
    return moderate_floor, dense_floor


def coverage_band_for(corpus_chunk_count: int, *, moderate_floor: int, dense_floor: int) -> str:
    """The §7.7 band derivation, pure and total: `dense` at or above
    `dense_floor`, `moderate` at or above `moderate_floor`, `thin`
    otherwise. The cut points are always read from config (or its
    fallback), never hardcoded at a call site."""
    if corpus_chunk_count >= dense_floor:
        return "dense"
    if corpus_chunk_count >= moderate_floor:
        return "moderate"
    return "thin"


def _touched_polities(claims: list[dict[str, Any]]) -> list[str]:
    """The polity set a claim graph touches (§7.7 "for every polity the
    record's claims touch"): the union of every claim's own
    `polities_touched` (§7.4 -- already the union of that claim's grounds
    chunks' own `polities_touched`, so this is a fold over claims, not a
    re-derivation from grounds). Sorted for the same explicit-sort
    determinism contract every other §7.5 tool follows."""
    polities: set[str] = set()
    for claim in claims:
        for polity in claim.get("polities_touched") or []:
            if isinstance(polity, str) and polity:
                polities.add(polity)
    return sorted(polities)


def _collect_grounds_chunk_ids(claims: list[dict[str, Any]]) -> set[str]:
    """Every distinct `chunk` grounds ref_id across every claim -- an
    artifact grounds pointer never contributes (`ArtifactNote` carries no
    `polities_touched`), and the same chunk cited by two claims is one
    entry, matching the plan's own dedup rule."""
    chunk_ids: set[str] = set()
    for claim in claims:
        for ground in claim.get("grounds") or []:
            if isinstance(ground, dict) and ground.get("ref_type") == "chunk":
                ref_id = ground.get("ref_id")
                if isinstance(ref_id, str) and ref_id:
                    chunk_ids.add(ref_id)
    return chunk_ids


def _evidence_counts_by_polity(
    claims: list[dict[str, Any]], *, vault_dir: Path | None
) -> dict[str, int]:
    """`evidence_chunk_count`'s numerator: each distinct grounds chunk
    counted once per polity in its OWN `polities_touched` (mirroring
    `axial.query.reader.coverage_count`'s per-chunk dedup). A grounds
    ref_id that does not resolve in the vault is skipped -- resolving
    grounds is the attribution validator's job (issue #258), not this
    one's; a broken pointer here must not crash the coverage computation."""
    counts: dict[str, int] = {}
    for chunk_id in sorted(_collect_grounds_chunk_ids(claims)):
        try:
            note = get_chunk(chunk_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            continue
        for polity in set(note.polities_touched):
            counts[polity] = counts.get(polity, 0) + 1
    return counts


def compute_coverage_map(
    claims: list[dict[str, Any]],
    *,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, dict[str, Any]]:
    """The §7.7 per-polity coverage map, computed deterministically from
    `polities_touched` -- never asked of a model. Empty claims (a `refuse`
    disposition, §7.2) yield an empty map, not an error.

    `corpus_chunk_count` comes from `axial.query.reader.coverage_count`
    over the WHOLE vault (never a recount over this run's own evidence);
    `evidence_chunk_count` comes from this run's own claim grounds;
    `coverage_band` is derived from `corpus_chunk_count` against the
    `coverage_bands` config block (§7.7's "stated tunable threshold").

    Built in ascending-polity-name order -- the same explicit-sort
    determinism contract every other §7.5-adjacent tool in this codebase
    follows, so the same record over the same pinned vault yields a
    byte-identical map."""
    touched = _touched_polities(claims)
    if not touched:
        return {}

    corpus_counts = coverage_count(vault_dir=vault_dir)
    evidence_counts = _evidence_counts_by_polity(claims, vault_dir=vault_dir)
    moderate_floor, dense_floor = _resolve_coverage_bands(config_path)

    return {
        polity: {
            "corpus_chunk_count": corpus_counts.get(polity, 0),
            "evidence_chunk_count": evidence_counts.get(polity, 0),
            "coverage_band": coverage_band_for(
                corpus_counts.get(polity, 0),
                moderate_floor=moderate_floor,
                dense_floor=dense_floor,
            ),
        }
        for polity in touched
    }


def format_coverage_map(coverage_map: dict[str, dict[str, Any]]) -> str:
    """Render `coverage_map` as the founder-facing inspection text (`axial
    brief coverage <brief_id>`): one line per polity, its counts and band,
    so the `coverage_bands` cut points can be proven against the real
    corpus before they gate anything (§7.7, plan). Empty prints a plain
    statement rather than nothing, so a `refuse`-disposition run is not
    mistaken for a missing command."""
    if not coverage_map:
        return "coverage map: (empty -- no polity touched by any claim)"
    lines = ["coverage map:"]
    for polity in sorted(coverage_map):
        entry = coverage_map[polity]
        lines.append(
            f"  {polity}: corpus_chunk_count={entry.get('corpus_chunk_count')} "
            f"evidence_chunk_count={entry.get('evidence_chunk_count')} "
            f"coverage_band={entry.get('coverage_band')!r}"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class CoverageConfidenceFailure:
    """One failed release-gate check: which of the three reasons, and a
    human-readable detail naming the polity/field involved."""

    reason: str
    detail: str


@dataclass(frozen=True)
class CoverageConfidenceReport:
    """The validator's whole verdict: `passed` is `True` only when
    `failures` is empty. A failure blocks release (§7.9)."""

    passed: bool
    failures: list[CoverageConfidenceFailure]


def validate_coverage_and_confidence(record: dict[str, Any]) -> CoverageConfidenceReport:
    """The §7.9 coverage/confidence release gate: a PURE, model-free check
    over `record["coverage_map"]` and `record["confidence"]` AS PERSISTED
    -- it never recomputes or edits either field (that is
    `compute_coverage_map`'s separate job, used by the inspection
    affordance, not this gate).

    Three checks, none short-circuiting the others so every failure is
    reported in one pass:
    1. Every polity the claims touch (§7.4 `polities_touched`, folded
       across `record["claims"]`) has an entry in `record["coverage_map"]`.
    2. `record["confidence"]` carries a non-blank `overall_band` and a
       non-empty `rationale`.
    3. When (2) holds and `overall_band` is the top band (`high`), no
       polity in `coverage_map` is disclosed `thin` -- an unjustified
       confidence disclosure otherwise (§7.4: "a band is never rendered
       instead of the counts that justify it").

    An empty `claims` list (a `refuse` disposition, §7.2) has no touched
    polities, so check 1 passes vacuously; checks 2-3 still apply, since
    §7.3 marks `confidence` non-nullable even on refusal."""
    claims = record.get("claims") or []
    coverage_map = record.get("coverage_map") or {}
    failures: list[CoverageConfidenceFailure] = []

    for polity in _touched_polities(claims):
        if polity not in coverage_map:
            failures.append(
                CoverageConfidenceFailure(
                    reason=REASON_MISSING_COVERAGE_ENTRY,
                    detail=f"polity {polity!r} is touched by claims but has no coverage_map entry",
                )
            )

    confidence = record.get("confidence") or {}
    overall_band = confidence.get("overall_band")
    rationale = confidence.get("rationale")
    has_band = isinstance(overall_band, str) and bool(overall_band.strip())
    has_rationale = isinstance(rationale, str) and bool(rationale.strip())

    if not (has_band and has_rationale):
        failures.append(
            CoverageConfidenceFailure(
                reason=REASON_MISSING_CONFIDENCE_DISCLOSURE,
                detail=(
                    f"confidence is {confidence!r}, expected a non-blank overall_band "
                    "and a non-empty rationale"
                ),
            )
        )
    elif overall_band == TOP_CONFIDENCE_BAND:
        thin_polities = sorted(
            polity
            for polity, entry in coverage_map.items()
            if isinstance(entry, dict) and entry.get("coverage_band") == THIN_COVERAGE_BAND
        )
        if thin_polities:
            failures.append(
                CoverageConfidenceFailure(
                    reason=REASON_CONFIDENCE_EXCEEDS_COVERAGE,
                    detail=(
                        f"overall confidence is {TOP_CONFIDENCE_BAND!r} but coverage_map "
                        f"discloses thin polity(ies) {thin_polities!r}"
                    ),
                )
            )

    return CoverageConfidenceReport(passed=not failures, failures=failures)


def format_coverage_confidence_report(report: CoverageConfidenceReport) -> str:
    """Render `report` as human-readable text for the CLI (`axial brief
    validate`): a one-line verdict plus one line per failure, naming the
    reason and its detail."""
    if report.passed:
        return "coverage/confidence validator: PASS (0 failures)"
    lines = [f"coverage/confidence validator: FAIL ({len(report.failures)} failure(s))"]
    for failure in report.failures:
        lines.append(f"  {failure.reason} -- {failure.detail}")
    return "\n".join(lines)
