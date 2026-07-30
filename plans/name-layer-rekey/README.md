# Sprint: the name-layer re-key — #500 and #498, paid for once

Two defects sit on the same expensive door. Fixing either one changes what
Gather hashes, which re-keys the name pages and forces a paid re-decide. Run
separately, that bill is paid twice and the corpus pin moves twice. This sprint
runs them as one change with one re-decide and one pin.

- **Slug:** name-layer-rekey
- **Created:** 2026-07-30
- **Status:** proposed, awaiting founder decisions D1 and D3 below
- **Issues:** #500 (the 400-char cap eats `arguing_against`), #498 (151 entities
  split from their own acronym)
- **Project directory:** `.`
- **Blocks:** #493's instrumented eval run, which pins its figures to a vault
  hash. Land this first or those numbers are stale on arrival.

## Why one sprint

`disagreements.jsonl` is keyed by a sha256 of a name's *rendered packets*.

- #500 changes `render_packet`. That re-keys **all 1,910 gathered names**.
- #498 changes which notes are members of ~151 name pages. That re-keys those
  names too.

#500 strictly contains #498's re-key. Land #498 first and its re-decide is free,
because it happens inside the pass #500 already forces. Land them apart and the
second pass re-asks names the first already paid for.

## Measured, not assumed

Every number below is already on the record. Nothing here needs a model call to
verify.

