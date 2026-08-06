# Prompt package — gold labelling (in-harness Sonnet-5 subagents)

*Simulated-academic development path (`docs/sim-academic/`, DEC-29). Gold labelling was
moved off the external chat-model roster and in-harness to dispatched Sonnet-5
subagents by DEC-30, 2026-07-21 — this file describes that method. It supersedes the
original GLM-5.2/GPT-5.6 chat-upload workflow (the run tracker in
[`../README.md`](../README.md) still records those original runs accurately as
history; only the *current* method changed). Re-executed on the rebuilt corpus
2026-07-25 (DEC-46) after DEC-44's corpus-deletion incident destroyed the prior label
sheets.*

## Why in-harness, and why the design changed twice

- **DEC-30** moved gold labelling in-harness because dispatched Sonnet-5 subagents made
  *controlled arms* affordable in a way the external roster never was, and found
  same-family agreement numbers are inflated relative to cross-family — any comparison
  must hold the model family fixed.
- **DEC-31** established **best-of-N majority voting** on the two blind axes
  (`claim_type`, `theory_school`) as the correctly-aimed fix for the measured
  intra-annotator ceiling (0.73 at N=1). **N=3** is the agreement-per-cost sweet spot
  (0.918 on `theory_school`, past the N=1 ceiling); N=5 if near-zero abstention is
  wanted instead.
- **DEC-39** found the original pre-fill-shown design for the three head axes
  (`field`, `empirical_scope`, `role_in_argument` — the original gold-coder method
  "kept the guess if right") was a rubber-stamp artifact producing a trivial 1.0
  agreement. The corrected method blinds those axes too: no pre-fill shown at all.

## Method

Dispatch **7 independent, non-forked** Sonnet-5 subagents against
`data/gold/label_sheet.xlsx` (from `axial gold sample` + `axial gold sheet`). No shared
context between any of them, or with the dispatching session. Every subagent gets only:
`config/domains/<domain>/codebook.yaml`'s relevant axis definitions, the chunk_id +
chunk_text for its assigned rows (**never** the sheet's other columns — no pre-fill,
no other axes), and a persona-neutral expert-coder framing (below). Export
`{chunk_id, chunk_text}` per assigned row to a plain JSON file for each subagent to
read, rather than attaching the whole sheet — this is what keeps a blind-axis subagent
from ever seeing a head-axis pre-fill and vice versa.

- **Blind axes (`claim_type`, `theory_school`) — 3 subagents, full sample each.**
  Every subagent independently labels **all** chunks in the sample. Majority-vote merge
  per chunk per axis; when the 3 draws split three ways (no strict plurality), the
  chunk **abstains** on that axis (`null` value, flagged) rather than being coin-flipped
  — DEC-33's abstention design. Expect roughly 3–13% abstention on `theory_school`,
  less on `claim_type` (DEC-31's measured range).
- **Head axes (`field`, `empirical_scope`, `role_in_argument`) — 4 subagents, disjoint
  quarters.** Split the sample into 4 non-overlapping partitions; each subagent labels
  only its own partition, once, no voting (DEC-39's exact method: 30 chunks each on a
  120-chunk sample).

## Subagent prompt (adapt row counts / file paths per run)

```
You are an expert qualitative coder applying a fixed codebook to short scholarly
passages. This is a coding task, not an interpretive essay: apply the codebook
faithfully and consistently, the same way a trained second coder would. You have no
memory of any other conversation — treat this as a standalone task.

Read these two files:
1. `config/domains/<domain>/codebook.yaml` — read only the axis section(s) you are
   labeling under `axes:`.
2. `<per-subagent chunk export>.json` — a JSON array of objects, each
   `{"chunk_id": "...", "chunk_text": "..."}`.

[Blind-axis variant] For every row, produce `claim_type` (one top-level tag id) and
`theory_school` (one tag id; `not-applicable` if the passage advances no theoretical
position, `unlisted` if a real school applies but isn't listed — decide
not-applicable-or-not FIRST, never use either marker as a hedge).

[Head-axis variant] You have NOT been shown any prior automated guess for these
passages — label from your own independent reading only. For every row, produce
`field` (one tag id), `empirical_scope` (one `scope:*` id, most specific level the
claims actually rest on), and `role_in_argument` (one `role:*` id, the passage's
function in the author's own argument).

Work through every row — do not skip any. Write your output to
`<designated output path>.json` as a single JSON object keyed by chunk_id, values
being the label object plus an optional short `notes` string. Do not echo chunk_text
back. Do not read or write any other files. Report back only the row count and output
file confirmation.
```

## Merging

Once all 7 subagents finish, run `docs/sim-academic/merge_gold_labels.py` (no
arguments — it reads the dispatch output directory and the label sheet, both at fixed
paths) to majority-vote the blind-axis draws, take the head-axis single draws, and
write `claim_type_gold` / `theory_school_gold` / `blind_axis_gold_notes` /
`field_gold` / `empirical_scope_gold` / `role_in_argument_gold` /
`head_axis_gold_notes` columns into `data/gold/label_sheet.xlsx` directly — leaving the
pipeline's own pre-filled `field`/`empirical_scope`/`polities_touched` columns
untouched, for later tagger-vs-gold comparison (DEC-37/38/39's method).

## Standing caveats (per DEC-29, still binding)

- Simulated, provisional development signal — never promoted as measured against
  human expert judgment (permanent, per DEC-40/44: no real academic input is coming).
- Verbatim passage text stays in-harness (this session's own subagents), never sent to
  an external chat model, per DEC-30's move away from the DEC-29 external roster for
  this specific workstream.
- Raw dispatch inputs/outputs are gitignored (`data/gold/dispatch/`, DEC-23) — never
  committed.
