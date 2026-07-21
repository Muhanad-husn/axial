# Feature: Corpus-wide pass runner — one resumable loop for any pass

Today every per-source pass carries its own loop-and-resume story, and only one
of them — `axial ingest` — is a real, tested driver. This feature builds the one
in-process loop that drives **any** per-source pass (extract, envelope, chunk,
tag, artifacts, xref, vault write) over a set of sources, with per-source failure
isolation, a single unified resume ledger, progress, and an end-of-run summary.
`axial run <pass>` is P1-4 ("re-running skips already-processed sources"), not
new ground: it generalizes `run_ingest` from one hard-wired pass to a registry of
passes, keeping that function's proven shape — read the source set, skip what is
done, run one source, append a result row, continue on failure. The operator
(founder) benefits: one command produces the corpus reproducibly instead of the
retired `ingest_worker.sh` round-robin and the bare-`except` loop wrapper the
postmortem named as root cause D.

- **Slug:** run
- **Created:** 2026-07-21
- **Status:** planned
- **New system?** no — it lands as a new `src/axial/run.py` module + an `axial
  run` CLI namespace, generalizing the existing `src/axial/ingest.py`; slice 01
  is the walking skeleton (loop + pass registry + failure isolation over one
  pass)
- **Project directory:** `.`

## Why this is one runner, not one loop per pass

There are three source-level resume mechanisms in the tree today, and the runner
unifies them:

1. **A TSV ledger of `vault_status=OK` rows** keyed by `source_id`
   (`src/axial/ingest.py`, `data/gold/ingest.results.tsv`). The skip guard reads
   it at the top of the per-source loop.
2. **Output-file-exists checks** — `extract()` returns a cached
   `data/trees/<source_id>.json` and `run_envelope()` returns a cached
   `data/envelopes/<source_id>.json` rather than recomputing.
3. **A per-source xref-done signal** — `run_xref` checkpoints each processed
   chunk to `<xref_dir>/<source_id>.jsonl` and a resumed call skips any chunk
   already recorded (the issue names this the `data/logs/xref-done/` marker).

