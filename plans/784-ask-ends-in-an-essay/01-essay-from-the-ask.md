# Slice 01: a finished ask serves its essay

- **Feature:** 784-ask-ends-in-an-essay
- **Slice slug:** essay-from-the-ask
- **Branch:** feat/784-ask-ends-in-an-essay/01-essay-from-the-ask
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

An ask run through the service ends in a Phase C paper, and
`GET /asks/{id}/paper` returns that essay beside the analysis record it was
drafted from, with the drafting passes counted in the ask's reported cost.

## INVEST check

- **Independent:** touches the service and the CLI's own composition seam. No
  web change; the client keeps working, ignoring a field it does not read yet.
- **Valuable:** the essay exists and is fetchable — every later slice is
  presentation over it. It is also what makes the cost real rather than
  estimated.
- **Small:** the composition is already written (`_ask_paper`,
  `src/axial/cli.py:2418`). This lifts it into a module the worker can import
  and threads one artifact through three call sites.
- **Testable:** an API-level test against the real app, driven off an analysis
  record already on disk with a stub client for the three paper passes.

## Before any code — the one measurement the issue asks for

`axial paper examine` over a handful of the 19 records in `data/analyses/`,
using each record's **own `brief.request` as the thesis** — the exact brief
`_ask_paper` builds. Zero drafting calls, ~$0.002–0.009 each. Record the
section count, the roles, and whether a counter-position section appears, into
`data/logs/2026-08-17-784-question-as-thesis/`, and compare against the
existing single-record papers' 5–10 sections. **Run it in `D:/axial`, not a
worktree — `data/` does not exist in a worktree.**

If a question thesis plans a visibly worse arc than a declarative one, that is
a finding for a new issue and this slice ships regardless: the essay's arrival
is the behaviour, its prompt quality is not.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a worker that answers an ask against a corpus snapshot
When  a principal POSTs a question to /asks and, once it is done, GETs
      /asks/{id}/paper
Then  the response carries an `essay` holding a thesis statement and the
      plan's sections in plan order as markdown prose
And   it still carries the same `record` and `metrics` it carries today
And   the ask's reported cost includes the paper_plan, paper_draft and
      paper_shape passes
