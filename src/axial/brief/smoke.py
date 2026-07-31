"""`axial brief smoke` -- the build's smoke alarm (specs/PHASE-B.md §9.0,
§8 P0-11, issue #491 Part 2).

Runs the five short briefs of `config/briefs/smoke/`, one draw each, and
reports pass or fail on **mechanical checks only**. Nothing here is a quality
judgment: this is a smoke alarm, not an eval. The six checks are the ones a
regression makes loud on the day it lands --

1. the record validates against the §7.3 shape and every grounds pointer
   resolves;
2. `disposition` is set and is one of the three (§7.2);
3. the coverage map is non-empty (the empty-map regression #490 exists to
   fix);
4. the draw raised no unhandled exception and the trajectory carries no call
   the dispatcher had to refuse;
5. the counter-position section was not marked `failed` (issue #558) --
   `axial.answer.record.build_record` persists a record even when
   counter-position GENERATION raises, precisely so this checker (and a
   human) can still see it happened; a failed section is a mechanical
   failure, checked here without paying for the (costed) counter-position
   validator's own steelman-quality model call;
6. a cost and latency budget per brief.

Built on `run_sweep`, not beside it
----------------------------------------------------------------------
`axial.brief.sweep.run_sweep` already solves everything except the checks:
resume, ONE FRESH CLIENT PER DRAW (a shared client accumulates each earlier
draw's tokens into every later draw's cost, so a cost budget read off a
shared client is wrong by construction), per-draw latency, per-pass cost
aggregation and `summary.json`. Rebuilding those here would hand-roll four
mechanisms already documented against their own failure modes.

Three deliberate differences from a plain sweep:

- **The checks and the budgets.** New, and the reason this command exists.
- **A non-zero exit on any mechanical failure.** `_brief_sweep` returns 0 by
  design even with FAILED draws, mirroring `axial run`'s loop rule. Smoke
  inverts that ON PURPOSE, because it is a gate rather than a loop -- see
  `SmokeSummary.passed`, which is what the CLI's exit code reads.
- **Gate scoring off** (`run_sweep(score_gates=False)`): the four rung-3
  gates are a quality judgment and a bill, and the grounding gate's
  independent judge would make the cost budget measure the wrong thing.

The budgets are UNMEASURED
----------------------------------------------------------------------
Their values come from the first five real runs and are deliberately unset
until then: absent from `config/pipeline.yaml`, or present and explicitly
`null`. An unset budget **skips** its check -- it never passes vacuously and
never fails -- and the console output says `UNMEASURED` where the number
would be, so a reader is never told a spend regression was checked when
nothing was compared.

P4-04 is a fragmentation probe (§7.5, §9.0)
----------------------------------------------------------------------
It must not silently substitute a nearest-neighbour name for `AANES`. That
is a judgment about which names a run reached, not a mechanical predicate,
and a brief-specific rule in `src/` would be domain content as code. So the
summary PRINTS the names each run actually queried, and the founder reads
them. No check asserts on them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

from axial.brief.sweep import (
    FAIL_STATUS,
    BriefSweepResult,
    SweepError,
    run_sweep,
)
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.query.reader import (
    ArtifactNotFoundError,
    ChunkNotFoundError,
    MalformedChunkIdError,
    get_artifact,
    get_chunk,
)
from axial.retrieve.tools import TOOL_REGISTRY
from axial.yaml_loader import SAFE_LOADER

SMOKE_BRIEFS_DIR = Path("config/briefs/smoke")

# The §7.3 record fields a smoke run asserts are present and non-null. Every
# one of them is non-nullable in §7.3; `claims` may be EMPTY on a refusal,
# which is not the same as absent.
REQUIRED_RECORD_KEYS = (
    "brief_id",
    "brief",
    "corpus_pin",
    "lens",
    "interrogation",
    "claims",
    "counter_position",
    "coverage_map",
    "confidence",
    "source_usage",
    "trajectory",
    "model_by_pass",
    "cost",
)

DISPOSITIONS = ("proceed", "proceed_bounded", "refuse")

CHECK_RECORD_SHAPE = "record_shape_and_grounds"
CHECK_DISPOSITION = "disposition"
CHECK_COVERAGE_MAP = "coverage_map_non_empty"
CHECK_TOOL_CALLS = "no_unhandled_failure"
CHECK_COUNTER_POSITION = "counter_position_not_failed"
CHECK_COST_BUDGET = "cost_budget"
CHECK_LATENCY_BUDGET = "latency_budget"


@dataclass(frozen=True)
class Budgets:
    """The per-brief cost and latency budgets (§9.0). Either may be `None`,
    which means UNMEASURED: its check is skipped, never passed and never
    failed."""

    max_usd_per_brief: float | None
    max_seconds_per_brief: float | None

    @property
    def any_measured(self) -> bool:
        return self.max_usd_per_brief is not None or self.max_seconds_per_brief is not None


@dataclass(frozen=True)
class CheckResult:
    """One mechanical check's outcome. `passed` is tri-state, the same
    discipline §10 states for a gate metric: `True`/`False` is a real
    verdict, `None` means the check was SKIPPED and measured nothing (an
    unset budget, a refusal that legitimately has no coverage map). A
    skipped check never contributes to the exit code."""

    name: str
    passed: bool | None
    detail: str


@dataclass(frozen=True)
class BriefSmokeResult:
    brief_stem: str
    brief_id: str | None
    checks: list[CheckResult]
    names_queried: list[str]
    total_usd: float | None
    total_seconds: float | None

    @property
    def failures(self) -> list[CheckResult]:
        return [check for check in self.checks if check.passed is False]


@dataclass(frozen=True)
class SmokeSummary:
    briefs: list[BriefSmokeResult]
    budgets: Budgets

    @property
    def failures(self) -> list[tuple[str, CheckResult]]:
        return [(result.brief_stem, check) for result in self.briefs for check in result.failures]

    @property
    def passed(self) -> bool:
        """True only when no brief failed a mechanical check. The CLI's
        exit code reads this: smoke is a gate, so any failure is non-zero --
        deliberately the opposite of `axial brief sweep`'s loop rule."""
        return not self.failures


