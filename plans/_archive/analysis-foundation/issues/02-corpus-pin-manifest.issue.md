# feat(analysis-foundation): corpus-pin manifest — a committed, reproducible corpus reference [slice 02]

**Spec:** specs/PHASE-B.md#7.12 · §8 P0-10 · **Plan:** plans/analysis-foundation/02-corpus-pin-manifest.md
**Depends on:** none (independent of slice 01; runnable in parallel)
**Labels:** sub:analysis-v0, enhancement

## Deliverable
`axial pin write <name>` computes and writes a corpus-pin manifest to
`evals/corpus_pin/<name>.json` in eval #1's format (§7.12,
`docs/eval/01-answer-quality.md`): a **source list** with a content hash per
ingested source (reusing `envelope.compute_source_id()`'s existing hashing path,
not a second convention), the **ingest-code SHA** (the current git commit), and a
**vault snapshot hash** over `(chunk_id, tags)` pairs in deterministic sorted
order. The snapshot hash **never** covers `chunk_text` (DEC-23): the manifest is
committed to the repo, so it carries ids and hashes only. Re-running over an
unchanged vault produces a byte-identical file; changing one chunk's tags moves
the snapshot hash while leaving the source list untouched. Nothing else in the
product owns this format, so it lands here (§7.12). LLM-free by construction:
zero model and zero embedding calls on any path.

## Acceptance criterion
```gherkin
Given a fixture vault with two prose notes under data/vault/prose/ and one
      envelope under data/envelopes/
When  `axial pin write baseline` runs
Then  evals/corpus_pin/baseline.json is written, the command exits 0, and the
      file carries a `sources` list (one entry per envelope, each with
      `source_id` and `content_hash`), an `ingest_code_sha` equal to the
      repository's current git commit, and a `vault_snapshot_hash`
  And no value anywhere in the file contains any chunk_text from the fixture notes

Given the same unchanged fixture vault
When  `axial pin write baseline` runs a second time
Then  the written file is byte-identical to the first run's file

Given one fixture prose note whose `field.primary` tag value is then changed
When  `axial pin write baseline` runs again
Then  the `vault_snapshot_hash` differs from the previous run's hash and the
      `sources` list is unchanged
```

## Out of scope
- Pin **verification** / drift detection against a live vault — this slice
  writes a pin; consuming one is stage-6 and eval work.
- Wiring `corpus_pin` into the analysis record (§7.3) — no record exists yet.
- Widening the snapshot projection beyond §7.12's chunk_ids + tags minimum.
- Committing a real production pin; the founder runs it against the full
  30-source vault as an ops step.
