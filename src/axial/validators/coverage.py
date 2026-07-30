"""Stage-5 coverage/confidence validator (specs/PHASE-B.md §7.7, §7.9, §5
stage 5, issues #260 and #490).

Two independent, model-free pieces live here, mirroring the split the
spec draws between "computed deterministically" content and the release
gate that reads it:

1. **`compute_coverage_map`** -- the §7.7 computation itself: for every
   name the answer is about, `{corpus_note_count, evidence_note_count,
   coverage_band}`, built from `axial.query.names.coverage_count` (the
   corpus denominator, a name page's own `member_count`) and this run's
   own claim grounds (the numerator). Never asked of a model. Exposed to
   the founder through `axial brief coverage <brief_id>` so the
   `coverage_bands` cut points can be proven against the real corpus
   before they gate anything.

2. **`validate_coverage_and_confidence`** -- the release gate (§7.9): a
   PURE presence/coherence check over a persisted §7.3 record's OWN
   `coverage_map` and `confidence` fields, exactly as `validate_attribution`
   checks a record's own `claims[].kind`/`grounds` -- it never recomputes or
   repairs the record, only reports pass/fail with reasons.

**The map is per-NAME, and its scope is the names the answer is about
(D2, issue #490).** The v0 map was per-polity over the deleted
`polities_touched` facet, returned 0 entries against the v1 vault, and
pinned `confidence.overall_band` to `low` on every run. The substrate is
now the name layer, and the scope rule is the one thing this module had to
settle that the plan did not:

- A name enters the map when the run **retrieved on it** (a name-layer tool
  call named it, `retrieved_names`) **and** at least one claim's grounds
  note is a member of it (§7.4's `names_touched`).
- `names_touched` alone is not that scope, measured. A real 24-note
  evidence set's grounds notes name **423 distinct canonical names on
  average** (663 for a Charles Tilly set, 810 for a Hanna Batatu one),
  because a live note's `names` answer lists every person, place, date and
  organisation the passage mentions -- median 21 per note. Keying the map
  on all of them yields a several-hundred-row map whose least-covered entry
  is always some one-member mention, so `confidence.overall_band` comes out
  `low` on 10 of 10 measured evidence sets whatever the band cut points
  are. That is the same "computation over nothing" #490 exists to fix,
  wearing a different costume. The retrieved-name scope is what D2's own
  worked example describes ("a brief about the state of exception now gets
  coverage disclosed for `state of exception` and `Giorgio Agamben`") and
  what §7.2 already calls "the names *this brief* is about".

Takes no `LLMClient` at all: nothing here can make a model call, so the
`explode` provider installed in tests never fires by construction, not by
a check that happens not to trip it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.names import NameNotFoundError, coverage_count, get_name

# The §7.4 three-band confidence vocabulary's top band -- the one a
# `thin` name in the coverage map may never be disclosed alongside.
TOP_CONFIDENCE_BAND = "high"

# The §7.7 band vocabulary's bottom band -- the one that triggers the
# confidence-vs-coverage check.
THIN_COVERAGE_BAND = "thin"

# The §7.5 name-layer tools that take a canonical name as an argument, and
# the one that RETURNS canonical names. Together they are "the names this
# run retrieved on" (`retrieved_names`) -- the §7.7 map's scope. `find_names`
# is the brief's own resolution step (§7.2); the other four are the
# traversals a run makes from a name it already resolved. `coverage_count`
# is deliberately absent: as a tool it returns EVERY canonical in the index
# (62,821 on the real corpus), which is the whole-index table §7.2 rules out.
NAME_ARG_TOOLS = frozenset({"get_name", "name_neighbors", "who_cites", "who_argues_against"})
NAME_RESULT_TOOLS = frozenset({"find_names"})

# The `coverage_bands` config block's code-level fallback: used only when
# `config/pipeline.yaml` (or its `coverage_bands` key) is absent, mirroring
# `axial.retrieve.loop.DEFAULT_STEP_BUDGET`'s own fallback convention.
# `thin` is below `moderate_floor`, `moderate` is [moderate_floor,
# dense_floor), `dense` is `dense_floor` and above.
#
# **Proven by inspection on the real corpus** (2026-07-30,
# `data/logs/2026-07-30-slice-05-coverage/`), which is what §7.7's "stated
# tunable threshold" owes. Over the 30 real brief-shaped names that resolve
# against the live index, these cut points split 15 thin / 9 moderate / 6
# dense: `bare life` 1, `AANES` 2, `Rojava` 3, `state formation` 5, `SDF` 7,
# `Giorgio Agamben` 9, `Stathis Kalyvas` 11, `PYD` 14, `N. Caspersen` 17,
# `Asef Bayat` 18 | `state of exception` 27, `Hanna Batatu` 30, `Idlib` 30,
# `Bashar al-Assad` 33, `Ba'th Party` 43, `sovereignty` 48, `Civil War` 61 |
# `Charles Tilly` 146, `Michael Mann` 378, `Iraq` 445, `Lebanon` 507,
# `Syria` 962. They are unchanged from #260's starting hypothesis because
# the measurement supports them, not because nobody looked.
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
    tunes the cut points."""
    if not config_path.is_file():
        return DEFAULT_MODERATE_FLOOR, DEFAULT_DENSE_FLOOR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    bands_config = document.get("coverage_bands") or {}
    moderate_floor = int(bands_config.get("moderate_floor", DEFAULT_MODERATE_FLOOR))
    dense_floor = int(bands_config.get("dense_floor", DEFAULT_DENSE_FLOOR))
    return moderate_floor, dense_floor


