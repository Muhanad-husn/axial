# Feature: an ask ends in an essay, not a claim list

An analyst asks a question in the web client and gets back an argued essay —
a thesis, sections in plan order, prose that carries the argument between
claims, and an opposing position where the record holds one. The claim list
stays reachable, unchanged, for a reader who wants to check the answer.

- **Slug:** 784-ask-ends-in-an-essay
- **Issue:** [#784](https://github.com/Muhanad-husn/axial/issues/784)
- **Created:** 2026-08-17
- **Status:** in-progress
- **New system?** no
- **Project directory:** `.` (the web slice's install/build run in `web/`)

## What was measured before slicing, at zero model cost

Four facts moved the plan off the issue's own framing. All read off records
already on disk.

1. **The composition already exists, in the CLI.** `axial ask` has ended in a
   Phase C paper since issue #668: `_ask_paper` (`src/axial/cli.py:2418`)
   builds an in-memory paper brief from the turn's question and its one fresh
   record, and calls `run_paper`. `--no-paper` turns it off. The issue's
   premise — *"the essay writer is not wired to the question box"* — is true
   of the **service and the web client only**. Nothing new is built here; a
   composition that lives inside a CLI print path is lifted into a seam the
   worker can call too.
2. **A single record already plans a sensible arc.** Six of the eight papers
   in `data/papers/` were drafted from exactly one analysis record, and their
   plans run 5, 6, 6, 6, 6 and 10 sections, each with `setup`, at least one
   `claim`, at least one `counter-position` and a `synthesis`. The issue names
   this as "the first thing to measure"; the measurement was already paid for.
   `run_paper` already tells the drafter that cross-source (b) claims are
   impossible on one record (`cross_source_possible`, `paper/record.py:216`),
   so the single-record case is supported by construction, not by luck.
3. **The cost estimate in the issue is 7–16× high.** Those six single-record
   papers cost **$0.008–$0.019** each, all three passes together
   (`paper_plan`, `paper_draft`, `paper_shape`). The $0.12–0.16 release-bar
   figure the issue quotes came from multi-record papers — $0.082 at two
   records, $0.199 at three. Drafting scales with the claim inventory, and one
   ask is one record. Still to be reported as measured, not estimated, per the
   issue's own bar.
4. **The 19 analysis records are usable material and hold no refusal.** All 19
   share one `corpus_pin`, all are `proceed_bounded`, they carry 11–32 claims,
   16 disclose a counter-position and 3 disclose `corpus_one_sided: true`. So
   the refusal path has no live example and its test needs a synthetic record.

**The one thing not yet measured, and slice 01's first act:** every existing
paper brief carries a *declarative* thesis. An ask supplies its **question**
(86–604 characters across the 19 records). Whether the planner produces the
same arc from an interrogative thesis is unproven, and `axial paper examine`
answers it for ~$0.002–0.009 per plan with zero drafting calls.

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Goal (one line) | Status | PR |
|---|-------|-----------------|--------|----|
| 01 | [essay-from-the-ask](01-essay-from-the-ask.md) | A finished ask serves its essay from the API, cost included | ✅ done | [#791](https://github.com/Muhanad-husn/axial/pull/791) |
| 02 | [essay-is-the-answer](02-essay-is-the-answer.md) | The web client shows the essay; the claim list moves behind disclosure | ☐ todo | — |
| 03 | [sections-stream-as-they-draft](03-sections-stream-as-they-draft.md) | Planning and each drafted section reach the walk over SSE | ☐ todo | — |

Slices 02 and 03 share no file and may be built concurrently once 01 has
landed — checked with `independence.mjs`, which reports the pair
parallel-safe over 15 declared paths. Both depend on 01: 02 reads the field 01
adds to the paper payload, 03 edits `src/axial/ask/paper.py`, which 01 creates,
and `src/axial/service/worker.py`, which 01 edits.

## Out of scope (whole feature)

- **Venue, length and house style** — that is #787, blocked on a founder
  ruling.
- **A second Phase B run of any kind.** Phase C consumes records (DEC-41); no
  slice here re-asks a question, and no test in this feature runs retrieval.
- **Changing the paper pipeline's own quality** — prompts, section count,
  claim assignment. Slice 01's real run came back `shape: weak` with a
  straw-manned counter-position; per the founder's 2026-08-18 ruling that work
  is folded into #787, alongside venue, length and house style, because all of
  them edit the same two prompt builders.
- **The four per-run Phase C gates.** They run through `axial gate run` and
  nothing here wires them into the ask path.
- **Chat mode / follow-up turns in the web client.** The composer still
  collapses during a run.

## Notes / open questions

- **The essay is the answer; the claim list keeps the disclosure the metrics
  panel already has.** That is the issue's own recommendation and this plan
  adopts it. Slice 02 is where it becomes visible.
- **A drafting failure must not lose the analysis the analyst already paid
  for.** The CLI treats a failed draft as a non-zero exit while still printing
  the answer; the service must do the analogous thing — the ask completes, the
  essay is absent, and the client falls back to the claim list. Fixed in slice
  01, tested there.
- **`GET /asks/{id}/paper` already means "the analysis record"** in this
  codebase, which now collides with the word the writer uses. The route name
  stays; the payload gains a field. Renaming a live route is not this
  feature's job.
- **A cache hit must serve its essay too.** The paper's id is content-derived
  from the same thesis and record id, so the cached paper is the same artifact
  — but `service/cache.py` copies the analysis record only. Slice 01 closes
  that, or a repeat question would silently lose its essay.
