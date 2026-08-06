# Three new books into the corpus, and the map rebuilt (#623)

2026-08-05. The first live exercise of "add books to a finished corpus": Gelvin,
Hinnebusch and Wedeen joining the 31 already ingested. Run from `D:\axial`.
Main at `680fccf` for the pipeline passes.

**Result: complete, zero failures at every pass.** 34 sources, 6,733 notes,
47,220 name pages, map pinned at `3c49f2e5a035fbc3`.

## The standing constraint held

The 31 existing sources were **not** re-ingested. Every pass reported it:

    envelope   total=34 ok=3 skipped=31 failed=0
    chunk      total=34 ok=3 skipped=31 failed=0

and the 31 existing chunk artifacts still carry their 2026-07-27 timestamps.

## One bug found before it cost anything

`data/run/ledger.tsv` has never been written on this corpus, and `chunk`
declared the ledger done-predicate — so `axial sources` would have re-chunked
all 31 books immediately after its own report called them `done`.

Measured on `agamben-2005` before the fix: the rewrite was byte-identical (53
chunks, same ids, same text) but cost seven model calls. Identical output is not
guaranteed in general — those calls decide which lines get routed out of a
section, and one landing differently would renumber that source's notes and
orphan every analysis pinned to them.

Fixed in PR #672: chunk now skips on its own artifact, like extract and envelope.

## A second gap, closed in-run

`axial sources` runs extract → envelope → chunk → interrogate and stops. The
`artifacts` pass is not in that chain, so the first materialize reported
`artifact_sources: 31` — the new books had no table/figure notes while the other
31 did. Run separately (deterministic, no model calls); the final materialize
reports `artifact_sources: 34`.

## Cost

| | |
|---|---|
| ingestion of the 3 books | **~$4.21** (estimated at the measured $0.0072/note; no credits baseline was taken before this half — a process miss) |
| the map rebuild | **$6.05** (measured credits delta, 705.579 → 711.63) |
| **total** | **~$10.26** |

Rebuild breakdown: merge $1.60 · Gather $2.30 · map build $1.28 ($0.874
positions + $0.405 relations) · residue $1.16 ($0.328 blocked + $0.827
unblocked). Materialize, names build and artifacts are free.

## Wall clock — 9.5 hours, and why

| step | min | notes |
|---|---|---|
| extract | 36 | docling, serial-only by constraint |
| envelope | 16 | 3 sources, 31 skipped |
| chunk | 7 | 3 sources, 31 skipped |
| interrogate | 102 | 3 books in parallel; **governed by hinnebusch alone** |
| names build | 9 | local, free |
| name merge | 48 | 5,143 re-asks of 13,900 batches |
| materialize | 10 | free |
| Gather | 104 | 1,174 asked, 666 reused |
| map build | 99 | cold — new pin, no reuse possible |
| residue | 28 | cold — new pin |
| materialize (final) | 13 | free, folds residue |

**Effective concurrency, measured** (summed model-call latency ÷ wall clock):

| pass | calls | call latency | effective | nominal |
|---|---|---|---|---|
| interrogate (one source) | 234 | 102 min | **1.00** | 1 |
| gather | 2,082 | 2,171 min | 20.9 | 24 |
| map build | 1,058 | 1,649 min | 16.7 | 20 |
| merge | 5,164 | 1,615 min | 33.9 | 36 |

Nothing idled — 8,971 calls totalling 94 hours of API latency. But
`interrogate` ran strictly one call at a time. PR #673 makes it concurrent
(default 12) and raises Gather 36→48 and map build 20→40; merge is left at 36
because it is already 94% utilised and #457 measured 2.8x the parse failures at
128 workers for 1.28x throughput.

Two operator errors of my own, recorded so they are not repeated: Gather was
launched with `--workers 24` copied from an old run log when its default was
already 36, making it slower than doing nothing; and the map build's completion
went unnoticed for ~2 hours because the watch pattern did not match the actual
output format — a watch whose success condition never fires is indistinguishable
from a job still running.

## The structural finding

Of 8,971 model calls, **594 (7%) were spent on the three new books and 8,304
(93%) on the 31 already ingested.** Adding three books cost 14x more calls
against the existing corpus than against the new material. This is not a bug:
the merge re-clusters globally, Gather re-renders any name page that gains a
single member, and the map's corpus pin invalidates every bag.

Reuse where it exists: merge reused 8,756 of 13,900 batches (63%), Gather 666 of
1,840 (36%). The map gets none by construction — bags are clusters over all
passages at once and the resume ledger is keyed by cluster label, so reusing an
old ledger under a new pin would attach old answers to differently-composed
bags.

Whether a name page that gains one note out of two hundred genuinely needs
re-asking is a design question this run raises and does not answer. Today's
content-key is all-or-nothing.

## Counts, before → after

| | before | after |
|---|---|---|
| sources | 31 | **34** |
| notes | 6,148 | **6,733** |
| name inventory entries | 61,612 | 57,834 |
| name pages | 49,555 | 47,220 |
| artifact notes | 910 | 963 |
| `store_note_opposed_position` | 0 | **2,049** |
| map positions | — | 1,890 |
| map relations | — | 1,410 (593 cross-author) |

The inventory and name-page drops are **not** a loss from the new books: this
was the first `names build` since #661's back-matter rule, and the old inventory
was built 2026-07-30. Back matter now leaves the name space.

## What this leaves stale

Every analysis pinned to the previous corpus. The map pin moved
`297bcfa93d6974b0` → `3c49f2e5a035fbc3`. Measured 2026-08-02: records pinned to
a superseded corpus resolve only 4–12 of 30–49 of their citations. Anything that
must stay citable gets re-run, or is knowingly retired.

## Drive

Not exercised. The connector needs a `[drive]` section with
`service_account_json` and `books_folder_id`; `secrets.toml` carries an unread
`[google_drive]` block pointing at a credentials file that does not exist.
Separately, `axial.drive`'s default ingest chain still ends in the retired
`run_vault_write` and never runs `interrogate`, so it would fail on every book
even with credentials. The three PDFs were fetched from the shared folder by
hand and ingested through the local backend, at the founder's direction.

## Files

`extract.log` · `envelope.log` · `chunk.log` · `interrogate-*.log` ·
`names-build.log` · `names-merge.log` (the gate abort) · `names-merge2.log` ·
`materialize.log` · `gather.log` · `map-build.log` · `map-residue.log` ·
`materialize-final.log`. Pre-run backups: `inventory-before.jsonl`,
`alias_map-before.json`, `merge_decisions-before.jsonl`,
`disagreements-before.jsonl`, `merge_manifest-before.json`.