def resolve_budgets(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> Budgets:
    """Read `smoke.max_usd_per_brief` / `smoke.max_seconds_per_brief` from
    `config/pipeline.yaml`. An absent block, an absent key, or an explicit
    `null` all resolve to `None` -- there is no code-level fallback on
    purpose, because a guessed budget is worse than no budget: it would
    either pass everything or fail the first real run for no measured
    reason."""
    if not config_path.is_file():
        return Budgets(None, None)
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
    block = document.get("smoke") or {}
    usd = block.get("max_usd_per_brief")
    seconds = block.get("max_seconds_per_brief")
    return Budgets(
        max_usd_per_brief=float(usd) if usd is not None else None,
        max_seconds_per_brief=float(seconds) if seconds is not None else None,
    )


def smoke_brief_paths(briefs_dir: Path | None = None) -> list[Path]:
    """Every brief file in the smoke set, in a deterministic (name-ascending)
    order. A `README.md` alongside them is not a brief and is not swept."""
    directory = Path(briefs_dir) if briefs_dir is not None else SMOKE_BRIEFS_DIR
    return sorted(directory.glob("*.yaml"))


def _check_record_shape(record: dict[str, Any], *, vault_dir: Path | None) -> CheckResult:
    """Check 1: the §7.3 shape, and that every grounds pointer resolves to a
    real vault id -- every pointer, not only the (a)/(b) claims the
    attribution validator gates on, since a (c) claim citing a note that
    does not exist is still a broken record."""
    missing = [key for key in REQUIRED_RECORD_KEYS if record.get(key) is None]
    if missing:
        return CheckResult(
            CHECK_RECORD_SHAPE, False, f"record is missing §7.3 field(s) {missing!r}"
        )

    unresolved: list[str] = []
    for claim in record.get("claims") or []:
        for ground in claim.get("grounds") or []:
            ref_type = ground.get("ref_type") if isinstance(ground, dict) else None
            ref_id = ground.get("ref_id") if isinstance(ground, dict) else None
            try:
                if ref_type == "chunk":
                    get_chunk(ref_id, vault_dir=vault_dir)
                elif ref_type == "artifact":
                    get_artifact(ref_id, vault_dir=vault_dir)
                else:
                    unresolved.append(f"{ref_id!r} (unknown ref_type {ref_type!r})")
            except (ChunkNotFoundError, ArtifactNotFoundError, MalformedChunkIdError) as exc:
                unresolved.append(f"{ref_id!r} ({exc})")
    if unresolved:
        return CheckResult(
            CHECK_RECORD_SHAPE,
            False,
            f"{len(unresolved)} grounds pointer(s) do not resolve: {unresolved[:3]!r}",
        )
    return CheckResult(
        CHECK_RECORD_SHAPE, True, "every §7.3 field present, every grounds pointer resolves"
    )


def _check_disposition(record: dict[str, Any]) -> CheckResult:
    disposition = (record.get("interrogation") or {}).get("disposition")
    if disposition in DISPOSITIONS:
        return CheckResult(CHECK_DISPOSITION, True, f"disposition={disposition}")
    return CheckResult(
        CHECK_DISPOSITION,
        False,
        f"disposition is {disposition!r}, expected one of {list(DISPOSITIONS)!r}",
    )


def _check_coverage_map(record: dict[str, Any]) -> CheckResult:
    """Check 3: the coverage map carries at least one name. A `refuse`
    disposition retrieves nothing and legitimately has no map, so it is
    SKIPPED with the reason stated rather than failed -- a refusal is a
    complete run (§7.2). Any other disposition with an empty map is the
    regression #490 exists to fix, and it must be loud."""
    disposition = (record.get("interrogation") or {}).get("disposition")
    coverage_map = record.get("coverage_map") or {}
    if disposition == "refuse":
        return CheckResult(
            CHECK_COVERAGE_MAP, None, "skipped: a refusal retrieves nothing, so it maps nothing"
        )
    if coverage_map:
        return CheckResult(
            CHECK_COVERAGE_MAP, True, f"{len(coverage_map)} name(s) disclosed with counts"
        )
    return CheckResult(
        CHECK_COVERAGE_MAP,
        False,
        "coverage_map is empty on a non-refusing run -- the #490 empty-map regression",
    )


def _check_tool_calls(record: dict[str, Any], *, draw_failed: bool, reason: str) -> CheckResult:
    """Check 4: no unhandled exception, and no tool call the dispatcher had
    to refuse.

    A refused call is one naming a tool the registry does not hold. That is
    a LOWER bound and says so: §7.6's shape is [FIRM] with no error field,
    so a registered tool rejected for malformed args is indistinguishable
    from a valid call that returned nothing. A valid call returning zero
    results is NOT a failure -- an empty result is a real answer (§7.5)."""
    if draw_failed:
        return CheckResult(CHECK_TOOL_CALLS, False, f"the draw raised: {reason}")
    refused = [
        entry.get("tool")
        for entry in record.get("trajectory") or []
        if isinstance(entry, dict) and entry.get("tool") not in TOOL_REGISTRY
    ]
    if refused:
        return CheckResult(
            CHECK_TOOL_CALLS, False, f"the dispatcher refused {len(refused)} call(s): {refused!r}"
        )
    return CheckResult(CHECK_TOOL_CALLS, True, "no unhandled exception, no refused tool call")


def _check_counter_position_not_failed(record: dict[str, Any]) -> CheckResult:
    """Check 5: the §7.8 section was not marked `failed` (issue #558).

    `build_record` persists a record even when counter-position GENERATION
    raises, exactly so a completed, already-paid-for run is never discarded
    -- but a failed section is still a mechanical failure, not a clean
    result, and the founder's own direction is that smoke's exit code must
    say so. This reads `counter_position.get("failed")` directly rather than
    calling `axial.validators.counter_position.validate_counter_position`:
    that function's steelman-quality half makes its own bounded model call
    whenever the section is genuinely present, which would make this smoke
    run's cost budget (check 6) measure a judge call the smoke set
    deliberately excludes (module docstring: "gate scoring off")."""
    counter_position = record.get("counter_position") or {}
    if counter_position.get("failed"):
        return CheckResult(
            CHECK_COUNTER_POSITION,
            False,
            f"counter-position generation failed: {counter_position.get('failure_reason')}",
        )
    return CheckResult(CHECK_COUNTER_POSITION, True, "counter-position generation did not fail")


def _check_budget(
    name: str, observed: float | None, budget: float | None, unit: str
) -> CheckResult:
    """Checks 5a/5b: compare `observed` against `budget`. An UNSET budget is
    skipped and labelled unmeasured -- never a vacuous pass. An unobservable
    figure (a `null` `total_usd` from an unpriced model) is skipped too, for
    the same reason: there is nothing to compare."""
    if budget is None:
        return CheckResult(name, None, "skipped: budget UNMEASURED (set from the first real runs)")
    if observed is None:
        return CheckResult(name, None, f"skipped: this run reports no {unit} figure to compare")
    if observed <= budget:
        return CheckResult(name, True, f"{observed:.4f}{unit} within budget {budget:.4f}{unit}")
    return CheckResult(name, False, f"{observed:.4f}{unit} over budget {budget:.4f}{unit}")


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _names_queried(record: dict[str, Any]) -> list[str]:
    """The name queries this run made, rendered for the console: the
    fragmentation probe (P4-04) is read off these by eye, not asserted on."""
    rendered: list[str] = []
    for entry in (record.get("source_usage") or {}).get("names_queried") or []:
        args = entry.get("args") or {}
        value = args.get("canonical") or args.get("query") or ""
        rendered.append(f"{entry.get('tool')}:{value}")
    return rendered


def check_brief(
    sweep_result: BriefSweepResult,
    *,
    budgets: Budgets,
    vault_dir: Path | None,
) -> BriefSmokeResult:
    """Run every mechanical check over one brief's single draw."""
    draw = sweep_result.draws[0] if sweep_result.draws else None
    record = _load_json(draw.record_path if draw is not None else None)
    report = _load_json(draw.report_path if draw is not None else None)

    if record is None:
        reason = draw.reason if draw is not None else "no draw was attempted"
        return BriefSmokeResult(
            brief_stem=sweep_result.brief_stem,
            brief_id=sweep_result.brief_id,
            checks=[
                CheckResult(CHECK_RECORD_SHAPE, False, f"no analysis record was written: {reason}"),
                CheckResult(CHECK_TOOL_CALLS, False, f"the draw did not complete: {reason}"),
            ],
            names_queried=[],
            total_usd=None,
            total_seconds=None,
        )

    operational = (report or {}).get("operational") or {}
    total_usd = (operational.get("cost") or {}).get("total_usd")
    total_seconds = (operational.get("latency_seconds") or {}).get("total")
    draw_failed = draw is not None and draw.status == FAIL_STATUS

    checks = [
        _check_record_shape(record, vault_dir=vault_dir),
        _check_disposition(record),
        _check_coverage_map(record),
        _check_tool_calls(
            record, draw_failed=draw_failed, reason=draw.reason if draw is not None else ""
        ),
        _check_counter_position_not_failed(record),
        _check_budget(CHECK_COST_BUDGET, total_usd, budgets.max_usd_per_brief, "usd"),
        _check_budget(CHECK_LATENCY_BUDGET, total_seconds, budgets.max_seconds_per_brief, "s"),
    ]
    return BriefSmokeResult(
        brief_stem=sweep_result.brief_stem,
        brief_id=sweep_result.brief_id,
        checks=checks,
        names_queried=_names_queried(record),
        total_usd=total_usd,
        total_seconds=total_seconds,
    )


def run_smoke(
    *,
    sweep_dir: str | Path,
    briefs_dir: Path | None = None,
    client_factory: Callable[[], LLMClient] | None = None,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    evals_dir: Path | None = None,
    lenses_dir: Path | None = None,
    cases_dir: Path | None = None,
    workers: int = 1,
) -> SmokeSummary:
    """Run the smoke set once each and check every record mechanically.

    Raises `SweepError` before any draw when the brief directory holds no
    brief -- an empty smoke set that reported a clean pass would be the
    worst possible smoke alarm.

    `workers` defaults to 1, not `run_sweep`'s 3: five briefs is a small set
    and a serial run keeps the per-brief latency figure a budget is compared
    against free of contention with four other draws on the same machine."""
    paths = smoke_brief_paths(briefs_dir)
    if not paths:
        directory = briefs_dir if briefs_dir is not None else SMOKE_BRIEFS_DIR
        raise SweepError(f"no brief files found under {directory}")

    sweep_dir = Path(sweep_dir)
    sweep_dir.mkdir(parents=True, exist_ok=True)
    worklist_path = sweep_dir / "worklist.txt"
    worklist_path.write_text("\n".join(str(path) for path in paths) + "\n", encoding="utf-8")

    summary = run_sweep(
        worklist_path,
        draws=1,
        sweep_dir=sweep_dir,
        client_factory=client_factory,
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        config_path=config_path,
        evals_dir=evals_dir,
        lenses_dir=lenses_dir,
        cases_dir=cases_dir,
        workers=workers,
        # See the module docstring: the four rung-3 gates are a quality
        # judgment and a model bill, and scoring them here would make the
        # cost budget measure the judge instead of the run.
        score_gates=False,
    )

    budgets = resolve_budgets(config_path)
    return SmokeSummary(
        briefs=[
            check_brief(result, budgets=budgets, vault_dir=vault_dir) for result in summary.briefs
        ],
        budgets=budgets,
    )


def _verdict_text(passed: bool | None) -> str:
    if passed is None:
        return "SKIP"
    return "PASS" if passed else "FAIL"


def format_smoke_summary(summary: SmokeSummary) -> str:
    """Render `summary` for the console: one block per brief with every
    check's verdict, the names it queried (the P4-04 fragmentation read),
    and a closing verdict line. States plainly when the budgets are
    unmeasured, so a reader is never told a spend regression was checked
    when nothing was compared."""
    lines: list[str] = []
    if not summary.budgets.any_measured:
        lines.append(
            "smoke: cost and latency budgets are UNMEASURED -- both checks are skipped "
            "until the values are set from the first real runs (config/pipeline.yaml, "
            "`smoke:`)"
        )
    for result in summary.briefs:
        lines.append(f"brief: {result.brief_stem} (brief_id={result.brief_id})")
        usd = "n/a" if result.total_usd is None else f"{result.total_usd:.4f}"
        seconds = "n/a" if result.total_seconds is None else f"{result.total_seconds:.1f}"
        lines.append(f"  cost: usd={usd}  wall clock: {seconds}s")
        lines.append(f"  names queried: {', '.join(result.names_queried) or '(none)'}")
        for check in result.checks:
            lines.append(f"  {_verdict_text(check.passed)} {check.name}: {check.detail}")
    failures = summary.failures
    if failures:
        lines.append(f"smoke: FAIL -- {len(failures)} mechanical check(s) failed")
        for brief_stem, check in failures:
            lines.append(f"  {brief_stem}: {check.name} -- {check.detail}")
    else:
        lines.append(f"smoke: PASS -- {len(summary.briefs)} brief(s), no mechanical failure")
    return "\n".join(lines)