| | |
|---|---:|
| notes carrying an interrogation answer | 6,148 |
| rendered packets over the 400-char cap | 4,241 (69.0%) |
| packets losing `arguing against` entirely | **1,379 (22.4%)** |
| median untruncated packet | 483 chars, against a 400 cap |
| median `claim` length | 245 chars, about half the packet |
| surfaces carrying a parenthesized acronym | 301 |
| distinct acronyms among them | 260 |
| **also present as a standalone name node** | **151** |
| names Gather has decided | 1,910, over 602 batch + 10 merge calls |
| pages carrying a disagreement section | 492 (after #497's union) |

The two defects meet at one field. #490 measured `arguing_against` as the only
clause that separates contested names from uncontested, at 1.9x to 2.4x lift
over a 0.26 base rate, and only when read literally. It is invisible to Gather
in 22.4% of notes. Meanwhile `AANS` and `Autonomous Administration of North and
East Syria` are two pages for one entity, so a caller asking by the acronym
reaches a 1-member fragment and never sees the other notes.

## D1 — how the cap is fixed (founder decision, recommendation attached)

#500 listed three candidates and settled none. A fourth is better than all
three and adds no constant.

**Render the bracket first, and give `claim` whatever is left of the 400.**

Today `render_packet` builds `author (year): claim [position of; arguing
against; position]` and truncates the tail, so the bracket is what dies. The
bracket fields are short and bounded by construction; `claim` is the only field
that runs long. Reserving the bracket and truncating `claim` into the remainder
means every bracket field survives, `MEMBER_PACKET_CHARS` stays a single
constant, and `GATHER_PACKET_CHAR_BUDGET // MEMBER_PACKET_CHARS` stays an exact
arithmetic guarantee. No per-field table, so no tripwire.

The one degenerate case is a bracket that alone exceeds the cap. That falls back
to today's tail truncation, which introduces nothing new, and its frequency is
measured rather than assumed.

This also retires the frame-0.2 trade recorded in `gather.py`: `position` is
currently truncated away in 62.5% of new-format packets to protect
`arguing_against`. Under D1 both survive and the field-order comment stops being
load-bearing.

Rejected, with reasons: raising the cap buys fewer members per batch and more
cost per name for the same underlying problem; a per-field budget is a table of
constants; truncating `claim` to a fixed number is D1 with a second constant
bolted on for no gain.

## D2 — the acronym becomes a key, through the evidence check

Not a string fold. `fold_groups` unions case, whitespace and punctuation
variants straight into the alias map with no model call, and that is right for
those, because they cannot be different entities. An acronym can be: `ABC`
resolves to `Al-Ahram Beverages Company` in this corpus and need not everywhere.

So the parenthesized acronym enters the **candidate** stream and the 151 pairs
go through the merge's existing evidence check, which already joins each surface
to the source books it appears in. `merge_decisions.jsonl` is content-keyed on
rendered members, so these are new batches: existing decisions are reused
untouched and only the new pairs are asked. On the merge pass's own measured
economics, a full pass is about $0.55, so 151 to 260 extra batches is noise.

151 is an upper bound on the folds, not a prediction. The decided count and the
pairs that stay split, with the reason, are reported rather than assumed to be
zero.

## D3 — the re-decide, and what it actually costs (founder decision)

**The money is unmeasured.** The corpus pass ran 602 batch calls plus 10 merge
calls over 1,910 names and its cost was never written to the run log. Gather
carries no `model_by_pass` entry, so it runs at whatever `llm_tier` names, with
reasoning on. Slice 03 measures cost per call on a bounded run and scales it by
602 before the full pass is authorized. Note that `--limit` takes the
alphabetical head and does not sample: it gives a cost-per-call figure, never a
yield figure.

**The risk is not the money, it is the re-roll.** Gather's findings are 53%
reproducible per item. When PR #474 relabelled one book's author, a cosmetic
one-word change, 93 of the 176 names with a finding in either pass reversed: 48
lost, 45 gained, 83 rewritten. The judgment is underdetermined, so any input
change re-rolls it.

#497 removed half of that exposure. The layer is now monotone against nulls: the
write loop takes the newest **non-null** record per canonical name, so a
re-decide that returns null cannot clear an existing finding. The 48-lost column
is closed.

It is **not** monotone against rewrites. A new non-null finding replaces the old
text on the page, and roughly 83 of 176 is the measured rewrite rate. So this
sprint will silently rewrite the wording of a few dozen live findings, and no
single pass can separate that from an improvement. The mitigation is disclosure,
not prevention: diff the entries that flipped and report the count, per the #472
lesson. Do not read the marginal non-null rate as evidence the change was good.

## Slices

**01 — the bracket survives the cap** (#500, no model calls). Change
`render_packet` per D1. Re-measure over all 6,148 notes: share losing
`arguing_against`, share losing `position`, share hitting the degenerate
bracket-over-cap path, before and after. Gather is **not** run in this slice.

**02 — the acronym becomes a lookup key** (#498). ✅ **Done, PR #502, 2026-07-30.**

Three parts shipped, not one: the shape test, a **refusal** when more than one
surface carries the same acronym, and matching on the **upstream fold**. The last
two exist only because real-corpus runs produced defects the fixtures could not
see, and both are worth remembering, since either would have shipped a wrong
corpus on a green suite:

- Without the refusal, an acronym node is a hub and the alias-map union chains
  its expansions together with no call ever asked to compare them. Run 1 fused
  `Marxist Social Democratic Federation (SDF)` into `Syrian Democratic Forces`,
  and Rwanda's `CDR` into Lebanon's, and gave `LECS` a paper title as its page
  name. 26 of 165 acronyms carried several expansions; 15 collapsed to one group.
  The evidence check *did* reject `LSE` and `MAD`, which is why the fix is a
  refusal at proposal time and not a better prompt — the failure is the union,
  not the call. Cost: 13 benign hub folds (`GATT`, `USAID`, `YPG`), accepted.
- Without the fold match, the eight most-cited acronyms were proposed and
  silently dropped: `CIA`, `PLO`, `UN`, `USA`, `IRA`, `FLN`, `PFLP`, `SLA`.
  `fold_groups` runs upstream of every candidate family and had already unioned
  each with its dotted form, and only one representative per group reaches the
  families. This hid itself twice because the validation script read the raw
  inventory and reported 139 pairs where the run saw 131.

Measured, three runs, `data/logs/2026-07-30-acronym-merge-498-run3/summary.md`:

| | run 1 | run 2 | run 3 |
|---|---:|---:|---:|
| pairs proposed | 196 | 139 | **140** |
| folded / newly folded | 153 / 143 | 109 / 99 | **117 / 107** |
| still split | 43 | 30 | **23** |
| wrong entity fusions | **2** | 0 | **0** |
| cost, list price | $0.041 | $0.030 | $0.003 |

Name pages 62,821 → **62,704**. The worked case is exact: `AANS` and
`Autonomous Administration of Northeast Syria (AANS)` are both aliases of
`Autonomous Administration of North and East Syria`, one `kind`, three notes.

**The 151 in this plan was never the operative number.** It counted a looser
mixed-case parenthetical shape over the raw inventory; after the upstream fold
the rule sees 140 pairs. Of the 23 still split, 11 are genuine declines (`ABC`
against `Al-Ahram beverages` among them) and **11 are not a judgment at all** —
the model returned a single node and omitted the acronym from its `aliases`, so
it was left unmapped. Filed as #504, since it lives in `parse_merge_response` and
affects every candidate family.

**Materialize was deliberately not run here**, against this slice's original
wording. Rendering the 117 folded pages now and again after slice 03's re-decide
renders them twice, and the first render would carry stale disagreement sections.
Nothing reads the vault before slice 03, so the pages are rendered once, there.
The pin has not moved. The `$0.55` figure below is wrong for this pass by an
order of magnitude: reconcile runs on `deepseek-v4-flash`, and all three runs
together cost **$0.074**.

**03 — one re-decide, one pin.** Bounded cost probe, founder authorizes, then
the full Gather pass. Diff the flipped entries. Re-cut the corpus pin once, whose
vault hash covers the name-layer index per D6. Run log under
`data/logs/2026-07-30-name-layer-rekey/`.

Slice 01 and 02 are independent and can be built in parallel worktrees. Slice 03
needs both merged and runs from the main checkout, since `data/` does not exist
in a worktree.

## Acceptance

- The share of live packets losing `arguing_against` is stated before and after,
  measured over `data/sources/`, not on fixtures.
- The 151 pairs are decided by the evidence check, and the count still split is
  reported with reasons.
- `find_names` by acronym reaches the spelled-out page for every decided pair.
- The re-decide's cost is measured on a bounded run and approved before the full
  pass, and the count of findings whose text changed is reported.
- The pin moves exactly once, and its vault hash changes.

## Out of scope

- The initialism tier for acronyms the corpus never writes, such as `AANES`.
  #498 records it as the smaller half. It helps only strings absent from the
  inventory, while D2 reaches 151 real pages. File it if a brief misses evidence
  because of it.
- Any Gather prompt or model change. A single pass cannot separate an
  improvement from a 53% noise band, and nothing in this sprint needs one.
- The similarity floor. #487 settled it at 0.5 and rejected the fitted window on
  the record.
