# Slice 04: Retire the per-pass non-prose gate; examine reads the router's decisions

- **Feature:** source-router
- **Slice slug:** gate-retire-examine
- **GitHub issue:** #169
- **Branch:** feat/source-router/04-gate-retire-examine
- **Project directory:** .
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

Two related closures of #164's "classify once, decide once" intent:

1. **Retire `nonprose_guard.non_prose_skip_reason` as the primary gate** in `tag` and `xref`.
   Because the chunk artifact is now prose-only (routed, slices 02–03), tag/xref no longer
   re-decide prose/non-prose per item at LLM entry. The guard is kept only as a **backstop**
   for genuinely garbled prose that slips type classification (the size/non-alpha arm stays
   available; it is no longer the pipeline's decision point).
2. **`axial chunk examine` reports dropped blocks from the router's decisions** — the single
   source of skip truth — rather than from a per-pass guard. Apparatus drops (TOC, index,
   endnotes, running heads) recorded by the router (slice 02) appear in examine's
   "skipped/dropped with reasons" section.

## INVEST check

- **Independent:** consumes the router + its skip artifact from slice 02; touches `tag.py`,
  `xref.py` (gate demotion) and `chunk.py`'s `examine` reporting (skip source). No change to
  routing logic or the artifact pass.
- **Valuable:** completes the retirement of the scattered per-pass heuristic in favour of
  classify-once; a reader of `examine` sees every dropped block and why, from one source.
- **Small-ish (M):** remove/guard the `non_prose_skip_reason` call sites in tag/xref, and point
  `examine_chunks`' skip aggregation at the router's decision records.
- **Testable:** run `tag`/`xref` on routed prose chunks and assert no chunk is dropped by a
  per-pass prose/non-prose decision (all reach their pass); run `axial chunk examine` and assert
  the router-dropped TOC/index/endnotes appear with reasons.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given routed prose chunks (data/chunks/<source_id>.jsonl) and the router's recorded drops
When   the operator runs the downstream passes (tag, xref) and then `axial chunk examine`
Then   no tag/xref pass re-derives the prose/non-prose decision — every prose chunk reaches its pass
And    `axial chunk examine` reports the dropped document_index / index / footnote blocks with
       the router's reasons (the single source of skip truth)
And    a genuinely garbled prose chunk is still caught by the retained backstop, not silently tagged
```

- **Boundary / endpoint:** the `tag` / `xref` / `axial chunk examine` CLI passes
- **Outer test type:** pytest integration test (fabricated routed chunks + router drops; stub LLM; no network)
- **Outer test file (planned):** tests/test_source_router.py (extend) — test-author, red, locked

## Inner loop — initial unit test list

- `tag.run_tag` no longer skips a chunk via `non_prose_skip_reason` as the primary gate; a
  normal prose chunk is tagged (was: could be pre-skipped). Backstop path still exists for a
  genuinely garbled chunk.
- `xref.run_xref` likewise: the primary prose/non-prose skip is gone; backstop retained.
- `examine_chunks` aggregates dropped blocks from the router's skip records (apparatus +
  garbage), not from a per-pass guard; `format_examine_report` lists them with reasons.
- The router's skip artifact is the single input to examine's drop reporting; no per-pass guard
  contributes drop reasons.

## Out of scope (this slice)

- **Deleting `nonprose_guard`** — the module and its size/non-alpha arm remain as the backstop;
  only its role as the *primary gate* is retired.
- **Routing logic / artifact pass** — unchanged from slices 02/03.

## Notes

- Call sites to demote (from `grep non_prose_skip_reason src/`): `tag.py:1173`, `xref.py:336`
  (`_non_prose_skip_reason`), and `artifacts.py:500`. Artifacts' own guard is covered by the
  router routing in slice 03; confirm it is not double-gating here.
- Keep the backstop deliberate and logged (a garbled-prose skip must remain distinguishable from
  a silent loss, per §7.7).
- Full acceptance suite runs once here (touches tag, xref, examine) per [[tiered-test-suite-principle]].
