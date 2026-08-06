# Plate I — The whole system

**What it shows.** The corpus is read once and written down; every later phase reads
artifacts, not books. Model calls concentrate in six places, and each sits between
deterministic code on the way in and a gate on the way out.

```mermaid
flowchart TB
    charter["CHARTER — every claim witnessed by the corpus, never by training memory<br/>each assertion marked (a) source-says · (b) tool-infers-across-sources · (c) the analyst's judgment<br/>counter-position mandatory · confidence disclosed"]

    src["Google Drive connector → intake<br/>text-layer check · English gate · holdings-completeness · bibliographic read"]

    subgraph A["PHASE A — the model reads the corpus, once"]
        direction LR
        a1["extract<br/>+ route"] --> a2["chunk<br/>3.5–9k chars"] --> a3["interrogate<br/>1 call / note"] --> a4["reconcile<br/>names merge"] --> a5["materialize<br/>writes the vault"] --> a6["gather<br/>1 call / name"] --> a7["argument map<br/>positions + relations"]
    end

    subgraph P["PERSISTED — a re-cut re-runs everything below extraction and re-reads no book"]
        direction LR
        p1["data/chunks/<br/>6,166 notes, bounded by construction"]
        p2["data/answers/<br/>one open-answer record per note"]
        p3["data/vault/<br/>49,558 name pages + notes.db"]
        p4["data/map/<br/>685 positions + their relations"]
    end

    subgraph B["PHASE B — one question in, one auditable answer out"]
        direction LR
        b1["interrogate<br/>the brief"] --> b2["intake fork-check<br/>ask only at a real fork"] --> b3["agentic query loop<br/>plate VII"] --> b4["synthesis<br/>claims + grounds"] --> b5["validators<br/>block release"]
    end

    rec["data/analyses/*.json<br/>claims · grounds · coverage · trajectory"]

    subgraph C["PHASE C — a paper, assembled from settled claims"]
        direction LR
        c1["claim<br/>inventory"] --> c2["arc plan"] --> c3["draft,<br/>per section"] --> c4["index<br/>+ render"] --> c5["four run<br/>gates"]
    end

    pap["data/papers/<br/>record + rendered markdown"]
    pan["offline panel<br/>measures, never blocks — plate IX"]

    charter -.->|"governs"| A
    charter -.->|"governs"| B
    charter -.->|"governs"| C
    src --> A
    A -->|"writes"| P
    P -->|"read through the LLM-free query API"| B
    B --> rec
    rec --> C
    C --> pap
    pap -.->|"sampled"| pan

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class src,a1,a2,a5,c1,c4 code;
    class a3,a4,a6,a7,b1,b2,b3,b4,c2,c3 model;
    class charter,b5,c5 gate;
    class p1,p2,p3,p4,rec,pap,pan store;
```

## Notes

- **Phase A is the substrate, not the product** (`specs/CHARTER.md` §0). It builds the
  corpus the reasoning layers stand on; the product is Phase B–E.
- **The charter is never patched into a phase spec.** Every phase spec cites it and
  derives its P0 criteria from the five principles.
- Phases A, B and C are built. **D (format adaptation) and E (lens application) are
  GitHub milestones, not a schedule** (DEC-63) — no spec, no date, no issue.
