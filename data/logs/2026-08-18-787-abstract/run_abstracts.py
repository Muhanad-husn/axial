"""Slice 04's measurement: one abstract per persisted paper record.

Reads the 10 records in `data/papers/`, composes an abstract for each from the
plan's thesis statement and the drafted section prose, and writes one
`run.jsonl` record per paper. No drafting call, no retrieval, no record is
written back -- this reads what is already on disk and produces text to read
by eye.

The substrate matters: these 10 include papers drafted from real analyst
questions through `axial ask`, not only the nine easy dev briefs whose
`shape.band` came back `strong` 35 times out of 35 (see the feature README).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from axial.llm import get_client  # noqa: E402
from axial.paper.abstract import AbstractError, run_abstract  # noqa: E402
from axial.paper.render import plan_sections, prose_by_section  # noqa: E402

HERE = Path(__file__).resolve().parent
PAPERS = Path(__file__).resolve().parents[2] / "papers"
OUT = HERE / "run.jsonl"


def emit(handle, payload: dict) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    handle.flush()
    import os

    os.fsync(handle.fileno())


def main() -> int:
    records = sorted(PAPERS.glob("*.json"))
    print(f"{len(records)} paper records", flush=True)
    client = get_client()

    with OUT.open("a", encoding="utf-8") as handle:
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
                result = run_abstract(client, thesis, sections)
            except AbstractError as exc:
                emit(
                    handle,
                    {
                        "paper": path.stem,
                        "status": "failed",
                        "error": str(exc),
                        "elapsed": round(time.time() - started, 1),
                    },
                )
                print(f"[{path.stem}] FAILED: {exc}", flush=True)
                continue

            words = len(result.text.split())
            emit(
                handle,
                {
                    "paper": path.stem,
                    "status": "ok",
                    "thesis": thesis,
                    "model": result.model,
                    "cost": result.cost,
                    "words": words,
                    "elapsed": round(time.time() - started, 1),
                    "abstract": result.text,
                },
            )
            print(
                f"[{path.stem}] {words} words, {round(time.time() - started, 1)}s, "
                f"${result.cost}",
                flush=True,
            )

    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
