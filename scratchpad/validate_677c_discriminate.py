"""Does `units_asked_touching_new` actually DISCRIMINATE on the real corpus?

The first validation pass (`validate_677c.py`) showed the counters compute and
the invariants hold, but neither pass exercised the one thing the field exists
for. Merge came back 13,900/13,900 decided, so `units_asked` was 0 in every arm
and `touching_new` had nothing to be a subset of. Gather's 683 was 100% of
asked by construction: the arm removed exactly the records touching a new book,
so of course every pending page touched one.

So each pass gets a mixed arm. The ledger loses BOTH some units that touch one
of the three books #623 added AND some that touch only the 31 already read. A
counter that discriminates reports `touching_new` equal to the first group and
strictly less than `asked`; a counter that is really just counting pending work
reports `touching_new == asked` again.

Zero model calls: `limit=0` means the worker pool reaches nothing, and a client
that raises is the belt to that brace. Every write path goes to the scratchpad.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path("D:/axial/data")
NAMES = DATA / "names"
OUT = Path(__file__).resolve().parent / "677c-out" / "discriminate"

NEW_SOURCES = {
    "gelvin-1998-f7e1df5f9b1d",
    "hinnebusch-1990-ac29981e616e",
    "wedeen-2019-3ae1f7af318d",
}

# How many old-books-only units to also strip, so `asked` exceeds the
# new-book group by a known amount.
OLD_ONLY_TO_DROP = 200


class NoCallsAllowed:
    def __getattr__(self, name):
        def _raise(*_args, **_kwargs):
            raise AssertionError(f"harness made a model call: client.{name}()")

        return _raise


def log(event: str, **fields: object) -> None:
    print(f"{event}: " + " ".join(f"{k}={v}" for k, v in fields.items()), flush=True)


def verdict(label: str, summary: dict) -> None:
    """The only claim worth asserting here is the one the first pass could not
    make: that `touching_new` is STRICTLY less than `asked`. Equality would
    mean the field is just re-counting pending work under a second name, which
    is exactly the failure a tautological arm hides."""
    total = summary["units_total"]
    reused = summary["units_reused"]
    asked = summary["units_asked"]
    touching = summary["units_asked_touching_new"]
    log(
        label,
        units_total=total,
        units_reused=reused,
        units_asked=asked,
        units_asked_touching_new=touching,
    )
    assert asked + reused == total, f"{label}: invariant broken"
    assert touching <= asked, f"{label}: touching_new {touching} > asked {asked}"
    assert asked > 0, f"{label}: nothing pending, so this arm proves nothing"
    assert touching < asked, (
        f"{label}: touching_new {touching} == asked {asked}; the mixed arm did not "
        f"separate the two groups, so this proves nothing"
    )
    log(
        f"{label}_VERDICT",
        touches_a_new_book=touching,
        touches_only_old_books=asked - touching,
        of_asked=asked,
    )


def run_merge() -> None:
    from axial.merge_names import _source_ids_of, _load_name_rows, run_merge_names

    out = OUT / "merge"
    out.mkdir(parents=True, exist_ok=True)

    # surface form -> the sources it appears in, off the same similarity view
    # the run itself reads.
    rows = _load_name_rows(NAMES / "embeddings.lance")
    sources_by_surface = {
        row["surface_form"]: _source_ids_of(json.loads(row["chunk_ids_json"])) for row in rows
    }
    log("merge_surface_source_index", surfaces=len(sources_by_surface))

    # Split the decision log by whether a decision's own members touch one of
    # the three new books, then drop every new-book decision plus a fixed
    # slice of old-only ones.
    src = NAMES / "merge_decisions.jsonl"
    touching, old_only = [], []
    with src.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            hits_new = any(
                sources_by_surface.get(member, frozenset()) & NEW_SOURCES
                for member in record.get("members", [])
            )
            (touching if hits_new else old_only).append(line)
    log("merge_decision_split", touching_new=len(touching), old_only=len(old_only))

    drop_old = set(range(0, len(old_only), max(len(old_only) // OLD_ONLY_TO_DROP, 1)))
    drop_old = set(sorted(drop_old)[:OLD_ONLY_TO_DROP])
    dropped_old = len(drop_old)
    keep = [line for i, line in enumerate(old_only) if i not in drop_old]
    ledger = out / "merge_decisions_mixed.jsonl"
    ledger.write_text("".join(keep), encoding="utf-8")
    log(
        "merge_mixed_ledger",
        dropped_touching_new=len(touching),
        dropped_old_only=dropped_old,
        kept=len(keep),
    )

    # Prior manifest rewound to the 31 books, so the 3 added ones read as new.
    manifest = out / "manifest_31.json"
    all34 = json.loads((OUT.parent / "merge" / "manifest_all34.json").read_text(encoding="utf-8"))
    manifest.write_text(
        json.dumps({**all34, "source_ids": sorted(set(all34["source_ids"]) - NEW_SOURCES)}),
        encoding="utf-8",
    )

    summary = run_merge_names(
        embeddings_dir=NAMES / "embeddings.lance",
        alias_map_path=out / "alias_map.json",
        index_path=out / "index.json",
        decisions_path=ledger,
        manifest_path=manifest,
        failures_path=out / "merge_failures.jsonl",
        similarity_manifest_path=NAMES / "similarity_manifest.json",
        client=NoCallsAllowed(),
        limit=0,
    )
    # A dropped decision only becomes a pending BATCH if this run's batching
    # still produces that batch, so the expected numbers come from what the
    # run itself found pending, split the same way -- not from the drop counts.
    verdict("merge_mixed_arm", summary)


def run_gather() -> None:
    from axial.gather import _source_ids_of
    from axial.gather import run_gather as _run_gather

    out = OUT / "gather"
    (out / "vault").mkdir(parents=True, exist_ok=True)

    src = NAMES / "disagreements.jsonl"
    touching, old_only = [], []
    with src.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            hits_new = bool(_source_ids_of(record.get("chunk_ids") or []) & NEW_SOURCES)
            (touching if hits_new else old_only).append(line)
    log("gather_record_split", touching_new=len(touching), old_only=len(old_only))

    drop_old = sorted(set(range(0, len(old_only), max(len(old_only) // OLD_ONLY_TO_DROP, 1))))[
        :OLD_ONLY_TO_DROP
    ]
    drop_old_set = set(drop_old)
    keep = [line for i, line in enumerate(old_only) if i not in drop_old_set]
    ledger = out / "disagreements_mixed.jsonl"
    ledger.write_text("".join(keep), encoding="utf-8")
    log(
        "gather_mixed_ledger",
        dropped_touching_new=len(touching),
        dropped_old_only=len(drop_old_set),
        kept=len(keep),
    )

    summary = _run_gather(
        alias_map_path=NAMES / "alias_map.json",
        inventory_path=NAMES / "inventory.jsonl",
        answers_dir=DATA / "answers",
        source_meta_dir=DATA / "source_meta",
        vault_dir=out / "vault",
        disagreements_path=ledger,
        client=NoCallsAllowed(),
        limit=0,
    )
    verdict("gather_mixed_arm", summary)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    run_merge()
    run_gather()
    log("done")


if __name__ == "__main__":
    main()
