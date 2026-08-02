"""The counter-position rung-3 gate for paper records (specs/PHASE-C.md
§10.1, §7.14, §8 P0-14; issue #608, B3 of #605).

One metric, **mechanical, zero model calls**: `paper_counter_position_
presence_rate` -- the share of **contested** paper records (§7.14's
four-arm predicate, `axial.validators.counter_position.detect_paper_
contested`) whose `counter_position` is present-with-grounds or discloses
one-sidedness with a reason. An uncontested paper leaves the denominator
entirely -- it never counts as a pass, mirroring PHASE-B's own `synthesis-
quality` gate (`axial.gates.synthesis_quality`) for its own `counter_
position_presence_rate`. A `failed` counter-position section (§7.3)
satisfies neither limb, exactly as `axial.validators.counter_position.
_check_presence_or_disclosure` already treats it (PR #558).

**Threshold 1.00, a distinct metric name from Phase-B's own gate.**
Phase-B's `synthesis-quality` gate scores the SAME conceptual check at
threshold 0.95 under the metric name `counter_position_presence_rate`.
`axial.gates.harness.resolve_threshold`/`comparison_for` are keyed on
metric name ALONE, shared across every gate that ever reports one --
reusing that exact name here would silently resolve Phase-B's 0.95 rather
than Phase C's own hard 1.00 (§10.1). `paper_counter_position_presence_
rate` is a new, independently-tunable metric name for exactly that reason,
not a re-derivation of the check itself.

**Takes only the mechanical half.** `axial.validators.counter_position.
validate_counter_position` also runs a bounded model-judged steelman-
quality check whenever a counter-position is genuinely present-with-
grounds -- this gate never calls it. The model-judged half belongs to the
eval track (§10.1, §10.2), mirroring PHASE-B's own split at §7.9/§10: this
module reuses `_check_presence_or_disclosure` and `detect_paper_contested`
directly rather than `validate_counter_position` wholesale, precisely to
avoid the model call that function's own presence check would otherwise
trigger as a side effect.

**The §7.14 fourth arm needs a paper's named SOURCE records.** A paper
record's `source_analyses` (§7.3) names the Phase-B analysis records it
draws on; `_load_source_records` reads them from `analyses_dir` (default
`axial.paths.default_analyses_dir`), mirroring `axial.gates.provenance`'s
own `_load_origin_record`/`analyses_dir` convention -- a small local loader
duplicated here rather than imported, for the same reason `axial.gates.
provenance`'s own module docstring gives for its local `_BAND_RANK` copy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from axial.gates.harness import GateReport, MetricResult, build_metric_result, not_scoreable_metric
from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH, LLMClient
from axial.paths import default_analyses_dir
from axial.validators.counter_position import _check_presence_or_disclosure, detect_paper_contested

GATE_NAME = "counter-position"


class CounterPositionGateError(Exception):
    """Base class for all paper counter-position-gate errors."""


class UnresolvableSourceRecordError(CounterPositionGateError):
    """Raised when a paper record's `source_analyses` names an analysis
    record that cannot be loaded from `analyses_dir` -- the §7.14 fourth
    arm cannot be checked against a source record this gate cannot read."""

    def __init__(self, brief_id: str, path: Path):
        self.brief_id = brief_id
        self.path = path
        super().__init__(
            f"paper record names source analysis {brief_id!r}, but no record exists at "
            f"{path} -- the counter-position gate cannot check the §7.14 fourth arm "
            "against a source record it cannot read"
        )


def _load_source_records(
    paper_record: dict[str, Any], *, analyses_dir: Path
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for brief_id in paper_record.get("source_analyses") or []:
        path = Path(analyses_dir) / f"{brief_id}.json"
        if not path.is_file():
            raise UnresolvableSourceRecordError(str(brief_id), path)
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _paper_id(record: dict[str, Any], index: int) -> str:
    """Best-effort paper identifier for the failing-record detail, mirroring
    `axial.gates.synthesis_quality._record_id`'s own positional fallback."""
    paper_brief_id = record.get("paper_brief_id")
    return (
        paper_brief_id
        if isinstance(paper_brief_id, str) and paper_brief_id
        else f"<record #{index}>"
    )


def _score_presence_rate(
    records: list[dict[str, Any]],
    *,
    vault_dir: Path | None,
    names_dir: Path | None,
    analyses_dir: Path,
    config_path: Path,
) -> MetricResult:
    contested_total = 0
    present_or_disclosed = 0
    failing_brief_ids: list[str] = []

    for index, record in enumerate(records, start=1):
        source_records = _load_source_records(record, analyses_dir=analyses_dir)
        coverage_map = record.get("coverage_map") or {}
        scope = sorted(coverage_map)
        contested = detect_paper_contested(
            record.get("claims") or [],
            source_records,
            scope=scope,
            vault_dir=vault_dir,
            names_dir=names_dir,
        )
        if not contested.contested:
            continue
        contested_total += 1
        failure = _check_presence_or_disclosure(record.get("counter_position") or {})
        if failure is None:
            present_or_disclosed += 1
        else:
            failing_brief_ids.append(_paper_id(record, index))

    if contested_total == 0:
        return not_scoreable_metric(
            "paper_counter_position_presence_rate",
            reason="no contested subset to evaluate (records carry claims, but none are contested)",
            config_path=config_path,
        )
    return build_metric_result(
        "paper_counter_position_presence_rate",
        numerator=present_or_disclosed,
        denominator=contested_total,
        config_path=config_path,
        detail={"failing_brief_ids": failing_brief_ids} if failing_brief_ids else {},
        empty_denominator_fails=True,
    )


def run_counter_position_gate(
    records: list[dict[str, Any]],
    *,
    client: LLMClient,
    vault_dir: Path | None = None,
    corpus_pin: str | None,
    trusted: bool,
    names_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    analyses_dir: Path | None = None,
) -> GateReport:
    """Score `paper_counter_position_presence_rate` over `records` (Phase-C
    paper records, `axial.gates.harness.load_paper_records`). `client` is
    accepted only to match `axial.gates.run_gate`'s shared per-gate dispatch
    signature -- it is never called: the check is mechanical, zero model
    calls (module docstring). Raises `UnresolvableSourceRecordError` when a
    paper's `source_analyses` names a record this gate cannot load."""
    del client
    resolved_analyses_dir = analyses_dir if analyses_dir is not None else default_analyses_dir()
    metric = _score_presence_rate(
        records,
        vault_dir=vault_dir,
        names_dir=names_dir,
        analyses_dir=resolved_analyses_dir,
        config_path=config_path,
    )
    return GateReport(
        gate=GATE_NAME,
        corpus_pin=corpus_pin,
        trusted=trusted,
        metrics=[metric],
    )
