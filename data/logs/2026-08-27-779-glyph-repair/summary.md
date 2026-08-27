# Repair: the PDF glyph, in place

Issue [#779](https://github.com/Muhanad-husn/axial/issues/779), corpus half.
2026-08-27. Zero model calls, zero cost, corpus pin unmoved, no re-chunking.

## What was applied

`_repair_underdot_glyph` from PR #814, run over the persisted trees and chunks
of the only two sources that carry the glyph. The rule removes every `●` and
makes one judgement, about spacing: a glyph touching a letter or hyphen sat
inside a word and the sides join; a glyph with whitespace on both sides sat
between two tokens and one space is left.

## Counts

| Artifact | Source | Removed | Left |
|---|---|---|---|
| tree | batatu-1999 | 3,014 | 0 |
| tree | heydemann-2004 | 260 | 0 |
| chunk `text` | batatu-1999 | 2,799 | 0 |
| chunk `text` | heydemann-2004 | 220 | 0 |
| chunk `section` | batatu-1999 | 3 | 0 |
| chunk `section` | heydemann-2004 | 6 | 0 |

The trees hold more than the chunks because they also carry text that never
became a chunk. The `section` field was a second pass: the first run repaired
only `text` and left the headings, which a corpus-wide recount caught.

## Verification

    files with glyph: 0   total occurrences: 0

over `data/chunks/*.jsonl`, `data/trees/*.json` and `data/answers/*.jsonl`,
counting both the literal character and its `●` escape — the trees store
it escaped, which is why a first check on the raw file text read zero and
missed 3,274 of them.

    chunk records parsed: 9405   failures: 0
    all trees parse OK

Every `chunk_id` was compared before and after and is unchanged, so nothing is
re-chunked and no analysis is orphaned.

## What this does not do

- **The 209 notes drawn from damaged `batatu-1999` chunks are not re-asked.**
  They were answered by a model reading text with the glyph in it. Re-asking is
  about $1 and twenty minutes against the recorded $34 for a full pass; it is
  the founder's call and is recorded in #779 as pending.
- **Words the extractor split elsewhere are untouched.** `A ● hmad Jibr il` is
  now `A hmad Jibr il`, not `Ahmad Jibril`. That fragmentation carries no glyph
  and needs a dictionary-backed joiner. Separate defect, not filed yet.

## Backup

The six pre-repair files are in the session scratchpad under `backup-779/`.
Session-scoped; the durable record is this log plus PR #814.
