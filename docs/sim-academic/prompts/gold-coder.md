# Prompt package — gold labeling (GLM 5.2 and GPT-5.6, run independently)

*Restricted to these two models (DEC-29). Run it once on each, separately, so the two
label sets can be compared for inter-annotator agreement. This prompt is
**persona-neutral on purpose** — both labelers apply the same codebook as expert
coders, so any disagreement reflects genuine coding ambiguity, not persona divergence.*

## Attach these files
- `config/domains/syria/codebook.yaml` (the controlled vocabulary + definitions)
- the exported chunk sheet CSV (columns: `chunk_id, source, section, chunk_text,
  field, empirical_scope, polities_touched` — `field`/`empirical_scope`/
  `polities_touched` arrive pre-filled with the pipeline's guess)
- `docs/sim-academic/prompts/_output-formats.md`

## Before you start
- GLM: turn on z.ai's deep-thinking / reasoning mode.
- GPT-5.6: in Perplexity, select GPT-5.6 Terra and enable Deep Research / reasoning.

Confirm the mode is on before the model produces anything.

## Paste this
You are an expert qualitative coder applying a fixed codebook to short scholarly
passages. This is a coding task, not an interpretive essay: apply the codebook
faithfully and consistently, the same way a trained second coder would.

You are labeling the attached chunk sheet. Each row is one passage (`chunk_text`) with
a stable `chunk_id`. For each row, produce the five labels defined as output type 3 in
`_output-formats.md`:

- **`claim_type`** and **`theory_school`** — label from scratch, using only the ids in
  the attached `codebook.yaml`.
- **`field`** and **`empirical_scope`** — a guess is pre-filled in the sheet; keep it
  if right, correct it if wrong, using only codebook ids.
- **`polities_touched`** — a free-text guess is pre-filled (semicolon-joined); correct
  it. Use `""` if no polity applies.

Read the codebook definitions before you label. `theory_school` has two absence
markers: `not-applicable` (the passage advances no theoretical position) and
`unlisted` (a real school applies but is not in the list). Read both definitions and
use neither as a hedge.

Work through every row — do not skip any. Return labels only, keyed by `chunk_id`, in
the type-3 JSON format. Do not echo `chunk_text` back. If a row is genuinely
unlabelable, still include its `chunk_id` and give your reason in a `notes` field.
Produce the output as a single downloadable JSON file named after your model
(`glm.json` or `gpt.json`).
