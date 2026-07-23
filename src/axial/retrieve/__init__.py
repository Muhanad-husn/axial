"""Stage-3 agentic retrieval loop (specs/PHASE-B.md §7.5/§7.6, issue #253;
planning + re-query-on-thin, issue #254).

`tools.py` registers the §7.5 vault-query tool set the model may call.
`dispatcher.py` validates a requested call against that registry before
ever reaching the query API (§4's hard gate). `loop.py` drives a model
client through `axial.llm.LLMClient.complete_with_tools`, dispatching each
requested call and appending one §7.6 trajectory entry per step, under a
bounded step budget (`run_retrieval_loop`), and, above that, plans the
step-1 prompt from the brief's case anchor and the §7.2 interrogation
result, short-circuits on a `refuse` disposition, and assembles the
deduplicated evidence set once the loop halts (`run_planned_retrieval`,
`plans/retrieval-loop/02-planning-anchor-and-requery.md`).
"""
