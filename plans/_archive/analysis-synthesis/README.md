# Feature: Evidence assembly & synthesis — the claim graph

Stage 4 of the analysis engine (§5 stage 4, P0-4): turn a retrieved evidence set
into a marked, grounded claim graph. The cheap half assembles the evidence set
and makes it inspectable *before* the expensive call, so the operator can look
at what retrieval found and decide whether to spend on synthesis. The expensive
half applies the named lens and performs axial coding across that evidence,
emitting the §7.4 claim graph: every claim marked `a` (source-says), `b`
(tool-infers-across-sources), or `c` (speculation), and every (a)/(b) claim
carrying grounds pointers that resolve to real vault ids. The founder benefits
twice: retrieval is auditable before a single high-tier token is spent, and the
analysis that follows is grounded by construction rather than generated and
back-fitted with citations (charter Principles I and II).

- **Slug:** analysis-synthesis
- **Created:** 2026-07-20
- **Status:** planned
- **New system?** no (new stage inside the existing `axial` CLI and LLM seams;
  slice 01 is the thinnest end-to-end thread through `src/axial/analyze/`)
- **Project directory:** `.`

## Slices

Develop top to bottom. One slice = one red-green-refactor pass = one PR.

| # | Slice | Issue | Goal (one line) | Status | PR |
|---|-------|-------|-----------------|--------|----|
| 01 | [evidence-assembly-and-examine](01-evidence-assembly-and-examine.md) | [#255](https://github.com/Muhanad-husn/axial/issues/255) | `axial brief examine <brief_file>` assembles the retrieved evidence set and reports it — chunk ids, raw per-polity coverage counts, interrogation result — while making **zero** stage-4 synthesis calls | ☐ todo | TBD |
| 02 | [synthesis-claim-graph](02-synthesis-claim-graph.md) | [#256](https://github.com/Muhanad-husn/axial/issues/256) | The synthesis pass applies the lens and axial coding over the assembled evidence and emits the §7.4 claim graph: every claim marked (a)/(b)/(c), every (a)/(b) claim grounded in real vault ids, prompt forbidding parametric-memory assertion | ☐ todo | TBD |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Dependencies

- Slice 01 depends on `retrieval-loop` slice 02 (the agentic query loop that
  produces the evidence set and the trajectory log, §7.6). Everything 01 reports
  is what that loop returned.
- Slice 01 depends transitively on `brief-interrogation` slice 01 (the
  interrogation result it prints) and `vault-query` slice 02 (`coverage_count`,
  the raw material of the coverage counts).
- Slice 02 depends on slice 01: the assembled evidence set is exactly the
  synthesis pass's input, and the seam 01 builds is the seam 02 spends against.
- `analysis-validators` and `analysis-record` both consume slice 02's claim
  graph. Nothing in this feature depends on them.

## Out of scope (whole feature)

- The validators (P0-5, P0-6, P0-7). This feature *emits* a claim graph shaped
  so the validators can check it; checking it is `analysis-validators`.
- The analysis record (§7.3) and anything that writes `data/analyses/`. Slice 02
  returns a claim graph; persisting it is `analysis-record` slice 01.
- The rendered markdown answer (§7.10) — `analysis-record` slice 02.
- The counter-position section (§7.8), the coverage *map* with bands (§7.7), and
  the confidence disclosure. Slice 01 reports raw per-polity counts only; the
  banding rule and the confidence vocabulary belong to `analysis-validators`.
- The retrieval loop itself (P0-3). This feature consumes the evidence set and
  the trajectory log; producing them is `retrieval-loop`.
- Tuning which model tier synthesis runs at. Slice 02 wires the `pass_name` seam
  and sets a `model_by_pass` entry per §7.11; §7.11 is **[TENTATIVE]** and
  "proven by measurement on the dev briefs", so the value is an operational pass.
- Any live-LLM test. Every acceptance test drives the `stub`/`record`/`explode`
  providers.

## Notes / open questions

- **The `explode` provider is the inspect-before-spend oracle.** P0-9's
  observable is "`examine` makes zero stage-4 synthesis calls". The cleanest
  mechanical proof is running `examine` under a client that raises on any
  synthesis-pass call and asserting exit 0. `src/axial/llm.py` already ships
  `ExplodingLLMClient` (`AXIAL_LLM_PROVIDER=explode`) with that exact poison
  shape. A call-counting seam is the fallback if per-pass poisoning proves
  awkward; the property asserted is the same either way.
- **Pass name and tiering.** Synthesis registers a `pass_name` constant
  (mirroring `ENVELOPE_PASS_NAME = "envelope"` in `src/axial/llm.py`) and adds
  a `model_by_pass` entry in `config/pipeline.yaml` alongside `envelope:
  production_high`, plus `reasoning_by_pass: true`. §7.11 puts stage 4 on the
  high tier with reasoning ON. This must be a config entry, never a hardcode.
- **Grounded-by-construction is a prompt-content property.** P0-4's third bullet
  is about what the prompt forbids, and that is deterministically assertable:
  the `record` provider writes every prompt to `AXIAL_LLM_RECORD_PATH`, which
  is how the #228 anti-anecdote test locks prompt content today. Slice 02 uses
  the same seam.
- **Lens selection is recorded, not silent.** §7.1 says an absent `lens` means
  the analysis stage selects one *and records which*. Slice 02 owns both halves:
  resolving a named lens from `config/lenses/`, and recording the selection when
  the brief omits it. `config/lenses/` does not exist yet; slice 02 lands it with
  a small seed vocabulary as data, no country logic in `src/` (§4).
- **`claim_id` determinism** (§7.4) is the same discipline as `brief_id`: no
  randomness, no timestamps. Deterministic *within a run* is what the spec
  requires, which a positional or content-derived id both satisfy; slice 02 pins
  the rule and locks it in a unit test.
- **The (b) seam is the risk surface.** §7.4 calls it "the product's whole value
  and its whole risk". Slice 02 can mechanically assert that (b) claims are
  *emitted and marked*; whether a (b) claim is *phrased* as a source assertion
  is a bounded independent model check and belongs to the attribution validator
  (§7.9, P0-5). Do not try to solve the phrasing check here.
