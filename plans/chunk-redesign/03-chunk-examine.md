# Slice 03: `axial chunk examine` — inspect chunk quality with zero LLM spend

- **Feature:** chunk-redesign
- **Slice slug:** chunk-examine
- **GitHub issue:** #153
- **Branch:** feat/chunk-redesign/03-chunk-examine
- **Project directory:** .
- **Status:** ☑ PR open — https://github.com/Muhanad-husn/axial/pull/161 (awaiting founder approval)
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

`axial chunk examine` reads the on-disk chunk artifact(s) under `data/chunks/` and reports
chunk-quality stats making **zero LLM and zero embedding-model calls**: total and per-source
chunk counts; the size distribution (min / max / mean / median), from which the two-sided
band is verifiable; and a boundary-sanity summary — count of chunks above `max`, count below
`min` (both expected zero modulo the section-tail exception), count of sections split into
multiple chunks, and count of sections skipped-as-garbage with reasons — plus an eyeball
sample of chunk texts showing where boundaries fall. It never mutates the artifact.

## INVEST check

- **Independent:** read-only over the JSONL artifact from slice 01; imports no embedder and
  no LLM client. Runs even when only the artifact exists.
- **Valuable:** the inspection loop the redesign exists to enable — chunk quality is
  checkable *before* any LLM spend (#148 DoD), and it's the instrument that proves the
  gradient/band defaults (founder direction: "prove with examine, don't assert").
- **Small:** one read + aggregate + format command; no new pipeline stage.
- **Testable:** run `axial chunk examine` over a fixture `data/chunks/` set; assert the
  reported counts / distribution / boundary-sanity numbers match the fixture and that the
  command imports/calls no LLM or embedding model.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture data/chunks/ with known chunk counts, a known size distribution, one section
      split into multiple chunks, and one recorded garbage-skip
When  the user runs `axial chunk examine`
Then  it exits 0 and reports total + per-source counts, the size distribution
      (min/max/mean/median), and boundary sanity (chunks above max, chunks below min,
      sections split, sections skipped-as-garbage with reasons), plus a chunk-text sample
And   the numbers match the fixture and no chunk above `max` is reported
And   the command makes zero LLM calls and zero embedding-model calls, and does not modify
      any file under data/chunks/
```

- **Boundary / endpoint:** CLI command `axial chunk examine`
- **Outer test type:** pytest integration test (subprocess; no network; asserts no
  LLM/embedder import is invoked)
- **Outer test file (planned):** tests/test_chunk_examine.py — test-author, red, locked

## Inner loop — initial unit test list

- Counts: total and per-source from multiple JSONL files.
- Size distribution: min/max/mean/median over `text` lengths.
- Boundary sanity: above-`max` count, below-`min` count, split-section count.
- Garbage-skip reporting: reads the logged skip reasons (source of truth for skips TBD in
  slice 01 — a sidecar/log the examine step can read without re-deriving).
- Eyeball sample: prints N chunk texts with their `chunk_id`/`section`.
- Zero-inference guarantee: no embedder/LLM constructed on this path.

## Out of scope (this slice)

- Producing chunks (slice 01) or caching embeddings (slice 02).
- Any judgment/scoring of boundary quality beyond the stats — examine reports, the operator
  judges.

## Notes

- Depends on slice 01's artifact format (§7.7) and on how slice 01 records garbage-skips so
  examine can report "sections skipped-as-garbage with reasons" without re-running the guard.
  If slice 01 does not persist skip reasons, examine reports what it can from the JSONL and
  the gap is flagged back for a slice-01 follow-up.
- **Boundary check for a possible future prior.** When eyeballing the boundary sample,
  specifically check whether cuts fall *across* the envelope's TOC/section skeleton
  (`data/envelopes/`, §7.3). The new chunker is deliberately envelope-blind — boundaries come
  from embedding troughs + the size band only (§7.3, P0-4: the chunk stage consumes no
  envelope). If examine shows cuts routinely crossing the author's stated structure, that is
  the trigger to raise a `spec-drift` issue for **envelope-as-boundary-prior** (let the TOC
  skeleton act as hard boundary priors, embedding deciding only *within* a stated section).
  That would be its own future slice gated on founder adjudication — not a change to this
  read-only examine command.
