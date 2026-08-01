"""The sim case set as a read contract (specs/PHASE-B.md §9.3, issue #491,
#560). `evals/cases/sim/` holds 29 committed cases, ids only (DEC-23). Two of
their fields are accuracy oracles §10.0 names, and until issue #491 neither
was read by anything in `src/`:

- `required_citation_legs` -- the phase's one MECHANICAL accuracy oracle:
  did this run's claim grounds reach the sources the case names? No
  judgment, no referee, no model call. A case states a list of legs, each
  `{"leg": "<short name>", "any_of": ["<source_id>", ...]}`; a leg is
  reached when the run's grounds cite ANY source in its `any_of` (issue
  #560 -- a flat AND list of ids cannot express "this leg is satisfied by
  any book that carries it"). A case that instead states the older flat
  `required_citation_source_ids` (a bare string list) is read as one leg per
  id, exactly preserving the score that shape has always produced. When a
  case states both, `required_citation_legs` wins and the flat field is
  ignored.
- `instant_dismissal_criteria` -- non-empty on every committed case, the
  sharpest judged oracle the set holds, since a case says plainly what would
  get the paper rejected on sight. `axial.answer.dismissal` runs it.

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
class RequiredLeg:
    """One citation demand a case's question makes (issue #560). Reached
    when the run's claim grounds cite any source in `any_of` -- OR
    semantics within a leg, since one book can carry a leg that a different
    book about the same author cannot."""

    leg: str
    any_of: tuple[str, ...]


@dataclass(frozen=True)
class SimCase:
    """One §9.3 case, narrowed to the two oracle fields §10.0 reads."""

    case_id: str
    required_citation_legs: tuple[RequiredLeg, ...]
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


def _legs(payload: dict) -> tuple[RequiredLeg, ...]:
    """`required_citation_legs` if the case states it, else the flat
    `required_citation_source_ids` normalised into one leg per id -- the
    back-compat path that keeps the cases not being re-authored in this
    slice scoring exactly as before. A leg with an empty `any_of` after
    dropping non-string entries is dropped: it can never be reached and
    would only silently deflate the denominator."""
    raw_legs = payload.get("required_citation_legs")
    if isinstance(raw_legs, list):
        legs = []
        for entry in raw_legs:
            if not isinstance(entry, dict):
                continue
            name = entry.get("leg")
            any_of = tuple(_string_list(entry.get("any_of")))
            if isinstance(name, str) and name.strip() and any_of:
                legs.append(RequiredLeg(leg=name, any_of=any_of))
        return tuple(legs)
    return tuple(
        RequiredLeg(leg=source_id, any_of=(source_id,))
        for source_id in _string_list(payload.get("required_citation_source_ids"))
    )


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
        required_citation_legs=_legs(payload),
        instant_dismissal_criteria=_string_list(payload.get("instant_dismissal_criteria")),
    )
