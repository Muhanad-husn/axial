# Feature: Reconcile — safe GC for orphaned derived artifacts

`source_id` is derived from the source file's content hash (§7.12,
`envelope.compute_source_id()` — the filename stem plus a 12-char sha prefix).
Rename or re-save a source and it gets a **fresh** `source_id`, which orphans
every derived artifact the old id produced: its tree, envelope, chunks, tags,
artifacts, xref records, and vault notes all keep living under the dead id.
Nothing garbage-collects them. The measured symptom: `data/chunks/` held ~56
`.jsonl` files against 30 live sources, so `axial chunk examine` counts chunks
for sources that no longer exist and over-reports the corpus (#291).

This feature builds the **general** mechanism to fix that: identify every
derived artifact whose `source_id` no longer maps to a live file in
`data/sources/`, show the operator the list, and — only on explicit consent —
remove the stale files and log exactly what was removed. It is not a one-off
cleanup script; it is a repeatable `axial reconcile gc` subcommand the operator
runs whenever a re-save or rename has drifted the derived tree.

- **Slug:** reconcile
- **Created:** 2026-07-21
- **New system?** yes (a new `src/axial/reconcile.py` module and a new
  `axial reconcile` subcommand group; slice 01 is the whole thread —
  compute the live-id set, scan the derived dirs, list, confirm, remove, log)
- **Status:** planned
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [orphan-gc](01-orphan-gc.md) | [#291](https://github.com/Muhanad-husn/axial/issues/291) | `axial reconcile gc` — dry-run-first: list derived artifacts whose `source_id` is not a live file in `data/sources/`, and on explicit `--apply` (consent-gated) remove them and write a paths/ids-only removal log | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

The problem is cohesive — one live-id computation, one derived-dir scan, one
consent-gated remove, one log — so it is a single slice, not two. If vault-note
attribution (see Notes) proves to need its own red-green pass it can split out,
but the walking skeleton carries the whole mechanism.

## Safety model — the whole point

Deletion is the risk, so the design borrows the vendored
`classify-branches.mjs` posture (DEC-19): **dry-run by default, delete only on
explicit consent, log before you remove.**

- **Dry-run is the default.** `axial reconcile gc` with no flags lists the
  orphans it *would* remove and touches nothing. Removal happens only under
  `--apply`.
- **Consent is explicit and injectable.** Under `--apply` the operator is shown
  the full list and asked to confirm interactively; `--yes` auto-confirms for
  non-interactive runs (and makes the acceptance test non-interactive). No
  deletion path exists that skips both the dry-run gate and the confirm.
- **A live `source_id` is never a deletion target.** The keep-set is recomputed
  from `data/sources/` via `compute_source_id()` at run time; a file is a
  candidate only if its attributed `source_id` is **not** in that set.
  `data/sources/` itself is read-only to this tool — it is never scanned for
  removal.
- **Only confidently-attributable files are removed.** A file whose `source_id`
  cannot be parsed or read is reported as *unattributed, skipped* and left in
  place — when in doubt, keep. Non-source-scoped files that share a derived dir
  (e.g. `data/tags/theory_school_candidates.jsonl`) are never attributed to a
  source and so are never removed.
- **Every removal is logged, paths/ids only.** Each `--apply` run writes a
  removal log recording the keep-set ids, the removed paths, and their orphaned
  ids — **no source text** (DEC-23). The log doubles as a rebuild list: every
  removed artifact is regenerable by re-running its pass over the untouched
  source, so nothing is truly lost.

## Dependencies

- **Independent.** Owns a new module (`reconcile.py`) and a new subcommand; it
  reads the existing per-dir path seams (`_default_chunks_dir` and siblings) but
  changes no producer. It is Wave-1 / Stage-0 hygiene in the phase-a-completion
  plan and shares no file with any other slice.
- Reuses `envelope.compute_source_id()` and its `content_digest()` primitive
  directly — the same hashing path the producers use, not a second convention.
- Nothing downstream depends on it; it only makes `chunk examine` and every
  later corpus count honest.

## Out of scope (whole feature)

- **Any change to how `source_id` is computed.** The churn is inherent to a
  content-hash id (that is what makes stale-cache reuse impossible); reconcile
  cleans up after it, it does not redesign it.
- **Content-based dedup or "did this source move?" matching.** Reconcile decides
  purely on `source_id`-not-in-`data/sources/`. It does not try to guess that a
  renamed file is "the same" work and re-home its artifacts.
- **Automatic or scheduled GC.** No cron, no post-pass hook, no delete-on-write.
  The operator runs it deliberately. Consent is the contract.
- **Touching `data/sources/`.** Reconcile never adds, moves, or removes a source
  file. It only clears *derived* artifacts.
- **A general `--data-root` flag or pluggable "artifact kind" registry.** The
  derived dirs resolve through the same relative-path seams the producers use
  (so a temp-cwd fixture isolates the test); the kinds are a short explicit list,
  not a plugin surface.

## Notes / open questions

- **The derived surfaces and their naming.** Six of the seven are named directly
  by `source_id`, so attribution is the file stem:
  `data/trees/<source_id>.json`, `data/envelopes/<source_id>.json`,
  `data/chunks/<source_id>.jsonl` (+ the `<source_id>.skips.jsonl` sidecar),
  `data/tags/<source_id>.jsonl`, `data/artifacts/<source_id>.jsonl`,
  `data/xref/<source_id>.jsonl`. The scan resolves each dir through the same
  seam its producer uses (`_default_chunks_dir`, `_default_envelopes_dir`, …).
- **Vault notes are the one wrinkle, and the one real decision.**
  `data/vault/prose/<chunk_id>.md` and `data/vault/artifacts/<artifact_id>.md`
  are named by `chunk_id`/`artifact_id`, not by `source_id`. `chunk_id` carries
  its `source_id` as a prefix (`{source_id}_{page_start}_{page_end}-…`), and
  artifact notes carry `source_id` in frontmatter. **Recommended:** attribute a
  vault note by reading its frontmatter `source_id` (authoritative), falling
  back to the filename prefix only when frontmatter is unreadable — and treat an
  unreadable note as *unattributed, skipped* rather than guessing. The
  implementer should pin this choice with a unit test. This is the load-bearing
  ambiguity of the slice.
- **The keep-set is a set of ids, not paths.** Build it once by running
  `compute_source_id()` over every file in `data/sources/`; a source with no
  derived artifacts yet contributes an id that simply matches nothing. Recompute
  every run — the hash is cheap and being current is the safety property.
- **Removal-log location.** Write under `data/logs/` (gitignored, DEC-23), e.g.
  `data/logs/reconcile/<timestamp>.jsonl`, one record per removed path plus a
  run header carrying the keep-set. Stage 0b (#270) introduces a richer
  `data/logs/<run>/` convention; reconcile lands **before** it and must stay
  self-contained, so it writes its own simple log now and aligns with #270 later
  rather than depending on it.
- **Forward-compat, not future-proofing.** Stage 1c (#285) adds
  `data/source_meta/<source_id>.json`; when it lands it becomes another
  source-id-named derived surface reconcile should sweep. The dir list is a
  short explicit constant — add the row then, do not build a registry now.
- **DEC-23 holds throughout.** The list shown to the operator, the confirm
  prompt, and the removal log carry paths and `source_id`s only — never chunk or
  source text.
