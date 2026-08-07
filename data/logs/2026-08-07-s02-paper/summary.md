# Run: S-02 paper draft, first pipeline-named paper

First paper drafted after #718, which moved the title from a hand-written
`title:` in the paper brief to the post-draft shape check. The brief carries no
`title`, so the heading below is the pipeline's own.

## Command

```
.venv/Scripts/axial paper draft config/paper_briefs/dev/nationalism-and-the-fiscal-military-nexus.yaml
```

## Input

- Analysis record `e7d6a2646523cb1d`, copied into `data/analyses/` from
  `data/runs/smoke-v7/analyses/S-02/draw0/`. Corpus pin `sim-2026-07-30`,
  15 claims (10 a, 3 b, 2 c), confidence `medium`.
- S-02 asked which of four accounts explains nationalism best. The record
  commits to boundary-making tied to war and names where that commitment
  fails; the paper brief's thesis is that verdict.

## Result

- Paper: `data/papers/9f449f41b88e5c70.md`, record `.json` beside it.
- Title, written by the shape check: **Extraction Bargains Make Nations, Rent
  Breaks Them** (7 words, names the paper's answer including its failure
  condition, does not restate the thesis).
- 5 sections, 15 claims cited, shape band `strong` with no defects,
  cross-section repetition 0.00%, confidence `low`.
- Cost $0.0081 across plan (deepseek-v4-pro), 5 draft calls (gpt-5.6-luna) and
  the shape check (deepseek-v4-pro). Cheap because the paper draws on one
  analysis record, not the two the earlier papers used.

## Next steps

- Confidence came out `low` against the record's own `medium`. Worth one look
  at whether a single-record paper is structurally penalised by the coverage
  disclosure, before reading it as a quality signal.
