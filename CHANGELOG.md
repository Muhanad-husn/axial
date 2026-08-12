# Changelog

Axial is versioned from its first release. Before 1.0.0 the record was the
issue and PR history, and it stays that way for detail: this file says what a
version is, not what every change was.

## 1.0.0 — 2026-08-12

The first tagged release. All three phases are built, run end to end, and
measured, and the analyst service they sit behind stands up from one
`docker compose up`.

**Phase A, corpus ingestion.** Ten stages from a PDF to an Obsidian vault:
intake, structural extraction, routing, envelope, chunking, artifacts,
interrogate, reconcile, materialize, gather. A structural tree is extracted once
per source and reused by everything after it. Chunking is deterministic and
spends nothing. One open-question call per passage grows the name layer from
what the corpus said.

**Phase B, analysis engine.** Brief interrogation before any spend, an LLM-free
query API, an agentic retrieval loop over the name layer and the argument map,
synthesis, and five deterministic validators.

**Phase C, paper authorship.** Brief intake, arc planning, section drafting,
citation indexing, apparatus. Four gates run on every paper, two mechanical and
two narrowly judged, plus an offline sealed-packet reviewer panel.

**The analyst service.** A Postgres job store, FastAPI over it, progress
streamed as events, a published corpus as a read-only SQLite snapshot pinned to
its build, identity carried to the request path, quotas and a content-keyed
paper cache, and citation mode.

**The two clients.** `web/` is the analyst client — Next.js and TypeScript, an
ask composer, the walk as it happens, the rendered paper, export, per-analyst
history and spend meters, invitation-only sign-in through Supabase including
Google. `axial console` is the operator's local Streamlit console over the CLI,
for one user on one machine.

**Deployment.** `Dockerfile`, `docker-compose.yml` and `.env.example` bring up
Postgres, the API and the worker together against a mounted snapshot. The image
carries the ask path and nothing else: 592 MB, 72 packages, no GPU runtime.
Built, not deployed (DEC-65): the deliverable is a stack someone else can stand
up.

### Measured at this release

| | |
|---|---:|
| Sources ingested | 35 |
| Passages | 6,842 |
| Name pages | 47,584 |
| Pages that can carry a comparison | 329 |
| One analysis | $0.12 to $0.43 |
| One paper | $0.08 to $0.20 |

Both dev papers pass all four Phase C gates on two separate builds, and the
positive control caught all three planted defects unanimously.

### Known limits

- The research briefs and gold labels driving answer-quality evaluation were
  authored by frontier models playing scholarly personas, not by real academics
  (DEC-29). Those figures measure the engine, not answer quality against a real
  academic question.
- The corpus is the binding constraint. The coverage report names three
  concept-level gaps, and selection becomes necessary somewhere near a hundred
  sources.
