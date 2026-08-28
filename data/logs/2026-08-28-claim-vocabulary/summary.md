# The claim column, assigned against its committed scheme

**Run:** 2026-08-28, issue #826 (positions-not-names, slice 01). Executed in the
main checkout `D:/axial` on `main` at `a7fff30`, pointed at the branch's scheme
with `--scheme-path D:/axial-wt/826/config/vocabulary.yaml`. The branch
`feat/positions-not-names/01-claim-vocabulary-committed` adds configuration and
tests only — `src/` is byte-identical between the two — so the code that ran is
the code the branch ships. `data/` does not exist in a worktree, which is why
the run happens here and not there.

`AXIAL_SECRETS_PATH=secrets/secrets.toml` on every command. The ambient value in
this shell is `/secrets/secrets.toml`, the container path, and every model call
dies without the override.

## The scheme

Nine categories, version `2026-08-28-claim-v1`, depth 1. Drafted by
`vocabulary examine` on 2026-08-27 — the run is
`../2026-08-27-vocabulary-categorise-v2/console-claim.log`, ten categories over a
400-value propose sample, scored on a disjoint 400 the model had never seen: 99.5%
assigned, largest category 21.2%, two-model agreement 77.0%, 9 of 10 categories
reaching 5 members and all 9 of those spanning 2+ sources.

**No new drafting run was paid for in this slice.** The 2026-08-27 pass already
covered `claim`; the operational step was the founder's edit of what it produced.

The founder approved the draft on 2026-08-28 with one edit: the tenth category,
"Acknowledgment or credit statement" (1 member, 1 source), is below the 5-member
bar and is dropped. Its material is folded into
`bibliographic-source-note-or-formal-description`, whose gloss gains a clause
naming acknowledgments — folded rather than deleted so those values land in a
category instead of becoming refusals.

## The build

```
uv run axial vocabulary build --columns claim \
  --scheme-path D:/axial-wt/826/config/vocabulary.yaml
```

6,697 answered values, 145 excluded as abstention or empty. **6,671 assigned,
26 refused ("none"), 0 out-of-scheme, 0 unanswered.** 68 calls,
**$0.0839**, `deepseek/deepseek-v4-flash`. Scheme `2026-08-28-claim-v1`, answers
pin `d5517979069efe79`.

**Coverage 99.6%, against the held-out estimate of 99.5%.** The sample predicted
this one almost exactly.

Per-call elapsed summed to 1,451.2s over 68 calls, 10.6s to 86.5s each. **Wall
clock was not captured on this run**, so no effective-concurrency figure is
reported for it — the number is not reconstructible after the fact and is not
guessed at here.

### Every category, by member count

| category | members | sources | share of assigned |
|---|---|---|---|
| causal argument about state formation or state power | 1,664 | 33 | 24.9% |
| empirical finding or observation without causal claim | 1,224 | 34 | 18.3% |
| causal argument about violence, war, or conflict dynamics | 913 | 32 | 13.7% |
| characterization of a regime, movement, or political system | 776 | 34 | 11.6% |
| bibliographic, source note, or formal description of the text | 673 | 35 | 10.1% |
| causal argument about nationalism, identity, or nation-building | 517 | 23 | 7.8% |
| critique of existing theories or concepts | 458 | 33 | 6.9% |
| methodological preconditions | 288 | 30 | 4.3% |
| comparative or typological classification | 158 | 31 | 2.4% |

All nine clear 5 members and 2 sources by a wide margin; the narrowest spans 23
sources of 35. The largest holds **24.9%**, against the 21.2% the held-out sample
predicted — bigger than the sample suggested, the same direction the `mechanism`
column moved (8.0% predicted, 11.7% actual), and still well under the shares that
failed four other columns in the drafting report.

## The resume clause

A second run under the same scheme version and the same answers pin:

```
REUSED: the scheme version and the answers pin are both unchanged
-- 0 model call(s), nothing re-assigned
```

**2.1 seconds, zero calls.** `assignments.jsonl` is byte-identical by md5
(`ea98c09699cb6c9ab7730f572d4da5ec` before and after) and its mtime did not move —
the file was not rewritten, not even with identical content.

## What this hands to slice 02, and the one thing to watch

`data/vocabulary/claim/` now holds the outer grouping axis the re-formed map is
built on. #827 reads it.

The axis mixes two kinds of category and this was committed deliberately. Six are
*kind of claim* — empirical finding, critique, methodological precondition,
classification, characterization, bibliographic. Three are *topic of claim* —
state formation, violence, nationalism. A passage making a causal argument about
state formation qualifies under both readings, and the model picks one, so the
mixture decides which passages get read together. **The three topical categories
hold 3,094 of 6,671 assigned values, 46.4%.**

Slice 02's cross-tab measures exactly this, offline and free. That is why the
mixture was committed rather than hand-corrected now: rewriting the axis on
argument is research, and the measurement is a run away.

## Files

- `console.log` — the build's raw output, verbatim.
- `console-resume.log` — the second run's output.
- `run.jsonl` — one record per category plus two run records. **Derived from
  `console.log` after the run, not journalled during it**; each record says so.

## Corrections after review, 2026-08-28

Two figures above were quoted the way the committed config first quoted them,
and both were corrected in `d385af9` after the verifier caught them:

- The drafting run's **77.0% two-model agreement was measured on a 100-value
  subsample** of the held-out 400, not on the 400. Wherever this log says 77.0%,
  read it with n=100.
- **99.5% assignment and 21.2% largest share were measured on the ten-category
  draft**, before the founder's fold. The nine categories actually committed
  have never been scored on held-out data. The fold moved one category of 398,
  so the difference should be small — but it was not measured, and the
  comparison of 99.6% actual against "99.5% predicted" above is therefore
  against a slightly different scheme than the one that ran.

The verifier also found two gloss pairs it could not choose between:
`causal-argument-state-formation-or-power` against
`causal-argument-violence-war-or-conflict` (2,577 assigned values, 38.6%), and
`characterization-of-regime-movement-or-system` against
`empirical-finding-without-causal-claim` (a further 2,000, 30%). Both were left
as committed. Separating them is a scheme edit and a version bump, which
re-asks the column under `--force` at roughly $0.08; #827 measures whether the
ambiguity costs anything first. The 77.0% agreement on 100 is consistent with
this — two models already picked differently about 23 times in 100.
