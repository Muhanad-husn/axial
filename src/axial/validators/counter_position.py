"""Stage-5 counter-position validator (specs/PHASE-B.md §7.8, §7.9, §5 stage
5, issue #259).

Reads a persisted §7.3 analysis record and reports pass/fail, never editing
it -- same "never edits the record" contract as the attribution validator
(src/axial/validators/attribution.py). Two checks, run in this order:

1. **Contested predicate (mechanical).** Whether the brief is contested is
   determined from corpus signal, never the brief's wording (§7.8): the
   union of chunk-typed grounds cited across every claim ("this run's
   evidence", the same source of truth §7.7's coverage map reads) is
   resolved via the query API and its `theory_school`/`role_in_argument`
   axes inspected. Contested when either fires, checked in this order:
   - **theory_school_spread** -- the evidence spans at least
     `contested_detection.min_distinct_theory_schools` (a stated tunable,
     default 2) distinct *substantive* `theory_school` primaries. The
     `not-applicable`/`unlisted` sentinels are excluded from this count
     (§7.8: neither is a position, so neither can oppose another value or
     itself).
   - **role_counter_position** -- any evidence chunk carries
     `role_in_argument: "role:counter-position"`.
   The fired signal (or `None` on an uncontested brief) is always recorded
   on the report, so the tunable rule can be tuned on evidence later
   (explicitly out of this slice's own scope).
2. **Presence-or-disclosure check (mechanical), on a contested brief only.**
   The record's `counter_position` section (§7.8, locked shape) must be
   either `present: true` with non-empty `grounds`, or `corpus_one_sided:
   true` with a non-empty `one_sided_reason`. Neither fails with
   `REASON_CONTESTED_WITHOUT_COUNTER_POSITION` and blocks release -- the
   whole point of this validator (§7.8: "a red flag, not a clean result").
   An uncontested brief never requires the section at all.

A **bounded model steelman-quality check**, anchored to the counter-position
`grounds` text and run under its own `pass_name` (never the generating
model), runs whenever the section itself is genuinely present (`present:
true` with non-empty `grounds`) -- independent of whether the brief is
contested, since judging an existing section's quality is a different
question from whether one was required. In this slice the check only
reports (`SteelmanCheck.verdict`); it never blocks release (§7.9, plan
02's "out of scope").

Out of scope for this slice (plans/analysis-validators/02-counter-position-
validator.md): making the steelman check blocking, the counter-position
presence *rate* over the contested-brief subset (§10), retrieving or
generating a counter-position when one is missing, tuning the contested
rule against the real dev briefs, and any change to the §7.8 section shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from axial.llm import COUNTER_POSITION_PASS_NAME, SYNTHESIZE_PASS_NAME, LLMClient, LLMError
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.reader import ChunkNotFoundError, get_chunk

# The §7.8/Appendix E sentinel `theory_school` values excluded from the
# contested-spread comparison: neither is a position, so neither counts as
# opposing another value, including another instance of itself. Named
# locally (rather than imported from `axial.tag`, the Phase-A tagging
# module) to keep this Phase-B validator decoupled from Phase-A's
# LLM-backed tagging stack -- these two strings are the whole of the
# schema's `theory_school` sentinel vocabulary (config/domains/*/schema.yaml
# `groups.none`/`groups.open`), not something either side will drift on
# independently.
_THEORY_SCHOOL_SENTINEL_VALUES = frozenset({"not-applicable", "unlisted"})

# The role_in_argument value marking a chunk as opposing material (§7.5's
# `role_in_argument` axis; config/domains/*/schema.yaml Appendix F).
COUNTER_POSITION_ROLE_VALUE = "role:counter-position"

# The stated tunable's code-level fallback (§7.8 "a stated tunable, proven
# on the dev briefs") -- used only when `config/pipeline.yaml` (or its
# `contested_detection.min_distinct_theory_schools` key) is absent, mirroring
# every other per-pass/per-check tunable in this codebase (e.g.
# `axial.retrieve.loop.DEFAULT_STEP_BUDGET`). 2 is the starting hypothesis
# stated directly in the spec text; tuning it against the real dev briefs is
# explicitly out of this slice's scope.
DEFAULT_MIN_DISTINCT_THEORY_SCHOOLS = 2

# The two contested signals this validator ever persists -- a fixed, small
# vocabulary (mirrors attribution.py's REASON_* constants), never open text.
SIGNAL_THEORY_SCHOOL_SPREAD = "theory_school_spread"
SIGNAL_ROLE_COUNTER_POSITION = "role_counter_position"

# The one blocking reason this validator ever reports.
REASON_CONTESTED_WITHOUT_COUNTER_POSITION = "contested_without_counter_position"

# The steelman-quality judge's closed verdict vocabulary.
VERDICT_STEELMAN = "steelman"
VERDICT_STRAWMAN = "strawman"


class CounterPositionValidatorError(Exception):
    """Base class for all counter-position-validator errors."""


class CounterPositionCheckFailedError(CounterPositionValidatorError):
    """Raised when the bounded steelman-quality model call itself fails: a
    transport error, or a response that never parsed as usable JSON (or
    never carried a real verdict) within `complete_json`'s bounded re-ask
    budget."""


class SamePassModelError(CounterPositionValidatorError):
    """Raised when `steelman_pass_name` resolves (via
    `client.model_for_pass`) to the same model as `SYNTHESIZE_PASS_NAME` --
    mirrors `axial.validators.attribution.SamePassModelError` exactly: the
    steelman-quality check must never run under the model that generated the
    counter-position it is grading (§7.9, charter §2). Raised before any
    model call is made."""

    def __init__(self, pass_name: str, model: str):
        self.pass_name = pass_name
        self.model = model
        super().__init__(
            f"the steelman-quality check (pass_name={pass_name!r}) resolves to "
            f"model {model!r}, the SAME model as the synthesis pass "
            f"(pass_name={SYNTHESIZE_PASS_NAME!r}) -- configure model_by_pass "
            "so the steelman-quality check runs under a different model family "
            "than the pass that generated the counter-position it checks"
        )


@dataclass(frozen=True)
class ContestedResult:
    """Whether the brief is contested (§7.8), and which signal fired
    (`None` when uncontested). Persisted on the report regardless of
    pass/fail so the tunable rule can be tuned on evidence."""

    contested: bool
    signal: str | None


@dataclass(frozen=True)
class SteelmanCheck:
    """The bounded steelman-quality check's outcome. `ran` is `False` (and
    `verdict`/`detail` are `None`) whenever the counter-position section
    itself is not genuinely present -- zero model calls in that case."""

    ran: bool
    verdict: str | None
    detail: str | None


@dataclass(frozen=True)
class CounterPositionFailure:
    """One failed mechanical check, with a human-readable detail."""

    reason: str
    detail: str


@dataclass(frozen=True)
class CounterPositionReport:
    """The validator's whole verdict. `passed` is `True` only when
    `failures` is empty -- the steelman check never contributes a failure
    in this slice, it only informs `steelman`."""

    passed: bool
    contested: ContestedResult
    failures: list[CounterPositionFailure]
    steelman: SteelmanCheck


def _resolve_min_distinct_theory_schools(config_path: Path) -> int:
    if not config_path.is_file():
        return DEFAULT_MIN_DISTINCT_THEORY_SCHOOLS
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    contested_config = document.get("contested_detection") or {}
    return int(
        contested_config.get("min_distinct_theory_schools", DEFAULT_MIN_DISTINCT_THEORY_SCHOOLS)
    )


def _evidence_chunk_ids(claims: list[Any]) -> list[str]:
    """The deduplicated, ordered set of chunk ids ("this run's evidence")
    cited across every claim's `grounds` -- the same union §7.7's coverage
    map reads to compute `evidence_chunk_count`. Artifact grounds are
    skipped: artifacts carry no `theory_school`/`role_in_argument`."""
    seen: dict[str, None] = {}
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        for entry in claim.get("grounds") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("ref_type") == "chunk":
                ref_id = entry.get("ref_id")
                if isinstance(ref_id, str) and ref_id:
                    seen[ref_id] = None
    return list(seen)


def _detect_contested(
    claims: list[Any], *, vault_dir: Path | None, min_distinct_theory_schools: int
) -> ContestedResult:
    """The §7.8 contested predicate, over the evidence resolved from the
    record's own claims -- never the brief's wording. A chunk id that fails
    to resolve is skipped here: grounds-resolution failures are the
    attribution validator's own job (§7.9), not this one's."""
    schools: set[str] = set()
    has_counter_position_role = False

    for chunk_id in _evidence_chunk_ids(claims):
        try:
            chunk = get_chunk(chunk_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            continue
        primary = (chunk.theory_school or {}).get("primary")
        if isinstance(primary, str) and primary not in _THEORY_SCHOOL_SENTINEL_VALUES:
            schools.add(primary)
        if chunk.role_in_argument == COUNTER_POSITION_ROLE_VALUE:
            has_counter_position_role = True

    if len(schools) >= min_distinct_theory_schools:
        return ContestedResult(contested=True, signal=SIGNAL_THEORY_SCHOOL_SPREAD)
    if has_counter_position_role:
        return ContestedResult(contested=True, signal=SIGNAL_ROLE_COUNTER_POSITION)
    return ContestedResult(contested=False, signal=None)


def _is_present_with_grounds(counter_position: dict[str, Any]) -> bool:
    grounds = counter_position.get("grounds")
    return counter_position.get("present") is True and isinstance(grounds, list) and bool(grounds)


def _is_disclosed_one_sided(counter_position: dict[str, Any]) -> bool:
    reason = counter_position.get("one_sided_reason")
    return counter_position.get("corpus_one_sided") is True and bool(
        isinstance(reason, str) and reason.strip()
    )


def _check_presence_or_disclosure(
    counter_position: dict[str, Any],
) -> CounterPositionFailure | None:
    """The §7.8 mechanical presence-or-disclosure check, called only on a
    contested brief. `present: true` with empty `grounds` is not a real
    counter-position (a stance with no grounds), and `corpus_one_sided: true`
    with an empty/absent reason is not a real disclosure -- both fail
    exactly as absence would."""
    if _is_present_with_grounds(counter_position) or _is_disclosed_one_sided(counter_position):
        return None
    return CounterPositionFailure(
        reason=REASON_CONTESTED_WITHOUT_COUNTER_POSITION,
        detail=(
            "the brief is contested and the record's counter_position section is "
            "neither present with non-empty grounds nor disclosed as corpus "
            "one-sided with a reason (§7.8)"
        ),
    )


def _compose_steelman_prompt(counter_position: dict[str, Any], grounds_texts: list[str]) -> str:
    lines = "\n".join(f"- {text}" for text in grounds_texts) or "(no grounds text resolved)"
    stance = counter_position.get("stance") or ""
    return f"""You are the independent steelman-quality check of an analysis engine's stage-5 counter-position validator (specs/PHASE-B.md §7.9). You are NOT the model that generated this counter-position -- you are judging its quality.

