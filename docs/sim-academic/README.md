# ⚠ Simulated academic inputs — INTERIM, THROWAWAY, re-run on real input

> **This whole folder and everything it produces is simulated.** Five frontier AI
> models, each in a distinct scholarly persona, stand in for the academic inputs that
> Phase B is otherwise blocked on. It exists so engine development proceeds during the
> academic pause. **Nothing here is a result.** When the app is stable, delete every
> simulated artifact and re-run the pipeline from scratch on the real academic input
> before anything is promoted or published. See `docs/DECISIONS.md` DEC-29.

## What is being simulated, and where it lands

| Academic deliverable | Real seam (never touched here) | Simulated stand-in | Committable? |
|---|---|---|---|
| Research questions (#250) | `config/briefs/dev/*.yaml` | `config/briefs/sim/*.yaml` | yes — info about sources only |
| Hard cases (eval #1) | `evals/cases/*` | `evals/cases/sim/*.json` | yes — chunk/source ids only |
| Gold labels | `data/gold/labels/label_sheet.xlsx` | `data/sim/gold/labels/<model>/label_sheet.xlsx` | no — gitignored (source text) |

Isolation is the whole point: the real seams stay empty until real input arrives, so
the real `axial eval` and the real #250 conformance test always measure real data.
Teardown is `rm -rf data/sim config/briefs/sim evals/cases/sim`.

## Model × persona × workstream

| Model | Interface | Persona | Research briefs | Hard cases | Gold labels |
|---|---|---|---|---|---|
| KIMI K3 | kimi.com | [P1](personas/P1.md) | ✓ | ✓ | — |
| GLM 5.2 | z.ai | [P2](personas/P2.md) | ✓ | ✓ | ✓ (labeler A) |
| GPT-5.6 Terra | perplexity.ai | [P3](personas/P3.md) | ✓ | ✓ | ✓ (labeler B) |
| Grok 4.5 | perplexity.ai | [P4](personas/P4.md) | ✓ | ✓ | — |
| Opus 4.8 | claude.ai (memory excluded) | [P5](personas/P5.md) | ✓ | ✓ | — |

Gold labeling is restricted to GLM and GPT — two independent models on two platforms,
which gives inter-annotator agreement. Their gold prompt is persona-neutral (a shared
expert-coder role) so disagreement reflects coding ambiguity, not persona divergence.

## How to run a workstream

1. Open the model's prompt package in [`prompts/`](prompts/) (`kimi-P1.md`,
   `glm-P2.md`, `gpt-P3.md`, `grok-P4.md`, `opus-P5.md`; gold uses
   [`gold-coder.md`](prompts/gold-coder.md)).
2. Attach the files the package lists (persona card, `corpus-bibliography.md`,
   `about-axial.md`, `_output-formats.md`; gold adds `codebook.yaml` + the chunk sheet).
3. **Turn on the model's deep-research / extended-thinking mode before it starts.**
4. Paste the perspective prompt. Ask for structured downloadable output.
5. Save the outputs to the landing paths above, then record the run in the tracker.

Gold input prep (once): `uv run axial gold sample` → `uv run axial gold sheet`
produces `data/gold/label_sheet.xlsx`; export its rows (chunk_id, source, section,
chunk_text, and the pre-filled `field`/`empirical_scope`/`polities_touched`) to a CSV
to attach. After a labeler returns `glm.json`/`gpt.json`, run
`python docs/sim-academic/merge_gold_labels.py <model> <labels.json>`.

## Run tracker

| Date | Model | Persona | Workstream | Mode confirmed | Output file(s) | Status |
|---|---|---|---|---|---|---|
| | KIMI K3 | P1 | briefs + hard cases | | | pending |
| | GLM 5.2 | P2 | briefs + hard cases | | | pending |
| | GLM 5.2 | (neutral) | gold labels | | | pending |
| | GPT-5.6 | P3 | briefs + hard cases | | | pending |
| | GPT-5.6 | (neutral) | gold labels | | | pending |
| | Grok 4.5 | P4 | briefs + hard cases | | | pending |
| | Opus 4.8 | P5 | briefs + hard cases | | | pending |

## Teardown checklist (when the app is stable)

- [ ] Real academic inputs received (research questions, gold labels, hard cases).
- [ ] `rm -rf data/sim config/briefs/sim evals/cases/sim`.
- [ ] Land real inputs in the real seams (`config/briefs/dev/`, `evals/cases/`,
      `data/gold/labels/`).
- [ ] Re-run the pipeline from scratch on the real corpus + real inputs.
- [ ] Re-run `axial eval` for the real, non-provisional numbers.
- [ ] Mark this folder archived (or remove it) and note the teardown in DEC-29.