The pattern under all three is identical: *ask whether this source is already
done for this pass; if so, skip it doing zero work; otherwise run it and record
the outcome.* Slice 02 makes that pattern explicit — the runner owns one ledger,
each pass declares its **done-predicate** — so the three become one.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [runner-core-and-failure-isolation](01-runner-core-and-failure-isolation.md) | [#277](https://github.com/Muhanad-husn/axial/issues/277) | `axial run <pass> --worklist FILE` drives one registered per-source pass over a worklist, isolating each source's failure (record and continue), exiting non-zero only when the loop itself cannot run — walking skeleton for `src/axial/run.py` and the pass registry | ☐ todo | TBD |
| 02 | [unified-resume-ledger](02-unified-resume-ledger.md) | [#277](https://github.com/Muhanad-husn/axial/issues/277) | The runner owns one resume ledger; each pass declares a **done-predicate**; a re-run skips every already-done source doing zero pipeline work, replacing the three source-level mechanisms with one | ☐ todo | TBD |
| 03 | [source-sets-and-run-summary](03-source-sets-and-run-summary.md) | [#277](https://github.com/Muhanad-husn/axial/issues/277) | Accept the corpus glob (`data/sources/*.pdf\|*.docx`) as an alternative source set to `--worklist`, and emit an end-of-run summary (OK/FAIL/SKIP counts + per-source outcomes) with the seam #288 attaches its rates report to | ◐ in review | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- **01 is the foundation:** the per-source loop, the pass registry (a plain dict
  of pass name → invoker + its declared error type), the failure-isolation seam,
  and the exit-code contract. 02 and 03 both build on it and cannot start before
  it.
- **02 depends on 01.** It adds the runner-owned ledger and the done-predicate
  protocol. Until 02 lands, the runner reruns whatever a pass does not itself
  skip; the passes' own file-exists idempotence (mechanism 2) still holds, so 01
  is honest, just not resume-aware at the runner level.
- **03 depends on 01** and composes with 02: the summary reports the SKIP counts
  02 produces, but 03's own tests exercise inputs and reporting and do not require
  02. Sequence 02 before 03 for a coherent summary, not for correctness.
- Nothing here depends on the tag-quality or metadata slices of the completion
  plan. The runner drives whatever passes exist; it does not change any pass.

## Cross-feature seams (note the boundary, do not build)

- **#288 (not-applicable / unlisted rates report)** attaches to this runner's
  end-of-run summary. Slice 03 defines the summary structure and leaves a named
  attachment point; computing the rates is #288's scope, not this feature's.
- **#270 (structured run logging)** is the sibling feature that owns the log
  emitter (`data/logs/<run>/run.jsonl` + `summary.md`). The runner is
  **logging-aware** — it produces the per-source outcomes and the run summary
  #270 serializes — but it does not implement the emitter. The boundary: the
  runner returns/records structured outcomes; #270 writes them to disk in its
  format. Keep the runner's summary a plain in-process value so #270 can consume
  it without reaching into runner internals.
- **Stage 4 of the completion plan (the frozen-corpus re-tag) runs on this
  runner.** It is the vehicle: the re-tag is `axial run` over the corpus with
  stages 1–2 in place. That makes this feature a **prerequisite for closing Phase
  A** — stage 4 cannot be reproducible until the runner exists.

## Out of scope (whole feature)

- **Any change to a pass's own logic.** The runner drives extract/envelope/chunk/
  tag/artifacts/xref/vault-write as they are. Their signatures are the contract;
  the runner adapts to them, never the reverse.
- **The per-chunk checkpoints inside passes** (tag/artifacts/xref `.jsonl`). These
  are a finer, intra-pass resume granularity for a single expensive source and
  stay the pass's own business. The runner unifies *source-level* resume only; a
  pass's done-predicate may consult its own checkpoints, but the runner never
  reaches into them. Ripping out the `.jsonl` checkpoints is not this feature.
- **The run-log emitter and its file format** (#270).
- **The rates computation** for not-applicable/unlisted (#288).
- **Parallelism across sources.** The loop is sequential and in-process, like
  `run_ingest`. Concurrency is a measured follow-up if the corpus run proves too
  slow, never a speculative add.
- **Cross-pass orchestration** (running extract→envelope→…→vault in one command).
  `axial run <pass>` drives one pass over many sources; chaining passes is the
  operator's sequence of `run` invocations, or the existing composite
  `run_vault_write`, not a new dependency graph here.

## Notes / open questions

- **Pass registry is a dict, not a plugin system.** Seven known passes, all in
  this repo, all with a `(source_path, client, …dirs, config_path)`-shaped
  entrypoint and a declared `*Error` base (`ExtractError`, `EnvelopeError`,
  `ChunkError`, `TagError`, `ArtifactsError`, `VaultError`). A dict mapping pass
  name → a small descriptor (the callable + its error type + its done-predicate)
  is the whole abstraction. Any registration/discovery/entry-point machinery is
  over-engineering for a closed set of seven — flag it if it appears.
- **Failure isolation generalizes `run_ingest`, which catches only `VaultError`.**
  The runner must catch the running pass's declared error base and record a FAIL
  row, then continue. The open decision for the builder: catch each pass's own
  declared error type (precise, but the descriptor must carry it) versus a shared
  `PassError` base the passes do not have today. Recommendation: carry the error
  type in the descriptor (no pass change needed); pin the choice with a test that
  a per-source failure is recorded and the loop continues. A truly unexpected
  exception (not the pass's declared failure) should still abort — that is a bug,
  not a recoverable per-source signal.
- **Ledger location and key (slice 02).** `run_ingest` uses one flat
  `data/gold/ingest.results.tsv` for a single pass. Generalizing to many passes
  needs a per-pass ledger (key `(pass, source_id)`), e.g.
  `data/logs/<pass>/ledger.tsv` or a `pass` column in one file. Decide in 02 and
  pin it; reuse `run_ingest`'s TSV columns rather than inventing a new schema.
- **`source_id` is content-derived** via `envelope.compute_source_id`, never
  guessed — the ledger key and every skip decision go through it, exactly as
  `run_ingest` already does. A source whose id cannot be computed records a FAIL
  row and the loop continues (mirroring `run_ingest`'s `MissingSourceError`
  handling).
- **DEC-23.** The ledger and the summary carry ids, statuses, counts, and short
  reasons only — never source text.
