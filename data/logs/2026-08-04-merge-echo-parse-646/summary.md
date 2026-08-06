# #646: replaying every refused merge response against the fixed parser

2026-08-04. Offline, read-only, no model calls, no cost.

`replay_646.py` reads all 80 rows of `data/names/merge_failures.jsonl` — every
merge batch the corpus of record threw away as "placed none of the batch's
surface forms" — rebuilds each batch's real `kinds` and `evidence` from
`data/names/inventory.jsonl`, and re-runs `parse_merge_response` on the raw
response the failure row recorded. 79 of the 80 carry a full raw response; the
80th was truncated to a `head=`/`tail=` diagnostic and cannot be replayed.

| parser | batches that parse (of 79) |
| --- | --- |
| `main` (4d0032e) | 1 |
| first cut of the fix, leading-quote anchor + exact evidence echo | 2 |
| shipped fix, `fix/merge-echoed-kind` | **75** |

All 75 place every member of their batch. None is partial.

## The four echo shapes, measured rather than guessed

The first cut assumed one shape (a relabeled kind, everything else verbatim)
and recovered 2 of 79. The replay showed four:

1. **Evidence suffix dropped, kind kept** — prompt
   `'Golden Age' (period) (in hall-2006-449559bfe4dc, mann-v3-2012-…, mann-v4-2013-…)`,
   response `'Golden Age' (period)`. The dominant shape, and the one the
   issue's own Renaissance example belongs to.
2. **The repr's quotes dropped** — prompt `'Battle of Beirut' (event) (in batatu-1999-…)`,
   response `Battle of Beirut (event)`.
3. **Outer repr wrapping dropped, the surface's own quotes kept** — a surface
   that literally is `'time of troubles'` renders double-quoted; the response
   echoed `'time of troubles' (period) (in batatu-1999-…)`, which is the member
   verbatim and must not be decoded as a literal.
4. **Every suffix dropped** — only `repr(surface)` survives:
   `"'Final Solution'"`, `"'Tskhinvali'"`, `"\"As'ad Abukhalil\""`. This alone
   is 15 of the 79.

## The 4 that stay refused

The same batch four times (`members: bellicist state building, state formation
through war, the state is a bureaucratic cage, the state is a protection
racket`). Its raw response is `{"nodes": []}` — an empty answer with nothing to
resolve. Correctly refused; not this bug.

## What this changes on the corpus

Nothing already decided. `merge_decisions.jsonl`'s 28,201 records are keyed on
the rendered batch, and this fix changes no rendering, so no recorded decision
is re-asked or re-parsed. Only the ~80 batches that never produced a decision
are re-asked on the next merge pass, and ~95% of them will now land instead of
failing again identically. `merge_manifest.json` should read `complete: true`
after that pass.

## Next steps

Re-run `axial merge-names` on the corpus of record to collect the recovered
batches, then a materialize. Not done here — this run touched nothing.
