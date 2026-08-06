# Plate IV — Reconcile

**What it shows.** Three tiers of decision, kept apart on purpose: a string fold decides
alone and never asks; clustering only chooses what is put in front of the model at once;
the model makes every merge, and may say it cannot tell.

```mermaid
flowchart TB
    ans["data/answers/*.jsonl"] --> cut["iter_name_occurrences<br/>one place, ten shape rules"]
    cut --> inv["inventory.jsonl"]
    inv --> fold["fold — case, whitespace,<br/>punctuation, transliteration"]

    fold -->|"no model call: whether two strings differ<br/>only by case is not a judgment"| direct["unioned straight into<br/>the alias map"]
    fold --> emb["embed + HDBSCAN<br/>the fit is persisted"]

    emb --> floor{"below the cluster's own<br/>fitted membership floor?"}
    floor -->|"yes"| res["the residue — freshly fit at the same dials,<br/>labels offset above the existing maximum"]
    floor -->|"no"| batch
    res --> batch["merge batches = clusters<br/>+ candidate rules"]

    batch --> merge["the merge call — one per batch,<br/>clusters as hints, joined to the books<br/>each surface came from"]

    merge --> n1["nodes → aliases folded"]
    merge --> n2["undecided → escalated,<br/>stands alone"]
    merge --> n3["unparseable → merge_failures.jsonl,<br/>retried on a later run"]

    n1 --> map["alias_map.json + index.json"]
    direct --> map

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class cut,fold,emb,batch,direct,res,n1 code;
    class merge model;
    class floor,n2,n3 gate;
    class ans,inv,map store;
```

## Notes

- **The cut set is a filter, not a lossless record.** Rows A–S drop citation-only
  surfaces, back matter, dates, locators and bare numerals: 61,612 surfaces → 44,382
  pages. A page disappears only when **every** surface that would have been its member
  matches.
- **Clustering is a viewing aid.** It decides nothing; it only chooses how much is put in
  front of the model at once. The dial is moved by reading the distribution report —
  start loose, tighten by looking.
- **The candidate rules refuse on ambiguity.** `C. Tilly ↔ Charles Tilly`,
  `Abercrombie ↔ Nikolas Abercrombie`, `(AANS) ↔ its expansion` — and every rule proposes
  nothing the moment a short form has more than one candidate.
- **A surface already seen keeps its label and its vector.** Only a genuinely new one is
  placed, by `approximate_predict`, and only when its strength clears that cluster's own
  fitted floor. Existing labels are never renumbered. This took merge re-asks from 5,143
  to 2,202 on an incremental build.
- **Every merge is reversible data.** Nothing else on disk records that a merge happened,
  so deleting one node undoes exactly that merge. `merge_decisions.jsonl` is keyed on the
  batch's rendered members, so a re-run reproduces the same merges for free.
- **"Cannot tell" is a third outcome, not a default.** An escalated surface stands alone
  — the same place an unplaced one stands — but the two are distinguishable on disk, so
  the rate is measurable.
