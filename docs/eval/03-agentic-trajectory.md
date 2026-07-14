# Eval 3 — agentic trajectory (process axis)

**Status:** foundation stub. Scope fixed to path *a* — the product's query agent.
**Depends on:** full 24-source re-run (rich corpus, for real distractors).

## Scope decision

An AI agent that drives Axial's retrieval/query layer to answer a query. We evaluate
**how it gets there**, not only the final answer. Explicitly *not* the engineering-org
agentic workflow (the role-subagent TDD harness) — that was considered and set aside.

## Question

Given a query, does the agent behave well on the way to the answer — pull the right
chunks, take efficient steps, use tools correctly, recover from dead ends — rather
than lucking into a right answer over a broken path?

## Why a separate axis

The answer-quality eval (#1) scores the output. It cannot distinguish a right answer
reached by sound retrieval from a right answer reached by a lucky guess over a broken
path. Trajectory eval catches "right answer, terrible process" and "wrong answer,
recoverable process." This is the trending agentic-benchmark category (trajectory
scoring, tool-call correctness, step-efficiency, LLM-as-judge over the trajectory).

## What gets measured

- **Retrieval correctness** — did the agent pull the chunks a good answer needs?
  Checkable against the required-citation set from #1's cases (programmatic oracle, no
  judge needed).
- **Step efficiency** — turns, tool calls, redundant retrievals vs. a reasonable
  budget.
- **Tool-call correctness** — well-formed calls, right tool for the step, no thrash.
- **Recovery** — behavior after an empty or wrong retrieval: does it re-query
  sensibly or spiral?
- **Outcome** — the final answer, scored by #1's judge, so trajectory and outcome are
  reported together.

## Oracles — mostly programmatic

Unlike #1, most of this needs **no academic and no judge**: retrieval-hit checks,
step/token counts, and tool-call validity are all programmatic. So the harness can be
built and dry-run now against the current small state, then pointed at the rich corpus
when the re-run lands. Only the outcome dimension reuses #1's judge.

## Open threads

- Trajectory representation to log and score (tool calls + retrieved chunk_ids + agent
  turns), and where it is stored.
- Reasonable step/token budgets per query stratum.
- Which dimensions are hard gates vs. reported metrics.
- How much of #1's required-citation set can serve as the retrieval-correctness oracle
  without leaking answers to the agent under test.
