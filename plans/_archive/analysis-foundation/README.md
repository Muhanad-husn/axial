# Feature: Analysis-engine foundation — briefs, corpus pin, dev backlog

Lay the ground Phase B stands on: the brief input contract, the reproducibility
pin, and the dev-brief backlog that lets the engine be built and dry-run without
the Academic in the loop. A brief loader reads a versioned brief file into the
§7.1 shape and computes a deterministic `brief_id` over its content. A corpus-pin
manifest (§7.12, P0-10) records the source list, the ingest-code SHA, and a vault
snapshot hash so two runs are comparable only when their pins match. The founder's
26 parked Academic research questions land as versioned dev briefs under
`config/briefs/dev/` (P0-11). The operator (founder) benefits: every later Phase-B
stage has a stable input shape, a reproducible corpus reference, and a real
backlog of briefs to build against — none of it blocked on the Academic (§9).

- **Slug:** analysis-foundation
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** yes (Phase B opens a new module tree per §6; slice 01 is the
  walking skeleton establishing `src/axial/brief/` and the `axial brief` CLI
  namespace)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [brief-intake-and-id](01-brief-intake-and-id.md) | [#247](https://github.com/Muhanad-husn/axial/issues/247) | A brief loader reads a versioned brief file into the §7.1 shape `{brief_id, case, request, lens?}`, validates it, and computes `brief_id` as a stable content hash — walking skeleton for `src/axial/brief/` and `axial brief` | ☐ todo | TBD |
| 02 | [corpus-pin-manifest](02-corpus-pin-manifest.md) | [#248](https://github.com/Muhanad-husn/axial/issues/248) | `axial pin write <name>` emits `evals/corpus_pin/<name>.json` carrying the source list with content hashes, the ingest-code SHA, and a vault snapshot hash over `(chunk_id, tags)` — never `chunk_text` | ☐ todo | TBD |
| 03 | [dev-brief-backlog](03-dev-brief-backlog.md) | [#250](https://github.com/Muhanad-husn/axial/issues/250) | The founder's 26 parked Academic research questions land under `config/briefs/dev/` as versioned dev briefs, each parsing under slice 01's loader — **BLOCKED on the founder supplying the question files** | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- 01 is the input contract. 03 depends on 01 (its conformance test runs every dev
  brief through 01's loader) and is additionally **blocked on the founder** for
  the 26 question files, which live with the founder and are not yet in the repo.
- **02 is independent of 01** and can run in parallel: the pin reads the vault
  and the envelopes, never a brief. Sequence it against 01 only for reviewer
  bandwidth, not for correctness.
- Nothing here depends on the vault-query feature. All three slices are LLM-free
  by construction: no model call, no embedding call, on any path.

## Out of scope (whole feature)

- The interrogation pre-pass itself (P0-1, §7.2). This feature lands the brief's
  *input* contract; interrogating it is a later sprint and the first model call
  in Phase B.
- `axial brief run` and `axial brief examine` (P0-9). Slice 01 establishes the
  `axial brief` namespace with read-only subcommands only.
- The analysis record (§7.3) and anything that writes `data/analyses/`.
- Lens vocabulary data under `config/lenses/` — the `lens` field is validated as
  an optional string here; resolving a lens name against a lens file is stage-4
  work (§7.1, §5 stage 4).
- Any change to the Phase-A ingest pipeline. The pin *reads* what Phase A wrote;
  Phase A is consumed, never modified (§0 inherits note, §3 non-goal 5).
- Pin verification / drift detection (comparing a live vault against a written
  pin). Slice 02 writes a pin; consuming it is stage-6 and eval work.

## Notes / open questions

- **Hash reuse:** `envelope.compute_source_id()` already computes a content
  hash (SHA256 of content, first 12 chars, plus the filename stem). Slice 02
  reuses that hashing path for the pin's source list rather than inventing a
  second content-hash convention.
- **DEC-23 is load-bearing in slice 02.** The vault snapshot hash is computed
  over `(chunk_id, tags)` pairs in a deterministic order and **never** over
  `chunk_text`. The pin file is committed to the repo; it must carry ids and
  hashes only. Any reviewer finding of source text in a pin is a hard fail.
- **Fixture briefs land in 01, not 03.** Slice 01 writes 2–3 hand-written
  fixture briefs into `config/briefs/dev/` so every downstream stage has real
  input to build against before the founder's 26 questions arrive. Slice 03
  adds the real backlog alongside them.
- **`brief_id` determinism** is the whole point of the field (§7.1): no
  randomness, no timestamps, no filename dependence. Re-running the same brief
  content yields the same id, so `data/analyses/<brief_id>.json` is stable
  across runs.
- **Corpus-pin format ownership:** `docs/eval/01-answer-quality.md` documents
  the format (lines ~40–58) but nothing implements it. §7.12 says implementing
  it is part of this phase. Slice 02 is the implementation; the doc stays the
  format's owner.
