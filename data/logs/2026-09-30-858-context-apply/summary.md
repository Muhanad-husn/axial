# 2026-09-30 — #858: apply #877 (keep context relations) to the current build

**309 context relations kept, $0.** `axial map relate-profile` rerun at
`bb58362` reused all 287 saved reads (no model calls, 60s). Counts:
relations_asserted 255, off_proposal_relations 618, context_relations 309.
`profile_relations.jsonl` now holds 564 rows (255 `profile` + 309
`profile-context`). The manifest's `cost_usd` (1.57) is the first run's,
carried forward; this run added nothing.

Then `axial vocabulary build --column relation` (log
`2026-09-30-858-context-kinds/`): 309 newly asked, 1,727 reused, 4 calls,
$0.0076, 14 refused of 2,036.

| kind | profile (271) | profile-context (309) | neighbourhood (1,456) |
|---|---|---|---|
| support | 20% | 23% | 19% |
| qualification | 24% | 20% | 15% |
| illustration | 18% | 17% | 17% |
| mechanism | 13% | 10% | 11% |
| extension | 7% | 8% | 6% |
| conflict | 4% | 6% | 13% |
| additional-cause | 4% | 6% | 6% |
| grounding | 4% | 5% | 7% |
| specification | 4% | 4% | 5% |

Cross-author relations on the map: 629 + 235 + 309 = 1,173, less at most
16 pairs both passes found. Conflicts still come mostly
from the neighbourhood pass.
