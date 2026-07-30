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
   **Two follow-ups from #496.** Frame 0.2 splits the question, so sources added
   from now on carry a separate `position` — the existing 6,148 notes never will,
   because no re-run is planned. Independently, every old record already carries
   `position_of_nearest`: the same answer mapped onto the 33-value theory-school
   list, present on 90.2% of the "the author" notes. That is a countable label
   available to this clause today, at no cost, though two thirds of it is a
   `loose` fit and it ranks rather than proves.
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
| P4-04 | 198 | thin coverage, and the name-layer **fragmentation** case: the corpus holds `Autonomous Administration of North and East Syria` (2 members) plus an unmerged `AANS` node, and the acronym `AANES` a brief writes reaches neither. Its shape moved — this is no longer an honest-resolution-failure case, since the entity is there; #491 reads it as a fragmentation probe |
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
| 02 | the name query API | #487 | `find_names`, `get_name`, `name_neighbors`, `who_cites`, `who_argues_against`, per-name `coverage_count`; deterministic, model-free, fully testable without an LLM. Validated on the live corpus: 14 of 17 queries resolve on a string tier, `Ungor` reaches `Uğur Ümit Üngör` only through the embeddings. The 0.5 floor stands as a stated tunable; the AANES premise was false and is corrected here and in §7.5 | ✅ |
| 03 | retrieval loop rewired | #488 | Tool registry and dispatcher onto 02's tools; trajectory log unchanged. Ten tools registered, per-arg types so `limit` is an honest int, and a `returns_chunk_ids` flag that keeps canonical names out of the evidence set. Validated LLM-free against the live vault: `Tilly` → `Charles Tilly` → 146 members, 58 citation edges, 2 oppositions, all three rejection paths firing before the vault, 0 names leaked. **The step budget was NOT re-proven** — raised 10 → 20 as stated provisional headroom, because the name surface needs ~3 calls per name; the real bound is measured on the smoke briefs in 06 | ✅ |
| 04 | synthesis on the new evidence | #489 | Evidence assembly and the synthesis prompt rebuilt around `claim` / `position_of` / `position` / `arguing_against` / `citations`. `ChunkNote` now exposes all 21 answer keys instead of 7, the abstention predicate moved into the read path as one shared function, and `names_touched` resolves through the alias map alone (99.9% of 9,434 real surfaces; the 8 drops are locator-shaped). **Gather findings are NOT plumbed into the prompt** — D4 permits rather than requires it and nothing carries one into stage 4, so the prompt states the never-cite rule and no finding-as-context path was built. Two shared-substrate bugs fixed: the reader read a bare-string abstention as fourteen one-letter names, and `brief examine` crashed writing its own report | ✅ |
| 05 | coverage and counter-position | #490 | Per-name coverage map, confidence derivation, contested detection and counter-position generation per D2 and D3 | ☐ |
| 06 | the run report, and the smoke harness that asserts on it | #491 | Source usage re-based, the response-quality table computed, per-pass latency captured, one report per run — plus `config/briefs/smoke/` and `axial brief smoke`: five briefs, mechanical checks and a cost and latency budget, built as a front end over the existing `run_sweep` | ☐ |
| ~~07~~ | ~~smoke harness~~ | ~~#492~~ | **Absorbed into 06 on 2026-07-30.** Two of its five mechanical checks read 06's and 05's output, so it was never independent; both slices also edit `cli.py` and the record layer | — |
| 08 | gates and the eval run | #493 | Gate fixtures re-pointed at the new record, `config/briefs/eval/` landed with the new brief and its case, the instrumented run executed and reported | ☐ |

<!-- Status values: ☐ todo · ◐ in-progress · ✅ done. Update the row when a slice's PR opens. -->

## Order and concurrency

After 06 absorbed 07, every remaining slice is a strict chain. Only the optional
00 ∥ 01 overlap is left.

```
00 → 01 → 02 → 03 → 04 → 05 → 06 → 08
```

