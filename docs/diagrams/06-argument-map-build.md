# Plate VI — The argument map, built

**What it shows.** Name-keyed retrieval only reaches a passage through a proper noun it
happens to mention. The position layer groups passages that make the same argument, once
and offline, so a question can land on the argument directly. Both model passes here are
deliberately blind to authorship.

## Stage 1 — positions

```mermaid
flowchart LR
    ans["data/answers/<br/>*.jsonl"] --> sel["select<br/>argues something"] --> bag["bag<br/>local encoder"] --> sli["author-spread<br/>slices"] --> ext["extract<br/>1 call / slice"] --> mrg["merge<br/>near-duplicate namings"] --> pos["positions.jsonl<br/>685 positions"]

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class sel,bag,sli,mrg code;
    class ext model;
    class ans,pos store;
```

Selected: a claim that is not abstained, sitting before its source's back-matter
boundary, not itself a front/back-matter section by heading, and not silent on all six of
`mechanism`, `comparison`, `concedes`, `assumes`, `position_of`, `ranges_over`.

## Stage 2 — relations

```mermaid
flowchart LR
    pos["positions.jsonl"] --> nb["neighbourhoods<br/>target 8, max 12,<br/>singletons skipped"] --> rel["relate<br/>1 call per neighbourhood"] --> out["relations.jsonl<br/>direction is meaningful"] --> drp["an invented or self-pointing<br/>handle is dropped, never repaired"]

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class nb code;
    class rel model;
    class drp gate;
    class pos,out store;
```

## Three things that look like details and are not

| | |
|---|---|
| **Blind on purpose** | The extraction prompt shows a bare handle and the claim, never the author — so the later cross-author balance count measures the corpus and not its own input. |
| **No menu of relation types** | The model coins its own label and says what the relation is. An engine told to look for opposition finds opposition: opposition came back at 6.6% precisely because nothing asked for it. "Unrelated" stays cheap to say. |
| **The pin hashes raw sources only** | A prompt, model or reasoning-tier change does not force a rebuild; a corpus change does. Two ledgers are flushed the instant a call returns, so no paid call is ever lost. |

## Notes

- **The grain is a stated choice, not a fitted one.** The same corpus yields 1,636
  positions at a tight threshold and 234 at a loose one. No correct number is hiding in
  the data.
- **The extraction call is told that producing roughly as many arguments as passages is a
  failed read** — the job is what recurs across passages, not a restatement of each.
- **Relations key on `position_id`, never on the argument sentence.** A sentence-keyed
  rejoin silently drops any relation whose sentence was not unique across positions.
- **All-pairs is never done.** A flat clustering at real-corpus scale produced a
  53-position group — 1,378 possible pairs in one call, which the model cannot weigh and
  which alone would dominate the denominator.
- **Measured:** 705 calls, 45 minutes at 20 workers, $0.75 for both stages on 31 sources.
  The map scales roughly linearly (k = 1.04) but densifies: cross-book arguments went
  from 8.7% to 38.4% and have not plateaued.
- **A passage already placed keeps its bag** (`bag_state.json`), which took an
  incremental build from 665 reads asked down to 148.
