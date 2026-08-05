"""Issue #700 half 1: does Gather agree with itself?

#700 has one clean case -- `state-building`, recorded as a disagreement at
06:36 and returned null by the same model on the same reconstructed packet at
16:20, with three independent judges saying null was right. One case is not a
rate. This is the rate: the direct analogue of what #695 did for merge.

Method, and why it is the cheap version:

- Only SINGLE-BATCH names are eligible. A single-batch name is decided by one
  call with no merge step, so a re-ask is a clean repeat of one question. A
  multi-batch name folds several calls plus a merge, and a difference there
  could come from any of them.
- The packet is reconstructed from the record's own `chunk_ids` through
  `axial.gather`'s own `build_packets`/`split_into_batches` -- the same path
  `axial.gather_eval` already uses -- and the reconstructed `GatherJob.key`
  must equal the recorded `name_key`. That equality IS the byte-identical
  input guarantee; a name whose key has moved is skipped, not measured.
- The comparison is null vs non-null: did the pass find a disagreement at all?
  That needs no judge model, and it is exactly the failure #700 documents. Two
  differently-worded accounts of the same disagreement are NOT counted here as
  a disagreement -- this measures the floor, not the ceiling, and a wording
  judge would cost a second pass to answer a question nobody has asked yet.

RUN THIS BEFORE #697's position backfill. The backfill writes `position` onto
6,148 notes and `build_packets` renders that key into the packet, so after it
lands no recorded name reproduces its key and this control arm is gone.

Read-only over the corpus. Writes nothing but its own log under `data/logs/`.
Never touches `data/names/disagreements.jsonl`.

Run from D:\\axial (the main checkout -- `data/` does not exist in a worktree):

    uv run python scratchpad/probe_700_gather_agreement.py --sample 150 --workers 12

`--arms ""` is not a thing here; `--sample 0` does the free dry run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from axial.gather import (
    DEFAULT_DISAGREEMENTS_PATH,
    GatherJob,
    _gather_one,
    build_packets,
    load_gather_context,
    split_into_batches,
)
from axial.llm import GATHER_PASS_NAME, get_client, usage_and_cost_by_pass

DATA_DIR = Path("data")
ANSWERS_DIR = DATA_DIR / "answers"
SOURCE_META_DIR = DATA_DIR / "source_meta"
LOG_DIR = DATA_DIR / "logs" / "2026-08-05-700-gather-self-agreement"

LOG_DIR.mkdir(parents=True, exist_ok=True)

if (LOG_DIR / "run.jsonl").exists():
    n = 1
    while (LOG_DIR / f"run-{n}.jsonl").exists():
        n += 1
    (LOG_DIR / "run.jsonl").rename(LOG_DIR / f"run-{n}.jsonl")

run_log = (LOG_DIR / "run.jsonl").open("w", encoding="utf-8")
console_log = (LOG_DIR / "console.log").open("w", encoding="utf-8")


def log(event: str, **fields: Any) -> None:
    record = {"event": event, "ts": time.time(), **fields}
    run_log.write(json.dumps(record, ensure_ascii=False) + "\n")
    run_log.flush()
    line = f"{event}: " + ", ".join(f"{k}={v}" for k, v in fields.items())
    print(line, flush=True)
    console_log.write(line + "\n")
    console_log.flush()


def load_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=150)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    t0 = time.time()
    answers_by_chunk_id, author_year = load_gather_context(ANSWERS_DIR, SOURCE_META_DIR)
    log(
        "context_loaded",
        notes=len(answers_by_chunk_id),
        sources=len(author_year),
        elapsed=round(time.time() - t0, 1),
    )

    records = load_records(DEFAULT_DISAGREEMENTS_PATH)
    log("disagreements_loaded", count=len(records))

    eligible: list[dict[str, Any]] = []
    reasons = {"multi_batch": 0, "key_moved": 0, "no_packets": 0, "resplit": 0}
    for record in records:
        if len(record.get("batches") or []) != 1:
            reasons["multi_batch"] += 1
            continue
        packets = build_packets(record["chunk_ids"], answers_by_chunk_id, author_year)
        if not packets:
            reasons["no_packets"] += 1
            continue
        batches = split_into_batches(packets)
        if len(batches) != 1:
            reasons["resplit"] += 1
            continue
        job = GatherJob(
            canonical=record["canonical"],
            batches=tuple(tuple(batch) for batch in batches),
        )
        if job.key != record["name_key"]:
            reasons["key_moved"] += 1
            continue
        eligible.append({"record": record, "job": job})

    log("eligible", reproducible=len(eligible), **reasons)
    if not eligible or args.sample == 0:
        log("stopped", reason="dry run" if args.sample == 0 else "nothing eligible")
        return

    eligible.sort(key=lambda item: item["record"]["name_key"])
    size = min(args.sample, len(eligible))
    stride = max(1, len(eligible) // size)
    sample = [eligible[i * stride] for i in range(size)]
    log("sampled", n=len(sample), stride=stride, of=len(eligible))

    with (LOG_DIR / "baseline.jsonl").open("w", encoding="utf-8") as handle:
        for item in sample:
            handle.write(json.dumps(item["record"], ensure_ascii=False) + "\n")

    client = get_client()
    log(
        "arm_start",
        model=client.model_for_pass(GATHER_PASS_NAME),
        members_note="single-batch names only",
    )

    started = time.time()
    results: list[dict[str, Any]] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_gather_one, item["job"], client): item for item in sample}
        for done in as_completed(futures):
            item = futures[done]
            _job, fresh, failure = done.result()
            recorded_has = item["record"].get("disagreement") is not None
            if fresh is None:
                failures += 1
                agrees = None
                fresh_has = None
            else:
                fresh_has = fresh.get("disagreement") is not None
                agrees = fresh_has == recorded_has
            row = {
                "name_key": item["record"]["name_key"],
                "canonical": item["record"]["canonical"],
                "member_count": len(item["record"]["chunk_ids"]),
                "recorded_has_disagreement": recorded_has,
                "fresh_has_disagreement": fresh_has,
                "agrees": agrees,
                "recorded_disagreement": item["record"].get("disagreement"),
                "fresh_disagreement": (fresh or {}).get("disagreement"),
                "failure": failure,
            }
            results.append(row)
            log(
                "reask", canonical=row["canonical"], member_count=row["member_count"], agrees=agrees
            )

    judged = [r for r in results if r["agrees"] is not None]
    flips = [r for r in judged if not r["agrees"]]
    # The two directions are not the same defect. A recorded disagreement that
    # comes back null is #700's own case -- the vault is shipping a page whose
    # claim the pass will not stand behind. A recorded null that comes back
    # with a disagreement is a missed page, which costs coverage, not truth.
    invented_then_dropped = [r for r in flips if r["recorded_has_disagreement"]]
    missed_then_found = [r for r in flips if not r["recorded_has_disagreement"]]

    by_size: dict[str, dict[str, int]] = {}
    for row in judged:
        count = row["member_count"]
        band = "2-4" if count <= 4 else "5-9" if count <= 9 else "10+"
        bucket = by_size.setdefault(band, {"n": 0, "flips": 0})
        bucket["n"] += 1
        bucket["flips"] += 0 if row["agrees"] else 1

    summary = {
        "judged": len(judged),
        "failures": failures,
        "self_disagreement": len(flips) / len(judged) if judged else None,
        "recorded_disagreement_now_null": len(invented_then_dropped),
        "recorded_null_now_disagreement": len(missed_then_found),
        "recorded_non_null": sum(1 for r in judged if r["recorded_has_disagreement"]),
        "by_member_count": by_size,
        "elapsed_s": round(time.time() - started, 1),
        "usage": usage_and_cost_by_pass(
            client, {GATHER_PASS_NAME: client.model_for_pass(GATHER_PASS_NAME)}
        ),
    }
    log("arm_done", **{k: v for k, v in summary.items() if k != "usage"})

    with (LOG_DIR / "results.jsonl").open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (LOG_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log("done")
    run_log.close()
    console_log.close()


if __name__ == "__main__":
    sys.exit(main())
