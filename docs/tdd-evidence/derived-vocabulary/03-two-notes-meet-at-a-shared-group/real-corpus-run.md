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

---

# Second run, 2026-08-28: the assembly-order fix

The first run above satisfied the acceptance criterion and missed its point. The
38 category-edge notes all landed at assembly index 52 or later, synthesis's char
budget cut 32 of them, and **the answer cited none of them** — 20 distinct cited
chunks, zero from the category edge, highest cited index 45. `map` and
`map+vocab` would have produced answers built from the same 52 passages, so #809
would have measured nothing.

Cause: `assemble_map_evidence` walks positions in the order given, one id per
position per turn, under a cap of 90. With the vocabulary positions appended
after landed and corridor, 22 + 30 map positions spent 52 slots on turn one
alone. The step was behind the evidence budget, not inside it.

Three changes, then the same brief re-run:

1. **Vocabulary positions assemble before the corridor.** Landed still leads.
2. **Cross-source is judged per category**, against the sources of the landed
   notes that touched that category — not the union of every landed source,
   which on 35 sources with 22 landed positions admits nobody to the preferred
   tier and lets the cap fill in arbitrary id order.
3. **Two counts per category in the record**, `offered_note_count` and
   `assembled_note_count`. They differ by a factor of four to six.

## Before and after, same brief, same corpus, same pin

| | first run | after the fix |
|---|---|---|
| assembled | 90 | 90 |
| of those, category-edge only | 38 | **63** |
| their assembly indices | 52–89 | **27–89** |
| composed into the prompt | 58 | 54 |
| distinct cited chunks | 20 | 9 |
| **cited via the category edge** | **0** | **2** |
| categories reached | 12 | 13 |
| offered / assembled | 240 / 38 | 260 / 63 |
| cost | $0.081, 240s | $0.066, 218s |
| claims (a/b/c) | 9 / 7 / 2 | 8 / 4 / 2 |
| cross-source rate | 0.571 over 7 | 0.750 over 4 |
| retrieval_hit | 0.833 | 0.667 |
| sources cited | 6 | 6 |

**Read this as n=1 against n=1.** Two live runs of one brief, on a pipeline
already measured as non-reproducible at 19.3% overall and 36.1% on recorded
disagreements (#700). The load-bearing number is the one that moved from a
structural zero to a non-zero: 0 cited category-edge chunks became 2, and the
zero was guaranteed by the ordering rather than sampled from it. Every other
row in that table is inside the noise and none of it should be quoted as an
effect of this change. `retrieval_hit` falling from 0.833 to 0.667 is one
mechanical oracle hit on a 3-item denominator, not a regression signal.

**The step now takes 70% of assembly (63 of 90), across 26 sources.** That is a
large share and it is the intended direction — the category edge is what is
under measurement — but it is also the number most likely to be misread. It does
not mean the vocabulary found 63 passages the map could not reach; the map arm
reached 217 candidates for 90 slots either way. It means the cap now cuts the
corridor rather than the vocabulary. If #809 says the join does not pay, this
ordering is the first thing to re-examine, not the last.

**The arm is a substitution, not an addition.** The map arm alone reaches 202
candidates against a cap of 90, so `map+vocab` cannot enlarge the evidence set —
it changes which passages fill it. #809 therefore answers "are these 54 composed
passages better than those 58", never "does more reach help". That framing is
the thing to carry into the comparison; the number is uninterpretable without
it.

Record: `data/analyses/dae632c369c18ffc.json` (overwritten — the brief id is
content-derived, so the second run replaced the first). Console:
`console-ordered.log`.
