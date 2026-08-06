# Issue #651 sample: semantic residue resolved against the argument map

2026-08-04. 100 unresolved `arguing_against` targets (seeded, seed=42, out of
5,846 in the live corpus recomputed directly from `data/answers/` and the
name layer -- matches the founder's own re-measured 5,846 exactly), matched
against the argument map's 1,830 positions
(`data/map/297bcfa93d6974b0/positions.jsonl`) with one model call per
target per arm, `deepseek/deepseek-v4-flash`. Code:
`src/axial/argmap/residue.py` on branch `feat/651-semantic-residue`.
No writes to `data/vault/notes.db` -- the live vault was mid-rewrite
(`axial names materialize`) when this ran; unresolved targets were
recomputed from `data/answers/` + `data/names/alias_map.json` directly.

Two process invocations made the 200 calls because the FIRST run (both
arms sequential in one process) was cut short by an external `timeout 300`
wrapper on the driver script at ~137 of 200 calls; the second invocation
resumed from the content-keyed decision log (`decisions.jsonl`) and asked
only the remaining targets -- a live demonstration of the decision log
actually working: zero of the 137 already-decided pairs were re-asked.

## The four numbers

| Metric | Value |
|---|---|
| Resolution rate, **with** section blocking | **11/100 (11.0%)** |
| Resolution rate, **without** section blocking | **19/100 (19.0%)** |
| Resolution rate, **either arm** (union) | 27/100 (27.0%) |
| False-match rate, hand-checked | **3/30 matched pairs (10.0%)** clearly wrong; 6 more borderline (see below) |
| Projected full-pass cost (5,846 targets) | **~$1.10 both arms** (~$0.30 blocked-only, ~$0.80 unblocked-only) |
| Projected full-pass duration, current (sequential) code | **~5.9 hours both arms** (~2.9h/arm) |
| Projected full-pass duration, if threaded like `argmap.build.run_extraction` | **~18 minutes both arms** (~9 min/arm, extrapolated from measured mean 1.81s/call and that module's own ~20x speedup at 20 workers) |

## Section blocking: measured, not assumed

Blocking and no-blocking resolved **mostly different targets, not a nested
subset**:

| | count |
|---|---|
| Resolved by blocked arm | 11 |
| Resolved by unblocked arm | 19 |
| Resolved by **both** | 3 |
| Resolved by blocked **only** | 8 |
| Resolved by unblocked **only** | 16 |

Unblocked resolves substantially more overall (19 vs 11) -- the founder's
own worry, stated on the issue, is confirmed: most section buckets are tiny
(median 1 position across the full corpus; mean 7.7 in this particular
100-target sample) because a position is a merged argument spanning many
books' worth of member notes and rarely shares an exact section TITLE with
more than a couple of others. A tiny bucket often does not contain the
target's true match at all.

But blocking is not simply strictly worse: **8 of its 11 hits are targets
the unblocked arm's own top-20-by-embedding-similarity cutoff missed
entirely** -- cases where the true match was not one of the 20 nearest by
raw cosine similarity over the full 1,830-position map, but WAS present in
the section's own (much smaller) bucket, so the model saw it without
competing against 1,829 distractors. Section blocking earns a real, if
narrow, place: not as a replacement for a full-map search, but as a
second, cheap pass that recovers matches the embedding funnel throws away.
Whether that recovery is worth doubling the pass's cost is a judgment call,
not a further measurement this sample can settle.

## False-match rate: hand-checked, all 30 matched pairs

Every `(target, position)` pair either arm returned a match for (30 pairs,
27 distinct targets -- some matched in both arms) was read by hand: the
free-text target and the position's own `argument` sentence, both quoted in
`matches_for_hand_check.json`.

**3 clearly wrong (10.0% of the 30 matched pairs):**

1. TARGET "IPCC 'business as usual' (BAU) do-nothing strategy" -> matched
   position: "The privatization of Torah and Ameriyah was conducted via
   tender requiring investors to publicly announce intentions to buy
   shares..." -- completely unrelated (climate policy vs. an Egyptian
   privatization tender). A clear model error, not a borderline call.
2. TARGET "sociological focus on economic and cultural forces... in
   generating inequalities" -> matched position: "Marxist class analysis
   yields powerful insights into collective action... rather than as sui
   generis events." -- topically adjacent (both class/inequality debates)
   but not the same claim; the position is about explaining collective
   action, not about which forces generate inequality.
3. TARGET "the assertion that the 1970s downturn was a global crisis" ->
   matched position: "The Great Depression was not a single global
   crisis... making the term itself ethnocentric." -- same ARGUMENT SHAPE
   ("X wasn't really global, it was uneven") applied to the wrong
   historical episode (1930s Depression, not the 1970s downturn the target
   names). A pattern-matched wrong referent, not a topic miss.

**6 borderline** (not counted as wrong, flagged for honesty): two targets
were bare category labels rather than sentences (`"modernization-
developmental"`, `"utilitarianism"` -- a corpus quirk in how some notes
answered `arguing_against`, unrelated to this resolver) matched to
positions that plausibly fit the label but could not be checked against a
specific claim; two matches were directionally right but pitched at a
looser grain than the target ("misunderstandings of Gellner's legacy" ->
a position stating one specific inadequacy critique of Gellner;
"Niall Ferguson's pro-imperial panegyrics" -> a position about imperial
ideology generally, not Ferguson's argument specifically); one match
("surveys that force mutually exclusive identity choices" -> a position
about surveys creating the reality they measure) shares the topic and the
critique family but not the identical claim; one match (Nasuh Babil's
"separatist rebels" framing -> a position about separatist rhetoric
constructing state authority) is a reasonable but general topical fit
rather than a precise rebuttal.

**Two matches are self-referential**, worth naming though not wrong: the
target and its matched position are drawn from the *same* passage (the
note states an opposing view and then, in the same breath, the claim the
argument map extracted from that exact passage) -- e.g. "earlier
descriptive writings on Shariati that lacked systematic critical
evaluation" matched a position built from the same `bayat-2017` chunk. This
is a real, correct match, but it is not the kind of cross-source
opposition edge #651 is chasing; a full pass should expect a real share of
its "resolved" count to look like this.

**21 of 30 (70%) are clean, direct, correct matches** -- several exactly the
kind of case no relational join could ever reach: "the view that fascists
were sadists, psychopaths, or had a rag-bag of half-understood dogmas"
correctly matched to a position about Milgram's obedience experiments
disproving that extreme brutality needs extreme personalities, sharing not
one content word.

## Cost and timing detail

Both arms together: 200 calls, 131,709 prompt tokens, 1,295 completion
tokens, **$0.0188 total** (well under the $2 approval ceiling; the
estimate made before spending, from local prompt-length measurement, was
$0.026 -- the real run came in slightly under). Mean call latency 1.81s.
`CANDIDATE_TOP_K=20` keeps the unblocked arm's prompts far cheaper than an
unfiltered full-map listing would be: average unblocked prompt was ~5,100
characters (20 candidates), not the ~365,000 characters the raw 1,830-
position map would run to.

`run_residue_sample`'s call loop is currently sequential (matches this
slice's size -- a 100-target calibration run does not need a worker pool).
A full pass over 5,846 targets at the measured 1.81s/call would take ~2.9
hours per arm run serially; threading it the same way
`axial.argmap.build.run_extraction` already does (a `ThreadPoolExecutor`
with one collecting thread for checkpoint writes, ~20 workers) would bring
that to an estimated ~9 minutes per arm, matching the ~20x speedup that
module measured on the real corpus. That change is mechanical, not a
redesign, if a full pass is approved.

## Founder's own read

Both arms are cheap and fast enough that cost is not the deciding factor
between them. The real question is whether ~$0.80 (unblocked) buys enough
more coverage (19% vs 11%) to skip blocking, or whether blocking's 8
extra, blocking-only hits are worth the ~$0.30 marginal cost of running
both arms on every target. Given blocking and no-blocking resolve mostly
disjoint targets, running BOTH and taking the union (27%) is the
best-measured option here, not a compromise between them -- at ~$1.10 for
the whole 5,846-target residue, cost does not argue against it.

## What this sample does not do

No edge was written into `data/vault/notes.db` or any store table -- #651's
own scoping keeps the persistence step out of this dispatch.
`resolve_target`'s decision record already carries `chunk_id`, `target`,
and `matches` (position ids), which is everything a materialize-time write
of a `note_arguing_against.resolved_position_id`-shaped column would need;
that write is a read of this log plus one `INSERT`, not a new resolution
mechanism.

## Files

- `run.jsonl` -- every `(target, mode)` decision record from this sample.
- `decisions.jsonl` -- the content-keyed decision log itself (the write
  format a full pass would keep appending to).
- `matches_for_hand_check.json` -- the 30 matched pairs quoted above.
- `console.log` -- raw `llm_call_request`/`llm_call_response` lines for
  every call (two process invocations concatenated; see above).
- `sample_summary.json` -- the numeric summary, reconstructed from
  `console.log` (see its own `note` field for why).
