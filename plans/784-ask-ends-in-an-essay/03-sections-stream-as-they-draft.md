# Slice 03: sections stream as they draft

- **Feature:** 784-ask-ends-in-an-essay
- **Slice slug:** sections-stream-as-they-draft
- **Branch:** feat/784-ask-ends-in-an-essay/03-sections-stream-as-they-draft
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** no

## Goal — the minimum testable behaviour

While an ask is drafting, the walk names the arc it planned and each section as
that section is written, so the last minute of a three-minute run is visible
work rather than a stalled spinner.

## INVEST check

- **Independent:** shares no file with slice 02 and may be built alongside it.
- **Valuable:** DEC-65 commits to streaming the work rather than tokens and
  names *"then each section as it drafts"* as part of that stream. Today the
  event stream goes quiet at `check` and stays quiet through the whole paper.
- **Small:** the emitter already exists (`axial.llm.emit_event`), the transport
  already exists (`store.append_event` → SSE), and the client already renders
  any event with a `detail.stage`. This threads one callback through
  `run_paper` and adds one phase badge.
- **Testable:** assert the stored event sequence for a drafted ask, and assert
  the badge renders in the walk.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a worker running an ask whose paper plans three sections
When  a client reads GET /asks/{id}/events through to the end of the run
Then  the stream carries an event naming the planned arc and its section
      count, then one event per section as that section finishes drafting,
      each naming the section's heading
And   those events arrive after the analysis stages and before the job
      reaches done
```

- **Boundary / endpoint:** HTTP — `GET /asks/{ask_id}/events` (SSE)
- **e2e test type:** API/integration test (`tests/service/`, alongside
  `test_api_events.py`)
- **e2e test file (planned):** `tests/service/test_essay_events.py`

## Files (parallel-safety declaration)

```aeo-independence
slice: 03-sections-stream-as-they-draft
edits: src/axial/paper/record.py
edits: src/axial/ask/paper.py
edits: src/axial/service/worker.py
edits: web/src/components/Walk.tsx
creates: tests/service/test_essay_events.py
depends-on: 01-essay-from-the-ask
```

## Design decisions this slice makes

1. **`run_paper` gains an `on_event` parameter and nothing else.** It is the
   same `EventCallback` the ask engine already takes, emitted through
   `axial.llm.emit_event`, which prints to stderr when no callback is given —
   so `axial paper draft` and `axial ask` gain the narration for free and no
   caller is forced to pass anything.
2. **Three messages, in the vocabulary the walk already speaks** — plain
   sentences an analyst reads, not stage names. One when the arc is planned,
   naming the section count; one per section as it finishes, naming its
   heading; one when the paper is written. `detail.stage` is `"draft"`, which
   is what the client discriminates on.
3. **A section event fires after that section's call returns, not before.**
   An event promising work that has not happened is worse than silence — it
   makes a stall look like progress. The loop in `paper/record.py:207` emits at
   the bottom.
4. **Retries are visible, not hidden.** `draft_section` already logs
   `paper_retry` to stderr; a retried section takes multiples of a section's
   time, and a walk that says nothing during it reads as a stall. Emit the
   retry too, in plain words.
5. **No new SSE frame type.** The transport carries one anonymous message type
   `{message, detail}` and `detail.stage` discriminates
   (`service/api.py:426`). Adding a named event type would be a second
   protocol for one badge.

## Inner loop — initial unit test list

- [ ] `run_paper` with no `on_event` behaves exactly as it does today (the
      regression pin for every existing caller).
- [ ] `run_paper` emits one plan event carrying the section count.
- [ ] `run_paper` emits exactly one event per plan section, in plan order,
      each naming that section's heading.
- [ ] A section that retries emits a retry event before its completion event.
- [ ] `run_ask_job` appends every paper event to the job under the same id as
      the analysis events, continuing the same `seq`.
- [ ] `Walk` renders a `draft`-stage event with its own phase badge.

## Out of scope for this slice (deferred)

- Streaming the prose itself. DEC-65 is explicit: what streams is the work,
  not tokens.
- Showing partial essay text in the client while the run is live. The walk
  names the section; the essay arrives whole.
- Any event from the shape check or the citation index — deterministic stages
  that take no perceptible time.

## Definition of done

- [ ] Acceptance test written, seen to fail for the right reason, now GREEN.
- [ ] All seeded unit behaviours covered; `uv run pytest` green,
      `uv run ruff check` clean; `npm run test` green in `web/`.
- [ ] A recording of one live run showing the walk moving through the sections,
      collected as PR evidence.
- [ ] Slice's tests run in CI.
- [ ] Evidence collected and PR opened via `/aeo:safe-pr`.

## Status / progress log

- 2026-08-17 planned.
