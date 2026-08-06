# Plate VII — The Phase B agentic query loop

**What it shows.** The one genuinely agentic loop in the system, and the shape of the
whole architecture: the model plans and re-queries freely in the middle, and code it
cannot reach stands on both sides. A fixed retrieval pipeline was rejected because thin
results demand a second look only an agent can decide to take.

## Intake — before the agent runs

```mermaid
flowchart LR
    brief["the brief<br/>case · request · lens? · weights?"] --> intr["interrogate the brief<br/>premises · bounds · refusal"] --> disp["disposition wrapper<br/>total, and never the model's own"]
    disp -->|"refuse"| stop["a completed run.<br/>No synthesis call is made."]
    disp -->|"proceed / proceed_bounded"| fork["fork-check<br/>measured, never a form"]
    fork --> con["ForkConstraint<br/>one compiled shape"]

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class disp,con code;
    class intr,fork model;
    class stop gate;
    class brief store;
```

## The loop, and the deterministic reduction after it

```mermaid
flowchart TB
    comp["compose the retrieval prompt — the fork's guidance folded in once.<br/>Guidance shapes reading, and can never be a reason to call fewer tools."]

    subgraph L["THE AGENTIC QUERY LOOP — bounded step budget"]
        direction LR
        m["the model proposes<br/>one tool call<br/>native tool-calling"] --> d["validating dispatcher<br/>checked against the registry<br/>and its schema, before the vault"] --> q["the vault query API<br/>ten tools, zero model calls<br/>same query → same ids, same order"] --> v["notes.db<br/>name pages<br/>positions.jsonl"]
        v -->|"a ToolResult of ids, total and detail → one trajectory<br/>entry per call → next turn's feedback"| m
    end

    asm["assemble the evidence — dedupe in call order, apply the fork constraint,<br/>then round-robin by source, with the analyst's weights biasing the rotation"]
    bud["prefix by the synthesis char budget<br/>measured across seven runs: 506 assembled, 146 composed"]
    syn["synthesis — evidence offered under opaque handles, each claim<br/>marked (a) / (b) / (c) with grounds"]

    comp --> L
    L --> asm
    asm --> bud
    bud --> syn
    syn --> v1["attribution — every claim has a kind,<br/>every (a)/(b) resolvable grounds"]
    syn --> v2["counter-position — present, or<br/>one-sidedness explicitly disclosed"]
    syn --> v3["coverage + confidence — a per-name<br/>map and a disclosed band"]
    v1 --> out["data/analyses/*.json<br/>+ rendered answer + run report"]
    v2 --> out
    v3 --> out

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class comp,q,asm code;
    class m,syn model;
    class d,bud,v1,v2,v3 gate;
    class v,out store;
```

## Notes

- **The feedback states composition and nothing else.** What the evidence set now holds
  and which books it spans, plus every returned id's own author, year and one-sentence
  claim. Never the budget, the cap or what would still fit: a cap the model can see gets
  widened on purpose.
- **And never "you already asked this."** Telling the model so was measured to *raise*
  repeats, 14% → 20%. The fix belongs in the resolver, not the memory.
- **What the tools return.** Notes, opposition edges and argument-map positions are the
  destination; a name, a publication year and a source are filters on them — WHERE
  clauses, never the destination. The entry point is `find_notes`, not a door lookup: a
  historian's question chains two relations and every name-layer tool walks exactly one.
- **An empty result is a real answer.** A tool that resolved nothing says the phrase it
  tried and each of its words, so a zero has somewhere to go other than the same query.
- **Opaque handles, not real ids.** The synthesis prompt never shows a real `chunk_id`;
  each evidence chunk is offered under a short per-call handle resolved by exact lookup.
  There is no long id in the prompt to transcribe, truncate or blend.
- **A failed mechanical check blocks release.** Where a check is genuinely not mechanical
  — does a cited chunk actually support the claim, is a counter-position steelmanned —
  it is a bounded separate call, never the generating model grading itself.
- **Retrieval precision measured against what was *composed*, not what was assembled:**
  506 assembled → 146 composed → 103 cited is 70.5%, not 20%.
