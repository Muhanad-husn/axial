# 2026-09-30 — #858: relation kinds for the profile relations

**Reading: the profile pass finds qualifications, not conflicts.** Conflict is
4% of its relations against 13% of the neighbourhood pass's; qualification is
24% against 15%. Other kinds are within a few points.

## Command

`axial vocabulary build --column relation`, from `D:/axial-runs` at `8aaed38`
(#872 merged), detached under `watch_run.py` (cap $0.50). 30s, 3 calls, $0.0041
(manifest; key delta rounded to $0.00). 255 newly asked, 1,472 reused.

## Result

| kind | profile (271) | neighbourhood (1,456) |
|---|---|---|
| qualification | 24% | 15% |
| support | 20% | 19% |
| illustration | 18% | 17% |
| mechanism | 13% | 11% |
| extension | 7% | 6% |
| conflict | 4% | 13% |
| specification | 4% | 5% |
| additional-cause | 4% | 6% |
| grounding | 4% | 7% |
| none | 1% | 1% |

Split by unordered pair against `profile_relations.jsonl`, so the 16 pairs both
passes found count as profile (271 = 255 + 16).

## What this says

Same mechanism, different position category, different book: the pairs this
proposes mostly narrow or back each other rather than disagree. For opposition,
the neighbourhood pass stays the source of conflicts.
