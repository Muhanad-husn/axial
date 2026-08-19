# 2026-08-19 — #802 slice 01: the window never cuts the first rotation

Validation of the fix on `feat/802-primary-outside-the-window/01-the-window-never-cuts-the-first-rotation`
(`e2abe2d`). The measurement that motivated it is
`data/logs/2026-08-19-802-tilly-retrieval/`.

## The change

`source_covering_limit` raises a query's `limit` to the distinct source count
when it is smaller, at the three sites that truncate after a per-source
rotation: `find_notes` and both `get_name` paths. Nothing is re-ordered,
nothing is ranked.

## 1. Offline, free: every name page, before and after

`sweep802.py` over the real vault, run once on `main`'s query layer and once on
the branch's, comparing the returned chunk ids page by page.

| | |
|---|---|
| Control pages (at or under the limit), sampled | 400 |
| — **changed in any way** | **0** |
| Over-limit pages | 257 |
| — `total`, the true pre-cap count, changed on | **0** |
| — gained at least one source | **257** |
| — **lost a source that was there before** | **0** |
| — now exactly one note per source | **257 of 257** |
| — old window survives as an exact **prefix** of the new one | **257 of 257** |
| Notes returned across the 257 | 2,570 → 4,159 (**1.62x**) |
| Notes returned across the 400 controls | 761 → 761 |

The prefix property is the one worth reading twice: nothing a query used to
return was dropped, re-ordered, or replaced. The window only grows, and only
where a book was being cut.

`find_notes("Charles Tilly")` at the **default** limit, on the live vault:

```
total=133  returned=20  distinct sources=20
tilly-1978 present: True
  tilly-1978-f908c910464c_110_general_001
    The author argues that the term 'political disturbance' is misleading and
    should be replaced with 'violent event' or 'collective action producing
    violence,' because the former presumes a political context and implies
    abnormality that evidence contradicts.
```

A substantive Tilly claim, not the self-identification notes. Before the fix
this call returned 10 notes from 10 books and none of them his.

## 2. Live retrieval: `axial brief examine` on S-01

The brief behind `data/papers/a1039fad4da31320.md` — "Does Mann's distinction
between infrastructural and despotic power overturn Tilly's war-centred
account, or merely specify its mechanisms?" `examine` runs interrogation and
retrieval and makes **zero synthesis calls**. Console:
`examine-after.txt`.

The fix is visible in the run's own narration:

```
looking for what the corpus says about 'Charles Tilly' -- found 20 passages (of 133 total)
```

Twenty, where every prior run of this brief found ten.

| | before (`ec94042430910584`) | after |
|---|---|---|
| Chunks assembled | 98 | 80 |
| Distinct sources | 10 | **20** |
| `tilly-1978` chunks | **0** | **1** |

The source spread doubled. Assembled count fell, which is a different draw of a
stochastic retrieval loop rather than an effect of this change — the two arms
are one draw each and nothing here separates them.

Retrieval prompt sizes did not blow up: median 45,574 → 55,123 chars, max
89,543 → 89,128. That comparison is against a different brief's console log
(`2026-08-18-784-cost-per-ask`), so read it as indicative, not measured.

## 3. Paid: does it reach the bibliography?

The issue's own bar. `brief run` then `paper draft`, over the same brief and
paper brief. Prior cost for this pair was **$0.3846** (analysis $0.3631, paper
$0.0214).

The prior analysis record and paper were copied to `before-records/` first —
`brief run` writes to the same `brief_id` and would otherwise overwrite the
only copy of what is being compared against.

**Retrieval: fixed. Composition: unchanged, and now the binding constraint.**

`brief run` on the same brief, $0.1691 (the prior draw cost $0.3631).

| | before (`before-records/`) | after |
|---|---|---|
| Distinct sources retrieval **reached** | 10 | **21** |
| `tilly-1978` chunks reached | **0** | **2** |
| Assembled | 98 | 111 |
| Composed | 49 | 51 |
| Sources surviving into the evidence set | 10 | **4** |
| `tilly-1978` in the evidence set | 0 | **0** |

So the fix does exactly what it claims and no more. Retrieval now reaches
`tilly-1978` — two chunks, `_16_durkheim_001` and `_110_general_001` — where
before it reached none. Composition then dropped both, along with most of the
other seventeen books retrieval newly reached.

**The paper's bibliography is therefore unchanged, and `paper draft` was not
run.** A bibliography is built from cited claims' grounds; a source absent from
the composed evidence cannot reach a claim, so the outcome was already
determined by the record above and the call would have bought a foregone
negative for $0.02.

### What this does and does not license

- **Deterministic and settled:** the window no longer cuts a book. Section 1
  proves that over the whole vault with zero regressions.
- **One draw, no rate:** everything in the table above is a single before and a
  single after of a stochastic loop. Retrieval findings in this repo reproduce
  roughly half the time. Nothing here supports "papers will now cite Tilly",
  and it should not be quoted that way.
- **Sources cited fell 10 to 4.** Read as one draw, not a regression — a drop
  in sources cited has been measured before alongside *better* grounding
  (`argmap-validated-fewer-sources-better-grounding`). It is not evidence
  against this change, and it is not evidence for it either.
- **The blocker moved downstream.** Whatever keeps a retrieved primary out of
  the composed evidence set is a different mechanism from the one fixed here,
  and it is not chased in this slice.

## Operational note

`AXIAL_SECRETS_PATH` is set in this shell to `/secrets/secrets.toml`, the
in-container path from the compose work. On this box it resolves to nothing, so
`_load_openrouter_secrets` returns `{}` and every run dies with "no API key was
found" while `secrets/secrets.toml` sits there perfectly valid. Every command
here passes `AXIAL_SECRETS_PATH=secrets/secrets.toml` explicitly.

## Reproduce

`sweep802.py` (writes a JSON of every page's window), `cmp802.py` (compares two
such files), `probe802f.py` (the one-line `find_notes` check). The two console
transcripts are `examine-after.txt` and `brief-run-after.txt`.
