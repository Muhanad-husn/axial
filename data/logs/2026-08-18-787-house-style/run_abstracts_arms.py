"""Slice 05's measurement: the same 10 abstracts, with and without the block.

Slice 04's harness (`data/logs/2026-08-18-787-abstract/run_abstracts.py`) with
one parameter added. Arm `control` composes the abstract prompt exactly as it
was before house style existed; arm `styled` passes the domain frame's block.
Everything else -- the records read, the fields written, the fsync per event --
is that harness unchanged.

    uv run python data/logs/2026-08-18-787-house-style/run_abstracts_arms.py control
    uv run python data/logs/2026-08-18-787-house-style/run_abstracts_arms.py styled

Each arm writes its own `run.<arm>.jsonl` and prints, at the end, how many of
the ten abstracts open with the formula slice 04 measured at 10 of 10. That
count is the primary signal; the block never names the string, so the count is
a consequence rather than the instruction restated.

No re-draft: the abstract call reads only the thesis and the prose already
persisted in `data/papers/`. About $0.026 and 35 seconds per arm at slice 04's
measured rate. NOT RUN by the builder -- the founder runs the paid arms.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from axial.llm import get_client  # noqa: E402
from axial.paper.abstract import AbstractError, run_abstract  # noqa: E402
from axial.paper.house_style import load_house_style  # noqa: E402
from axial.paper.render import plan_sections, prose_by_section  # noqa: E402

HERE = Path(__file__).resolve().parent
PAPERS = Path(__file__).resolve().parents[2] / "papers"

# The formula slice 04 found on 10 of 10 abstracts. Counted here, never stated
# to the model: naming it in the house-style block would measure instruction
# following on one string instead of whether house style reaches the prompt.
FORMULA = "this paper argues that"


def emit(handle, payload: dict) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def main() -> int:
    arm = sys.argv[1] if len(sys.argv) > 1 else ""
    if arm not in {"control", "styled"}:
        print("usage: run_abstracts_arms.py control|styled", flush=True)
        return 2

    house_style = load_house_style() if arm == "styled" else None
    if arm == "styled" and house_style is None:
        print("no house style found in the configured domain frame", flush=True)
        return 2

    out = HERE / f"run.{arm}.jsonl"
    records = sorted(PAPERS.glob("*.json"))
    print(f"arm={arm} {len(records)} paper records", flush=True)
    client = get_client()

    openings = 0
    written = 0
    with out.open("a", encoding="utf-8") as handle:
        for path in records:
            record = json.loads(path.read_text(encoding="utf-8"))
            plan = record.get("plan") or {}
            prose = prose_by_section(record)
            sections = [
                {
                    "heading": str(section.get("heading") or ""),
                    "prose": prose.get(str(section.get("section_id")), ""),
                }
                for section in plan_sections(record)
            ]
            thesis = str(plan.get("thesis_statement") or "")
            started = time.time()
            print(f"[{path.stem}] {len(sections)} sections ...", flush=True)
            try:
                result = run_abstract(client, thesis, sections, house_style)
            except AbstractError as exc:
                emit(
                    handle,
                    {
                        "arm": arm,
                        "paper": path.stem,
                        "status": "failed",
                        "error": str(exc),
                        "elapsed": round(time.time() - started, 1),
                    },
                )
                print(f"[{path.stem}] FAILED: {exc}", flush=True)
                continue

            opens_with_formula = result.text.strip().lower().startswith(FORMULA)
            openings += int(opens_with_formula)
            written += 1
            words = len(result.text.split())
            emit(
                handle,
                {
                    "arm": arm,
                    "paper": path.stem,
                    "status": "ok",
                    "thesis": thesis,
                    "model": result.model,
                    "cost": result.cost,
                    "words": words,
                    "opens_with_formula": opens_with_formula,
                    "elapsed": round(time.time() - started, 1),
                    "abstract": result.text,
                },
            )
            print(
                f"[{path.stem}] {words} words, {round(time.time() - started, 1)}s, "
                f"formula={opens_with_formula}",
                flush=True,
            )

    print(f"arm={arm}: {openings} of {written} open with {FORMULA!r}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
