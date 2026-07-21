# Slice 01: Orphan GC — `axial reconcile gc`, dry-run-first, consent-gated, logged

- **Feature:** reconcile
- **Slice slug:** orphan-gc
- **GitHub issue:** #291
- **Branch:** feat/reconcile/01-orphan-gc
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** yes (establishes the new `src/axial/reconcile.py` module
  and the new `axial reconcile` subcommand group)

## Goal — the minimum testable behaviour

`axial reconcile gc` computes the **live** `source_id` set by running
`envelope.compute_source_id()` over every file in `data/sources/`, scans the
derived-artifact dirs (`trees`, `envelopes`, `chunks`, `tags`, `artifacts`,
`xref`, `vault`), and attributes each file to a `source_id`. Any file whose
`source_id` is **not** in the live set is an orphan.

By default the command is a **dry run**: it prints the orphan list (grouped by
orphaned `source_id`, paths only) and removes nothing. With `--apply` it shows
the same list, asks the operator to confirm, and on confirmation removes the
orphaned files and writes a removal log under `data/logs/reconcile/`. `--yes`
auto-confirms so the run is non-interactive. A live `source_id` is never a
deletion candidate, `data/sources/` is never scanned for removal, and a file
that cannot be confidently attributed is reported and left in place. This is the
reconciliation spine: live-id set → derived-dir scan → attribute →
orphan diff → dry-run list → consent → remove + log.

## INVEST check

- **Independent:** owns a new `reconcile.py` and a new `reconcile` subcommand;
  reuses `compute_source_id()` and the existing per-dir path seams, changing no
  producer pass.
- **Valuable:** the first mechanism that makes `data/` honest after a rename or
  re-save — the `data/chunks/` ~56-against-30 over-count (#291) is the presenting
  symptom, and every corpus count downstream inherits the fix.
- **Small:** one subcommand, one live-id computation, one scan, one diff, one
  consent gate, one log writer.
- **Testable:** build a temp `data/` tree with live sources and known orphans,
  run `axial reconcile gc` (dry run asserts a listing with nothing removed) then
  `--apply --yes` (asserts orphans gone, live artifacts kept, log written).

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a temp data tree with a source file in data/sources/ whose derived
      artifacts (tree, envelope, chunks, tags, artifacts, vault notes) exist
      under its live source_id
And   a set of derived artifacts under a stale source_id whose source file is
      absent from data/sources/ (a renamed / re-saved source's old id)
When  the operator runs `axial reconcile gc`
Then  it exits 0 and lists exactly the stale source_id's artifacts as orphans,
      grouped by source_id, and removes nothing (dry run is the default)
And   the live source_id's artifacts are absent from the orphan list
When  the operator runs `axial reconcile gc --apply --yes`
Then  the stale source_id's artifacts are removed from every derived dir
And   the live source_id's artifacts remain untouched on disk
And   data/sources/ is unchanged
And   a removal log is written under data/logs/reconcile/ recording the removed
      paths and their orphaned source_ids and the live keep-set, with no source text
```

- **Boundary / endpoint:** CLI command `axial reconcile gc` (flags `--apply`,
  `--yes`); the derived and source dirs resolve through the same relative-path
  seams the producers use, so a temp-cwd fixture isolates the run from real
  `data/`.
- **Outer test type:** pytest integration test (subprocess; no LLM client
  present — the whole surface is deterministic and model-free)
- **Outer test file (planned):** tests/test_reconcile.py — test-author, red,
  locked (DEC-1)

The test builds its `data/` tree under a tmp path (never real `data/`) and runs
the CLI with cwd set there. Consent is injected via `--yes`; no interactive
prompt is ever driven. Files are tiny stand-ins with valid shapes (a vault note
with a `source_id` frontmatter line, a `<source_id>.jsonl` chunk file, etc.),
carrying no real source text.

## Inner loop — initial unit test list

- [ ] `live_source_ids(sources_dir)` returns `compute_source_id()` for every
      file in `data/sources/`, and an empty set when the dir is absent/empty
- [ ] a `<source_id>.json` / `.jsonl` artifact whose id is in the live set is
      **not** an orphan; one whose id is absent from the live set **is**
- [ ] the `<source_id>.skips.jsonl` chunk sidecar is attributed to the same
      `source_id` as its main artifact (the `.skips` suffix is stripped, not
      treated as a distinct id)
- [ ] a vault note is attributed by its frontmatter `source_id`, falling back to
      the `chunk_id`/`artifact_id` filename prefix; an unreadable note is
      reported *unattributed, skipped*, never removed (the load-bearing decision)
- [ ] a non-source-scoped file in a derived dir (e.g.
      `data/tags/theory_school_candidates.jsonl`) is never attributed to a
      source and never listed as an orphan
- [ ] dry run (no `--apply`) returns the orphan list and performs zero deletions
      and zero writes
- [ ] `--apply` without `--yes` calls the injected confirm; a "no" answer
      removes nothing; a "yes" answer removes exactly the listed orphans
- [ ] `--apply --yes` removes every orphan path and leaves every live-id path and
      all of `data/sources/` untouched
- [ ] the removal log is one record per removed path plus a run header with the
      keep-set; it contains paths and `source_id`s only and no source text
      (DEC-23)
- [ ] an empty/absent derived dir, and a data tree with no orphans at all, both
      exit 0 with an empty orphan list and no log write

## Design notes for the implementer

- **Reuse, don't reinvent.** Build the keep-set with
  `envelope.compute_source_id()` (and its `content_digest()` primitive) — the
  same hashing path the producers use. Resolve each derived dir through its
  existing seam (`_default_chunks_dir`, `_default_envelopes_dir`, and the
  `TREES_DIR` / `TAGS_DIR` / `ARTIFACTS_DIR` / `XREF_DIR` / `VAULT_DIR`
  module defaults), so the scan honours `config/pipeline.yaml` where the
  producer does and stays relative-to-cwd where it does not.
- **Dir list is an explicit constant**, one row per surface — not a plugin
  registry (over-engineering tripwire). Add `data/source_meta/` when #285 lands.
- **CLI wiring** mirrors the `gold` / `vault` / `polity` subcommand groups in
  `cli.py`: a `reconcile` parser with a `reconcile_command` dest, a `gc`
  subparser carrying `--apply` and `--yes`, dispatched from `main()`.
- **Safety posture** follows `classify-branches.mjs` (DEC-19): dry-run default,
  delete only under `--apply` + confirm, mandatory log before removal.

## Out of scope for this slice (deferred)

- **Any change to `source_id` computation** — the churn is inherent to a
  content-hash id; reconcile cleans up after it.
- **Content-based "did this move?" matching** — reconcile decides purely on
  `source_id`-not-in-`data/sources/`, never by re-homing a renamed file's
  artifacts.
- **Automatic / scheduled / on-write GC** — the operator runs it deliberately.
- **Sweeping `data/source_meta/`** — that surface arrives with #285; add its row
  then.
- **Alignment with the #270 run-log format** — reconcile writes its own
  self-contained log now (0a lands before 0b) and aligns later.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED
      (flag-approved), seen to fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test
      GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI.
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` — merge awaits founder
      approval.

## Status / progress log

- 2026-07-21 planned.
