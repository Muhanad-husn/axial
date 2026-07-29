# Feature: Phase B v1 — retrieval over the graph, not over the bins

Phase A v1 replaced a filing system with a graph. Phase B still retrieves by
filtering bins that no longer exist. Measured against the live vault on
2026-07-29, four of its eight query tools return zero results and the four that
work all require an id the caller already holds. `axial brief` is not producing
poor answers. It cannot reach the corpus at all.

The fix is the same inversion Phase A just went through, applied one layer up.
Retrieval stops being a conjunction of closed-vocabulary filters and becomes
traversal of the name layer the interrogation grew: find the names a brief is
about, read the notes that meet at them, follow what those notes say they argue
against and who they cite.

- **Slug:** phase-b-v1
- **Created:** 2026-07-29
- **Status:** planned
- **New system?** no — it replaces Phase B's query layer and the three contracts
  that read the retired tag axes. The record shape, validators, gates, CLI and
  trajectory log survive.
- **Project directory:** `.`

## Measured, not assumed

Run against `data/vault/` at `64d4cab`.

| tool | v1 result | cause |
|---|---|---|
| `query_by_tag` | 0 on every axis | `field` / `claim_type` / `theory_school` / `role_in_argument` deleted |
| `query_by_polity` | 0 | `polities_touched` deleted — 0 of 6,148 prose notes carry it |
| `coverage_count` | 0 entries | same facet, so the coverage map is empty and `confidence.overall_band` is pinned to `low` by its own derivation rule |
| `follow_backlinks` | `[]` | `artifact_refs` / `cited_by` gone |
| `query_by_source` | 53 for agamben-2005 | works |
| `get_envelope` | works | envelopes untouched by v1 |
| `get_chunk` / `get_artifact` | work | text and `source_meta` intact; every tag field empty |

Three further findings shaped the plan.

**Exact name lookup fails on the names briefs actually use.** The index holds
`Charles Tilly`, `Giorgio Agamben`, `Uğur Ümit Üngör`. Briefs say Tilly, Agamben,
Ungor. It also holds `C. Tilly 1975` and `Charles Tilly (1964)` as separate
pages. Name resolution has to go through the alias map plus the embeddings
Reconcile already built (`data/names/embeddings.lance`), not string equality.
Confirmed in slice 02 against the live vault (2026-07-30,
`data/logs/2026-07-30-name-query-487/`): `Tilly`, `Agamben`, `Bayat`, `Batatu`
and `Caspersen` all land through the alias map, and `Ungor` reaches
`Uğur Ümit Üngör` only through the embeddings, at cosine 0.7752.

**~~`AANES` is absent from the index.~~ It is not — the entity is there and the
acronym cannot reach it.** Measured in the same run: `Autonomous Administration
of North and East Syria` is an exact hit with 2 members, carrying the alias
`Autonomous Administration of Northeast Syria (AANS)`, and a separate,
fragmented `AANS` node with 1 member never folded into it. The acronym `AANES`
reaches neither, because MiniLM scores an acronym against its own expansion
below every piece of lexical noise (`Aarts` 0.7062, `AANS` 0.6716, `Aas Rustad`
0.6200, ...) — an embedding model is not a string matcher. So this is a
**name-layer gap filed against Phase A**, not a `find_names` behaviour and not
a case any similarity floor can rescue: a floor tight enough to cut those five
would also deny an entity the corpus holds.

**~~The vault is missing 130 of its own disagreements.~~ It is not — the two
numbers were never comparable.** `disagreements.jsonl` is append-only and keyed
by a content hash of each name's rendered packets, so it holds history: 2,430
records over 1,910 names, 520 of which carry more than one record. Of the 575
non-null findings, 131 are superseded by a newer record for the same name, and
575 − 131 = 444, exactly the live page count. Measured in slice 01: the free
re-run made 0 model calls and wrote 0 pages, and every one of the 1,910 pages
already agreed with its own newest record. Corrected here rather than left
standing, because the residue turned out to measure something real — see
**Notes and open questions**.