def coverage_band_for(
    corpus_note_count: int | None, *, moderate_floor: int, dense_floor: int
) -> str:
    """The §7.7 band derivation, pure and total: `dense` at or above
    `dense_floor`, `moderate` at or above `moderate_floor`, `thin`
    otherwise. The cut points are always read from config (or its
    fallback), never hardcoded at a call site.

    `None` -- the index carries the name but the vault holds no page for it,
    so there is no honest denominator (§7.5) -- reads `thin`, the most
    conservative band. It is never dressed up as a count: the entry's
    `corpus_note_count` stays `null` and travels with the band everywhere it
    is disclosed (§7.4)."""
    if corpus_note_count is None:
        return THIN_COVERAGE_BAND
    if corpus_note_count >= dense_floor:
        return "dense"
    if corpus_note_count >= moderate_floor:
        return "moderate"
    return THIN_COVERAGE_BAND


def touched_names(claims: list[dict[str, Any]]) -> set[str]:
    """The canonical names a claim graph's grounds notes are members of: the
    union of every claim's own `names_touched` (§7.4 -- already resolved
    through the alias map at synthesis time, so this is a fold over claims,
    never a re-derivation from grounds)."""
    names: set[str] = set()
    for claim in claims:
        for name in claim.get("names_touched") or []:
            if isinstance(name, str) and name:
                names.add(name)
    return names


def retrieved_names(trajectory: list[dict[str, Any]]) -> set[str]:
    """The canonical names this run retrieved on, read off the §7.6
    trajectory: the `canonical` argument of every name-layer traversal
    (`NAME_ARG_TOOLS`) and every canonical `find_names` resolved
    (`NAME_RESULT_TOOLS`, whose `result_ids` are canonical names, not chunk
    ids -- `ToolSpec.returns_chunk_ids` is `False` for exactly that reason).

    This is "the names this brief is about" (§7.2) as the run itself
    recorded them, and it is what keeps the §7.7 map to the handful of names
    the answer is anchored at rather than every name its evidence mentions
    in passing (see the module docstring's measurement)."""
    names: set[str] = set()
    for entry in trajectory:
        if not isinstance(entry, dict):
            continue
        tool = entry.get("tool")
        if tool in NAME_ARG_TOOLS:
            canonical = (entry.get("args") or {}).get("canonical")
            if isinstance(canonical, str) and canonical.strip():
                names.add(canonical)
        elif tool in NAME_RESULT_TOOLS:
            for result_id in entry.get("result_ids") or []:
                if isinstance(result_id, str) and result_id.strip():
                    names.add(result_id)
    return names


def coverage_scope(claims: list[dict[str, Any]], trajectory: list[dict[str, Any]]) -> list[str]:
    """The names the §7.7 map covers, ascending: the names this run
    retrieved on that at least one claim's grounds note is also a member of.

    Both halves are load-bearing. Without `retrieved_names` the map is every
    name the evidence mentions (measured: 423 on average, and a constant
    `low` confidence -- see the module docstring). Without `touched_names` it
    would disclose coverage for a name the run looked at and then never used,
    which no claim is grounded in."""
    return sorted(retrieved_names(trajectory) & touched_names(claims))


def _collect_grounds_chunk_ids(claims: list[dict[str, Any]]) -> set[str]:
    """Every distinct `chunk` grounds ref_id across every claim -- an
    artifact grounds pointer never contributes (an artifact note is a member
    of no name page), and the same chunk cited by two claims is one entry."""
    chunk_ids: set[str] = set()
    for claim in claims:
        for ground in claim.get("grounds") or []:
            if isinstance(ground, dict) and ground.get("ref_type") == "chunk":
                ref_id = ground.get("ref_id")
                if isinstance(ref_id, str) and ref_id:
                    chunk_ids.add(ref_id)
    return chunk_ids


