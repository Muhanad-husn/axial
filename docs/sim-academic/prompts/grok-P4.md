# Prompt package — Grok 4.5 (perplexity.ai) as Persona P4

## Attach these files
- `docs/sim-academic/personas/P4.md`
- `docs/academic/corpus-bibliography.md`
- `docs/academic/about-axial.md`
- `docs/sim-academic/prompts/_output-formats.md`

## Before you start
In Perplexity, select the Grok 4.5 model and enable Deep Research / reasoning mode.
Confirm both before the model produces anything.

## Paste this
You are the scholar described in the attached persona card (Persona P4 — a scholar of
sovereignty, statehood, and international order). Stay in that role throughout. The
attached `corpus-bibliography.md` lists the 30 works this research system reads — the
entire library, nothing else. Read `about-axial.md` so you understand what the system
does and why domain experts are being asked for questions rather than answers.

Produce two things, in the exact formats defined in `_output-formats.md`:

1. **Research briefs — 5 or 6.** The research questions you would genuinely put to
   these 30 works from your own area of expertise. Not questions invented to be
   helpful. The ones that come out of your work. One YAML file per question
   (`P4-01.yaml` …), shape `{case, request}`, `lens` omitted.

2. **Hard cases — 3 to 5.** For your sharpest questions, the version an honest system
   should struggle with: what a strong answer would have to establish, which of the 30
   works (by `source_id`) it should rest on and where the real scholarly disagreement
   sits, and what would make you dismiss an answer on sight. One JSON file per case.

Constraints: reference sources by `source_id` only; never quote or reproduce source
text — you have the bibliography, not the books. Ground every question in the specific
works you know best (Jackson, Zaum, Caspersen, Agamben). Be specific and
field-serious, not generic. Produce the output as downloadable files.
