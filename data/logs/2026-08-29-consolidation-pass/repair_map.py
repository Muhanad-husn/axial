"""One repair wave over the FINISHED map -- no rounds, no rebuild.

Every folded position (2+ raw arguments) is re-read once against its own
members, concurrently, in a single wave. Three differences from the in-pass
re-read, all deliberate:

- it runs at every fold size, not only 10+, because the audit found
  standing-sentence failures at two and three members as well;
- the prompt does not presume the group is a heading. RE_READ_PROMPT opens
  by telling the model a group this large is usually not one shared claim,
  which is true of a 12-member fold and false of a 2-member one; and
- when the call stands by the grouping it ADOPTS the sentence that call
  wrote. The in-pass re-read keeps the original, which is right there (the
  fold was just made) and wrong here (the sentence is the thing under
  repair, written by a call that had not seen every member).

Writes a new positions file beside the map; never overwrites it.
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

OUT = Path("data/logs/2026-08-29-consolidation-pass/repair")
MAP = Path("data/map/9b796b3a6312b329-category")
CONFIG = Path("D:/axial-wt/830-consolidation/config/pipeline.yaml")
WORKERS = 40


def main() -> int:
    from axial.argmap import consolidate as C
    from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
    from axial.llm import get_client
    from axial.model_json import parse_model_json

    assert Path.cwd() == Path("D:/axial"), Path.cwd()
    assert "axial-wt" in C.__file__, C.__file__

    prompt_template = """These arguments were drawn from academic books and one reading put them into a single group, writing this one sentence to stand for all of them:

{sentence}

{arguments}

Read each argument against that sentence and ask whether it actually asserts it. Keep together only arguments that assert THE SAME THING ABOUT THE SAME THING. Sharing a rhetorical move is not sharing a claim: criticising an existing account, rejecting a single cause, describing something as proceeding in stages, calling something complex or context-specific are moves, and two arguments making the same move about different objects stay apart. An argument that does not assert the group's claim goes into a group of its own, or with whichever others it does share a claim with.

If every one of these arguments really does assert one shared claim, say so by returning them all as one group -- and write the sentence that states it exactly, no wider and no narrower than what they all assert.

Answer as JSON only, no other text:

{{"groups": [
   {{"argument": "<one sentence stating what this group asserts, in the listed arguments' own terms>",
    "handles": ["a1", "a4"]}},
   ...
 ]}}

- """ + C.SENTENCE_RULE + """
- Every handle listed above must appear in exactly one group. Never drop an argument and never rewrite one: an argument nothing else here shares a claim with gets a group of its own, keeping its original sentence."""

    OUT.mkdir(parents=True, exist_ok=True)
    ledger = OUT / "repair_reads.jsonl"

    positions = [json.loads(l) for l in (MAP / "positions.jsonl").open(encoding="utf-8")]
    folded = [p for p in positions if len(p.get("folded_from") or []) >= 2]
    print(f"positions {len(positions)} | folded {len(folded)} to repair", flush=True)

    done = {
        r["key"]: r
        for r in load_checkpoint_records(ledger, C.CorruptConsolidationLedgerError)
    }
    client = get_client(config_path=CONFIG)

    def shape(entry: dict) -> dict:
        """A `_pool` entry in the shape the merged map emits."""
        members = entry.get(C.FOLDED_FROM_KEY) or []
        category = entry.pop("category", None)
        if category:
            entry["categories"] = [category]
        entry["variants"] = sorted({m["argument"] for m in members}) or [entry["argument"]]
        entry["named_times"] = max(len(members), 1)
        return entry

    def repair(position: dict) -> dict:
        members = tuple(C._members_of(position))
        key = C._re_read_key(members)
        if key in done and "error" not in done[key]:
            return done[key]
        listing, handles = C.render_arguments_blind(members)
        record = {
            "key": key,
            "shown": len(members),
            "split": False,
            "resentenced": False,
            "positions": [position],
        }
        try:
            parsed = parse_model_json(
                client.complete(
                    prompt_template.format(
                        sentence=position["argument"], arguments=listing
                    ),
                    pass_name=C.PASS_NAME,
                )
            )
            named: set[str] = set()
            groups = []
            for group in parsed.get("groups") or []:
                text = (group.get("argument") or "").strip()
                offered = group.get("handles") or []
                real = [
                    h
                    for i, h in enumerate(offered)
                    if h in handles and h not in named and h not in offered[:i]
                ]
                if not text or not real:
                    continue
                named.update(real)
                groups.append((text, [handles[h] for h in real]))
            if not groups:
                record["error"] = "no usable group"
            else:
                cats = position.get("categories") or []
                category = cats[0] if cats else ""
                new = [shape(C._pool(text, placed, category)) for text, placed in groups]
                new.extend(
                    shape(C._pool(handles[h]["argument"], [handles[h]], category))
                    for h in handles
                    if h not in named
                )
                record["positions"] = new
                record["split"] = len(new) > 1
                record["resentenced"] = (
                    len(new) == 1 and new[0]["argument"] != position["argument"]
                )
        except Exception as exc:  # noqa: BLE001 -- fault isolation: keep the original
            record["error"] = repr(exc)[:200]
            record["positions"] = [position]
        return record

    started = time.monotonic()
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(repair, p): p for p in folded}
        for n, future in enumerate(as_completed(futures), 1):
            record = future.result()
            if record["key"] not in done:
                append_checkpoint_record(ledger, record)
            results[record["key"]] = record
            if n % 25 == 0:
                print(
                    f"  repaired {n}/{len(folded)}  {round(time.monotonic() - started)}s",
                    flush=True,
                )

    out = [p for p in positions if len(p.get("folded_from") or []) < 2]
    split = resent = failed = 0
    for p in folded:
        record = results[C._re_read_key(tuple(C._members_of(p)))]
        out.extend(record["positions"])
        split += bool(record.get("split"))
        resent += bool(record.get("resentenced"))
        failed += "error" in record

    from axial.argmap.build import assign_position_ids

    stamped = assign_position_ids(out)
    with (OUT / "positions.jsonl").open("w", encoding="utf-8") as handle:
        for p in stamped:
            handle.write(json.dumps(p, ensure_ascii=False) + "\n")
    summary = {
        "folded_repaired": len(folded),
        "split": split,
        "resentenced": resent,
        "failed": failed,
        "positions_before": len(positions),
        "positions_after": len(stamped),
        "sum_consolidated_from": sum(x.get("consolidated_from", 1) for x in stamped),
        "wall_sec": round(time.monotonic() - started, 1),
        "usage": client.usage_for_pass(C.PASS_NAME),
    }
    (OUT / "repair.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