The counter-position's stated stance:
"{stance}"

The corpus grounds it cites:
{lines}

Judge whether this stance represents the opposing school at its STRONGEST (a steelman), grounded in the cited material, or whether it is a weakened, dismissible version of the opposing view (a strawman).

Return ONLY this JSON object, no prose and no code fence:
{{"verdict": "steelman" or "strawman", "detail": "<one sentence why>"}}"""


def _resolve_grounds_text(grounds: list[Any], *, vault_dir: Path | None) -> list[str]:
    """Best-effort chunk text for every chunk-typed grounds entry, anchoring
    the steelman judge to real corpus material (§7.9). A grounds pointer
    that fails to resolve is skipped -- grounds resolution is the
    attribution validator's own job, not this check's."""
    texts: list[str] = []
    for entry in grounds:
        if not isinstance(entry, dict) or entry.get("ref_type") != "chunk":
            continue
        ref_id = entry.get("ref_id")
        if not isinstance(ref_id, str) or not ref_id:
            continue
        try:
            chunk = get_chunk(ref_id, vault_dir=vault_dir)
        except ChunkNotFoundError:
            continue
        texts.append(chunk.chunk_text)
    return texts


def _run_steelman_check(
    counter_position: dict[str, Any],
    *,
    client: LLMClient,
    vault_dir: Path | None,
    steelman_pass_name: str,
) -> SteelmanCheck:
    synthesis_model = client.model_for_pass(SYNTHESIZE_PASS_NAME)
    steelman_model = client.model_for_pass(steelman_pass_name)
    if steelman_model == synthesis_model:
        raise SamePassModelError(steelman_pass_name, steelman_model)

    grounds_texts = _resolve_grounds_text(
        counter_position.get("grounds") or [], vault_dir=vault_dir
    )
    prompt = _compose_steelman_prompt(counter_position, grounds_texts)
    try:
        raw = complete_json(client, prompt, pass_name=steelman_pass_name)
    except (LLMError, httpx.HTTPError, ModelJsonError) as exc:
        raise CounterPositionCheckFailedError(f"steelman-quality check call failed: {exc}") from exc

    data = parse_model_json(raw)
    verdict = data.get("verdict") if isinstance(data, dict) else None
    if verdict not in {VERDICT_STEELMAN, VERDICT_STRAWMAN}:
        raise CounterPositionCheckFailedError(
            f"steelman-quality response is missing a valid 'verdict': {data!r}"
        )
    detail = data.get("detail") if isinstance(data.get("detail"), str) else ""
    return SteelmanCheck(ran=True, verdict=verdict, detail=detail)


def validate_counter_position(
    record: dict[str, Any],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    steelman_pass_name: str = COUNTER_POSITION_PASS_NAME,
) -> CounterPositionReport:
    """Validate `record`'s §7.8 counter-position section against its own
    claim-graph evidence. Never edits `record` -- returns a report, nothing
    more.

    1. Detects contested-ness (`ContestedResult`) from the evidence resolved
       out of `record["claims"]`'s grounds.
    2. On a contested brief only, checks the section is present-with-grounds
       or disclosed-one-sided-with-reason; failing both is
       `REASON_CONTESTED_WITHOUT_COUNTER_POSITION` and blocks release.
    3. Runs the bounded steelman-quality check whenever the section is
       genuinely present-with-grounds, regardless of contested-ness --
       zero model calls otherwise.
    """
    claims = record.get("claims") or []
    min_distinct = _resolve_min_distinct_theory_schools(config_path)
    contested = _detect_contested(
        claims, vault_dir=vault_dir, min_distinct_theory_schools=min_distinct
    )

    counter_position = record.get("counter_position") or {}
    failures: list[CounterPositionFailure] = []
    if contested.contested:
        failure = _check_presence_or_disclosure(counter_position)
        if failure is not None:
            failures.append(failure)

    steelman = SteelmanCheck(ran=False, verdict=None, detail=None)
    if _is_present_with_grounds(counter_position):
        steelman = _run_steelman_check(
            counter_position,
            client=client,
            vault_dir=vault_dir,
            steelman_pass_name=steelman_pass_name,
        )

    return CounterPositionReport(
        passed=not failures, contested=contested, failures=failures, steelman=steelman
    )


def format_counter_position_report(report: CounterPositionReport) -> str:
    """Render `report` as human-readable text for the CLI (`axial brief
    validate`): the contested verdict + signal, a one-line pass/fail
    verdict plus one line per failure, and the steelman-quality verdict
    when the check ran."""
    lines = [
        f"counter-position validator: contested={report.contested.contested} "
        f"signal={report.contested.signal!r}"
    ]
    if report.passed:
        lines.append("counter-position validator: PASS (0 failures)")
    else:
        lines.append(f"counter-position validator: FAIL ({len(report.failures)} failure(s))")
        for failure in report.failures:
            lines.append(f"  {failure.reason} -- {failure.detail}")
    if report.steelman.ran:
        lines.append(
            f"counter-position validator: steelman-quality={report.steelman.verdict} "
            f"({report.steelman.detail})"
        )
    return "\n".join(lines)
