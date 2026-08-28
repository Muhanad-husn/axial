# 2026-08-28 — vocabulary join, real-corpus validation (#807, slice 03)

## Command

```
cd D:/wt-807
AXIAL_SECRETS_PATH=D:/axial/secrets/secrets.toml \
  uv run axial brief run config/briefs/eval/A.yaml --arm map+vocab
```

Run from the slice-03 worktree with `D:/axial/data` junctioned in — `data/` is
gitignored, so a worktree has none of it, and a run launched there would
silently operate on nothing. The junction is the read side; the analysis record
it wrote landed in the real `data/analyses/`.

Branch `feat/derived-vocabulary/03-two-notes-meet-at-a-shared-group` at `0602a74`.

## What ran

- Brief: `config/briefs/eval/A.yaml` — the bellicist state-formation transfer
  question. Chosen because its landed positions were certain to carry notes in
  `mechanism`'s largest categories.
- Vocabulary artifact: `data/vocabulary/mechanism/`, scheme
  `2026-08-28-mechanism-v1`, answers pin `417777fd2373b7e6`, **5,315 of 5,871
  values assigned** across 20 categories (556 refusals, 9.5%).
- Map pin `9b796b3a6312b329`, the current corpus pin.
- Record: `data/analyses/dae632c369c18ffc.json`.

## Cost and clock

| | |
|---|---|
| Total | **$0.081**, 134,009 tokens, **240.3s** |
| brief_decompose | 86.8s, 844 tokens, $0.000 |
| interrogate | 34.9s, 2,762 tokens, $0.008 |
| synthesize | 81.6s, 110,004 tokens, $0.035 |
| counter_position_generate | 36.9s, 20,399 tokens, $0.038 |

Plan estimated ~$0.04 for this slice's run. Actual is 2x that, and the whole
overage is `counter_position_generate` ($0.038) — a pass the estimate did not
name at all, not a vocabulary-step cost. The join itself makes no model call.

## The acceptance criterion, on the real corpus

- **`map_retrieval` carries a `vocabulary` block.** Present, alongside `asks`,
  `landed`, `corridor`, `assembled_chunk_ids`. 12 categories reached, each with
  its id, name, note count, source count and whether the cap bit.
- **Evidence reached assembly only through the category edge.** 22 landed and 30
  corridor positions between them make 202 chunks reachable without the
  vocabulary step. Of the 90 chunks actually assembled, **38 (42.2%) are not in
  that set** — they reached the answer only because they share a `mechanism`
  category with a landed note. Those 38 span **16 distinct sources**.
- **Trajectory stays empty.** `trajectory: []`, `steps=0`. The map arm writes no
  §7.6 entry and this slice did not start.

## What the run says beyond the bar

- **Every one of the 12 categories hit the per-category cap of 20.** 12 × 20 =
  240 candidate notes competing for an `ASSEMBLE_CAP` of 90. The cap is doing
  real work, and it is the only thing standing between one category and the
  whole assembly budget. It is also the slice's one hand-picked constant.
- **`state-repression-and-violence` contributed 20 notes from 1 source.** This is
  #651's warning made visible: a category can be one book talking to itself, and
  the `source_count` in the record is what lets a reader see it without opening
  the notes. Every other category spanned 3 to 12 sources.
- Answer shape: `proceed_bounded`, 18 claims (9 a / 7 b / 2 c), 6 sources cited,
  cross-source rate 0.571 over 7 (b) claims, retrieval_hit 0.833,
  attribution_completeness 1.000.

## Reading the categories

`category-reading.md` beside this file holds three `mechanism` categories — one
large, one mid, one small — with six members each, one per distinct source,
taken in file order. The founder's verdict on whether the members are actually
saying the same thing goes there. One member is already visibly wrong:
`chouliaraki-2024` filed under `war-and-state-formation` for a passage about the
First World War replacing a horse-drawn streetcar.

## Two failed attempts before the run that worked

Both are environment, not code, and both cost a paid `interrogate` call:

1. `AXIAL_SECRETS_PATH` is set to the **container** path `/secrets/secrets.toml`
   in this shell, and `secrets/` is gitignored so the worktree holds only
   `secrets.example.toml`. Pass `AXIAL_SECRETS_PATH=D:/axial/secrets/secrets.toml`
   — the absolute path, not the relative one, when running from a worktree.
2. A plain `uv sync` omits `sentence_transformers`; the map arm needs it for
   `_default_encoder`. `uv sync --group distill --group service --group operator`.
