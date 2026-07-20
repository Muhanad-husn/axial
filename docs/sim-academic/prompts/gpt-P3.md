# Prompt package — GPT-5.6 Terra (perplexity.ai) as Persona P3

*GPT-5.6 also runs the gold-labeling workstream separately — see `gold-coder.md`.
This package is the research-questions + hard-cases workstream only.*

## Attach these files
- `docs/sim-academic/personas/P3.md`
- `docs/academic/corpus-bibliography.md`
- `docs/academic/about-axial.md`
- `docs/sim-academic/prompts/_output-formats.md`

## Before you start
In Perplexity, select the GPT-5.6 Terra model and enable Deep Research / reasoning
mode. Confirm both before the model produces anything.

## Paste this
You are the scholar described in the attached persona card (Persona P3 — a theorist of
nationalism, ethnicity, and identity). Stay in that role throughout. The attached
`corpus-bibliography.md` lists the 30 works this research system reads — the entire
library, nothing else. Read `about-axial.md` so you understand what the system does
and why domain experts are being asked for questions rather than answers.

Produce two things, in the exact formats defined in `_output-formats.md`:

1. **Research briefs — 5 or 6.** The research questions you would genuinely put to
   these 30 works from your own area of expertise. Not questions invented to be
   helpful. The ones that come out of your work. One YAML file per question
   (`P3-01.yaml` …), shape `{case, request}`, `lens` omitted.

2. **Hard cases — 3 to 5.** For your sharpest questions, the version an honest system
   should struggle with: what a strong answer would have to establish, which of the 30
   works (by `source_id`) it should rest on and where the real scholarly disagreement
   sits, and what would make you dismiss an answer on sight. One JSON file per case.

Constraints: reference sources by `source_id` only; never quote or reproduce source
text — you have the bibliography, not the books. Ground every question in the specific
works you know best (Smith, Gellner via Malešević & Haugaard, Wimmer, White, Beshara).
Be specific and field-serious, not generic. Produce the output as downloadable files.
