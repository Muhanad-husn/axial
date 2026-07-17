# Axial

![Axial](axial_logo.svg)

Axial is a single-operator pipeline that turns a corpus of born-digital academic
sources (PDF / DOCX) into a **tagged Obsidian knowledge graph**, and validates the
tagging against a small human-labeled **gold corpus** so tagging reliability becomes a
measured number rather than an assumption. The corpus is comparative-historical
political sociology, heavily weighted toward Syria and the surrounding literature
(Mann, Kalyvas, Brubaker, Hinnebusch, Migdal, Skocpol, Tilly, Wedeen, Malešević).

The pipeline is **domain-general in mechanism, Syria-specific in content**: no
country-specific logic lives in code. Every piece of domain content — the axes, the
controlled vocabularies, the codebook definitions — is one versioned schema loaded at
runtime (`config/domains/syria/`). Porting to another country is a schema edit, not a
code change. This repository builds **Phase A (ingestion + the gold/eval loop)**: the
clean, tagged substrate that downstream research-production phases will consume. The
full build specification lives in [`specs/PRODUCT.md`](specs/PRODUCT.md).

## The pipeline

Seven stages, each an independently testable module. A structural tree is extracted
**once per source**, persisted, and reused by every later stage.

1. **Intake** — accept PDF/DOCX, verify a real text layer, reject scanned files. No
   OCR path.
2. **Structural extraction + normalization + routing** — docling builds a hierarchical
   tree (Unstructured is the fallback); a deterministic, model-free normalization pass
   repairs decoding defects (soft-hyphens, whitespace damage, glyph-name leaks); then a
   **source router** classifies every block into one of three routes — **prose**
   (→ chunking), **artifact** (→ artifact pass), or **apparatus** (TOC, endnotes,
   reference lists — dropped and recorded). The route is computed once and shared by
   every downstream pass.
3. **Structural envelope** — one API call per source extracts the author's thesis, TOC,
   scope, and stated argument, grounded only in a substantive slice of the source's own
   prose. Reused by tagging.
4. **Chunking** — a **recursive/structural splitter** (paragraph → line → sentence →
   character) finds boundaries and bounds every chunk into a two-sided size band. Fully
   deterministic and **LLM-free**: no embedding model, no generative call. Chunks are
   written to disk before any inference spend, so quality is inspectable with
   `axial chunk examine`.
5. **Artifact classification** — tables, figures, and captions get a role tag and route
   to a separate artifact pool with provenance and back-references.
6. **Tagging** — each prose chunk is tagged on the schema's axes (claim-type, field,
   empirical-scope, candidate theory-school), a role-in-argument tag, and the
   many-valued `polities_touched` facet.
7. **Cross-reference + vault write** — prose→artifact references become bidirectional
   links; everything is written to the Obsidian vault (separate prose and artifact
   pools).

The **gold-corpus and eval loop** wraps stages 4–6: sampled chunks are emitted into a
label sheet, handed to the Academic offline, labeled, and scored per axis.

## Command surface

The pipeline is driven through the `axial` CLI (`uv run axial <command>`). The main
commands, roughly in pipeline order:

| Command | Does |
|---------|------|
| `schema show` / `schema validate` | Inspect a domain schema; cross-check schema against codebook |
| `intake <src>` | Validate a source and probe for a real text layer |
| `extract <src>` | Structural extraction → persisted normalized JSON tree |
| `envelope <src>` | Structural-envelope pass → `data/envelopes/<id>.json` |
| `chunk <src>` | Recursive/structural chunk stage → `data/chunks/<id>.jsonl` (LLM-free) |
| `chunk examine` | Report chunk-quality stats over `data/chunks/` (zero LLM/embedding calls) |
| `tag <src>` | Tagging pass |
| `artifacts <src>` | Artifact-classification pass |
| `xref <src>` | Cross-reference detection |
| `vault write <src>` | Chunk + artifact passes → prose and artifact notes under `data/vault/` |
| `ingest <worklist>` | Batch vault-write over a worklist, skipping already-ingested sources |
| `gold sample` / `gold sheet` / `gold deliver` | Sample gold chunks, render the label sheet, package the offline Academic handoff |
| `eval` | Score returned Academic labels against the tagger → `eval_report.json` |
| `polity build` / `polity report` | Offline, model-free canonical polity-map operations |
| `pipeline-ready --manifest` | Run the canary gate (single-attempt completion, quarantine budget, time envelope) |

## Repository layout

```
config/
  pipeline.yaml              # providers, model-per-pass, paths
  domains/syria/             # schema.yaml, codebook.yaml, polity_canonical.yaml
src/axial/                   # one module per stage + co-located unit tests
  intake, extract, router, envelope, chunk, artifacts, tag, xref, vault,
  gold, eval, llm, schema, ...
tests/                       # outer acceptance contracts (locked, committed red first)
data/                        # trees/, envelopes/, chunks/, vault/, gold/ (gitignored)
specs/PRODUCT.md             # the complete build specification
docs/                        # DECISIONS.md, eval/, tdd-evidence/, postmortem/
```

## Status

The Phase A pipeline is **built end-to-end** — intake through vault write, plus the
gold-set generation and eval harness. It has been **validated at scale**: the corpus was
rebuilt from ~30 processable sources into ~17k chunks, with a healthy chunk-size
distribution and the routing/normalization passes holding across new table- and
OCR-heavy sources.

Two things gate the remaining work, by design:

- **Eval runs against placeholder labels.** The real per-axis agreement numbers wait on
  the Academic's labeling pass (§11 of the PRD). When the labels arrive it is a data
  swap plus an `axial eval` run — never a code change.
- **No full-corpus run until the eval closes.** v0 processes only the sample needed to
  build and score the gold set; generalizing to all sources waits on a passing eval.

GitHub issues and PRs are the system of record; [`docs/DECISIONS.md`](docs/DECISIONS.md)
holds the decision log.

## How this repository is built

Axial is built with a behavior-first, test-driven workflow: every change lands behind a
locked acceptance test, is reviewed, and merges via pull request only on explicit human
approval — no change lands on a red test suite. Development is AI-assisted with
[Claude Code](https://claude.com/claude-code), with a single human holding architecture
and approval authority.

## Quick start

```bash
uv sync            # install dependencies
uv run pytest      # run the suite
uv run axial --help
```
