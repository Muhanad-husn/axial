# Slice 02: Corpus-pin manifest — a committed, reproducible corpus reference

- **Feature:** analysis-foundation
- **Slice slug:** corpus-pin-manifest
- **GitHub issue:** #248
- **Branch:** `feat/analysis-foundation/02-corpus-pin-manifest`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no
- **Depends on:** none — independent of slice 01 and runnable in parallel with it

## Goal — the minimum testable behaviour

`axial pin write <name>` computes and writes a corpus-pin manifest to
`evals/corpus_pin/<name>.json` in eval #1's format (§7.12): a **source list**
with a content hash per ingested source, the **ingest-code SHA** (the current
git commit), and a **vault snapshot hash** over the produced notes. The snapshot
hash is computed over `(chunk_id, tags)` pairs in a deterministic sorted order
and **never** over `chunk_text` (DEC-23) — the manifest is committed to the
repo, so it must carry ids and hashes only. Content hashing reuses
`envelope.compute_source_id()`'s existing path rather than inventing a second
convention. Re-running the command over an unchanged vault produces a
byte-identical manifest; changing one chunk's tags changes the snapshot hash.

No model call and no embedding call on any path.

## INVEST check

- **Independent:** it reads the vault and the envelopes and writes one JSON
  file. It touches no brief, no query API, and no Phase-A code. Slice 01 can
  land before or after it.
- **Valuable:** P0-10. Scores only compare against a pinned corpus, and because
  all of `data/` is gitignored the pin is the *only* reproducibility handle the
  product has. Nothing else in the codebase owns this format, so until it lands
  no eval number is comparable across runs (§7.12, §9).
- **Small:** one hash-assembly module plus one CLI subcommand. The hashing
  primitive already exists.
- **Testable:** build a tiny fixture vault on disk, write a pin, assert its
  fields and its stability, mutate a tag and assert the snapshot hash moved.
  Hermetic — no network, no LLM.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault with two prose notes under data/vault/prose/ and one
      envelope under data/envelopes/
When  `axial pin write baseline` runs
Then  evals/corpus_pin/baseline.json is written and exits 0
  And it carries a `sources` list with one entry per envelope, each with a
      `source_id` and a `content_hash`
  And it carries an `ingest_code_sha` equal to the repository's current git commit
  And it carries a `vault_snapshot_hash` string
  And no value anywhere in the file contains any chunk_text from the fixture notes

Given the same unchanged fixture vault
When  `axial pin write baseline` runs a second time
Then  the written file is byte-identical to the first run's file

Given one fixture prose note whose `field.primary` tag value is then changed
When  `axial pin write baseline` runs again
Then  the `vault_snapshot_hash` differs from the previous run's hash
  And the `sources` list is unchanged
```

- **Boundary / endpoint:** CLI — `axial pin write <name>`; the written file
  `evals/corpus_pin/<name>.json`; library entry
  `axial.eval.corpus_pin.write_pin(name, vault_dir=..., envelopes_dir=...)`.
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_corpus_pin.py` — authored by the
  test-author, committed red, then locked (DEC-1).

## Inner loop — initial unit test list

- [ ] The source list is built from `data/envelopes/*.json`, one entry per
      source, each carrying `source_id` and a `content_hash` from the existing
      `compute_source_id` hashing path.
- [ ] `ingest_code_sha` reads the current git HEAD commit; a repository state
      where the SHA cannot be read fails loudly rather than writing a pin with a
      null or placeholder SHA.
- [ ] The vault snapshot hash is computed over `(chunk_id, tags)` pairs sorted
      by `chunk_id`, so filesystem enumeration order does not affect it.
- [ ] The snapshot hash's tag projection covers the tag axes only — `field`,
      `claim_type`, `theory_school`, `empirical_scope`, `role_in_argument`,
      `polities_touched` — and **excludes** `chunk_text` and `source_meta`
      (DEC-23).
- [ ] Changing a chunk's tags changes the hash; changing only a chunk's
      `chunk_text` does **not** change the hash (the pin tracks tagging, not
      prose).
- [ ] Adding or removing a note changes the hash.
- [ ] Two pins written from the same vault compare equal field-by-field; the
      manifest serializes with sorted keys so the file is diff-stable in git.
- [ ] An absent vault directory or an absent envelopes directory fails with a
      clear error naming the missing path.
- [ ] The `axial pin write` subparser is registered on the existing argparse
      tree; `evals/corpus_pin/` is created if absent.

## Out of scope for this slice (deferred)

- Pin **verification** — comparing a live vault against a written pin and
  reporting drift. This slice writes a pin; consuming one is stage-6 and eval
  work.
- Wiring `corpus_pin` into the analysis record (§7.3). No analysis record exists
  yet.
- Artifact notes in the snapshot hash beyond what the tag projection needs — the
  §7.12 minimum is chunk_ids + tags; widening the projection is a later,
  measured decision.
- Any pin over a partially-ingested vault being treated specially. The pin
  records what exists; judging completeness is the operator's call.
- Committing a real production pin. The slice ships the mechanism; the founder
  runs it against the full 30-source vault as an ops step.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed — including an explicit DEC-23 check
      that no source text can reach a committed pin file.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-20 planned.