def _evidence_note_count(canonical: str, grounds: set[str], *, vault_dir: Path | None) -> int:
    """`evidence_note_count`: how many of this run's grounds notes are
    members of `canonical`'s page (§7.7). The intersection of the run's
    grounds with the page's own member list, never a re-query and never a
    recount off the notes' `names` answers. A name with no page has no
    member list, so the intersection is empty.

    `get_name`'s `members` is capped at its own `limit` (issue #505's own
    default), which this correctness-critical intersection cannot accept: a
    grounds note that is a real member past the cap would silently read as
    uncovered. So a first call at the default cap is only ever used when it
    already proves uncapped (`member_count <= len(members)`); a page over
    the cap pays one extra `get_name` call, at its own true `member_count` as
    `limit`, to see every member. This is the one caller of `get_name` that
    needs the whole page rather than a bounded window."""
    try:
        page = get_name(canonical, vault_dir=vault_dir)
    except NameNotFoundError:
        return 0
    if page.member_count > len(page.members):
        page = get_name(canonical, page.member_count, vault_dir=vault_dir)
    return len({member.chunk_id for member in page.members} & grounds)


def compute_coverage_map(
    claims: list[dict[str, Any]],
    *,
    trajectory: list[dict[str, Any]] | None = None,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> dict[str, dict[str, Any]]:
    """The §7.7 per-name coverage map, computed deterministically from the
    name layer -- never asked of a model. Empty claims (a `refuse`
    disposition, §7.2) or an empty trajectory yield an empty map, not an
    error.

    `corpus_note_count` is the name page's own `member_count`, read through
    `axial.query.names.coverage_count` (never a recount -- the denominator
    already exists and Materialize wrote it, D2); it is `null` for a name
    the index carries but the vault holds no page for, never a fabricated 0.
    `evidence_note_count` is this run's grounds notes that are members of
    that page. `coverage_band` is derived from `corpus_note_count` against
    the `coverage_bands` config block (§7.7's "stated tunable threshold").

    Built in ascending-name order -- the same explicit-sort determinism
    contract every §7.5 tool follows, so the same record over the same
    pinned vault yields a byte-identical map."""
    scope = coverage_scope(claims, trajectory or [])
    if not scope:
        return {}

    corpus_counts = coverage_count(vault_dir=vault_dir)
    grounds = _collect_grounds_chunk_ids(claims)
    moderate_floor, dense_floor = _resolve_coverage_bands(config_path)

    return {
        canonical: {
            "corpus_note_count": corpus_counts.get(canonical),
            "evidence_note_count": _evidence_note_count(canonical, grounds, vault_dir=vault_dir),
            "coverage_band": coverage_band_for(
                corpus_counts.get(canonical),
                moderate_floor=moderate_floor,
                dense_floor=dense_floor,
            ),
        }
        for canonical in scope
    }


# The §7.7 coverage-band vocabulary, worst to best -- a coverage_band value
# outside this vocabulary is treated as the worst case (`thin`) rather than
# crashing, so a run cannot manufacture a favorable overall confidence band
# by carrying an unrecognized coverage_band string.
_COVERAGE_BAND_RANK = {THIN_COVERAGE_BAND: 0, "moderate": 1, "dense": 2}

# The §7.4 confidence-band vocabulary, one-to-one with the §7.7 coverage-band
# vocabulary in the same worst-to-best order -- the natural reading of "a
# band is never rendered instead of the counts that justify it" (§7.4):
# overall confidence can be no better than the least-covered name the answer
# is about.
_CONFIDENCE_BAND_BY_COVERAGE_RANK = {0: "low", 1: "medium", 2: TOP_CONFIDENCE_BAND}


def compute_confidence(coverage_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The §7.3/§7.4 record-level `confidence` disclosure, computed
    deterministically from `coverage_map` (§7.7) -- never asked of a model,
    the same "computed separately and deterministically" contract §7.9
    states for the map itself.

    `overall_band` is set by the LEAST-covered name the answer is about
    (`dense` -> `high`, `moderate` -> `medium`, `thin` -> `low`, issue
    #400): a run that grounds part of its argument in a thin-coverage name
    cannot disclose high confidence overall. This satisfies
    `validate_coverage_and_confidence`'s `confidence_exceeds_coverage` check
    by construction rather than by coincidence.

    `rationale` names every mapped name's own coverage band and counts
    (§7.4: "states the coverage counts that justify the band, drawn from
    coverage_map"), in ascending name order for the same determinism
    contract `compute_coverage_map` follows.

    An empty `coverage_map` (a `refuse` disposition, or a run that never
    retrieved on a name any claim then used) still returns a non-nullable
    disclosure (§7.3), pinned to the most conservative band with a rationale
    that says plainly why there are no counts to cite."""
    if not coverage_map:
        return {
            "overall_band": "low",
            "rationale": (
                "no name is both retrieved on by this run and touched by a claim, so "
                "there is no coverage_map entry to justify a higher band"
            ),
        }

    worst_name = min(
        coverage_map,
        key=lambda name: (
            _COVERAGE_BAND_RANK.get(coverage_map[name].get("coverage_band"), 0),
            name,
        ),
    )
    worst_rank = _COVERAGE_BAND_RANK.get(coverage_map[worst_name].get("coverage_band"), 0)
    overall_band = _CONFIDENCE_BAND_BY_COVERAGE_RANK[worst_rank]

    per_name = "; ".join(
        f"{name} ({entry.get('coverage_band')}: {entry.get('corpus_note_count')} "
        f"corpus notes, {entry.get('evidence_note_count')} evidence notes)"
        for name, entry in sorted(coverage_map.items())
    )
    rationale = (
        f"overall confidence is {overall_band!r}, bounded by the least-covered "
        f"name touched ({worst_name!r}, band {coverage_map[worst_name].get('coverage_band')!r}); "
        f"coverage by name: {per_name}"
    )
    return {"overall_band": overall_band, "rationale": rationale}


def format_coverage_map(coverage_map: dict[str, dict[str, Any]]) -> str:
    """Render `coverage_map` as the founder-facing inspection text (`axial
    brief coverage <brief_id>`): one line per name, its counts and band, so
    the `coverage_bands` cut points can be proven against the real corpus
    before they gate anything (§7.7). Empty prints a plain statement rather
    than nothing, so a `refuse`-disposition run is not mistaken for a
    missing command."""
    if not coverage_map:
        return "coverage map: (empty -- no name both retrieved on and touched by a claim)"
    lines = ["coverage map:"]
    for name in sorted(coverage_map):
        entry = coverage_map[name]
        lines.append(
            f"  {name}: corpus_note_count={entry.get('corpus_note_count')} "
            f"evidence_note_count={entry.get('evidence_note_count')} "
            f"coverage_band={entry.get('coverage_band')!r}"
        )
    return "\n".join(lines)


@dataclass(frozen=True)
class CoverageConfidenceFailure:
    """One failed release-gate check: which of the three reasons, and a
    human-readable detail naming the name/field involved."""

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
    1. Every name the map is required to cover -- `coverage_scope` over the
       record's own `claims` and `trajectory` -- has an entry in
       `record["coverage_map"]`.
    2. `record["confidence"]` carries a non-blank `overall_band` and a
       non-empty `rationale`.
    3. When (2) holds and `overall_band` is the top band (`high`), no name
       in `coverage_map` is disclosed `thin` -- an unjustified confidence
       disclosure otherwise (§7.4: "a band is never rendered instead of the
       counts that justify it").

    An empty `claims` list (a `refuse` disposition, §7.2) has an empty
    scope, so check 1 passes vacuously; checks 2-3 still apply, since §7.3
    marks `confidence` non-nullable even on refusal."""
    claims = record.get("claims") or []
    trajectory = record.get("trajectory") or []
    coverage_map = record.get("coverage_map") or {}
    failures: list[CoverageConfidenceFailure] = []

    for name in coverage_scope(claims, trajectory):
        if name not in coverage_map:
            failures.append(
                CoverageConfidenceFailure(
                    reason=REASON_MISSING_COVERAGE_ENTRY,
                    detail=(
                        f"name {name!r} was retrieved on and is touched by a claim "
                        "but has no coverage_map entry"
                    ),
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
        thin_names = sorted(
            name
            for name, entry in coverage_map.items()
            if isinstance(entry, dict) and entry.get("coverage_band") == THIN_COVERAGE_BAND
        )
        if thin_names:
            failures.append(
                CoverageConfidenceFailure(
                    reason=REASON_CONFIDENCE_EXCEEDS_COVERAGE,
                    detail=(
                        f"overall confidence is {TOP_CONFIDENCE_BAND!r} but coverage_map "
                        f"discloses thin name(s) {thin_names!r}"
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
