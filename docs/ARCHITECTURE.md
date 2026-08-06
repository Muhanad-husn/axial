# Architecture

Nine drawings of one pipeline. The first shows the whole of it; the rest open each place
a model is handed a judgment, and show the deterministic code standing on both sides of
it.

Rendered: [muhanad-husn.github.io/axial](https://muhanad-husn.github.io/axial/) (opens on this plate set).

These are a **reading of the specs, not a second source of truth.** Where a diagram and a
spec disagree, the spec is right: [`specs/CHARTER.md`](../specs/CHARTER.md) governs
behaviour product-wide, [`specs/PRODUCT.md`](../specs/PRODUCT.md) is Phase A,
[`specs/PHASE-B.md`](../specs/PHASE-B.md) is the analysis engine, and
[`specs/PHASE-C.md`](../specs/PHASE-C.md) is authorship. Decisions live in
[`docs/DECISIONS.md`](DECISIONS.md).

## The plates

| | Plate | What it opens |
|---|---|---|
| I | [The whole system](diagrams/01-system.md) | Drive → Phase A → persisted artifacts → Phase B → Phase C, with the charter over all of it |
| II | [The Phase A ingestion ledger](diagrams/02-phase-a-pipeline.md) | Ten stages, what each costs in model calls, what it writes — and the source router's three-way fork |
| III | [Interrogate](diagrams/03-interrogate.md) | One reading per note, fourteen open questions, free-answer-first, and the right to abstain |
| IV | [Reconcile](diagrams/04-reconcile.md) | The fold that needs no model, clustering as a hint, the merge call, and "cannot tell" as a real third outcome |
| V | [Gather](diagrams/05-gather.md) | Two member gates, a code-side packet budget, batching, null-dropping, the merge |
| VI | [The argument map, built](diagrams/06-argument-map-build.md) | Select, bag, blind extract, merge — then neighbourhoods and a blind relate call |
| VII | [The agentic query loop](diagrams/07-agentic-query-loop.md) | The one real agent: model turn → validating dispatcher → LLM-free query API → feedback, then deterministic assembly and three validators |
| VIII | [Retrieval over the argument map](diagrams/08-map-retrieval-arm.md) | Door, landing, corridor, assembly — the opt-in arm that replaces stage 3 and nothing else |
| IX | [Phase C authorship](diagrams/09-phase-c-authorship.md) | Assembly from settled claims, four per-run gates, and the offline sealed-packet panel |

## How to read them

One visual grammar throughout:

| | |
|---|---|
| **Deterministic** (teal) | Code. Zero model calls. Same input, same output. |
| **Model call** (mulberry) | A judgment. |
| **Gate** (dashed brass) | A blocking check the model cannot reach. |
| **Artifact** (grey) | Persisted on disk. Resumable, inspectable. |

## The shape all nine share

Every model call in this system is surrounded the same way. Code assembles what the model
sees, so a packet cannot overflow and a prompt cannot be talked into fetching more. Code
reads what comes back, so an invented handle is dropped rather than repaired and a batch
nothing could be parsed from is never recorded as a verdict. And code holds a ledger
beside every paid pass, so an interrupted run resumes instead of paying twice.

The model does the judgment. The code holds the line.
