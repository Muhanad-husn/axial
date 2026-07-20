# Slice 01: Tool-loop skeleton — registry, validating dispatcher, budget, trajectory

- **Feature:** retrieval-loop
- **Slice slug:** tool-loop-skeleton
- **GitHub issue:** #253
- **Branch:** `feat/retrieval-loop/01-tool-loop-skeleton`
- **Project directory:** `.`
- **Status:** ☐ todo
- **Walking skeleton?** yes (the first thread through stage 3: model → tool call
  → validated dispatch → vault query → trajectory entry → next step → halt)
- **Depends on:** `vault-query` slice 02 (the six §7.5 tools the registry exposes)

## Goal — the minimum testable behaviour

A model-driven loop calls the deterministic vault-query tools and leaves an
exact audit trail. The slice ships four things plus the seam that makes them
possible:

1. **The tool-use seam.** `LLMClient.complete()` has no tool-calling today, so
   the loop cannot exist without one. See Notes in
   [README.md](README.md) for the two options and the recommendation
   (native tool-calling, founder to confirm at issue review).
2. **A tool registry** exposing the §7.5 tools to the model: `query_by_tag`,
   `query_by_polity`, `query_by_source` / `get_envelope`, `get_chunk` /
   `get_artifact`, `follow_backlinks`, `coverage_count`.
3. **A validating dispatcher.** The requested tool name is checked against the
   registry and the args against the tool's signature **before** the call. An
   unknown name or malformed args is caught there and returned to the model as
   an error result — never passed through to the query API, never a crash.
4. **A bounded step budget** (a stated tunable in `config/pipeline.yaml`) and
   the **retrieval trajectory log** (§7.6): one entry per tool call in call
   order, `{step, tool, args, result_ids[], result_count}`.

## INVEST check

- **Independent:** sits above the query API and below synthesis. It plans
  nothing yet (that is slice 02) — a scripted model supplies the calls.
- **Valuable:** it is the machinery P0-3 names, and the tool-use seam every
  later agentic pass in the product will reuse. The trajectory log is eval #3's
  raw material (§7.6).
- **Small:** registry + dispatcher + counter + append-only log. The seam is the
  one non-trivial piece, and it is additive.
- **Testable:** a scripted fake model returning a fixed call sequence makes the
  whole loop deterministic; the trajectory is compared field for field.

## Acceptance criterion (outer loop — the failing e2e/integration test)

```gherkin
Given a fixture vault with known chunk ids
  And a scripted model that issues exactly three tool calls in order:
      query_by_tag{field: "state-formation"}, then
      query_by_polity{polity: "Syria"}, then
      get_chunk{chunk_id: <a known id>}
When  the retrieval loop runs against that vault
Then  the trajectory log has exactly 3 entries in that order
  And entry 1 is {step: 1, tool: "query_by_tag", args: {field: "state-formation"},
      result_ids: [<the ids that query returns>], result_count: <their count>}
  And every entry's `result_count` equals the length of its `result_ids`
  And `step` increments 1, 2, 3 with no gaps

Given a scripted model that requests tool "query_by_vibes" with args {q: "x"}
When  the retrieval loop runs
Then  the vault query API is never called for that step
  And the model receives a validation-error result naming the unknown tool
  And the loop continues to the next step rather than crashing

Given a scripted model that requests query_by_polity with a missing required arg
When  the retrieval loop runs
Then  the dispatcher rejects it before calling, with a named arg error

Given a step budget of 5 and a scripted model that issues an unbounded stream
      of valid query_by_tag calls
When  the retrieval loop runs
Then  the loop halts after exactly 5 tool calls
  And the trajectory log has exactly 5 entries
  And the halt is a clean bounded return, not an exception
```

- **Boundary / endpoint:** the retrieval-loop module entry point in
  `src/axial/retrieve/` (§6), driven with an injected scripted model client; the
  emitted trajectory log (§7.6).
- **Outer test type:** pytest integration/acceptance test.
- **Outer test file (planned):** `tests/test_retrieval_loop_skeleton.py` —
  authored by the test-author, committed red, then locked.

## Inner loop — initial unit test list

- [ ] Registry: exactly the §7.5 tool set is exposed; each entry carries a name
      and an arg schema the dispatcher can validate against.
- [ ] Dispatcher accepts a known tool with well-formed args and calls through to
      the query API with exactly those args.
- [ ] Dispatcher rejects an unknown tool name and returns a structured error
      result rather than raising.
- [ ] Dispatcher rejects missing / extra / wrong-typed args before the call.
- [ ] Trajectory entry shape: `{step, tool, args, result_ids[], result_count}`
      with `result_count == len(result_ids)`.
- [ ] Trajectory is append-only and in call order; `step` starts at 1 and has no
      gaps, including across steps whose dispatch failed validation.
- [ ] Step budget: the loop halts at exactly the configured count; the budget is
      read from config, not hardcoded.
- [ ] A budget halt returns cleanly with the trajectory intact.
- [ ] The loop registers its `pass_name` so `model_by_pass` /
      `reasoning_by_pass` can route it (§7.11).
- [ ] The tool-use seam: the loop drives the scripted client through the new
      tool-capable entry point, and existing `complete()` callers are unaffected.

## Out of scope for this slice (deferred)

- Retrieval **planning** and re-query-on-thin — slice 02. Here the model is
  scripted; nothing decides what to call.
- Evidence assembly and synthesis (P0-4).
- Any ranking or similarity. Retrieval is exactly the §7.5 structured queries.
- The eval #3 trajectory-scoring harness (P0-12).
- A richer standalone trajectory store (P1-1).
- Choosing the stage-3 model tier (§7.11 [TENTATIVE], measured on dev briefs).
- Retrying a model turn that emits no tool call at all — v0 ends the loop.

## Definition of done

- [ ] Outer acceptance test authored by the test-author, committed RED, seen to
      fail for the right reason — then locked.
- [ ] All seeded unit behaviours covered; full suite passes locally; outer test GREEN.
- [ ] Refactor pass complete with the bar green.
- [ ] Slice's tests run in CI (`tdd-ci`).
- [ ] Reviewer's two-stage review passed.
- [ ] Evidence collected and PR prepared into `main` (`safe-pr`) — merge awaits
      founder approval.

## Status / progress log

- 2026-07-20 planned.
