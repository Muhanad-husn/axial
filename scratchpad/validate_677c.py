"""Real-corpus validation of #677 slice C's four reuse counters, zero model calls.

Runs the SHIPPED `run_merge_names` and `run_gather` against the real 34-book
corpus in `D:/axial/data/`, never a fixture. Two things make it free and safe:

  * `limit=0`. `to_attempt = pending[:0]` is empty, so the worker pool reaches
    nothing, while the counters -- computed over the whole of `pending` before
    `--limit` trims it, which is exactly the decision this slice documented --
    are still the real ones. A client that raises on any call is the belt to
    that brace.
  * Every WRITE path is redirected into this scratchpad: alias map, index,
    manifest, failures, vault, disagreements copy. The real artifacts are
    opened read-only. Nothing under `data/names/` is touched.

Each pass runs twice. Run 1 sees a prior source set holding all 34 books, so
nothing is new and `units_asked_touching_new` should be 0 or near it. Run 2
sees a prior source set with the three books #623 added stripped out, so every
asked unit touching one of them should count. The gap between the two runs is
the discriminator; a counter that reports the same number both times is
measuring nothing.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

DATA = Path("D:/axial/data")
NAMES = DATA / "names"
OUT = Path(__file__).resolve().parent / "677c-out"

# The three books #623 added to the 31-book corpus.
NEW_SOURCES = {
    "gelvin-1998-f7e1df5f9b1d",
    "hinnebusch-1990-ac29981e616e",
    "wedeen-2019-3ae1f7af318d",
}


class NoCallsAllowed:
    """Any model call at all is a bug in this harness, not a cost to absorb."""

    def __getattr__(self, name):
        def _raise(*_args, **_kwargs):
            raise AssertionError(f"harness made a model call: client.{name}()")

        return _raise


def log(event: str, **fields: object) -> None:
    line = " ".join(f"{k}={v}" for k, v in fields.items())
    print(f"{event}: {line}", flush=True)


def check(summary: dict, label: str) -> None:
    total, reused = summary["units_total"], summary["units_reused"]
    asked, touching = summary["units_asked"], summary["units_asked_touching_new"]
    log(
        label,
        units_total=total,
        units_reused=reused,
        units_asked=asked,
        units_asked_touching_new=touching,
    )
    assert asked + reused == total, f"{label}: {asked} + {reused} != {total}"
    assert touching <= asked, f"{label}: touching_new {touching} > asked {asked}"


def run_merge() -> None:
    from axial.merge_names import run_merge_names

    out = OUT / "merge"
    out.mkdir(parents=True, exist_ok=True)

    def go(label: str, manifest: Path) -> dict:
        summary = run_merge_names(
            embeddings_dir=NAMES / "embeddings.lance",
            alias_map_path=out / "alias_map.json",
            index_path=out / "index.json",
            decisions_path=NAMES / "merge_decisions.jsonl",  # read-only at limit=0
            manifest_path=manifest,
            failures_path=out / "merge_failures.jsonl",
            # Without this the relative default resolves inside the worktree,
            # where `data/` does not exist, and the run pays for a 10-minute
            # full HDBSCAN re-fit whose batches are not the ones the corpus
            # was actually decided against.
            similarity_manifest_path=NAMES / "similarity_manifest.json",
            client=NoCallsAllowed(),
            limit=0,
        )
        check(summary, label)
        return summary

    # Run 1: prior manifest carries all 34 books, so nothing is new.
    full = out / "manifest_all34.json"
    shutil.copy(NAMES / "merge_manifest.json", full)
    prior = json.loads(full.read_text(encoding="utf-8"))
    if "source_ids" not in prior:
        # The real manifest predates this field. Seed it from the corpus the
        # embeddings themselves cover, which is what a post-slice-C run writes.
        log("merge_prior_manifest_lacks_source_ids", note="seeding from this run's own coverage")
        probe = go("merge_seed_probe", out / "manifest_seed.json")
        seeded = json.loads((out / "manifest_seed.json").read_text(encoding="utf-8"))
        prior["source_ids"] = seeded["source_ids"]
        log("merge_corpus_source_ids", count=len(prior["source_ids"]))
        assert NEW_SOURCES <= set(prior["source_ids"]), "the 3 new books are not in the coverage"
        del probe
    full.write_text(json.dumps(prior, indent=2), encoding="utf-8")
    all34 = go("merge_run1_prior_has_all_34", full)

    # Run 2: same corpus, prior manifest rewound to the 31 books.
    rewound = out / "manifest_31.json"
    prior31 = dict(prior)
    prior31["source_ids"] = sorted(set(prior["source_ids"]) - NEW_SOURCES)
    rewound.write_text(json.dumps(prior31, indent=2), encoding="utf-8")
    log("merge_rewound_prior", source_ids=len(prior31["source_ids"]))
    only31 = go("merge_run2_prior_missing_3_books", rewound)

    log(
        "merge_discriminator",
        touching_new_with_all_34=all34["units_asked_touching_new"],
        touching_new_with_31=only31["units_asked_touching_new"],
        asked=only31["units_asked"],
    )


def run_gather() -> None:
    from axial.gather import _source_ids_of
    from axial.gather import run_gather as _run_gather

    out = OUT / "gather"
    (out / "vault").mkdir(parents=True, exist_ok=True)

    def go(label: str, ledger: Path) -> dict:
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
        check(summary, label)
        return summary

    # Run 1: the real ledger, whose records already cover all 34 books.
    full = out / "disagreements_all34.jsonl"
    shutil.copy(NAMES / "disagreements.jsonl", full)
    all34 = go("gather_run1_ledger_covers_all_34", full)

    # Run 2: every record mentioning one of the 3 new books removed, so the
    # ledger's own source coverage rewinds to the 31-book corpus. This also
    # rewinds `units_reused`, which is the point -- those are exactly the
    # pages a new book would put back in play.
    rewound = out / "disagreements_31.jsonl"
    kept = dropped = 0
    with (
        full.open(encoding="utf-8") as src,
        rewound.open("w", encoding="utf-8") as dst,
    ):
        for line in src:
            if not line.strip():
                continue
            record = json.loads(line)
            chunk_ids = record.get("chunk_ids") or []
            if _source_ids_of(chunk_ids) & NEW_SOURCES:
                dropped += 1
                continue
            dst.write(line)
            kept += 1
    log("gather_rewound_ledger", kept=kept, dropped_touching_new_books=dropped)
    only31 = go("gather_run2_ledger_missing_3_books", rewound)

    log(
        "gather_discriminator",
        touching_new_with_all_34=all34["units_asked_touching_new"],
        touching_new_with_31=only31["units_asked_touching_new"],
        asked_with_all_34=all34["units_asked"],
        asked_with_31=only31["units_asked"],
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log("start", cwd=Path.cwd(), axial=sys.modules.get("axial", "not-yet-imported"))
    run_merge()
    run_gather()
    log("done")


if __name__ == "__main__":
    main()
