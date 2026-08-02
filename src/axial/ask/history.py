"""Past `axial ask` turns, found by what they were asked (issue #536).

Every persisted analysis record already carries its own `brief.case`/
`brief.request` (`axial.answer.record.build_record`, §7.3); this module
lists them by recency and reopens one by the number `list_past_turns` gave
it, so an analyst never needs to know a `brief_id` hash or a file path
(#536's own acceptance: "reopening a past answer needs no knowledge of
hashes or paths").

Reads only artifacts `axial.answer.record.run_brief` already wrote --
`<analyses_dir>/<brief_id>.json` and `<runs_dir>/<brief_id>.json` (the §7.15
run report) -- never a model call, and never a second, independently
computed figure: the headline this module lists is `report[
'response_quality']['cross_source_rate']`, read straight off the persisted
report exactly as `axial.answer.render.render_analyst_answer` (#535) does,
so listing and reopening can never disagree about it.

`asked_at` is the record file's own mtime. §7.3's record shape carries no
timestamp field -- it is FIRM, and this is read-only history over what
already exists, not a reason to grow it -- and a file's own write time is
the honest, zero-schema-change proxy for "when it was asked": `persist_
record` writes it once, at the very end of the run this lists.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_analyses_dir, default_runs_dir

# The §7.2 disposition vocabulary, worded plainly (issue #536's own "what
# happened (proceed, bounded, refused)"). A disposition this map does not
# recognise renders as itself rather than crashing -- `DISPOSITIONS`
# (`axial.brief.interrogate`) is not imported here to keep this module's
# only dependency on the record shape at the two keys it actually reads.
_DISPOSITION_WORDS = {
    "proceed": "proceeded",
    "proceed_bounded": "proceeded, bounded",
    "refuse": "refused",
}


@dataclass(frozen=True)
class PastTurn:
    """One past turn: everything `axial ask --list` shows for it, joined
    from its persisted record and its persisted run report -- no third,
    separately computed figure."""

    brief_id: str
    asked_at: float
    case: str
    question: str
    disposition: str
    cross_source_rate: float | None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def list_past_turns(
    *,
    analyses_dir: Path | None = None,
    runs_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> list[PastTurn]:
    """Every past turn with a readable analysis record, most recently asked
    first. An empty/never-run `<analyses_dir>` yields an empty list rather
    than raising -- a normal state for a fresh install, not an error."""
    analyses_dir = (
        Path(analyses_dir) if analyses_dir is not None else default_analyses_dir(config_path)
    )
    runs_dir = Path(runs_dir) if runs_dir is not None else default_runs_dir(config_path)

    turns: list[PastTurn] = []
    if not analyses_dir.is_dir():
        return turns
    for path in analyses_dir.glob("*.json"):
        record = _read_json(path)
        brief_id = record.get("brief_id")
        if not isinstance(brief_id, str) or not brief_id:
            continue
        report = _read_json(runs_dir / f"{brief_id}.json")
        cross_source = (report.get("response_quality") or {}).get("cross_source_rate") or {}
        brief = record.get("brief") or {}
        disposition = (record.get("interrogation") or {}).get("disposition")
        turns.append(
            PastTurn(
                brief_id=brief_id,
                asked_at=path.stat().st_mtime,
                case=brief.get("case", ""),
                question=brief.get("request", ""),
                disposition=_DISPOSITION_WORDS.get(disposition, disposition or "unknown"),
                cross_source_rate=cross_source.get("value"),
            )
        )
    turns.sort(key=lambda turn: turn.asked_at, reverse=True)
    return turns


def load_turn(
    brief_id: str,
    *,
    analyses_dir: Path | None = None,
    runs_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """`(record, report)` for `brief_id`, or `None` when no record exists --
    the exact pair `axial.answer.render.render_analyst_answer` (#535) needs
    to render this turn again exactly as it was first answered."""
    analyses_dir = (
        Path(analyses_dir) if analyses_dir is not None else default_analyses_dir(config_path)
    )
    runs_dir = Path(runs_dir) if runs_dir is not None else default_runs_dir(config_path)

    record_path = analyses_dir / f"{brief_id}.json"
    if not record_path.is_file():
        return None
    record = _read_json(record_path)
    if not record:
        return None
    return record, _read_json(runs_dir / f"{brief_id}.json")
