# 2026-08-19 — #802: is the missing primary retrieval or selection?

Offline measurement over `data/vault/notes.db`, `data/analyses/` and
`data/source_meta/`. **No model calls, no cost, minutes.** Issue #802 asked
for a measurement before any fix was proposed; this is it.

## Verdict

**Retrieval, not selection.** The drafter never had the choice.

## What was measured

### 1. Did `tilly-1978` ever reach an analysis?

Across **all 19 analysis records** in `data/analyses/`, `tilly-1978-f908c910464c`
appears in `source_usage.sources` **zero times** — so retrieval surfaced not one
of its 189 notes, in any run. Four of the 19 name Charles Tilly in their own
`coverage_map`; all four surfaced zero Tilly passages.

`ec94042430910584`, the analysis behind `data/papers/a1039fad4da31320.md` —
whose thesis is about "Tilly's war-centred account" — assembled 98 chunks and
composed 49, from these ten sources:

```
source                                   available evidence
hall-2006-449559bfe4dc                         166        1
mann-v2-1993-ec759675dcbd                       50        2
malesevic-2010-fd2cbe41384f                     44        1
mann-v4-2013-1b7e828e0199                       26        1
mann-v1-2012-5f90ead66c93                       23        1
malesevic-2007-323a2518e61b                     17        3
heydemann-2000-66701ffbb36c                     16        3
malesevic-2026-4faeb528594d                      6        1
ayubi-1995-16fd6a2e503f                          3        1
caspersen-2012-fbc0efe4fffc                      2        1
```

`tilly-1978` is absent from the table entirely — `available_chunk_count` is not
low, it does not exist. "Retrieved 8×, cited 0" from the unread-sources finding
counts a different thing; at the point where a paper is written, the count is 0.

### 2. Why — the exact mechanism

All four Tilly-naming analyses reached the name layer through `find_notes`.
`find_notes` spreads members by source (`_spread_by_source`) and truncates at
`limit`, default **10**. Groups are visited in `source_id` **ascending** order.

The `Charles Tilly` page draws on **20 sources** and 133 citable notes.
`tilly-1978-f908c910464c` is **16th alphabetically**. Measured directly:

```
limit= 10  total= 133  returned= 10  tilly-1978 present: False
limit= 15  total= 133  returned= 15  tilly-1978 present: False
limit= 16  total= 133  returned= 16  tilly-1978 present: True
```

At `limit=10` the window is: bayat, caspersen, gelvin, hall, heydemann,
kalyvas, and **four** malesevic volumes. Tilly's own book first appears at
`limit=16`.

**`_round_robin_by_source` (#562) is a partial fix, not a complete one.** It
corrects the ordering *within* a window; it does not correct *selection* when
the source count exceeds the limit. When it does, round-robin degenerates to
"one note from each of the alphabetically first `limit` sources" — alphabetical
again, one rung up.

### 3. How systemic

| | |
|---|---|
| Name pages total | 42,026 |
| Pages drawing from more than 10 sources | **257** (0.6%) |
| Pages in the usable 5+ source band | 1,182 |
| — of those, over the limit | **257 (21.7%)** |

Sources cut by the alphabetical window, on the pages they appear on:

```
wimmer-2013          168 of 1713   9.8%
mann-v4-2013         147 of 2934   5.0%
smith-2009           108 of 1234   8.8%
ungor-2020           101 of 1239   8.2%
tilly-1978            87 of 1402   6.2%
...
agamben-2005           0 of  624   0.0%
ayubi-1995             0 of 3345   0.0%
batatu-1999            0 of 2988   0.0%
bayat-2017             0 of 1881   0.0%
```

**Every source sorting in the alphabetical first ten is cut on exactly zero
pages.** That contrast, 0.0% against up to 9.8%, is the whole finding: the cut
is not about what a source says.

Of 23 author name pages, 6 draw from more than 10 sources, and on **2 the
author's own book falls outside the window**: `Charles Tilly` (rank 16 of 20)
and `mann-v4-2013` (rank 11 of 14).

### 4. A second, independent reason — widening the window does not fix it

`tilly-1978` supplies only **11 of the `Charles Tilly` page's 145 notes**, and
most of those eleven are incidental self-reference rather than his argument:

```
'From Mobilization to Bevolalion'  The passage identifies the author as
                                   Charles Tilly of the University of Michigan.
'Prefaee'                          The book is a collaborative product shaped
                                   by many contributors...
```

A book rarely names its own author. Tilly's substantive claims index under the
subjects he writes about — `France` (44 notes), `England` (25), `nineteenth
century` (20), `America` (19) — while the commentary indexes under his name
*because commentary names him*. **An author name page is structurally a
commentary page.** Raising the limit puts Tilly's book on the page; it does not
put his argument there.

## What this does not settle

- No fix is proposed here, per the issue. In particular nothing that promotes a
  source for being a primary — "don't fix by ranking" already binds.
- 0.6% of all pages is small; 21.7% of the usable band is not. Which number
  matters depends on which pages a paper actually queries, and the four
  Tilly-naming analyses queried a page in the 21.7%.
- Finding 4 is a structural observation over one author, measured on one page.
  It generalises by argument, not by measurement.

## Reproduce

`probe802.py` (the window), `probe802b.py` (scale), `probe802d.py` (author
pages). Raw output in `console.log`. Each is a plain read of the vault; none
writes anything.
