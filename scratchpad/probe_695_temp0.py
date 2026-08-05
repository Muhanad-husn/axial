"""Issue #695: is the merge pass's 3+-member self-disagreement temperature?

Paired two-arm probe over already-decided batches, byte-identical input.

The pass runs at temperature 1 and disagrees with itself on 18.8% of 3+-member
batches (`data/logs/2026-08-05-677-merge-noise-floor/`, n=64). #695's first
question is whether temperature is the cause.

Two things make this run worth more than a bare temperature-0 arm:

1. The existing 18.8% control is n=64, a by-product of a sample that was mostly
   2-member batches. Its confidence interval is far too wide to be the "before"
   in a before/after. So this run re-asks the SAME batches at BOTH temperatures
   -- arm B is a fresh, size-matched temperature-1 control.
2. `config/pipeline.yaml` already records a 2026-07-28 finding that temperature
   0 on this pass was worse on tokens and latency AND "not even deterministic,
   giving two distinct answers over five greedy draws". That was one cluster,
   five draws, measuring cost -- not a self-disagreement rate over a sample.
   It predicts this probe comes back negative. Pre-registering that here so a
   negative result reads as a confirmation, not a surprise.

Pre-registered reading of the result, set before the run:

    arm A (temp 0) self-disagreement <= 5%   -> temperature IS the cause;
                                                cost/latency then decides.
    arm A within 5 points of arm B           -> temperature is NOT the cause;
                                                go to #695's second hypothesis
                                                (the unstable batches are the
                                                ambiguous ones).
    in between                               -> report both, change nothing.

Read-only over the corpus. Writes nothing but its own log under `data/logs/`.
Never touches `data/names/merge_decisions.jsonl`.

Run from D:\\axial (the main checkout -- `data/` does not exist in a worktree):

    uv run python scratchpad/probe_695_temp0.py --sample 150 --workers 12
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from axial.llm import (
    RECONCILE_PASS_NAME,
    _build_openrouter_client,
    usage_and_cost_by_pass,
)
from axial.merge_names import (
    MergeBatch,
    _decide_batch,
    build_evidence_index,
    render_member,
)
from axial.names import (
    build_inventory,
    collect_occurrences,
    load_answer_records,
    load_back_matter_sections,
)

DATA_DIR = Path("data")
ANSWERS_DIR = DATA_DIR / "answers"
TREES_DIR = DATA_DIR / "trees"
DECISIONS_PATH = DATA_DIR / "names" / "merge_decisions.jsonl"
CONFIG_PATH = Path("config/pipeline.yaml")
DEFAULT_LOG_DIR = DATA_DIR / "logs" / "2026-08-05-695-merge-temp0"

MIN_MEMBERS = 3

LOG_DIR = DEFAULT_LOG_DIR
run_log: Any = None
console_log: Any = None


def open_logs(log_dir: Path) -> None:
    global LOG_DIR, run_log, console_log
    LOG_DIR = log_dir
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # A re-run must never truncate a previous run's record in place: an existing
    # run.jsonl is a PRIOR run's log and is preserved before this run opens its own.
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


def partition_of(nodes: list[dict[str, Any]] | None, members: tuple[str, ...]) -> frozenset:
    """A decision's answer reduced to the only thing being compared: which
    surfaces ended up together. Canonical choice within a group is not part of
    it -- two answers that group the same surfaces but elect a different
    canonical are the same partition, and calling that a disagreement would
    inflate the floor this run exists to measure. A member no node mentions is
    its own singleton, which is what `build_alias_map_nodes` does with it."""
    groups: list[frozenset[str]] = []
    seen: set[str] = set()
    for node in nodes or []:
        group = {node["canonical"], *(node.get("aliases") or [])}
        group &= set(members)
        if not group:
            continue
        groups.append(frozenset(group))
        seen |= group
    for member in members:
        if member not in seen:
            groups.append(frozenset({member}))
    return frozenset(groups)


def build_client(temperature: float | None):
    """The configured OpenRouter client with `reconcile`'s temperature forced.

    Goes through the same `llm.temperature_by_pass` seam the pass itself reads,
    so model, reasoning effort and every other request-shaping decision stay
    exactly what the real pass sends. `None` removes the key entirely, which is
    NOT the same as 1 -- but `reconcile` is explicitly `temperature: 1` in
    config, so arm B passes 1 and sends the identical body the pass sends."""
    llm_config = dict(
        (yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}).get("llm", {})
    )
    by_pass = dict(llm_config.get("temperature_by_pass") or {})
    if temperature is None:
        by_pass.pop(RECONCILE_PASS_NAME, None)
    else:
        by_pass[RECONCILE_PASS_NAME] = temperature
    llm_config["temperature_by_pass"] = by_pass
    return _build_openrouter_client(llm_config)


def usable_band_surfaces(notes_of: dict[str, set[str]]) -> set[str]:
    """Every surface that lands on a page Axial actually produces output from.

    The founder's test for #695 is impact on "the material required to produce
    better output", not on all 47,220 pages -- 84% of which draw on a single
    source and can carry no disagreement at all. The usable band is the measured
    one: 30-200 notes drawn from 5 or more sources. Membership is read off the
    alias map the vault was built from, so this is the product's own view of its
    pages, not a re-derivation."""
    nodes = json.loads((DATA_DIR / "names" / "alias_map.json").read_text(encoding="utf-8"))["nodes"]
    surfaces: set[str] = set()
    for node in nodes:
        page = [node["canonical"], *(node.get("aliases") or [])]
        chunks: set[str] = set()
        for surface in page:
            chunks |= notes_of.get(surface, set())
        sources = {c.split("_", 1)[0] for c in chunks}
        if 30 <= len(chunks) <= 200 and len(sources) >= 5:
            surfaces.update(page)
    return surfaces


def load_decisions(path: Path) -> list[dict[str, Any]]:
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
    parser.add_argument(
        "--arms",
        default="0,1",
        help="comma-separated reconcile temperatures to run, in order (default: 0,1)",
    )
    parser.add_argument(
        "--usable-only",
        action="store_true",
        help="sample only batches ruling on a surface that lands on a usable-band page",
    )
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    args = parser.parse_args()

    open_logs(Path(args.log_dir))

    t0 = time.time()
    records = load_answer_records(ANSWERS_DIR)
    back_matter = load_back_matter_sections(TREES_DIR)
    entries = build_inventory(list(collect_occurrences(records, back_matter)))
    kinds = {e.surface_form: e.kind for e in entries}
    evidence = build_evidence_index({e.surface_form: e.chunk_ids for e in entries})
    log(
        "corpus_loaded",
        records=len(records),
        entries=len(entries),
        elapsed=round(time.time() - t0, 1),
    )

    decisions = load_decisions(DECISIONS_PATH)
    log("decisions_loaded", count=len(decisions))

    # Only batches whose CURRENT rendered input still hashes to their recorded
    # key are usable: that equality IS the byte-identical-input guarantee, and
    # anything else would be measuring a changed prompt, not the pass's noise.
    notes_of = {e.surface_form: set(e.chunk_ids) for e in entries}
    usable = usable_band_surfaces(notes_of) if args.usable_only else set()
    if args.usable_only:
        log("usable_band", surfaces=len(usable))

    eligible: list[dict[str, Any]] = []
    stale = 0
    off_band = 0
    for record in decisions:
        members = tuple(record.get("members") or ())
        if len(members) < MIN_MEMBERS:
            continue
        if args.usable_only and not (usable & set(members)):
            off_band += 1
            continue
        rendered = tuple(render_member(m, kinds, evidence) for m in members)
        payload = json.dumps(list(rendered), ensure_ascii=False, sort_keys=False)
        key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if key != record["batch_key"]:
            stale += 1
            continue
        eligible.append({"record": record, "members": members, "rendered": rendered})
    log(
        "eligible",
        min_members=MIN_MEMBERS,
        reproducible=len(eligible),
        stale_input=stale,
        off_band=off_band,
    )
    if not eligible:
        log("aborted", reason="no 3+-member decision still reproduces its recorded key")
        return

    # Stride over key order, the same deterministic sampling the noise-floor
    # run used -- no RNG, so the sample is reproducible from the log alone.
    eligible.sort(key=lambda item: item["record"]["batch_key"])
    size = min(args.sample, len(eligible))
    stride = max(1, len(eligible) // size)
    sample = [eligible[i * stride] for i in range(size)]
    log("sampled", n=len(sample), stride=stride, of=len(eligible))

    baseline_path = LOG_DIR / "baseline.jsonl"
    with baseline_path.open("w", encoding="utf-8") as handle:
        for item in sample:
            handle.write(json.dumps(item["record"], ensure_ascii=False) + "\n")

    summary_by_arm: dict[str, Any] = {}
    for raw_arm in args.arms.split(","):
        # `--arms ""` runs the whole selection and sampling with no model call
        # at all -- the free dry run that checks how many batches still
        # reproduce their key before anything is paid for.
        if not raw_arm.strip():
            continue
        temperature = float(raw_arm.strip())
        arm = f"temp{raw_arm.strip()}"
        client = build_client(temperature)
        log(
            "arm_start",
            arm=arm,
            temperature=temperature,
            model=client.model_for_pass(RECONCILE_PASS_NAME),
        )

        started = time.time()
        results: list[dict[str, Any]] = []
        failures = 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {}
            for item in sample:
                batch = MergeBatch(
                    cluster_label=item["record"]["cluster_label"],
                    members=item["members"],
                    rendered=item["rendered"],
                )
                futures[pool.submit(_decide_batch, batch, kinds, client, evidence)] = item
            for done in as_completed(futures):
                item = futures[done]
                batch, fresh, failure = done.result()
                recorded = partition_of(item["record"].get("nodes"), item["members"])
                if fresh is None:
                    failures += 1
                    agrees = None
                else:
                    agrees = partition_of(fresh.get("nodes"), item["members"]) == recorded
                row = {
                    "arm": arm,
                    "batch_key": item["record"]["batch_key"],
                    "members": list(item["members"]),
                    "member_count": len(item["members"]),
                    "recorded_partition": sorted(sorted(g) for g in recorded),
                    "fresh_partition": (
                        sorted(sorted(g) for g in partition_of(fresh.get("nodes"), item["members"]))
                        if fresh
                        else None
                    ),
                    "agrees": agrees,
                    "recorded_escalated": item["record"].get("escalated") or [],
                    "fresh_escalated": (fresh or {}).get("escalated") or [],
                    "failure": failure,
                }
                results.append(row)
                log("reask", **{k: row[k] for k in ("arm", "batch_key", "member_count", "agrees")})

        judged = [r for r in results if r["agrees"] is not None]
        disagreements = [r for r in judged if not r["agrees"]]
        rate = len(disagreements) / len(judged) if judged else None

        # #695's second hypothesis, bought for free by the same calls: are the
        # unstable batches the ambiguous ones? Escalation is the pass's own
        # recorded "could not judge this member", so it is the cheapest proxy
        # available without another model call.
        escalated_rows = [r for r in judged if r["recorded_escalated"] or r["fresh_escalated"]]
        escalated_unstable = [r for r in escalated_rows if not r["agrees"]]
        clean_rows = [r for r in judged if not (r["recorded_escalated"] or r["fresh_escalated"])]
        clean_unstable = [r for r in clean_rows if not r["agrees"]]

        # A flip rate counts batches; the founder's 5% test is about material.
        # Weight each flip by the notes behind the surfaces that actually moved
        # group -- one flip shifting a 400-note surface is not the same event as
        # one shifting two surfaces of a single note each.
        notes_sampled = 0
        notes_moved = 0
        usable_sampled = 0
        usable_moved = 0
        for row in judged:
            notes_sampled += sum(len(notes_of.get(m, ())) for m in row["members"])
            usable_sampled += sum(len(notes_of.get(m, ())) for m in row["members"] if m in usable)
            if row["agrees"]:
                continue
            recorded_of = {m: frozenset(g) for g in row["recorded_partition"] for m in g}
            fresh_of = {m: frozenset(g) for g in (row["fresh_partition"] or []) for m in g}
            moved = [
                m for m in set(recorded_of) | set(fresh_of) if recorded_of.get(m) != fresh_of.get(m)
            ]
            notes_moved += sum(len(notes_of.get(m, ())) for m in moved)
            usable_moved += sum(len(notes_of.get(m, ())) for m in moved if m in usable)

        by_size: dict[int, dict[str, int]] = {}
        for row in judged:
            bucket = by_size.setdefault(min(row["member_count"], 6), {"n": 0, "disagree": 0})
            bucket["n"] += 1
            bucket["disagree"] += 0 if row["agrees"] else 1

        usage = usage_and_cost_by_pass(
            client, {RECONCILE_PASS_NAME: client.model_for_pass(RECONCILE_PASS_NAME)}
        )
        summary_by_arm[arm] = {
            "temperature": temperature,
            "judged": len(judged),
            "failures": failures,
            "self_disagreement": rate,
            "notes_sampled": notes_sampled,
            "notes_moved": notes_moved,
            "notes_moved_share": (notes_moved / notes_sampled) if notes_sampled else None,
            "usable_notes_sampled": usable_sampled,
            "usable_notes_moved": usable_moved,
            "usable_notes_moved_share": (usable_moved / usable_sampled) if usable_sampled else None,
            "by_member_count": by_size,
            "escalated_n": len(escalated_rows),
            "escalated_unstable": len(escalated_unstable),
            "clean_n": len(clean_rows),
            "clean_unstable": len(clean_unstable),
            "elapsed_s": round(time.time() - started, 1),
            "usage": usage,
        }
        log("arm_done", arm=arm, **{k: v for k, v in summary_by_arm[arm].items() if k != "usage"})

        with (LOG_DIR / f"results-{arm}.jsonl").open("w", encoding="utf-8") as handle:
            for row in results:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    (LOG_DIR / "summary.json").write_text(
        json.dumps(summary_by_arm, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log("done", arms=list(summary_by_arm))
    run_log.close()
    console_log.close()


if __name__ == "__main__":
    sys.exit(main())
