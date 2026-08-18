# Feature: Venue, length and house style — the original Phase D scope

Issue [#787](https://github.com/Muhanad-husn/axial/issues/787). A reader now
gets an essay from `axial ask` (#784, closed). This feature decides how that
essay is written: the counter-position stated at its strongest, a length the
plan allocates to rather than truncates against, APA citations, an abstract,
and one house style carried as domain data.

The founder's ruling of 2026-08-18 settled the two questions that blocked the
issue, and both are closed — do not reopen either while executing:

- **No venue picker.** An analyst never names a journal. Axial produces one
  essay in one house style. Per-venue section conventions, a venue-conditional
  abstract, and citation style as a selectable system are out of scope
  permanently.
- **APA is the house citation style.** One style, applied everywhere, not
  selectable.

- **Slug:** 787-venue-length-house-style
- **Created:** 2026-08-18
- **Status:** planning
- **New system?** no
- **Project directory:** .

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [counter-position-at-its-strongest](01-counter-position-at-its-strongest.md) | The drafter is told what a counter-position section is for, so it stops introducing the opposing view already diminished | ☐ todo | — |
| 02 | [length-is-a-plan-target](02-length-is-a-plan-target.md) | A brief may set a target word count, and the planner allocates sections to it instead of the paper being truncated afterwards | ☐ todo | — |
| 03 | [apa-citations-and-bibliography](03-apa-citations-and-bibliography.md) | The reader-facing paper cites and lists its sources in APA | ☐ todo | — |
| 04 | [every-paper-carries-an-abstract](04-every-paper-carries-an-abstract.md) | A finished paper opens with a ~200-word abstract of the argument it actually made | ☐ todo | — |
| 05 | [house-style-is-domain-data](05-house-style-is-domain-data.md) | House style reaches the drafter from `config/domains/<domain>/`, as context and never as a gate | ☐ todo | — |

## Dependency order

01 and 03 are independent of each other and may be built in parallel — they
share no file. Everything else is sequenced:

- **02 depends on 01** — both edit `src/axial/paper/draft.py`, and the ruling
  is explicit that length ships after the counter-position and not before it:
  a tight cap crushes the counter-position section first, which is exactly how
  a strawman gets written.
- **04 depends on 03** — both edit `src/axial/paper/reader.py`.
- **05 depends on 02** — edits `draft.py` after 01 and 02 have settled it.

## Out of scope (whole feature)

- **Any notion of a venue.** No journal selector, no per-venue section
  conventions, no venue-conditional anything. Founder ruling, closed.
- **A selectable citation style.** APA is the house style; there is no
  `--citation-style` flag and no style registry. If a per-journal style is ever
  genuinely needed, it is a CSL library over a finished essay, not code here.
- **A submission-ready manuscript for a named journal.** Different user,
  different product, different acceptance bar.
- **Contributor roles in the bibliography** (author vs editor). Filed
  separately as #481; §7.13 records an edited volume's editor in `author` and
  nothing downstream reads a role.
- **Re-running Phase B.** Every slice works from `data/papers/` (8 records) and
  `data/analyses/` (19 records), already on disk. Re-drafting needs no
  retrieval.

## Hazards that apply to every slice

These are recorded operational facts, not cautions. Read them before running
anything that costs money.

- **Measurement runs happen in the main checkout `D:/axial`, never a
  worktree.** `data/` is gitignored, so it does not exist in a worktree; a
  re-draft launched there silently operates on nothing. Code and tests are fine
  in a worktree. The paid run is not.
- **Re-drafting overwrites the record it is measured against.** Copy the
  `data/papers/*.json` records being measured into the run log *before* the
  first arm runs, or the before/after has no "before".
- **A single draw of a judged metric is not a measurement.** #695 and #700 both
  established this. Any before/after on `shape.band` or a steelman verdict
  needs several draws across several briefs.
- **Every run that costs money writes `data/logs/<YYYY-MM-DD>-<run-name>/`**
  with `run.jsonl`, `console.log` and `summary.md`. Write it where the run
  happens.
- **Install with the optional groups:** `uv sync --group distill --group
  service --group operator`. A plain `uv sync` omits three and `tests/operator`
  then fails to import streamlit.
- **Before committing:** `uv run pytest` (this resolves to `src` only, ~2,464
  tests in ~40s) and `uv run ruff check`, which no gate runs for you. The full
  `tests/` tree takes ~55 min serially — leave it to CI.

## Notes / open questions

- **The sharper instrument for slice 01 already exists, and the ruling did not
  name it.** The ruling nominates `shape.band` as the acceptance signal.
  `src/axial/validators/counter_position.py` already carries a bounded
  steelman-quality model call with a closed `steelman`/`strawman` verdict
  vocabulary, built for Phase B. It is directly on target where `shape.band` is
  a coarse whole-paper judgment. Slice 01 uses both: the steelman verdict as
  the primary signal, `shape.band` as the secondary. Flagged for the founder
  rather than decided silently.
- **Slice 02 re-keys every existing paper.** `compute_paper_brief_id` hashes an
  explicit four-key dict; adding `target_words` to it changes every brief's id
  and orphans the 8 records in `data/papers/`. Including it is the semantically
  correct call — a different target length genuinely is a different paper — and
  the cost is one re-draft at $0.008–$0.019 each. The plan takes that trade
  deliberately; see slice 02.
