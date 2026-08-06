# Issue #677 slice B: real-corpus validation

31-book baseline: 5376 passages, 596 bags, 612 reads (4.9s) -- NOTE: differs from the #623 paid build's own 5726 passages; see module docstring, data/answers changed between the two runs, not this script
34-book (delta = 3 books) incremental build: 535 new passages placed (of 535 in the 3 new books), 645 bags, 663 reads (0.6s)

## Reuse against this run's own incremental read count
- reused (no re-ask): 515 of 663 (77.7%)
- asked (new call needed): 148 of 663
- compare to the fresh 34-book bagging below, which reproduces what the OLD global-refit build actually paid for: every one of its reads is asked, 0 reused

## Disturbance breakdown, among the asked reads
- genuinely new content (89): the slice itself carries a passage from one of the 3 new books
- author_spread re-cut (10): the slice belongs to a bag that gained a new member elsewhere, so its own EXTRACT_SLICE boundary moved even though every passage IN this slice already existed
- re-bagged, brand new bag (49): a residue bag with no baseline counterpart at all -- offset above the existing maximum label, never a re-cut of something old

## units_asked_touching_new: 138 of 148 asked reads touch one of the 3 new books

## Coherence -- the acceptance bar (mean cosine similarity of a bag's own members to that bag's own mean direction; NOT the average-linkage criterion placement decides by -- see module docstring)
- fresh 34-book fit, all bags: mean=0.808 p10=0.739 (n=473)
- fresh 34-book fit, bags touching a new-book passage (the reference for 'coherent enough to trust'): mean=0.793 p10=0.732 (n=79)
- incremental, unaffected bags (no new member, kept verbatim): mean=0.810 p10=0.739 (n=362)
- incremental, grown bags (gained >=1 new-book passage): mean=0.776 p10=0.729 (n=88)
- incremental, residue bags (brand new, no baseline counterpart): mean=0.840 p10=0.772 (n=22)
- the bar: incremental's grown-bag coherence should read close to the fresh fit's own bags-with-a-new-passage coherence, at both mean and p10 (the worst decile) -- not agreement in WHICH bag a passage landed in (see the demoted drift figure below and the module docstring for why that yardstick was rejected).

## Drift vs a fresh 34-book bagging -- DEMOTED, not the acceptance bar
- fresh full bag: 647 bags, 665 reads (6.0s)
- incremental's own reads are byte-identical to a fresh fit's on 476 of 665 (71.6%).
- This is drift, not free reuse: most of these were never asked about under either build, and a fresh fit REORGANISES on new passages (bag count moves), so a new passage landing somewhere a fresh fit would not put it is not, by itself, a defect. `--force` is the periodic corrective for this drift; coherence above is what actually justifies the design.

## Notes
- Zero model calls: every vector computed once by the local MiniLM encoder (sentence-transformers/all-MiniLM-L6-v2) via a shared claim-text cache, nothing written to any persisted map artifact under `data/map/`.
- `_incremental_bag_passages` is called with an in-memory `prior_state` built directly from the 31-book baseline's own bags/centroids -- this validates the MECHANISM exactly as `run_map_build` would use it, without needing a real prior pin directory or a real `bag_state.json` on disk.
