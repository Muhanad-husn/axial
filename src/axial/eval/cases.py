"""The sim case set as a read contract (specs/PHASE-B.md §9.3, issue #491).

`evals/cases/sim/` holds 21 committed cases, ids only (DEC-23). Two of their
fields are accuracy oracles §10.0 names, and until this module neither was
read by anything in `src/`:

- `required_citation_source_ids` -- the phase's one MECHANICAL accuracy
  oracle: did this run's claim grounds reach the sources the case names? No
  judgment, no referee, no model call. Verified 2026-07-29 to still resolve
  after the Phase A v1 rebuild (28 distinct ids across 97 references).
- `instant_dismissal_criteria` -- non-empty on all 21 cases, the sharpest
  judged oracle the set holds, since a case says plainly what would get the
  paper rejected on sight. `axial.answer.dismissal` runs it.

`expected_answer` is deliberately NOT exposed here. §9.3 retires it as the
primary referee and forbids putting it in a reviewer packet; a reader that
hands it back invites exactly that.

The join from a brief to its case is the file stem: `config/briefs/smoke/
P3-01.yaml` is scored against `evals/cases/sim/P3-01.json`. A brief with no
case file of that name simply has no oracle, which `load_case` reports as
`None` rather than as an error -- most briefs (every dev fixture, every
adversarial seed) have none by construction.

Zero model calls, zero vault reads: this module only parses committed JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

CASES_DIR = Path("evals/cases/sim")


@dataclass(frozen=True)
class SimCase:
    """One §9.3 case, narrowed to the two oracle fields §10.0 reads."""

    case_id: str
    required_citation_source_ids: list[str]
    instant_dismissal_criteria: list[str]


def default_cases_dir() -> Path:
    """Where the committed sim cases live. A plain constant rather than a
    `config/pipeline.yaml` key: `evals/` is repo content, not a `data/`
    pipeline directory, and no caller has ever needed to move it."""
    return CASES_DIR


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def load_case(case_id: str, *, cases_dir: Path | None = None) -> SimCase | None:
    """The case named `case_id`, or `None` when no such file exists or it is
    unreadable. Never raises on a missing or malformed case: the case set is
    an oracle a run is scored against, not a precondition of the run, so an
    absent one costs the accuracy figure and nothing else (the caller
    discloses it as not-scored with a reason)."""
    directory = Path(cases_dir) if cases_dir is not None else default_cases_dir()
    path = directory / f"{case_id}.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return SimCase(
        case_id=str(payload.get("case_id") or case_id),
        required_citation_source_ids=_string_list(payload.get("required_citation_source_ids")),
        instant_dismissal_criteria=_string_list(payload.get("instant_dismissal_criteria")),
    )
