# Plate III — Interrogate

**What it shows.** One reading per note, fourteen open questions, and an explicit right
to abstain. Closed vocabularies return bins; open questions return specifics, and
specifics are what two passages can share.

```mermaid
flowchart LR
    i1["the note<br/>3,500–9,000 chars"]
    i2["author · title · date"]
    i3["thesis · scope<br/>· stated argument"]
    i4["chapter + section heading"]
    i5["domain frame examples"]

    ncall["note_interrogate<br/>one call per note<br/>no web, no external lookup,<br/>no memory of the book"]

    abst["abstention is explicit: not-in-passage<br/>an empty list is an answer, not a blank"]

    out["THE ANSWER RECORD<br/>about · claim · move · ranges_over · stops_holding<br/>position_of · position · arguing_against · names<br/>citations · mechanism · evidence · comparison<br/>defines / uses · concedes · assumes"]

    i1 --> ncall
    i2 --> ncall
    i3 --> ncall
    i4 --> ncall
    i5 --> ncall
    ncall --> out
    ncall --- abst

    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class ncall model;
    class abst gate;
    class i1,i2,i3,i4,i5,out store;
```

## The ordering that keeps the examples from capturing the answer

The single biggest regression risk in the feature: if the interrogation answers in the
frame's vocabulary, v1 has rebuilt tagging with more values and failed silently.

```mermaid
flowchart LR
    s1["1 — the free answer is asked for<br/>first, in the model's own words"] --> s2["2 — only now is the example<br/>list for that question shown"] --> s3["3 — field_nearest, a separate<br/>field, marked as an example"]
    s1 -.->|"code never bridges the two: no normalization,<br/>no rewriting, no filling one from the other"| s3

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    class s1,s2,s3 code;
```

## Three record kinds, one file per source

```mermaid
flowchart LR
    r1["answers"] --> chk
    r2["failure_reason"] --> chk
    r3["skip_reason"] --> chk
    chk["answered + failed + skipped must equal this source's<br/>own chunk count, or the pass raises"]

    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class chk gate;
    class r1,r2,r3 store;
```

## Notes

- **A guessed answer is worse than an abstention**, because nothing downstream can tell
  it from a read one. Every field is in exactly one of three states, and the states are
  distinguishable by reading the record.
- **The file is also the resume point.** A note already carrying any of the three kinds
  is never re-sent to the model.
- **`names` is where cross-book edges come from**; `citations` is the author's own
  cross-book edge, available from the first reading and never looked for by any v0 pass.
- **The corpus is a permanent mixed frame.** A record written before frame 0.2 carries
  `position_of` and no `position` key. Every reader branches on **key presence**, never
  on the `frame_version` string.
- Per-question yield is measured: only `stops_holding` is broadly refused (60.2%), and
  `position` exists on 585 of 6,733 notes before the targeted backfill.
