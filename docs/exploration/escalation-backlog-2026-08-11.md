# The name-merge escalation backlog: is it worth resolving?

Two measurement passes run on 2026-08-11 against the 34-source corpus, to decide
whether issue #730 — an operator console screen for resolving name-merge
escalations — should be built. Both are disk reads only: **zero model API calls,
nothing paid for.**

The passes are reproduced below as they were posted to
[#730](https://github.com/Muhanad-husn/axial/issues/730). The scripts were ad
hoc and are not committed: they carried absolute founder paths, and the method
is stated in full in each pass, which is what a re-run needs.

## Verdict: #730 is not worth building as scoped

Resolving the entire backlog by hand would touch **69 of the vault's 329 usable
pages (21%)** and move **under 1,000 of 6,860 notes**, concentrated in 15–20
surfaces already at the top of any ranked list. Pass 1 killed the issue's own
premise — that an operator could state a rule once and clear a class of the
9,714 — by showing nothing safe clears more than 9.1%. Pass 2 then showed the
90.9% residual was never worth clearing.

This is the same shape #695 established: **a surface changing group is not its
notes moving.** There, 13.3% self-disagreement moved 0.4% of the material. Here,
99.0% of live escalated surfaces sit on a page with fewer than 30 notes, and
60.7% sit on a page with one note or fewer — below the usable band, where
rearranging them changes nothing anyone reads.

The hand-read of the top 20 is the part that settles it. Not one goes from
useless to useful. Every one is already usable or already a hub, and the
genuinely hard cases — Faysal I versus Faysal II, "the South" as the US South or
the Global South or a compass direction — are exactly where an automated batch
rule would be actively dangerous.

## What survived

- **#735** — the reported backlog is inflated. `axial names escalations` joins
  every record in a permanent, content-keyed decision log to a rebuilt
  inventory, and a miss is neither an error nor a filter. 1,831 of 9,714 entries
  (18.8%) are about surface forms the corpus no longer has.
- **A narrow tool, if ever** — scoped to the ~50–70 load-bearing pages pass 2
  identifies, not a general queue or a ranked slice. It needs a product
  justification beyond anything measured here, since most of what it would show
  a human is genuine ambiguity to referee, not a backlog to clear.
- **The quarantine half is dead.** `quarantine_reason` does not exist in the
  code or the data — it is a name inherited from the retired tag pass. The live
  equivalent is 18 of 6,860 notes (0.26%), read only as a scalar gate, with no
  itemized list and no write path.

## A correction between the two passes

Pass 1 reported 3,000 of 9,714 entries (30.9%) as stale, and #735's body was
filed quoting it. That figure counts every entry in a batch where **any** member
is missing from the inventory. Pass 2 established the entry-level number — the
escalated surface itself is gone — as **1,831 (18.8%)**, leaving a live backlog
of 7,883. Both are real and answer different questions; the entry-level one is
what the command reports, so it is the one #735 fixes. Pass 1's own composition
breakdown corroborates it: 1,832 entries with no kind at all, which is what an
inventory miss produces.

One further claim of pass 1's did not survive contact: the `Party`/`party` and
`ISIS`/`Isis` case-fold cohort was described as stale rows a re-run drops for
free. Measured directly, both spellings are still live surfaces with a resolved
kind. What #463 killed is the batch being posed again, not the surfaces
themselves — so those 305 entries do not come off through the staleness rule.

---

## Pass 1 — clearability

Read against `data/names/merge_decisions.jsonl` joined to `data/names/inventory.jsonl` and `data/names/alias_map.json` in the main checkout, 2026-08-11. No model calls; string-level measurement only. Script: ad hoc, not committed (per the task's rules).

### The number, confirmed

`uv run axial names escalations --json` still returns **9,714** escalated surface entries, unchanged from the issue's 2026-08-10 count. That is 4,730 decision batches (a batch = one HDBSCAN/candidate cluster the merge model was asked about) touching 8,405 distinct surface forms — some surfaces escalate in more than one batch, per `list_escalations`' own docstring.

### Composition

- **By kind** (off the inventory join): person 34.2% (3,319), institution/group 17.6% (1,706), concept 11.5% (1,115), work 6.4% (618), place 5.2% (504), event 3.7% (362), movement/religion 1.6%, period 0.9%. **18.9% (1,832) have no kind at all** — their surface string isn't in the current inventory (see staleness, below).
- **Batch size**: 2-member batches 4,864 (50.1% of all batches, escalated or not — but escalation is concentrated here too), 3-member 2,309, 4-member 1,235, 5+-member 1,306 (13.4%).
- **Escalation shape**: 79.0% (7,675) are whole-batch refusals — the model placed zero members. 21.0% (2,039) are partial — the model placed some members and refused only the rest.
- **Staleness / pin drift**: **1,528 of 4,730 batches (32.3%), covering 3,000 of 9,714 entries (30.9%), reference at least one surface form that no longer exists in the current inventory at all.** `data/names/inventory.jsonl` was last written 2026-08-05 21:44; every affected batch was decided before that. A concrete example: 151 batches / 305 entries (3.1%) are pairs that differ *only* by letter case (`Party`/`party`, `ISIS`/`Isis`) — all decided 2026-07-28T20:10–21:27Z, which is *before* commit `5d14c38` (#463, "fold case, whitespace and punctuation upstream," merged 2026-07-29T00:30Z) started folding exactly these pairs before they ever reach the model. These are not live escalations a rule needs to clear — they are stale log rows a re-run already resolves for free, without ever asking the model again.
- **Batch size kills rule-clearability**: of batches a string rule (below) can clear, 20.0% of 2-member batches clear, 6.2% of 3-member, 2.0% of 4-member, 0.7% of 5+-member. The backlog's hard core sits in the bigger, messier clusters no normalization rule touches.

### Candidate batch rules, scored and spot-checked

Each rule: does normalizing every member of a batch to one key collapse it to a single entity? If yes, every escalated surface in that batch is "cleared." Spot-check = I read a random sample of the actual cleared pairs and judged them by hand (n=25 unless noted).

| rule | batches | entries cleared | % of 9,714 | spot-check verdict |
|---|---|---|---|---|
| `citation_year_suffix` (strip trailing `(YYYY)`/`, YYYY`) | 251 | 508 | 5.2% | ~21/25 (84%) correct. Failure mode: common-surname collision — `Anderson 1986`/`Anderson, 1987` merges two citations that could be different Andersons; the corpus has multiple distinct Anderson clusters elsewhere. |
| `leading_article` (strip leading the/a/an) | 25 | 54 | 0.6% | ~20/25 (80%) correct. Failure mode: generic-vs-proper clash — `Constitution`/`the Constitution` can mean different countries' constitutions across sources. |
| `translit_diacritic_apostrophe` | 11 | 20 | 0.2% | ~9/10 correct. One clear miss: `Fay`/`fay'` — an English name collided with an unrelated Arabic legal term only because stripping the apostrophe made them equal. |
| `singular_plural` | 67 | 136 | 1.4% | ~10–12/25 (40–48%) correct. **Not safe to auto-merge**: majority failure is proper-noun-singular vs generic-plural — `Red Army`/`Red armies`, `Silicon Valley`/`Silicon Valleys`, `Moro`/`Moros` are not the same referent. |
| `initials_vs_full` | 71 | 143 | 1.5% | ~10/25 (40%) correct. **The rule itself is unreliable as specified** — it also collapses any two unrelated "Word Year"/"Word Word" pairs sharing a first letter: `Ebel 1988`/`Egnal 1988`, `task compensation`/`time-effort compensation` are flatly different things caught by the same first-letter coincidence that also catches genuine `G. Smith`/`Greg Smith` cases. |
| `case_fold_only` (case difference only) | 151 | 305 | 3.1% | ~23/25 (92%) correct, but **this is a purge, not a rule** — see staleness above. One genuine miss even here: `ISIS`/`Isis` (militant group vs the goddess). |

Union of all six: 576 batches / **1,166 entries (12.0%)**.

**Defensible subset** — the three rules whose spot-check accuracy held up (`citation_year_suffix` + `leading_article` + `translit_diacritic_apostrophe`), plus purging the stale case-fold batches instead of trying to "clear" them: **287 batches / 582 entries (6.0%) from rules, plus 305 entries (3.1%) that a plain re-run after #463 already drops — 887 of 9,714 (9.1%) total.** `singular_plural` and `initials_vs_full` are excluded: both clear over 100 entries each but are wrong on more than half of what they'd touch, which is worse than leaving them for a human per the issue's own bar.

### What's left

Even in the best case measured here, **8,827 of 9,714 (90.9%) still need a human.** That is not a smaller problem than the issue started with — a one-decision-per-row queue over 8,827 rows is still ~2.5 hours of clicking.

A ranked slice is real, though. Of the 4,154 residual batches (8,548 entries) no rule clears, ranking by inventory occurrence-count (chunk mentions, the best available proxy for notes moved) concentrates sharply: **the top 500 residual batches (12% of them) carry 56.8% of the residual's total occurrence-weight**, covering 981 of 8,548 entries by raw count. The single heaviest case is `Second Syria`/`Syria` (1,304 occurrences across 25 sources) — and it's genuinely ambiguous, not a rule-clearing miss (same for `World War`/`World War I`, `Middle East`/`Middle Eastern`, `Islam`/`Islamic` further down the list): the top of a weight-ranked queue is exactly what most needs a human, not what a smarter rule would also catch. 500 human decisions on a weight-ranked list is a real product; 8,548 unranked rows is not.

### Quarantine half

`quarantine_reason` does not exist anywhere in `src/` or the current `data/` tree — it's a name inherited from the retired tag pass (`pipeline_ready.py`'s own docstring calls the interrogation checkpoint's `failure_reason`/`skip_reason` "the direct successor of the tag pass's own `quarantine_reason` records"). The live equivalent lives inside each source's per-chunk answers checkpoint (`data/answers/<source_id>.jsonl`): across all 34 checkpointed sources, 18 of 6,860 notes (0.26%) carry no `answers` key. `pipeline_ready.py` reads that fraction only as a scalar PASS/FAIL gate on a single canary run — there is no cross-corpus itemized list, no chunk-level "Drop/Keep" state, and no write path. Building the mockup's buttons means inventing that surface from nothing, not surfacing something that already exists.

**Recommendation: drop quarantine from #730's scope**, per the issue's own opt-out clause — the measured rate (0.26%) doesn't justify building a new backing surface for it right now, and the decisions screen should ship on the escalations half alone: a weight-ranked slice over the ~90% residual, not a rule-clearing UI, since no rule measured here clears enough of the backlog to change the screen's shape.


---

## Pass 2 — payoff


Read against `data/names/merge_decisions.jsonl`, `data/names/inventory.jsonl`, `data/names/alias_map.json` and `data/answers/*.jsonl` in the main checkout, 2026-08-11. Zero model calls, disk reads only. Scripts: ad hoc under `scratchpad/`, not committed (per the task's rules). All files unchanged since the first pass (`inventory.jsonl`/`alias_map.json` last written 2026-08-05).

### 1. The corrected denominator — and a discrepancy with #735's own number

`uv run axial names escalations --json` still returns **9,714** entries / **8,405** distinct surfaces / **4,730** batches, unchanged.

Joining each *escalated surface itself* to the inventory — exactly the join `list_escalations` performs per #735's own quoted source (`kind, chunk_ids = inventory.get(surface_form, (None, ()))`) — gives:

- **Live: 7,883 entries (81.2%), 6,651 distinct surfaces (79.1% of 8,405), across 3,508 of 4,730 batches.**
- **Stale (the escalated surface itself is gone from `inventory.jsonl`): 1,831 entries (18.8%), 1,754 distinct surfaces, across 1,222 of 4,730 batches (25.8%).** Cross-checked directly against `axial names escalations --json`: 1,831 entries have empty `source_ids` (one further entry has `kind: null` but *is* live — its inventory row itself carries no kind — so the CLI's raw `(no kind)` count of 1,832 overstates staleness by exactly one).

This is **not** #735's number. #735 reports 3,000/9,714 (30.9%) and 1,528/4,730 batches (32.3%). I reproduced that number exactly, but only under a looser definition: a batch counts as fully stale, and *every* escalated entry in it counts as stale, if **any** member of the batch — escalated *or already-placed* — is missing from the inventory, not just the escalated surface itself. Confirmed by direct computation: that definition gives 1,528 batches / 3,000 entries, matching #735 to the entry.

The two numbers answer different questions. #735's is "how much of the decision log's *context* has decayed" — a real, useful signal for #735's own scope (report staleness in the CLI). Mine is "how much of what an operator would actually be asked to resolve today is about a surface that still exists" — the one that matters for sizing #730's UI, since the CLI only ever renders `(no kind)` for the 1,831/1,832 count, not the 3,000. **I use the surface-level 81.2%/7,883/6,651 numbers throughout below.** Both are reported here so nothing is hidden.

### 2. Weight in notes — how much is "in play" at all

Total inventory: 58,282 surfaces, 138,163 occurrence mentions, 6,511 distinct chunks carrying at least one name mention. Corpus total: **6,860 notes** (`data/answers/*.jsonl`, 35 checkpointed sources) — so 94.9% of all notes mention some name.

The 6,651 live escalated surfaces, unioned, touch **5,176 distinct chunks — 75.4% of the corpus's 6,860 notes (79.5% of the 6,511 name-bearing ones).**

**This number is a trap and I'm flagging it as one.** It is a union across 6,651 surfaces, most of which mention almost nothing (median 1 occurrence, mean 2.4, p90 = 3). It says "some escalated surface appears somewhere in three-quarters of the corpus's notes" — not that resolving anything changes what's on the page for those notes. Per #695: a surface changing is not its notes moving. This is the surface-count version of that same trap, one level up.

### 3. Weight in what materializes — does it reach a usable page

An escalated surface never appears in a decision's own `nodes` (confirmed by reading `parse_merge_response`/`build_alias_map_nodes`, `src/axial/merge_names.py:957-1264`), so an escalated surface stays its own singleton alias-map node unless an unrelated seed/case-fold already merged it. Checked against the live 47,584-node `alias_map.json`:

- **99.0% (6,582 of 6,651) of live escalated surfaces sit on a page with fewer than 30 notes today.** 60.7% (4,037) sit on a page with ≤1 note — effectively dead.
- Only **43 (0.6%)** are already, on their own, in the usable band (30–200 notes, 5+ sources); 9 (0.1%) are already hubs (>200 notes); 17 (0.3%) are mid-size but under 5 sources.
- 507 (7.6%) are already the canonical of a page with other members, via a seed or case-fold path unrelated to this escalation (e.g. `Ba'th` already lives on the 288-note `Ba'th Party` page via the polity seed, despite escalating against `Ba'th dam` in its own HDBSCAN batch).

Corpus-wide: 329 of 47,584 pages (0.69%) are in the usable band at all; 83.0% of all pages draw from exactly one source (matches the 84% figure from the pre-#514 memory, within drift).

### 4. The counterfactual — what a full human resolution would buy

**Method** (stated plainly since this needs one): for each live escalated surface, take every co-member it was ever proposed with across all its escalation batches, keep the co-members that are themselves live, and pick the one whose *current* page has the most notes — the most generous plausible resolution target, not a verified-correct one (no model call can verify "correct" here). Simulate merging the escalated surface's own chunks into that page.

- **335 of 6,651 (5.0%) have no live co-member at all** — the batch's only other members are themselves stale. No target is measurable without a model call; flagged as a gap, not filled in.
- Of the remaining 6,316: **76 escalated surfaces (1.1%) target a page already in the usable band** — 50 distinct pages, gaining 719 note-chunks combined.
- A further **19 (0.3%) would push a currently-small target page across the threshold into the usable band by itself** (e.g. `Jackson` → `Robert H. Jackson` 16→41 notes; `New York` co-merging `New York City` 5→160).
- **6,221 (93.5%) fold two small pages together (still under 30 notes) or land on a page that's already an oversized hub (12 cases)** — no reader-facing change either way.

**Combined: 69 of the vault's 329 usable pages (21.0%) would be touched by a full resolution, moving well under 1,000 of the corpus's 6,860 notes (≈10-12%) — concentrated almost entirely in the ~15-20 heaviest surfaces**, the same ones the ranked-weight list already surfaces at the top. The other ~6,600 live escalations move at most a handful of notes each (median own-footprint: 1 note) between pages nobody was going to read regardless of which one it's on.

### 5. Hand-read of the top 20 (by live-escalated occurrence weight)

| surface (kind) | count | proposed with | own current page | verdict |
|---|---|---|---|---|
| `Syria` (place) | 1,303 | `Second Syria` | Syria, 1,298 notes/25 src (hub) | Genuinely ambiguous (region vs. state); already a hub — resolving doesn't unlock anything, hub stays a hub |
| `World War I` (event) | 524 | `World War` | 522/20 (hub) | Same shape as above |
| `Asad` (person) | 160 | `Asads` | 161/7 (usable) | Family vs. individual; already usable regardless |
| `New York` (place) | 157 | City/State/`N.Y.`/`York` | 157/26 (usable) | Real but low-stakes; already usable |
| `Ba'th` (movement) | 147 | `Ba'th dam` | Ba'th Party, 288/13 (hub, via unrelated seed) | Correctly refused — party vs. a physical dam are different entities; irrelevant either way since `Ba'th` already lives on a healthy page |
| `modernity` (period) | 86 | `Modernity` | 90/10 (usable) | Case variant, plausible merge, stays usable either way |
| `South` (place) | 78 | `New South`/`south`/`the South`/`the extreme south` | 85/12 (usable) | Highly polysemous (US South / Global South / compass point) — correctly a human call |
| `Faysal` (person) | 74 | `King Faysal`/`King Faysal II`/`King Fayṣal` | 81/5 (usable) | Real risk: Faysal I and Faysal II are different kings — a wrong auto-merge here would conflate two monarchs |
| `IMF` (institution) | 71 | `IMF (2010)` | International Monetary Fund, 94/11 (usable) | Correct-looking merge, low material stakes |
| `Oxford` (place) | 56 | `Oxford University`/`University of Oxford` | 56/18 (usable) | City vs. institution — correctly distinguished by kind already |

(Remaining 10 of the top 20 — `The Dark Side of Democracy`, `Somaliland`/`British Somaliland`, `North`, `Parliament`, `Korea`, `Roosevelt`, `UNTAET`, `Smith`, `Bryant`, `High Commission` — follow the identical pattern: either genuinely ambiguous items correctly left to a human, or items whose target page is already usable/hub so resolution changes nothing a reader would notice.)

**None of the top 20 is a page that goes from useless to useful.** Every one is already sitting in the usable band or already a hub; the escalation is either a real judgment call (Faysal I/II, South) where an automated batch rule would be actively dangerous, or cosmetically low-stakes. This confirms the first pass's own read of the ranked slice, now with the actual pages behind the numbers: a weight-ranked queue mostly surfaces decisions that don't move material into or out of readability, it just rearranges hubs.

### Verdict

Resolving the *entire* 8,827-entry residual (or even all 6,651 live, non-stale escalations) would touch at most **~21% of the vault's usable pages, moving under 1,000 of 6,860 notes, concentrated in ~15-20 surfaces already visible at the top of the existing ranked list** — the same shape #695 already established (13.3% self-disagreement moved 0.4% of the material). **#730 is not worth building as scoped.** The measurable return doesn't justify a batch-resolution UI, a reversible write path, and re-materialize wiring. If anything survives from this: (a) land #735 so the CLI stops reporting an inflated number, and (b) if a decisions surface is ever built, scope it to the ~50-70 pages this pass identifies as load-bearing, not a general queue or ranked slice over the full backlog — and even that narrow version needs a real product justification beyond what's measured here, since the top 20 shows it would mostly be refereeing genuine ambiguity (Faysal I vs II, "the South"), not clearing a backlog.

