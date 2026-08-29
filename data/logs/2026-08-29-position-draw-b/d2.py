"""D2 baseline over the default build, for two draws of the `position` column.

D2 = held-out `position`-axis purity of the default build's positions, size-matched
against a permutation null. Reported member-weighted (primary, matching the
"weighted conditional purity" of #838's correction 2) and per-position mean.
The floor is |D2(draw A) - D2(draw B)|.
"""

import json
import random
from collections import Counter
from pathlib import Path

MAP = Path("data/map/9b796b3a6312b329/positions.jsonl")
DRAWS = {
    "A (deepseek-v4-flash)": Path("data/vocabulary/position/assignments.jsonl"),
    "B (gpt-5.6-luna)": Path("data/vocabulary-draw-b/position/assignments.jsonl"),
}
TRIALS = 20
SEED = 831


def load_positions():
    out = []
    with MAP.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            out.append(rec["chunk_ids"])
    return out


def load_draw(path):
    got = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if rec.get("refused"):
                continue
            cid = rec.get("category_id")
            if cid:
                got[rec["chunk_id"]] = cid
    return got


def purity(groups):
    """(member-weighted, per-position mean, n positions, n categorised members)"""
    num = den = 0
    per = []
    for labels in groups:
        if len(labels) < 2:
            continue
        modal = Counter(labels).most_common(1)[0][1]
        num += modal
        den += len(labels)
        per.append(modal / len(labels))
    return (num / den if den else 0.0), (sum(per) / len(per) if per else 0.0), len(per), den


def main():
    positions = load_positions()
    placed = sorted({c for ids in positions for c in ids})
    print(f"default build: {len(positions)} positions, {len(placed)} distinct placed chunks\n")

    results = {}
    for name, path in DRAWS.items():
        assign = load_draw(path)
        groups = [[assign[c] for c in ids if c in assign] for ids in positions]
        obs_w, obs_p, n_pos, n_mem = purity(groups)

        # size-matched permutation null: relabel the placed pool, keep position sizes
        pool = [assign[c] for c in placed if c in assign]
        missing = [c for c in placed if c not in assign]
        rng = random.Random(SEED)
        nulls_w, nulls_p = [], []
        for _ in range(TRIALS):
            shuffled = pool[:]
            rng.shuffle(shuffled)
            lookup = {}
            it = iter(shuffled)
            for c in placed:
                if c in assign:
                    lookup[c] = next(it)
            ngroups = [[lookup[c] for c in ids if c in lookup] for ids in positions]
            nw, np_, _, _ = purity(ngroups)
            nulls_w.append(nw)
            nulls_p.append(np_)
        null_w = sum(nulls_w) / TRIALS
        null_p = sum(nulls_p) / TRIALS

        covered = sum(1 for c in placed if c in assign)
        results[name] = dict(
            obs_w=obs_w, obs_p=obs_p, null_w=null_w, null_p=null_p,
            lift_w=obs_w / null_w, lift_p=obs_p / null_p,
            n_pos=n_pos, n_mem=n_mem, covered=covered, placed=len(placed),
            null_spread=max(nulls_w) - min(nulls_w), missing=len(missing),
        )

        print(f"draw {name}")
        print(f"  categorised placed chunks : {covered} of {len(placed)} ({covered/len(placed):.1%})")
        print(f"  positions scored (2+ categorised members) : {n_pos}, {n_mem} member slots")
        print(f"  member-weighted purity : {obs_w:.4f}  null {null_w:.4f} (spread {max(nulls_w)-min(nulls_w):.4f})  lift {obs_w/null_w:.3f}")
        print(f"  per-position mean purity: {obs_p:.4f}  null {null_p:.4f}  lift {obs_p/null_p:.3f}\n")

    a, b = results["A (deepseek-v4-flash)"], results["B (gpt-5.6-luna)"]
    print("D2 assignment-instability floor")
    print(f"  |D2(A) - D2(B)| member-weighted purity : {abs(a['obs_w']-b['obs_w']):.4f}")
    print(f"  |D2(A) - D2(B)| per-position mean      : {abs(a['obs_p']-b['obs_p']):.4f}")
    print(f"  |lift(A) - lift(B)| member-weighted    : {abs(a['lift_w']-b['lift_w']):.3f}")
    print(f"  null spread within a draw (20 trials)  : A {a['null_spread']:.4f}  B {b['null_spread']:.4f}")

    # direct label agreement between the two draws, full population
    assign_a = load_draw(DRAWS["A (deepseek-v4-flash)"])
    assign_b = load_draw(DRAWS["B (gpt-5.6-luna)"])
    both = set(assign_a) & set(assign_b)
    agree = sum(1 for c in both if assign_a[c] == assign_b[c])
    union = set(assign_a) | set(assign_b)
    print(f"\nlabel agreement, full column")
    print(f"  both draws assigned : {len(both)} chunks; agree {agree} = {agree/len(both):.1%}")
    print(f"  either draw assigned: {len(union)}; agreement over that base {agree/len(union):.1%}")

    # per-source coverage of draw B, for correction 2's blind-spot check
    from collections import defaultdict
    answered = defaultdict(int)
    assigned_b = defaultdict(int)
    assigned_a = defaultdict(int)
    with DRAWS["B (gpt-5.6-luna)"].open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            answered[rec["source_id"]] += 1
            if not rec.get("refused") and rec.get("category_id"):
                assigned_b[rec["source_id"]] += 1
    with DRAWS["A (deepseek-v4-flash)"].open(encoding="utf-8") as fh:
        for line in fh:
            rec = json.loads(line)
            if not rec.get("refused") and rec.get("category_id"):
                assigned_a[rec["source_id"]] += 1
    rows = []
    for src, n in answered.items():
        rows.append((1 - assigned_b[src] / n, src, n, assigned_a[src] / n, assigned_b[src] / n))
    rows.sort(reverse=True)
    print("\nworst refusal rates, draw B (draw A beside it)")
    for rate, src, n, ra, rb in rows[:6]:
        print(f"  {src:28s} n={n:5d}  A assigned {ra:6.1%}  B assigned {rb:6.1%}  B refused {rate:6.1%}")


if __name__ == "__main__":
    main()
