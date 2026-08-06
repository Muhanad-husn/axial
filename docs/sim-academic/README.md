# Simulated academic inputs — permanent, not interim

> **Everything this folder produces is simulated.** Five frontier AI models, each in a
> distinct scholarly persona, stood in for the academic inputs Phase B was once blocked
> on. **This is now the only path there is.** Issues #250 and #295 closed as not-planned
> on 2026-07-24, and every number measured on these inputs is a provisional development
> signal permanently, not until real input arrives (DEC-29, `specs/PRODUCT.md` §14).
> Nothing here is a result about answer quality against a real academic question.

Earlier versions of this file called the folder INTERIM and THROWAWAY and ended in a
teardown checklist. That framing was wrong from 2026-07-24 onward and is retired.

## What was simulated, and where it landed

| Academic deliverable | Real seam (never touched) | Simulated stand-in | Committable? |
|---|---|---|---|
| Research questions (#250) | `config/briefs/dev/*.yaml` | `config/briefs/sim/*.yaml` | yes — info about sources only |
| Hard cases (eval #1) | `evals/cases/*` | `evals/cases/sim/*.json` | yes — chunk/source ids only |

The isolation is still real: the simulated inputs live in their own `sim/`
subdirectories and the real seams stay empty, so nothing can quietly read a simulated
brief as an academic-authored one.

**Gold labels are gone.** The third row of this table used to be a gold label sheet.
The gold set, the labelling method and the scoring harness were deleted on 2026-08-06
(#710) along with the tag axes they graded. The measurement record is preserved at
[`docs/_archive/sim-academic-gold-labelling.md`](../_archive/sim-academic-gold-labelling.md)
and the dispatch method at `docs/_archive/gold-coder.md`.

## Model × persona

| Model | Interface | Persona | Research briefs | Hard cases |
|---|---|---|---|---|
| KIMI K3 | kimi.com | [P1](personas/P1.md) | ✓ | ✓ |
| GLM 5.2 | z.ai | [P2](personas/P2.md) | ✓ | ✓ |
| GPT-5.6 Terra | perplexity.ai | [P3](personas/P3.md) | ✓ | ✓ |
| Grok 4.5 | perplexity.ai | [P4](personas/P4.md) | ✓ | ✓ |
| Opus 4.8 | claude.ai (memory excluded) | [P5](personas/P5.md) | ✓ | ✓ |

## How a workstream was run

1. Open the model's prompt package in [`prompts/`](prompts/) (`kimi-P1.md`,
   `glm-P2.md`, `gpt-P3.md`, `grok-P4.md`, `opus-P5.md`).
2. Attach the files the package lists: the persona card, `docs/corpus-bibliography.md`,
   the repository `README.md`, and `_output-formats.md`.
3. Turn on the model's deep-research or extended-thinking mode before it starts.
4. Paste the perspective prompt. Ask for structured downloadable output.
5. Save the outputs to the landing paths above, then record the run in the tracker.

The prompt packages named `docs/academic/about-axial.md` as the product description
until 2026-08-06. That file described the v0 tagging product and is retired; the
repository `README.md` is what a persona should read now.

## Run tracker

| Date | Model | Persona | Workstream | Mode confirmed | Output | Status |
|---|---|---|---|---|---|---|
| 2026-07-21 | **Gemini 3.1 Pro** (substituted for KIMI K3) | P1 | briefs + hard cases | not stated in output | `P1-01..06.yaml`, `P1-01..04.json` | ✅ landed — **prose output, hand-mapped** |
| 2026-07-21 | GLM 5.2 | P2 | briefs + hard cases | extended-thinking | `P2-01..06.yaml`, `P2-01..04.json` | ✅ landed |
| 2026-07-21 | GPT-5.6 Terra | P3 | briefs + hard cases | extended-thinking | `P3-01..06.yaml`, `P3-01..04.json` | ✅ landed |
| 2026-07-21 | Grok 4.5 | P4 | briefs + hard cases | extended | `P4-01..06.yaml`, `P4-01..04.json` | ✅ landed |
| 2026-07-21 | Opus 4.8 | P5 | briefs + hard cases | extended-thinking | `P5-01..06.yaml`, `P5-01..05.json` | ✅ landed |

The gold-labelling rows of this tracker moved to the archived record with the rest of
that path.

**Totals landed:** 30 briefs (5 personas × 6, all load, 30 unique `brief_id`s) · 21
hard cases (all schema-valid, all `source_id`s resolve).

**Deviations from plan.**

- **Gemini 3.1 Pro ran P1 in place of KIMI K3.** It ignored the output format and
  returned a long-form essay with briefs and hard cases embedded in prose (no fenced
  blocks, markdown-escaped JSON). Hand-mapped into schema. Its `case` values were
  *thematic titles* rather than the polity anchor PHASE-B §7.1 requires; corrected to
  polity plus period, with the original title preserved as a `# theme:` YAML comment.
  Its reasoning mode was never stated, recorded honestly as `not-stated-in-output`.
