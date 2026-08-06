"""Re-ask only the judge calls whose verdict came back truncated.

`judge.py`'s first pass capped completions at 4000 tokens; three judges spent
that on reasoning and returned a half-written JSON object. This re-asks those
(unit, model) pairs ONLY -- the judges that answered are never paid for twice --
and appends a `repair` record whose verdict supersedes the truncated one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LOG_DIR = Path(r"D:\axial\data\logs\2026-08-05-luna-vs-glm")
sys.path.insert(0, str(LOG_DIR))

import judge  # noqa: E402


def failed_pairs() -> dict[str, set[str]]:
    """unit_key -> the judge models whose latest verdict is unusable."""
    latest: dict[tuple[str, str], dict] = {}
    for line in (LOG_DIR / "judgments.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        for entry in event.get("judges") or []:
            latest[(event["unit_key"], entry["model"])] = entry
    failed: dict[str, set[str]] = {}
    for (unit_key, model), entry in latest.items():
        verdict = entry.get("verdict") or {}
        overall = (verdict.get("overall") or {}).get("winner")
        if "error" in entry or "parse_error" in verdict or overall is None:
            failed.setdefault(unit_key, set()).add(model)
    return failed


def main() -> int:
    failed = failed_pairs()
    if not failed:
        print("nothing to repair")
        return 0
    print("repairing:", {k: sorted(v) for k, v in failed.items()})

    judge.COLLECT = []
    judge.synthesis_units(set())
    judge.counter_units(set())
    judge.paper_units(set())
    prompts = {unit_key: (prompt, meta) for unit_key, prompt, meta in judge.COLLECT}
    judge.COLLECT = None

    for unit_key, models in failed.items():
        if unit_key not in prompts:
            print(f"skip {unit_key}: prompt no longer rebuildable")
            continue
        prompt, meta = prompts[unit_key]
        results = []
        for model, price_in, price_out in judge.JUDGES:
            if model not in models:
                continue
            try:
                results.append(judge.ask(model, prompt, price_in, price_out))
            except Exception as exc:  # noqa: BLE001
                results.append({"model": model, "error": f"{type(exc).__name__}: {exc}"[:400]})
        judge.journal({"unit_key": unit_key, "repair": True, **meta, "judges": results})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