```

- **Boundary / endpoint:** HTTP — `POST /asks`, `GET /asks/{ask_id}/paper`
- **e2e test type:** API/integration test (`tests/service/`, the real app and a
  real Postgres, the pattern `tests/service/test_api_citation.py` already uses)
- **e2e test file (planned):** `tests/service/test_ask_ends_in_an_essay.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 01-essay-from-the-ask
edits: src/axial/cli.py
edits: src/axial/test_cli_ask.py
edits: src/axial/service/worker.py
edits: src/axial/service/api.py
edits: src/axial/service/cache.py
edits: src/axial/service/export.py
edits: src/axial/service/jobs.py
edits: tests/service/test_worker.py
creates: src/axial/ask/paper.py
creates: src/axial/ask/test_paper.py
creates: tests/service/test_ask_ends_in_an_essay.py
depends-on: 783
depends-on: 785
```

Three paths were added while building, all for the same reason — the
composition moved, so the two files that stub it moved their stub point with
it, and the job row needed somewhere to put the paper's path. `jobs.py`,
`test_cli_ask.py` and `tests/service/test_worker.py` were not foreseen at
planning time. `docs/DECISIONS.md` was declared and not used: nothing here
overturns a decision, it executes DEC-41 and DEC-65 as written.

## Design decisions this slice makes

1. **The seam is `src/axial/ask/paper.py`.** `_ask_paper` today does three
   things in one function: decide whether a paper is owed, run the pipeline,
   and print the result. Lift the first two into
   `draft_paper_for_turn(client, question, brief_id, *, analyses_dir,
   papers_dir, ...) -> dict | None`, returning the persisted paper record or
   `None` when none is owed. `cli.py` keeps the printing and the exit code.
   Behaviour through the CLI must not move — its existing tests are the guard.
2. **The paper is served, not re-derived.** `run_ask_job` persists the paper
   into a principal-scoped `papers/` beside `analyses/` and `runs/`
   (`axial.paths.scoped_for_principal`, the same call the other two already
   get). Its path travels to the API the same way the analysis record's does.
   Do **not** recompute `paper_brief_id` at serve time to guess a filename: a
   derived path that silently misses is exactly the failure the content-keyed
   id makes look correct.
3. **`essay` is the reader render, taken from the record.**
   `axial.paper.reader.render_reader_paper` is what `persist_paper` already
   writes to `<id>.md`. The payload carries that string plus the §7.3 paper
   record, so a client can render prose without parsing markdown for structure
   and an auditor can still see the plan. The audit render (`.audit.md`) is not
   served.
4. **Cost is the sum, and it is honest about nulls.** `run_ask_job` returns
   `cost_usd`/`tokens` for the job row, which feeds the spend report and the
   quota. Add the paper's three passes to both, preserving the existing
   null rule: an unpriced pass keeps the total `None` rather than fabricating a
   zero. A cache hit stays a genuine `0.0`.
5. **A refusal is skipped, not failed** — the rule `_ask_paper` already
   states, and PHASE-C §7.1's refusal rejection is why. `essay` is absent and
   the record's own refusal still renders.
6. **A drafting failure does not fail the ask.** The analysis is already
   persisted and already paid for. The job completes, `essay` is absent, and
   the failure is recorded as an event on the job so it reads as a failure of
   the drafting run, not as a corpus with nothing to say. This is the same
   distinction PHASE-C §7.3 draws between a failed counter-position and a
   one-sided corpus, applied one level up.
7. **The export follows the screen.** `render_export_markdown`
   (`service/export.py:73`) serves the reader *answer* today. Once the essay is
   the answer, an export that disagrees with what the analyst read is a defect,
   so the export carries the essay, with the claim list beneath it.

## Inner loop — initial unit test list

- [x] `draft_paper_for_turn` builds a brief whose thesis is the question and
      whose single `analysis_ids` entry is the turn's `brief_id`.
- [x] `draft_paper_for_turn` returns `None`, and makes zero model calls, when
      the record's `interrogation.disposition` is `refuse`.
- [x] `draft_paper_for_turn` writes the record and both renders under the
      `papers_dir` it was given, never `data/papers/`.
- [x] Two identical questions against one record produce one
      `paper_brief_id` (the content-keyed id, pinned).
- [x] `run_ask_job` returns a `cost_usd` that is the analysis total plus the
      paper's three passes (`_combined`, `None` only when neither half
      priced — dropping a known half would report less than the ask cost).
- [x] `run_ask_job` completes the job when drafting raises — the failure is
      an event, not a failed job, and the claim list still serves.
- [x] A cache hit serves the same essay the first ask produced, proven with a
      client that raises on any call.
- [x] `_paper_payload` returns `record`, `metrics`, `essay`, `paper`, and
      omits `essay`/`paper` when no paper was drafted.
- [x] `render_export_markdown` leads with the essay when one exists and is
      unchanged when none does.
- [x] The job row carries `paper_ref`, under the principal's own scoped
      directory (added during the loop — the path has to travel somewhere).

## Out of scope for this slice (deferred)

- Any web client change — slice 02.
- Any SSE event for the planning or drafting stages — slice 03.
- Renaming `GET /asks/{id}/paper`.
- A `--no-paper` equivalent on the API. Nobody has asked for one; a config
  option nobody sets is a named tripwire.
- Running the Phase C gates on the ask path.

## Definition of done

- [x] `axial paper examine` measurement run, logged under
      `data/logs/2026-08-17-784-question-as-thesis/`.
- [x] Acceptance test written, seen to fail for the right reason, now GREEN
      (8 tests in `tests/service/test_ask_ends_in_an_essay.py`, real
      Postgres).
- [x] All seeded unit behaviours covered; `uv run pytest` green (src tier),
      `uv run ruff check` clean.
- [x] **Cost per ask measured on a real end-to-end run and reported.**
      $0.134203 total = $0.121133 answer + **$0.013070 essay**, 307,793
      tokens, 486 s. The essay is **9.7% of the ask**, not the +$0.13 the
      issue estimated — that figure was a multi-record paper's, and an ask is
      one record. `data/logs/2026-08-18-784-cost-per-ask/summary.md`.
- [x] CLI behaviour unmoved: `src/axial/test_cli_ask.py` green with every
      assertion unchanged, only its stub point moved.
- [ ] Slice's tests run in CI.
- [ ] Evidence collected and PR opened via `/aeo:safe-pr`.

## Status / progress log

- 2026-08-17 planned.
- **The measurement ran first and answered its question.** Six paired
  `axial paper examine` runs, zero drafting calls, 10–18 s each: a question
  thesis plans 5–8 sections against the same records' declarative-thesis
  baselines of 5–10, every plan well-formed. The mechanism is that stage 2
  *restates* the question as a declarative thesis, so the interrogative never
  reaches the drafter.
  `data/logs/2026-08-17-784-question-as-thesis/summary.md`.
  **One record was run twice on byte-identical input and planned 5 sections
  then 7** — a single draw of this pass is not a measurement, and no
  one-or-two-section difference in that table means anything.
- **The Bash tool exports `AXIAL_SECRETS_PATH=/secrets/secrets.toml`** — MSYS
  mangling the repo-relative default into a POSIX path that resolves to
  nothing on Windows. Six runs died with `no API key was found` before any
  model call, which reads exactly like a missing key. Everything needing
  secrets ran through PowerShell after that.
- Acceptance test watched red with `KeyError: 'essay'` off the real route,
  against a real Postgres, before any production line was written.
- **`paper_ref` is a column, not a derivation.** Recomputing
  `paper_brief_id` at serve time was considered and rejected: a follow-up
  turn's thesis is the question the analyst typed, while its record's own
  `request` carries the previous turn folded in, so the two hash differently
  and a derived filename would miss silently. `ALTER TABLE ... ADD COLUMN IF
  NOT EXISTS` is the idiom #686 and #724 already established here.
- **`JobRunner`'s five-tuple was left alone.** The paper path is written by
  the job body through `JobStore.set_paper_ref`, the way it already writes
  events, rather than widening a contract every job kind and every test stub
  is written against for a column only `ask` fills.
- **The essay is rendered at the API boundary, not read off the worker's
  `.md`.** Otherwise a worker resolving `passage` could put book text into a
  `locator` deployment's response by baking it into a file first — which is
  exactly the enforcement point DEC-65 and DEC-72 put at the API.
- **The drafting had to move above `cache.store`.** With the original order
  the cache entry was written before the paper existed, so every later hit
  would have served an answer with no essay.
- `_ask_paper` took `(client, turn)`; the seam briefly took `(client,
  question, record)` and broke three worker tests whose stub records carry no
  `brief_id`. Reverted to taking the turn — the shape the CLI always had.
- Two test files moved their stub point with the composition
  (`src/axial/test_cli_ask.py`, `tests/service/test_worker.py`); every
  assertion in them is unchanged.
- **The real run's paper came back `shape: weak`, with one defect: the
  counter-position is introduced already diminished rather than at its
  strongest.** That is the strawman failure already on record for the argument
  map, now visible in the writer. The shape check reports and never blocks
  (§7.16), so the run stands and this slice ships — prompt quality is out of
  scope here by design. It is a finding for #787 or its own issue, not
  something to fix inside a wiring slice.
- **Attempt 1 of the cost run hung on the intake fork check and was killed**
  after paying for five retrieval turns; `axial ask`'s one-shot form promises
  "no prompts" and the fork check breaks that promise. Filed as **#790**. The
  hosted path is unaffected — `run_ask_job` passes no `on_fork`.
- **`tests/service/test_api_under_load.py::test_post_asks_returns_under_100ms
  _while_an_ask_is_running` fails when the whole package runs on this box and
  passes on its own.** Nothing in this slice is on its path: its `run_job` is
  a local closure, and `POST /asks` still does a quota check and an enqueue
  and nothing else. Read as a wall-clock budget losing to local contention,
  not as proven pre-existing — the clean baseline run was not obtained. CI's
  own runner is the arbiter.
