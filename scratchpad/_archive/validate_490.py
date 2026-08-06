"""Real-corpus validation for issue #490 (Phase B v1 slice 05): the per-name
coverage map's band threshold and scope rule, and the contested predicate,
measured against the live vault.

LLM-free, zero model calls, read-only. It never writes into `data/vault/`,
`data/names/` or anywhere else under `data/` except its own log directory.

**It measures THIS BRANCH's code, not `main`'s.** A script run from the main
checkout imports `main`'s `src/` unless told otherwise, and that mistake has
silently produced wrong numbers here before. This file inserts its own
worktree's `src/` at the front of `sys.path` and prints the resolved module
path of every module under test at the top of the run, so the reader can see
which code produced the table.

Run it from the orchestrator's main checkout, where `data/` actually exists
(it does not exist inside a worktree):

    cd D:/axial
    uv run python .claude/worktrees/05-coverage-counter-position/scratchpad/validate_490.py

Three things it answers, all of which §7.7/§7.8 owe an inspection:

1. **The band cut points on the real distribution.** `coverage_bands`
   (20/100) has never been proven against the name layer. The honest
   population is not every name in the index -- it is the names a brief
   actually resolves and retrieves on.
2. **The map's scope rule.** §7.7 keys the map on the names the answer is
   ABOUT: retrieved on by the run AND touched by a claim's grounds. The
   counterfactual -- keying it on `names_touched` alone -- is measured
   beside it, because that is what the plan's literal wording would build.
3. **The contested predicate's fire rate**, per path, over the same evidence
   sets, plus the size of the counter-position whitelist it produces.

An "evidence set" here is a real name page's own first 24 member notes: the
shape `get_name` hands the retrieval loop, and the closest LLM-free stand-in
for a brief's grounds. The seeds are the brief-shaped queries slice 02
measured against this same vault.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

WORKTREE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKTREE / "src"))

import axial.analyze.synthesis as synthesis_mod  # noqa: E402
import axial.query.names as names_mod  # noqa: E402
import axial.validators.counter_position as contested_mod  # noqa: E402
import axial.validators.coverage as coverage_mod  # noqa: E402
from axial.analyze.assembly import name_surfaces  # noqa: E402
from axial.query.reader import ChunkNotFoundError, get_chunk  # noqa: E402

REPO = Path(r"D:/axial")
VAULT = REPO / "data" / "vault"
NAMES = REPO / "data" / "names"
LOG_DIR = REPO / "data" / "logs" / "2026-07-30-slice-05-coverage"

EVIDENCE_SET_SIZE = 24

# The brief-shaped queries slice 02 measured, plus the polities and concepts
# the five smoke and five eval briefs are written around.
QUERIES = [
    "Tilly",
    "Charles Tilly",
    "Agamben",
    "Giorgio Agamben",
    "Bayat",
    "Asef Bayat",
    "Batatu",
    "Hanna Batatu",
    "Caspersen",
    "Kalyvas",
    "Stathis Kalyvas",
    "SDF",
    "Rojava",
    "PYD",
    "state of exception",
    "bare life",
    "Autonomous Administration of North and East Syria",
    "AANS",
    "Syria",
    "Iraq",
    "Lebanon",
    "Ba'th Party",
    "Hafez al-Assad",
    "Bashar al-Assad",
    "Idlib",
    "Robert Jackson",
    "Michael Mann",
    "revolution",
    "sovereignty",
    "state formation",
    "civil war",
    "primitive accumulation",
]

# The seeds whose member notes become evidence sets. A subset of the above:
# every distinct canonical with enough members to stand in for a brief's
# grounds, capped so one pass stays under a couple of minutes.
SEED_QUERIES = [
    "Charles Tilly",
    "Giorgio Agamben",
    "Stathis Kalyvas",
    "state of exception",
    "Hanna Batatu",
    "Asef Bayat",
    "Syria",
    "Ba'th Party",
    "Hafez al-Assad",
    "Rojava",
]

records: list[dict[str, Any]] = []
console: list[str] = []


def say(line: str = "") -> None:
    print(line, flush=True)
    console.append(line)


def emit(record: dict[str, Any]) -> None:
    records.append(record)


def evidence_set(canonical: str) -> list[str]:
    page = names_mod.get_name(canonical, vault_dir=VAULT)
    return [member.chunk_id for member in page.members[:EVIDENCE_SET_SIZE]]


def claims_for(chunk_ids: list[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """One (b) claim grounded in every note of the evidence set, with
    `names_touched` computed exactly the way §7.4 computes it: each grounds
    note's own `names` answers, resolved through the alias map alone."""
    touched: set[str] = set()
    for chunk_id in chunk_ids:
        try:
            note = get_chunk(chunk_id, vault_dir=VAULT)
        except ChunkNotFoundError:
            continue
        for surface in name_surfaces(note.names):
            canonical = names_mod.canonical_name_for_surface(surface, names_dir=NAMES)
            if canonical:
                touched.add(canonical)
    claim = {
        "claim_id": "c-1",
        "text": "A synthetic claim grounded in this evidence set.",
        "kind": "b",
        "grounds": [{"ref_type": "chunk", "ref_id": chunk_id} for chunk_id in chunk_ids],
        "confidence": "medium",
        "names_touched": sorted(touched),
    }
    return [claim], touched


