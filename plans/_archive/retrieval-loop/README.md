# Feature: Retrieval planning and the agentic query loop

Put a model in the middle of retrieval. Stage 3 (§5) is a model-driven agent
that plans retrieval from the interrogation result and the case anchor, calls
only the deterministic vault-query tools (§7.5), inspects what came back, and
**re-queries when results are thin** — the one behaviour a fixed retrieval
pipeline cannot express, and the reason the architecture is an agent wrapped in
hard gates (§4). Its freedom is bounded by code the model cannot reach: a
dispatcher that validates every tool name and its args before calling, a bounded
step budget, and a retrieval trajectory log (§7.6) that records every call in
order so a right answer reached by a lucky path is distinguishable from one
reached by sound retrieval. The founder benefits: retrieval that adapts to a
thin corpus instead of silently returning three chunks, and an audit trail that
eval #3 can score.

- **Slug:** retrieval-loop
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** yes for the tool-use seam — `LLMClient.complete()` is
  JSON-completion only today and has no tool-calling; slice 01 is the walking
  skeleton that adds it and threads one loop end to end
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [tool-loop-skeleton](01-tool-loop-skeleton.md) | [#253](https://github.com/Muhanad-husn/axial/issues/253) | A tool-use seam plus a registry, a validating dispatcher, a bounded step budget, and the §7.6 trajectory log: a scripted model driving 2–3 vault-query calls produces an exactly-matching trajectory, and a runaway loop is halted by the budget | ☐ todo | TBD |
| 02 | [planning-anchor-and-requery](02-planning-anchor-and-requery.md) | [#254](https://github.com/Muhanad-husn/axial/issues/254) | Retrieval is planned from the interrogation result and the case anchor; a thin first result triggers a broadened second query, and a country-case brief can surface cross-polity evidence — case-as-anchor, not case-as-fence | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- Slice 01 depends on `vault-query` slice 02 — the six §7.5 tools
  (`query_by_tag`, `query_by_polity`, `query_by_source`/`get_envelope`,
  `get_chunk`/`get_artifact`, `follow_backlinks`, `coverage_count`) are what the
  registry exposes. The loop registers them; it does not implement them.
- Slice 02 depends on slice 01 (the loop and the trajectory it plans within) and
  on `brief-interrogation` slice 01 (the §7.2 interrogation result it plans
  retrieval from).
- Stage 4 (evidence assembly and synthesis, P0-4) consumes this feature's
  evidence set and trajectory; it is not part of this feature.

## Out of scope (whole feature)

- Implementing the vault query tools themselves (P0-2, `vault-query`). This
  feature exposes and calls them.
- Synthesis, the claim graph, the validators, rendering (P0-4 … P0-8).
- Any ranking model or vector similarity. Retrieval in v0 is exactly the
  structured queries of §7.5; the embedding index is a stated Phase-B non-goal,
  reopened only on demonstrated recall failure (§3, Open Questions).
- The eval #3 trajectory-scoring harness (P0-12). This feature produces the
  trajectory; the gate that scores it is built with the other gates.
- A richer standalone trajectory store (P1-1). The in-record log format of §7.6
  is what ships.
- Any live-LLM test. Every acceptance test drives a scripted model through the
  `stub`/`record` provider.

## Notes / open questions

- **The central design decision: how the model calls tools.** `LLMClient` is
  today `def complete(self, prompt: str, pass_name: str | None = None) -> str` —
  JSON completion only. The OpenRouter client posts to `/chat/completions` with
  no tool definitions and no `tool_calls` handling. An agentic loop needs a tool
  channel, so slice 01 must add one. Two options:

  **(a) Native tool-calling in the provider client.** Extend the OpenRouter
  client to send `tools` and read `tool_calls` off the response, and widen the
  `LLMClient` protocol with a tool-capable entry point alongside `complete()`.
  More robust, reusable by any later agentic pass, and it inherits the
  provider's own schema validation and multi-step tool conventions. Cost: it
  touches `llm.py`, a hot shared file every Phase-A pass runs through.

  **(b) Simulate tool use over the existing `complete()`.** Define a JSON
  response protocol — the model returns `{"tool": ..., "args": {...}}`, the
  dispatcher executes it, the result is appended to the next prompt. No client
  change at all. Cost: it is a hand-rolled re-implementation of a solved
  problem, brittle to malformed JSON and hallucinated tool names, and every
  robustness fix is one we write ourselves.

  **Recommendation: (a), native tool-calling.** The model here is doing
  genuine multi-step tool use, and (b) re-implements badly what the provider
  already does well; the brittleness it buys lands exactly on the loop's
  correctness. **The founder should confirm at issue review**, since `llm.py` is
  a hot shared file and the change is additive-but-central. If (a) is rejected,
  slice 01 still ships unchanged in shape — only the seam swaps — because the
  registry, dispatcher, budget, and trajectory log all sit above it.

- **Dispatcher is the hard gate.** Whichever seam wins, the dispatcher validates
  the requested tool name against the registry and the args against the tool's
  signature **before** calling. An unknown tool name or malformed args is
  caught there and returned to the model as an error result — never passed
  through to the query API, never raised as a crash. This is §4's "the model
  does the judgment; the code holds the line", applied to tool use.

- **Step budget is a stated tunable.** P0-3 requires "a bounded step budget (a
  stated tunable)". It lands in `config/pipeline.yaml` with a starting value,
  and the loop halts cleanly at the budget with the trajectory intact — a halted
  run is a bounded run, not an error.

- **Thin-result rule.** "Thin" needs a definition the test can pin. v0: a
  result whose `result_count` falls below a configured floor. Like the
  contested-detection rule of §7.8, the threshold is a stated tunable proven on
  the dev briefs; the *agent deciding to re-query on it* is the firm behaviour.

- **Model tier.** §7.11 puts stage 3 at "tier chosen for tool-use reliability,
  measured on the dev briefs". The loop registers its `pass_name` so
  `model_by_pass` can route it; picking the tier is an operational pass, not
  part of these slices.
