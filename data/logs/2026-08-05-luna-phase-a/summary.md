# Three Phase A jobs, re-run on gpt-5.6-luna

2026-08-05, the companion to `data/logs/2026-08-05-luna-vs-glm/`. That run
covered the three judgment-heavy passes glm-5.2 held in Phases B and C; this one
covers the layer underneath, where the corpus money actually goes.

**Result: luna takes the envelope outright, loses Gather badly, and splits the
Interrogator three ways — and the Gather comparison turned up something bigger
than the model question.**

## What was compared

Each job against its own incumbent, not against glm across the board.

| job | incumbent | reasoning | what it is |
|---|---|---|---|
| `note_interrogate` | `z-ai/glm-5.2` | off | ~6,000 calls per corpus pass |
| `gather` | `deepseek-v4-flash` | high | what a name page's authors disagree about |
| `envelope` | `deepseek-v4-pro` | high | what a book argues, once per source |

The prompt is composed ONCE per sample by the product's own composer and the
identical string goes to both models. No upstream stage runs, so nothing but the
model can differ. Three samples per job, arms alternating, both models warmed
before timing.

## Cost and latency

| job | | incumbent | luna | |
|---|---|---|---|---|
| **interrogate** | mean $ | $0.0069 | **$0.0021** | **3.3x cheaper** |
| | mean s | **11.7s** | 21.1s | 1.8x slower |
| **gather** | mean $ | **$0.0011** | $0.0022 | **2.1x DEARER** |
| | mean s | 48.0s | **29.3s** | 1.6x faster |
| **envelope** | mean $ | $0.0066 | **$0.0042** | 1.6x cheaper |
| | mean s | 173.8s | **49.0s** | **3.6x faster** |

**Luna is not cheap in the abstract — it is cheap against expensive models.**
Against `deepseek-v4-flash` it costs twice as much, because it writes roughly
twice as many output tokens on every job here and flash is a tenth its output
price. The Phase B/C run's 6–12x savings came from replacing glm-5.2 and
nothing else.

Scaled to a full pass, the Interrogator is the only figure with real money in
it: at 6,148 notes, **$42 on glm against $13 on luna**, a saving of ~$29 per
corpus pass. Gather's whole pass is about a dollar either way; the envelope is
34 calls.

**Total spend: $0.54** — $0.044 the incumbents, $0.026 luna, $0.475 the judges.

## Quality: 27 blind ballots

Same instrument as the Phase B/C run — three judges from three labs
(`deepseek-v4-pro`, `gemini-3.5-flash`, `claude-sonnet-5`), pair relabelled A/B
with the assignment flipped per sample, and the source material the pass was
reading put in front of the judge. Dimensions: faithfulness, usefulness,
restraint.

| job | units | ballots | verdict |
|---|---|---|---|
| **envelope** | luna 3, incumbent 0 | **luna 8–1** | **luna** |
| **gather** | incumbent 2, luna 1 | **incumbent 7–2** | **deepseek-flash** |
| **interrogate** | luna 2, tied 1 | luna 5–3 (1 tie) | **contested** |

### envelope — luna, clearly

Luna reconstructs the table of contents closer to the book's real structure.
Judges repeatedly named the same thing: it keeps front and back matter the
incumbent drops (translator's note, appendices, acknowledgments) and does not
invent part numbering. sonnet-5: "B more faithfully mirrors Signal B's heading
hierarchy without collapsing or inventing structure."

The one loss (gemini on `zaum-2007`) is the mirror image — it preferred the
incumbent for *filtering out* subsection noise. So the disagreement is about how
much structure a reconstruction should keep, and two of three judges want more.

At 1.6x cheaper and 3.6x faster this is the easiest call in either run.

### gather — the incumbent, and it is not close

**Luna manufactures disagreements.** On two of the three names all three judges
independently said the passages carry no disagreement at all, and luna wrote one
anyway. deepseek: "statement A invents a disagreement with a non-present school."
sonnet-5: "A forces a false composite disagreement while B rightly declines."

This is the worst possible failure for this pass. The product's premise is that
passages meet at a name and their authors actually disagree; a model that
fabricates the disagreement poisons the page it writes.

### interrogate — genuinely contested, and split by judge

Field coverage is identical: both models answer 21–22 of 22 questions on every
note. The difference is what they put in the fields, and the judges do not agree
about it.

**The split is by lab, not by sample.** `deepseek-v4-pro` voted for glm on all
three notes; `gemini` and `sonnet-5` voted for luna on three and two. Both
models were caught inventing: glm invented an entity ("Ahdath") on one note,
luna misattributed a position on another.

Nine ballots cannot settle that. This is the one job worth buying more samples
for, because it is also the only one where the money is material.

## The bigger finding: Gather contradicts itself

`state-building` — 10 members, one batch, so the whole name fits in one call:

- **06:36 today** Gather recorded a disagreement: "The main disagreement is over
  the scope of 'state-building.' Heydemann/Sayigh and Caspersen use it for
  non-sovereign and unrecognized actors..."
- **16:20 today** the same model, same pass, same reconstructed packet returned
  **null — no disagreement**.
- All three judges, reading the passages, said null is the correct answer, and
  called the recorded version a forced composite.

The newest answer record on disk predates the 06:36 Gather run (05:49), so the
input did not change between the two calls. `Syria` shows the same shape
(recorded disagreement, null on re-ask) but is not clean evidence — it spans 37
batches and only batch 1 was re-asked. `Great Powers` had an answer file touched
after its Gather ran, so its input is not provably identical.

**One clean case, not a rate.** But it is the same shape as #695 for the merge
pass: a judgment call that does not reproduce on identical input, whose
recorded output is what the vault ships. Worth measuring properly — the re-ask
is cheap.

## What this supports

- **Move `envelope` to luna.** Wins 8–1, 1.6x cheaper, 3.6x faster.
- **Leave `gather` on `deepseek-v4-flash`.** Loses 2–7 and costs twice as much.
- **Hold `note_interrogate`.** ~$29 a pass is real, but 9 ballots split by judge
  lab is not a decision, and both models hallucinated. More samples first.
- **`reconcile` was deliberately not measured** — issue #695's 9.3%/18.8%
  self-disagreement floor makes any three-sample comparison of that pass
  unreadable.

## Caveats

- **N=3 per job, one draw each.** No variance estimate anywhere.
- **Sim corpus (DEC-29).** Every figure is provisional-on-sim.
- **The judges are models.** No human read these outputs.
- **The Gather packets are reconstructed**, not replayed from a stored prompt.
  The mtime check above is the evidence that the reconstruction matches, and it
  holds only for `state-building`.

## Reproduce

```
uv run python data/logs/2026-08-05-luna-phase-a/experiment.py
uv run python data/logs/2026-08-05-luna-phase-a/judge.py
```

`run.jsonl` one record per unit, `judgments.jsonl` one per judged pair,
`outputs/` every raw response both models produced.
