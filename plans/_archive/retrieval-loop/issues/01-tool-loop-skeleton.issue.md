# feat(retrieval-loop): tool-loop skeleton — registry, validating dispatcher, budget, trajectory [slice 01]

**Spec:** specs/PHASE-B.md#7.6 · §7.5 · §5 stage 3 · §4 · §8 P0-3 · **Plan:** plans/retrieval-loop/01-tool-loop-skeleton.md
**Depends on:** #251
**Labels:** sub:analysis-v0, enhancement

## Deliverable
The walking skeleton of the stage-3 agentic loop, plus the seam that makes it
possible. `LLMClient.complete()` is JSON-completion only today, with no
tool-calling anywhere in the provider clients, so this slice adds the tool-use
seam. **This is the slice's central design decision and needs founder
confirmation at issue review**, since `llm.py` is a hot shared file: option (a)
extend the OpenRouter client with native `tools` / `tool_calls` support and
widen the `LLMClient` protocol — more robust and reusable, but touches the hot
file; option (b) simulate tool use with a JSON response protocol over the
existing `complete()` — no client change, but brittle to malformed JSON and
hallucinated tool names. **Recommendation: (a).** The model is doing genuine
multi-step tool use, and a hand-rolled protocol re-implements badly what the
provider already does well. Everything above the seam is unchanged either way.

On top of it the slice ships: a **tool registry** exposing the §7.5 tools
(`query_by_tag`, `query_by_polity`, `query_by_source`/`get_envelope`,
`get_chunk`/`get_artifact`, `follow_backlinks`, `coverage_count`); a
**dispatcher** that validates the requested tool name and args **before**
calling, so an unknown name or malformed args is caught there rather than passed
through to the query API; a **bounded step budget** (a stated tunable in
`config/pipeline.yaml`); and the **retrieval trajectory log** (§7.6) — one entry
per tool call in call order, `{step, tool, args, result_ids[], result_count}`.

## Acceptance criterion
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
Then  the vault query API is never called for that step, the model receives a
      validation-error result naming the unknown tool, and the loop continues

Given a scripted model that requests query_by_polity with a missing required arg
When  the retrieval loop runs
Then  the dispatcher rejects it before calling, with a named arg error

Given a step budget of 5 and a scripted model that issues an unbounded stream
      of valid query_by_tag calls
When  the retrieval loop runs
Then  the loop halts after exactly 5 tool calls, the trajectory log has exactly
      5 entries, and the halt is a clean bounded return, not an exception
```

## Out of scope
- Retrieval planning and re-query-on-thin (slice 02); here the model is scripted.
- Implementing the §7.5 query tools themselves (P0-2, `vault-query`).
- Evidence assembly and synthesis (P0-4).
- Any ranking model or vector similarity — v0 retrieval is exactly the §7.5
  structured queries.
- The eval #3 trajectory-scoring harness (P0-12); a richer standalone
  trajectory store (P1-1).
- Choosing the stage-3 model tier (§7.11 [TENTATIVE], measured on dev briefs).