def trajectory_for(canonical: str) -> list[dict[str, Any]]:
    return [
        {
            "step": 1,
            "tool": "find_names",
            "args": {"query": canonical},
            "result_ids": [canonical],
            "result_count": 1,
        },
        {
            "step": 2,
            "tool": "get_name",
            "args": {"canonical": canonical},
            "result_ids": [],
            "result_count": 0,
        },
    ]


def main() -> None:
    started = time.time()
    say("MODULES UNDER TEST (must all be under the worktree, not D:/axial/src):")
    for module in (coverage_mod, contested_mod, synthesis_mod, names_mod):
        say(f"  {module.__name__}: {module.__file__}")
    say(f"vault: {VAULT}")
    say(f"names: {NAMES}")
    say(
        f"band cut points: moderate_floor={coverage_mod.DEFAULT_MODERATE_FLOOR} "
        f"dense_floor={coverage_mod.DEFAULT_DENSE_FLOOR} "
        f"(config: {coverage_mod._resolve_coverage_bands(REPO / 'config' / 'pipeline.yaml')})"
    )
    say()

    corpus_counts = names_mod.coverage_count(vault_dir=VAULT)
    say(f"name pages in the vault: {len(corpus_counts)}")
    moderate_floor, dense_floor = coverage_mod._resolve_coverage_bands(
        REPO / "config" / "pipeline.yaml"
    )

    # -- 1. the cut points, over the names a brief actually resolves --------
    say()
    say("== 1. band distribution over the real brief-shaped query set ==")
    resolved_rows = []
    for query in QUERIES:
        canonical = names_mod.canonical_name_for_surface(query, names_dir=NAMES)
        count = corpus_counts.get(canonical) if canonical else None
        band = coverage_mod.coverage_band_for(
            count, moderate_floor=moderate_floor, dense_floor=dense_floor
        )
        resolved_rows.append((query, canonical, count, band))
        emit(
            {
                "kind": "query_band",
                "query": query,
                "canonical": canonical,
                "member_count": count,
                "band": band,
            }
        )
        say(f"  {query[:38]:40s} -> {str(canonical)[:44]:46s} {count} {band}")
    band_counts = Counter(band for _q, _c, count, band in resolved_rows if count is not None)
    unresolved = [q for q, c, count, _b in resolved_rows if count is None]
    total_resolved = sum(band_counts.values())
    say(
        f"  RESOLVED {total_resolved}/{len(QUERIES)}: thin={band_counts['thin']} "
        f"moderate={band_counts['moderate']} dense={band_counts['dense']}"
    )
    say(f"  no page / no resolution: {unresolved}")
    emit(
        {
            "kind": "query_band_summary",
            "resolved": total_resolved,
            "thin": band_counts["thin"],
            "moderate": band_counts["moderate"],
            "dense": band_counts["dense"],
            "unresolved": unresolved,
        }
    )

    # -- 2. the map, over real evidence sets, both scopes -------------------
    say()
    say("== 2. the §7.7 map over real evidence sets: scoped vs names_touched-only ==")
    seeds = []
    for query in SEED_QUERIES:
        canonical = names_mod.canonical_name_for_surface(query, names_dir=NAMES)
        if canonical and canonical in corpus_counts:
            seeds.append(canonical)
        else:
            say(f"  (seed {query!r} does not resolve to a page; skipped)")

    scoped_bands = Counter()
    scoped_overall = Counter()
    touched_overall = Counter()
    touched_sizes = []
    for canonical in seeds:
        chunk_ids = evidence_set(canonical)
        claims, touched = claims_for(chunk_ids)
        trajectory = trajectory_for(canonical)

        scoped_map = coverage_mod.compute_coverage_map(
            claims,
            trajectory=trajectory,
            vault_dir=VAULT,
            config_path=REPO / "config" / "pipeline.yaml",
        )
        scoped_conf = coverage_mod.compute_confidence(scoped_map)
        for entry in scoped_map.values():
            scoped_bands[entry["coverage_band"]] += 1
        scoped_overall[scoped_conf["overall_band"]] += 1

        # The counterfactual: the plan's literal wording, keyed on every name
        # the grounds notes are members of.
        naive_map = {
            name: {
                "coverage_band": coverage_mod.coverage_band_for(
                    corpus_counts.get(name),
                    moderate_floor=moderate_floor,
                    dense_floor=dense_floor,
                )
            }
            for name in touched
        }
        naive_conf = coverage_mod.compute_confidence(naive_map)
        touched_overall[naive_conf["overall_band"]] += 1
        touched_sizes.append(len(touched))

        say(
            f"  {canonical[:34]:36s} notes={len(chunk_ids):3d} "
            f"scoped_map={len(scoped_map)} "
            f"({', '.join(f'{n}={e["corpus_note_count"]}/{e["evidence_note_count"]} {e["coverage_band"]}' for n, e in scoped_map.items())}) "
            f"-> {scoped_conf['overall_band']:6s} | names_touched={len(touched):4d} "
            f"-> {naive_conf['overall_band']}"
        )
        emit(
            {
                "kind": "evidence_set_coverage",
                "seed": canonical,
                "evidence_notes": len(chunk_ids),
                "scoped_map": scoped_map,
                "scoped_overall_band": scoped_conf["overall_band"],
                "names_touched_count": len(touched),
                "names_touched_overall_band": naive_conf["overall_band"],
            }
        )

    mean_touched = sum(touched_sizes) / len(touched_sizes) if touched_sizes else 0
    say(
        f"  SCOPED entries: thin={scoped_bands['thin']} moderate={scoped_bands['moderate']} "
        f"dense={scoped_bands['dense']}; overall bands {dict(scoped_overall)}"
    )
    say(
        f"  names_touched-only: mean {mean_touched:.0f} names per set; "
        f"overall bands {dict(touched_overall)}"
    )
    emit(
        {
            "kind": "coverage_summary",
            "scoped_entry_bands": dict(scoped_bands),
            "scoped_overall_bands": dict(scoped_overall),
            "names_touched_mean": mean_touched,
            "names_touched_overall_bands": dict(touched_overall),
        }
    )

    # -- 3. the contested predicate, over the same evidence sets ------------
    say()
    say("== 3. the §7.8 contested predicate over the same evidence sets ==")
    signals = Counter()
    for canonical in seeds:
        chunk_ids = evidence_set(canonical)
        claims, _touched = claims_for(chunk_ids)
        trajectory = trajectory_for(canonical)
        result = contested_mod.detect_contested(
            claims, trajectory, vault_dir=VAULT, names_dir=NAMES
        )
        signals[str(result.signal)] += 1
        candidates = 0
        if result.contested:
            candidates = len(
                synthesis_mod._counter_position_candidates(
                    claims, trajectory, vault_dir=VAULT, names_dir=NAMES
                )
            )
        say(
            f"  {canonical[:34]:36s} contested={result.contested!s:5s} "
            f"signal={str(result.signal):22s} whitelist={candidates}"
        )
        emit(
            {
                "kind": "contested",
                "seed": canonical,
                "contested": result.contested,
                "signal": result.signal,
                "whitelist_size": candidates,
            }
        )
    say(f"  SIGNALS over {len(seeds)} sets: {dict(signals)}")
    emit({"kind": "contested_summary", "signals": dict(signals), "sets": len(seeds)})

    elapsed = time.time() - started
    say()
    say(f"done in {elapsed:.1f}s, 0 model calls, $0.00")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "run.jsonl").write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    (LOG_DIR / "console.log").write_text("\n".join(console) + "\n", encoding="utf-8")
    say(f"wrote {LOG_DIR}")


if __name__ == "__main__":
    main()
