"""Stage-3 agentic retrieval loop (specs/PHASE-B.md §7.5/§7.6, issue #253).

`tools.py` registers the §7.5 vault-query tool set the model may call.
`dispatcher.py` validates a requested call against that registry before
ever reaching the query API (§4's hard gate). `loop.py` drives a model
client through `axial.llm.LLMClient.complete_with_tools`, dispatching each
requested call and appending one §7.6 trajectory entry per step, under a
bounded step budget.

Retrieval PLANNING -- deciding what to call from the interrogation result
and the case anchor, and re-querying on a thin result -- is out of scope
here (plan `plans/retrieval-loop/02-planning-anchor-and-requery.md`); this
module only executes, validates, dispatches, and records what a caller
(a real planning layer, or a scripted test model) tells it to call.
"""