**The eval oracles survived intact.** The 21 sim cases name 28 distinct
`source_id`s across 97 references, and all 28 resolve against `data/envelopes/`
(31 envelopes; `gellner-1981`, `hall-2006` and `mann-v1-2012` are unreferenced).
So `evals/cases/sim/`'s `required_citation_source_ids` still point at real
sources. That is the one mechanical accuracy oracle in the phase and Phase A v1
did not break it.

## Decisions this plan encodes

Settled with the founder, 2026-07-29.

1. **D1 — Names replace tags as the retrieval surface.** `query_by_tag` and
   `query_by_polity` are deleted, not repaired. In their place: `find_names`
   (alias map, then the existing embeddings, never string equality) and
   `get_name`, which returns a page's member notes with author, year and
   one-sentence claim. A polity is a name whose `kind` is
   `country/state/place`; nothing special-cases it.
2. **D2 — Coverage is per-name, and its denominator already exists.** The
   §7.7 map moves from per-polity chunk counts to per-name counts, with
   `corpus_note_count` read off a name page's own `member_count`. This is
   strictly wider than what it replaces: it covers concepts and scholars, not
   only polities.
3. **D3 — Contestedness comes from what the notes say, not from a tag.** A
   brief is contested when its evidence carries notes whose `position_of`
   differ and whose `arguing_against` names the other side, or when it touches
   a name the Gather pass found a disagreement at. The corpus states the
   disagreement instead of a tag implying it.
   **Measured before building (2026-07-29, on #490).** The two clauses are not
   equal. `position_of` is free text with 90% singletons, and 76% of it answers
   "the author" rather than naming a position (#496), so "positions differ" is
   true of 99% of names and discriminates nothing; no count threshold rescues it.
   The `arguing_against` clause does separate — 1.9x–2.4x lift over a 0.26 base
   rate — but **only when "names the other side" is implemented literally**; read
   loosely as "an `arguing_against` exists" it is a 1.00x no-op. Name size is the
   dominant confound and must not be counted as independent evidence, since
   thinness is already disclosed through `member_count` under D2. Recall caps at
   0.35–0.59, so contestedness is a graded disclosure, never a boolean gate.
4. **D4 — Gather findings are a retrieval hint, never a citation.** The agent
   may read a disagreement to decide where to look, then follows its own
   `chunk_ids` to the real notes and cites only those. Grounds stay anchored to
   passages, so charter Principle II is untouched, and a wrong Gather finding
   costs a wasted hop rather than a bad citation. This matters because the 575
   findings have never been scored — `axial gather-eval` exists and has never
   run (DEC-55).
5. **D5 — Backlinks become the citation graph.** `follow_backlinks` is replaced
   by two traversals the interrogation actually produced: names co-occurring on
   a note, and `citations[].cited` with its `support` / `foil` / `authority`
   stance. These are author-stated cross-book edges.
6. **D6 — The pin is re-cut, and its vault hash covers what retrieval reads.**
   Absorbs #484. The hash covers prose note ids plus the name-layer index
   (`index.json`, the alias map version, the disagreement count), because both
   are retrieval substrate now. It changes when a Gather run changes what the
   engine can find, which is correct rather than noisy.
7. **D7 — Two named brief sets replace the 30-brief sweep.** Five short briefs
   in `config/briefs/smoke/` run on every slice. Five hard briefs in
   `config/briefs/eval/` run when the engine is stable. Real files, not a
   manifest over the pool: the eval brief is the one that counts, and
   `config/briefs/sim/` stays untouched as history.
8. **D8 — There is no single accuracy number, and the plan does not invent
   one.** Accuracy decomposes into four, two mechanical and two judged:
   attribution completeness, retrieval hit against
   `required_citation_source_ids`, grounding-support rate on (a) claims, and
   instant-dismissal violations. The case files carry the dismissal criteria and
   nothing reads them today.
9. **D9 — The cross-source rate is the headline quality metric.** The share of
   (b) claims whose grounds span two or more sources. Phase A v1's whole premise
   is cross-book meeting points, and a (b) claim grounded in one book has
   produced no synthesis however well it is attributed.
10. **D10 — Reusing the name embeddings does not reopen the deferred embedding
    index.** `specs/PHASE-B.md` §3 non-goal 4 defers a *chunk* similarity index
    on the grounds that no recall failure has been demonstrated. Name resolution
    is a different problem, the index is already built and paid for, and exact
    match demonstrably fails on the names briefs use. Building a string matcher
    instead would be reinventing a wheel sitting in `data/names/`.

## The brief sets

**Smoke — five short briefs, four retrieval shapes, all with case files.**

| brief | chars | shape it exercises |
|---|---|---|
| P3-01 | 181 | scholar against scholar over a densely covered question |
| P3-04 | 183 | concept anchor at the corpus's centre of gravity |
| P4-03 | 185 | a concept name page whose own book is in the corpus |
| P4-04 | 198 | thin coverage, and the name-layer **fragmentation** case: the corpus holds `Autonomous Administration of North and East Syria` (2 members) plus an unmerged `AANS` node, and the acronym `AANES` a brief writes reaches neither. Its shape moved — this is no longer an honest-resolution-failure case, since the entity is there; #492 should read it as a fragmentation probe |
| P2-02 | 248 | single-book-heavy retrieval, the source-concentration probe |

No P1 or P5 brief is in this set. Both personas write long compound questions by
construction, which is why they carry the hard set instead.

**Eval — five hard briefs, five theory clusters.**

| brief | what it tests |
|---|---|
| **new** — Bayat vs Tilly | organized challengers against revolution-without-revolutionaries, over the same object |
| P1-02 | White × Batatu, a causal chain across two books that barely overlap |
| P5-01 | Kalyvas control logic mapped onto observed violence; 5 required sources, 4 dismissal criteria |
| P5-04 | victim and perpetrator discourse, a different corpus region entirely |
| P4-01 | juridical against empirical sovereignty, Jackson versus Caspersen |

The new brief, drafted:

```yaml
case: "Syria, 2011–2024"
request: "Tilly makes organized challengers and their accumulated resources the
  mechanism that converts a revolutionary situation into a revolutionary outcome.
  Bayat argues the 2011 uprisings were revolutions without revolutionaries — mass
  mobilization uncoupled from the organization and ideas that conversion is
  supposed to require. Which account better explains sustained Syrian mobilization
  without a revolutionary outcome? Where the two disagree about what organization
  is for, is Bayat describing a case Tilly's model excludes, or a failure of the
  model itself?"
```

Its last clause cannot be answered by summarising either book, so it forces a
cross-source (b) claim. It needs a case file authored alongside it or that slot
loses its mechanical oracle; proposed `required_citation_source_ids` are
`bayat-2017-ce6bb0643cfb`, `tilly-1978-f908c910464c`, `beshara-2011-8410a9059300`,
`vignal-2021-c7005c2bf8ef`, `kao-2025-ab19e646ab7d`.

**P1-01 moves to the adversarial set.** It asks about "Tilly's coercive-extraction
cycle", which is *Coercion, Capital and European States*. The corpus holds Tilly
1978, *From Mobilization to Revolution*. That is a smuggled premise the
interrogation pre-pass should catch, so the brief is worth keeping — as a seeded
adversarial case with `kind: smuggled_premise`, not as a synthesis eval.

## What every run records

One report per brief run, keyed on `brief_id` and corpus pin so runs join.

**Operational.** Total and per-pass dollars and tokens (§7.14 already carries
these). Wall clock total and per pass — per-pass latency is new, nothing captures
it today. `model_by_pass`, disposition, trajectory step count, tool calls, failed
tool calls.

**Accuracy**, per D8. Attribution completeness and retrieval hit are mechanical.
Grounding-support rate and instant-dismissal violations are judged, each under
its own pass name and never by the generating model.

**Response quality.**

| metric | definition |
|---|---|
| sources cited | distinct `source_id`s in claim grounds |
| per-source share | `source_usage.evidence_share`, already built |
| concentration | top-1 share and HHI over those shares — one number for monoculture |
| usage ratio | already built; its denominator re-bases from tag filters onto names queried |
| claim mix | count and share of (a) / (b) / (c) |
| **cross-source rate** | share of (b) claims whose grounds span ≥2 sources (D9) |
| grounds per claim | mean and median; share of claims with ≥2 grounds |
| retrieval precision | distinct chunks cited ÷ distinct chunks retrieved |
| name reach | distinct name pages touched; share of grounds notes that are members of one |
| disagreement reuse | did the run reach a note a Gather finding also cites |
| coverage bands | count of names disclosed thin / moderate / dense |
| answer size | claim count, rendered word count |

## Slices

One slice = one issue = one PR. Develop top to bottom, with the one exception
in **Order and concurrency** below.

| # | Slice | Issue | Goal (one line) | Status |
|---|-------|-------|-----------------|--------|
| 00 | spec rewrite | #485 | `specs/PHASE-B.md` v2: §7.5 tool set, §7.7 per-name coverage, §7.8 contestedness from `arguing_against` and Gather, §7.12 pin, §7.13 re-based, §9 the 5+5 sets, §10 gates; retired criteria struck rather than left dangling | ✅ |
| 01 | restore and re-pin | #486 | Re-cut the corpus pin per D6, its vault hash over prose ids plus the name layer. The 130 "missing" findings were superseded history, not damage: the free re-run made 0 calls and wrote 0 pages, and all 1,910 pages already agreed with their newest record. LLM-free | ✅ |
| 02 | the name query API | #487 | `find_names`, `get_name`, `name_neighbors`, `who_cites`, `who_argues_against`, per-name `coverage_count`; deterministic, model-free, fully testable without an LLM | ◐ |
| 03 | retrieval loop rewired | #488 | Tool registry and dispatcher onto 02's tools; trajectory log unchanged; step budget re-proven | ☐ |
| 04 | synthesis on the new evidence | #489 | Evidence assembly and the synthesis prompt rebuilt around `claim` / `position_of` / `arguing_against` / `citations`, with Gather findings as hints per D4 | ☐ |
| 05 | coverage and counter-position | #490 | Per-name coverage map, confidence derivation, contested detection and counter-position generation per D2 and D3 | ☐ |
| 06 | metrics and the run report | #491 | Source usage re-based, the response-quality table computed, per-pass latency captured, one report per run | ☐ |
| 07 | smoke harness | #492 | `config/briefs/smoke/` and `axial brief smoke`: five briefs, mechanical gates plus a cost and latency budget so a spend regression shows up the day it lands | ☐ |
| 08 | gates and the eval run | #493 | Gate fixtures re-pointed at the new record, `config/briefs/eval/` landed with the new brief and its case, the instrumented run executed and reported | ☐ |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Order and concurrency

Eight of the nine slices are a strict chain. There is exactly one real parallel
pair.

```
00 → 01 → 02 → 03 → 04 ┬→ 05 → 06 ┐
                       └→ 07 ─────┴→ 08
```

| wave | slices | why it cannot move earlier |
|---|---|---|
| 1 | 00 (#485) | the contract moves before the code, as in Phase A v1 slice 00 |
| 2 | 01 (#486) | every later run needs a pin that resolves and a vault holding all its findings |
| 3 | 02 (#487) | the foundation slice — 03, 04, 05 and 06 all read its tools |
| 4 | 03 (#488) | consumes 02's tool set |
| 5 | 04 (#489) | consumes 03's trajectory |
| 6 | **05 (#490) ∥ 07 (#492)** | 05 needs 04's claims; 07 needs an engine that produces a record |
| 7 | 06 (#491) | needs 05's coverage map |
| 8 | 08 (#493) | reports what 06 computes, over the harness 07 built |

**05 ∥ 07 is the parallel pair.** 05 touches `src/axial/validators/coverage.py`,
`counter_position.py` and `analyze/`; 07 touches `config/briefs/smoke/`,
`cli.py` and a smoke runner. Disjoint files, separate worktrees, no coordination
needed. 07 degrades gracefully without 06's metrics, so it may also spill into
wave 7 — but there it collides with 06 on `cli.py`, so keep both edits additive.

Build 07 as early as wave 6 for a reason beyond the parallelism: it is the
feedback loop 05, 06 and 08 are all checked against.

**00 ∥ 01 is optional.** 00 writes only `specs/PHASE-B.md`; 01 is a corpus
operation. The one condition is that 01 must not touch §7.12 — 00 already
rewrites it. 00 is a pure `.md` change and may land straight on `main` under the
docs-only gate exception.

- 01, 02 and 07 are LLM-free by construction.
- **01 runs in the main checkout `D:/axial`, never a worktree.** `data/` is
  gitignored, so a corpus operation launched in a worktree silently operates on
  nothing. It is LLM-free and therefore cheap; there is no reason to overlap it
  with 02 to save time.

## Out of scope

- **Any change to Phase A.** The vault is read-only here. A gap found in the
  index routes to a Phase A issue under the DEC-55 rule: new issues come from
  using the product, and this feature is the first real use.
- **A chunk embedding index.** Still deferred on demonstrated recall failure
  (§3 non-goal 4). D10 covers name resolution only.
- **The reviewer panel.** `src/axial/panel/` stands as specified. It is an
  offline instrument on a sample, and nothing here triggers or waits on one.
- **Scoring the 575 Gather findings.** `axial gather-eval` is Phase A's
  instrument and Phase A is closed. D4 is what makes this feature independent of
  whether that score ever runs.
- **The frontier-versus-hybrid model comparison.** Carried over from #362 and
  still unsettled since PR #361. It re-files against the five hard briefs once
  they produce numbers, not before.

## Notes and open questions

- **The name layer is dirty and this feature is what will say how much that
  costs.** Bibliography-shaped names sit in the index (#482, closed as future
  expansion), fragmentation leaves `Charles Tilly` and `C. Tilly 1975` apart
  (#460, same), and diacritics are deliberately unfolded so `Üngör` and `Ungor`
  do not meet. All three were closed against a 5% bar with no failure to aim
  them. A brief that visibly misses evidence because of one is exactly the
  trigger their bodies name.
- **Gather's findings are 53% reproducible, which is why D4 is load-bearing
  rather than merely cautious.** Slice 01 turned the two passes on disk into an
  accidental experiment. PR #474 relabelled one book's author — `heydemann-2000`
  carried the literal string `"unavailable"`, rendered into packets as *"the
  'unavailable (2000)' author"* — and that changed the packet hash of every name
  touching that book and no other name (520 re-asked, all of them; 1,390
  untouched, none of them). Same model, identical `chunk_ids`, identical batches.
  On that one-word change, **93 of the 176 names with a finding in either pass
  reversed** — 48 lost, 45 gained, plus 83 rewritten — while the marginal rate
  barely moved (131 → 128). Flip rate does not track the relabelled book's share
  of the packet, which rules out "it learned something". So a single pass cannot
  distinguish a prompt or model improvement from noise, and no Gather tuning
  issue was filed. What was filed is #495: both answers are already on disk and
  Gather reads only the newest key, so unioning them lifts the hint set 444 → 492
  for zero model calls. Under D4 a coin-flip hint costs a wasted hop, and all 48
  lost names still carry the evidence — differing positions, an `arguing_against`,
  and (46 of 48) notes from two or more books — reachable by `get_name`.
- **Retrieval recall has never been measured and now can be.** The five hard
  briefs have `required_citation_source_ids`. The share of those a run's grounds
  actually reach is the first real recall number this product has had, and it is
  also the signal §3 non-goal 4 names as the condition for reopening the chunk
  index.
- **`available_chunk_count` needs a defensible denominator under names.** Under
  tags it was the union of chunks matching the filters queried. Under names the
  natural analogue is the union of member notes across the names queried. Prove
  it on the smoke set before the concentration metrics are read as meaning
  anything.
