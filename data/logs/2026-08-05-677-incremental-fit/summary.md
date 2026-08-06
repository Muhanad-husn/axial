# Issue #677 slice A: real-corpus validation

Two independent runs of `scratchpad/validate_677.py`, both from the main checkout `D:\axial` with the worktree branch's code (`uv run --project <worktree> python scratchpad/validate_677.py`), cwd pinned to `D:\axial` so relative `data/` paths resolve against the real corpus while the branch's `src/axial/names.py` executes. Zero model/embedding calls either time: every vector is reused from the already-persisted `data/names/embeddings.lance`.

- **Run 1** (`run-1.jsonl`, reconstructed): the simpler first version of the script, no disturbance-cause breakdown yet.
- **Run 2** (`run.jsonl`, authoritative): the same measurement plus the disturbance-cause breakdown below.

**Every shared metric reproduced byte-identical across the two runs** (both HDBSCAN fits are deterministic at `random_state=0`, fixed dials, and the same persisted vectors): baseline 12,458 batches, accepted 580 / residue 3,752, 847 residue clusters minted, incremental 13,305 batches, identical-to-baseline 11,103, new 2,202, disturbed 1,355, and incremental-vs-fresh-34 identical 11,172. That determinism is itself part of the acceptance bar (`axial names build` run twice over unchanged input must behave identically), and this cross-run reproduction is additional evidence for it, on top of the inner unit tests that assert it directly.

*(`run-1.jsonl`'s own timestamps could not be recovered -- a second run's `open("w")` truncated `run.jsonl` in place before its content was saved elsewhere, the same class of bug as the `brief_id` overwrite lesson. Its field VALUES are reconstructed verbatim from that run's own captured stdout. The script is now fixed to rename an existing `run.jsonl` to `run-N.jsonl` before opening a fresh one, rather than truncating it.)*

## The headline numbers (run 2)

- 31-book subset: 53,502 entries, 12,458 batches (12,458 unique keys), fit in 436.9s
- 34-book (delta = 3 books) full inventory: 57,834 entries (53,502 known, 4,332 new)
- `approximate_predict` over the 4,332 new entries: 580 accepted (13.4%), 3,752 residue (86.6%) (50.9s)
- residue re-fit: 847 new cluster(s) minted from the 3,752 residue entries, offset above label 12,457 (1.9s) -- 847 distinct new clusters from one 3-book delta reads as new books genuinely bringing new names, not the floor being over-strict: a strict floor swallowing real new names into an existing cluster would show up as noise or as one or two oversized clusters, not 847 separately-shaped ones.

## Incremental vs the 31-book baseline

| | count | share of 12,458 baseline batches |
|---|---:|---:|
| byte-identical (free, no re-ask) | 11,103 | 89.1% |
| new batches (the 3-book delta's own work) | 2,202 | -- |
| disturbed (baseline batch no longer exists) | 1,355 | 10.9% |

**Compare to #623's own baseline under the OLD global-refit `axial names build`: 5,143 re-asks of 13,900 batches (37.0%).** Incremental assignment cuts the re-ask rate from 37.0% to 10.9% -- roughly a 3.4x reduction -- on the exact same 3-book delta.

### Why 580 accepted new entries disturbed 1,355 old batches -- the split-budget hypothesis is refuted

| cause | count | share of 1,355 disturbed |
|---|---:|---:|
| evidence-only (member set unchanged, a member's `(in <sources>)` suffix changed) | 896 | 66.1% |
| cluster grew (an accepted new entry actually joined) | 459 | 33.9% |
| -- of which: cluster already split into >1 baseline batch | 0 | 0.0% |
| unexplained | 0 | 0.0% |

**The character-budget split-amplification hypothesis is refuted: `split_amplified_of_grew = 0`.** Not one of the 459 "grew" disturbances belongs to a cluster `_split_into_batches` had already divided into more than one batch -- a new member joining a split cluster does not cascade into reshuffling every later slice. Every disturbance is explained by one of the two remaining causes, with **none left over**.

**The dominant cause (66.1%) is not incremental assignment moving a label at all.** `MergeBatch.key` hashes each member's *rendered* line, and issue #449's evidence join appends `(in <source ids>)` to that line. A surface form already decided under the 31-book fit that simply appears in one of the 3 new books too gets a new evidence suffix, which changes the batch's content hash even though its cluster membership is byte-identical. This is a property of the existing evidence-join design, independent of this issue's mechanism, and is not something this slice fixes -- flagged for separate measurement, not built here.

## Incremental vs a fresh full re-fit over all 34 books -- the drift, stated honestly

- fresh 34-book fit: 13,458 batches (13,458 unique keys), 533.6s
- incremental agrees with a fresh fit on 11,172 of 13,458 batches (83.0%). **This is not "free reuse of a decision"** -- most of these were never asked about under either fit -- it is how much the two partitions agree. The other 17.0% is real drift: incremental assignment approximates what a fresh fit would say, it does not replace one.
- incremental-only (2,133): batches incremental kept stable that a fresh fit would have reshuffled -- this is the point of the mechanism.
- fresh-only (2,286): batches only a fresh fit produces -- what `--recluster` is for. Periodic reclustering is the corrective this drift calls for, not a defect in the incremental path.

## Notes

- Zero model/embedding calls: every vector reused from the persisted `data/names/embeddings.lance`; the 31-book/34-book split is answer-record filtering over the already-cached corpus; both fits are local HDBSCAN/PCA/StandardScaler.
- `fold_groups` (case/whitespace/punctuation dedup, upstream of the real `axial names merge`) is not applied here -- this measures label-key stability directly, not the full merge pipeline's exact batch count.
- Both HDBSCAN fits (~437s and ~534s) ran once each in a single clean background process per run; an earlier accidental double-launch was killed and its log directory cleared before the runs reported here.
