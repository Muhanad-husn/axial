# Does a question work as a thesis? — #784 slice 01 pre-measurement

**Date:** 2026-08-17 · **Branch:** `feat/784-ask-ends-in-an-essay/01-essay-from-the-ask`

## The question

Every paper brief that has ever been run in this repo carries a **declarative**
thesis, hand-written by the operator. An ask supplies its **question** —
`_ask_paper` passes `turn.question` straight into `PaperBriefContent.thesis`.
The arc planner has never been asked to plan from an interrogative. Before
wiring the composition into the service, find out whether it can.

## Command

```
uv run axial paper examine data/logs/2026-08-17-784-question-as-thesis/briefs/<id>.yaml
```

Six briefs, each `{thesis: <the record's own brief.request>, analysis_ids: [<id>]}`
— byte-for-byte the brief `_ask_paper` builds, no lens, no title. Stages 1–2
only; **zero drafting calls**. Runner: `run.ps1`.

Paired design: each of the six analysis records **already has** a
single-record paper in `data/papers/` drafted from a declarative thesis, so
every run has its own baseline rather than a corpus-wide average.

## Result — a question plans a normal arc

All six exited 0 in 10–18 s. Every plan is well-formed: exactly one `setup`,
at least one `counter-position`, exactly one `synthesis`, claims assigned to
every non-setup section.

| analysis record | claims | sections, question thesis | sections, declarative baseline | baseline paper |
|---|---|---|---|---|
| `92d2d85745ecaa2d` | 20 | 8 | 6 | `5d866ef2ce4971ae` |
| `be50533708e44f33` | 24 | 7 | 6 | `408378f2e286fff2` |
| `c2afb6d42f713e1c` | 32 | 8 | 10 | `273aea05df54e2df` |
| `e7d6a2646523cb1d` | 15 | 6 | 5 | `9f449f41b88e5c70` |
| `ec94042430910584` | 13 | 5 | 6 | `a1039fad4da31320` |
| `fa44475aaaa90a48` | 12 | 7 | 6 | `f5ae5ff2f09766af` |

Mean 6.8 sections from a question against 6.5 from a declarative thesis. The
difference is inside the noise (see below), and the direction is not
consistent — two of six planned *fewer* sections than their baseline.

**The mechanism is that the planner restates the question as a thesis.** Every
`thesis_statement` it emitted is a declarative sentence carrying a position,
never the question echoed back. `fa44475aaaa90a48`'s question — *"do later
accounts extend Jackson's concept of quasi-states, or contest what it was
meant to explain?"* — came back as *"Later accounts … do not simply extend
Jackson's concept; they contest what it was meant to explain, because read
through a political-economy lens…"*. So the interrogative never reaches the
drafter: stage 2 converts it.

## The caveat that matters more than the table

**A single draw is not a measurement.** `fa44475aaaa90a48` was run twice on
byte-identical input during this session: **5 sections** in an ad-hoc first
run, **7 sections** in the logged run, with different headings. Same brief,
same record, same model. Nothing in the table above should be read as a
difference of 1–2 sections meaning anything; the paired comparison is only
strong enough to say a question thesis does not *break* the planner, and that
is what it was run to find out.

Consistent with `gather-manufactures-disagreements` and the #695 merge finding:
this pass is not deterministic and never claimed to be.

## Two incidental findings

1. **`axial paper examine` reports no cost.** It makes one real `paper_plan`
   call and prints the plan, but neither the CLI nor `run_paper_examine`
   surfaces what that call cost. Nothing here needed it — the existing paper
   records price `paper_plan` at $0.0015–0.0094 — but "inspect before you
   spend" is the command's whole purpose and it does not say what was spent.
   Worth a small issue; not fixed here.
2. **The Bash tool exports `AXIAL_SECRETS_PATH=/secrets/secrets.toml`** — MSYS
   mangles the repo-relative default into a POSIX absolute path that resolves
   to nothing on Windows. Every run under `bash` failed with
   `LLMConfigError: no API key was found` **before any model call**, which
   reads exactly like a missing key rather than a mangled path. The first six
   runs in `run.sh` died this way (exit 1, 1–2 s each; `run.jsonl` was
   overwritten by the PowerShell rerun, the tracebacks are not). Run anything
   that needs secrets through PowerShell in this repo, or clear the variable.

## Verdict

Question-as-thesis is fine. Slice 01 proceeds as planned — no change to the
brief `_ask_paper` builds, and no prompt work in scope.