| wave | slices | why it cannot move earlier |
|---|---|---|
| 1 | 00 (#485) | the contract moves before the code, as in Phase A v1 slice 00 |
| 2 | 01 (#486) | every later run needs a pin that resolves and a vault holding all its findings |
| 3 | 02 (#487) | the foundation slice — 03, 04, 05 and 06 all read its tools |
| 4 | 03 (#488) | consumes 02's tool set |
| 5 | 04 (#489) | consumes 03's trajectory |
| 6 | 05 (#490) | needs 04's claims |
| 7 | 06 (#491) | needs 05's coverage map, and the harness it now carries asserts on that map being non-empty |
| 8 | 08 (#493) | reports what 06 computes, over the harness 06 built |

**~~05 ∥ 07 is the parallel pair.~~ It was never real.** The plan put the smoke
harness beside 05 on the grounds that it only needs an engine producing a record.
Two of its five mechanical checks say otherwise: the cost and latency budget
reads 06's per-pass figures, and the non-empty coverage check is exactly the
regression 05 exists to fix, so it fails by construction before 05 lands. The
"degrades gracefully without 06's metrics" clause was buying a path no ordering
takes, and the two slices collide on `cli.py` and the record layer either way.
They are one issue and one PR from 2026-07-30.

**What that costs, stated.** The harness was also meant to be the feedback loop
05, 06 and 08 are checked against. It now arrives after 05, so 05 is checked by
its own acceptance test and the commit gate alone. In substance that was already
true.

### 04 and 05 stay two slices, and this is the seam

Reconciled 2026-07-30 against the shipped code rather than the two issue bodies.
Their scopes do not overlap: 04 keeps evidence assembly, the synthesis prompt and
the claim contract; 05 keeps the coverage map, confidence, contested detection
and counter-position generation. What they share is substrate neither issue
claims, and the chain would have surfaced it as 05 reopening a file 04 had just
closed.

**The reader is short of both slices, so 04 extends it once, for both.** A live
prose note carries 21 answer keys. `ChunkNote` (`src/axial/query/reader.py`)
exposes seven: `claim`, `move`, `position_of`, `position`, `arguing_against`,
`names`, `citations`. Every other field #489 names is unreachable today
(`ranges_over`, `stops_holding`, `mechanism`, `evidence`, `comparison`,
`defines`, `uses`, `concedes`, `assumes`), and so is `position_of_nearest`, which
D3 wants and 95.7% of notes carry (5,857 of 6,119 parsed). 04 adds the fields
only 05 reads as well. `reader.py` is shared substrate on a strict chain, and
opening it twice is the collision the chain exists to prevent.

**The abstention predicate is 04's, in one place.** `not-in-passage` in its three
forms (§7.15) is implemented on the write side only (`interrogate.is_abstention`);
no reader applies it. 05 imports 04's rather than writing a second one, because
two abstentions comparing as "different positions" would manufacture a
disagreement, which is the failure D3's own measurement warns about.

Measured over the 6,148 answer records, correcting a figure this section first
carried:

| field | explicit abstention | `[]`, an answer | named answer |
|---|---:|---:|---:|
| `position_of` | 1,451 (23.6%) | 0 | 4,697 (76.4%) |
| `arguing_against` | 301 (4.9%) | 1,184 (19.3%) | 4,663 (75.8%) |
| `position_of_nearest` | 11 | — | 5,882 (95.7%) |

The first draft of this section said "24% of notes abstain on `arguing_against`",
which fused two states that §7.15 keeps apart: `[]` is an answer, and it says
the passage names no opponent. Only 4.9% abstain. **05 must not read those 1,184
`[]` notes as abstentions**, or it discards a fifth of that field's real
answers. The parse also reported 29 unreadable notes; the real number is 0, and
the 29 were an artifact of splitting frontmatter on `---`.

**`polities_touched` → `names_touched` is 04's, whole.** Blast radius:
`analyze/assembly.py`, `analyze/synthesis.py:608` where the union is computed,
`answer/record.py`, `answer/render.py`, and their tests. `validators/coverage.py`
reads the old key, so after 04 it reads a key that is not there,
`compute_coverage_map` returns `{}`, and `validate_coverage_and_confidence` check
1 passes **vacuously**. That is today's state exactly: the map is already empty at
0 entries and confidence is already pinned `low`. So the interim is honest and
green, 04 must not take on 05's job to keep the map alive, and 05 inherits a
vacuous pass rather than a real one. Surface forms resolve through the alias map
alone (`canonical_for_surface`, which needs a public wrapper), never through
`find_names`' embedding tier: §7.4 drops a surface the index does not carry
instead of inventing one, and a fuzzy match here would fabricate coverage.

**`EvidenceSet.polity_coverage` dies with 04; the §7.7 map is 05's alone.**
`assembly.py` carries a second coverage roll-up (`PolityCoverage`,
`_roll_up_polity_coverage`) reading the field 04 deletes, and neither issue names
it. Under §7.7 the map is computed from `names_touched` over the claim graph,
which is post-synthesis, so the pre-synthesis roll-up has no contract left. 04
deletes it and leaves `brief examine` a plain per-name count of assembled notes:
no bands, no corpus denominator, no confidence. One banded map, one inspection
count. Otherwise this feature ships two per-name coverage computations with
different denominators.

**05 follows §7.8, not its own body, and owes the spec one clause.** #490
restates D3 as it read before the measurement; the contract is §7.8, which
absorbed it. One real gap survives. Contested can fire on path 2, a Gather
disagreement at a touched name, while the whitelist rule in
`_counter_position_candidates` finds nothing, and the empty-candidates guard then
writes `one_sided_reason: "none of the underlying grounds chunks resolved in the
vault"`. That is false: they resolved, and simply carry no opposing position. The
issue's whitelist is right and §7.8's is a clause short, since the Gather
finding's own member notes belong on it. 05's PR adds the clause and re-derives
that reason.

**Contested stays a boolean.** The measurement caps recall at 0.35–0.59 and
argues for a graded disclosure. Two contracts block on the boolean, the
counter-position validator and #405's one-sided outcome, and grading it would not
recover a disagreement the predicate never saw. The cap is a stated limit of the
validator: it requires a counter-position only where the predicate sees the
disagreement. Recorded here, not reopened.

One adjacent item belongs to neither slice. `usage_report.py`'s display relabel
for the deleted `query_by_polity` tool is dead code, and it goes with 06's
source-usage re-base.

**Found while building 04, and fixed there.** The reader coerced `names`,
`citations` and `arguing_against` with `list(value or [])`, which turned a
bare-string abstention into a list of its own 14 characters: an abstention read
as fourteen one-letter names. It also made an absent key indistinguishable from
a real `[]`. Both break the contract 04 implements, so those three are raw now,
with `None` for absent. Nothing else read them off `ChunkNote`.

**00 ∥ 01 is optional.** 00 writes only `specs/PHASE-B.md`; 01 is a corpus
operation. The one condition is that 01 must not touch §7.12 — 00 already
rewrites it. 00 is a pure `.md` change and may land straight on `main` under the
docs-only gate exception.

- 01 and 02 are LLM-free by construction. 06 is not: its harness is *built and
  tested* against the stub client, but the five smoke runs that set its budgets
  make real calls, and two of its four accuracy numbers are judged.
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
- **The retrieval planner is blind to how good a name resolution was** (found in
  slice 03, filed on #491, 2026-07-30). The loop hands the model back each tool
  call's `result_ids` and nothing else, so `find_names` arrives as bare name
  strings: no `member_count`, no `kind`, no tier. An embedding hit at cosine 0.78
  and an exact match are indistinguishable to it. This is inherited loop design
  from Phase B slice 01, not something the rewiring introduced, and the fix is a
  real design change — §7.6's `result_ids` shape is FIRM, so richer feedback has
  to ride beside the trajectory rather than inside it. Measured mitigation:
  `find_names("Tilly")` returns exactly one hit, not the `C. Tilly 1975`
  fragments, because the alias tier resolves before the embedding tier runs. So
  the fragmentation half of the risk is narrow; the tier-invisibility half
  stands. Decide it on 06's smoke numbers, not on speculation.
- **The first real `brief examine` run cost more than the plan assumed, and #505
  says why** (2026-07-30, slice 04's evidence run, `config/briefs/sim/P3-01.yaml`).
  One `get_name` returned 962 members, the trajectory re-sent that id list for
  twelve turns, and the prompt went from 4,172 to 72,000 characters and stayed
  there: 21 calls and 374,083 prompt tokens for one examine, most of it the same
  list. The loop also ran to 20 of 20 turns without converging, so slice 03's
  "provisional headroom" hit its ceiling on its first real brief rather than
  settling under it. The assembled evidence set came out at **964 notes**, which
  is what would reach a synthesis prompt. Decide the shape of the fix on 06's
  smoke numbers; the measurement is on #505 so it is not relearned.
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
