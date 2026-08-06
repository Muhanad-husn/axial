# Plate IX — Phase C authorship, and the strangers who measure it

**What it shows.** Two halves on two different clocks. The paper is assembled and gated
on every run; the system is measured on a sample, by reviewers from a different training
lab, and only after a positive control proves the panel is still reading.

## The per-run pipeline — cheap, and run on every paper

```mermaid
flowchart TB
    pb["paper brief<br/>thesis · a list of analysis ids"] --> intake["intake<br/>one shared corpus pin,<br/>and no refused record"] --> inv["claim inventory<br/>keyed (brief_id, claim_id)<br/>— the drafter's whole world"] --> plan["arc plan<br/>sections, roles, and which<br/>claims each one may cite"] --> draft["draft — one call per section<br/>sees that section's claims and what<br/>earlier sections cited. No tools at all."]

    draft --> cidx["citation index<br/>an unknown marker is fatal here"] --> bib["bibliography + render<br/>exactly the cited sources"] --> pap["data/papers/<br/>record + rendered markdown"]

    pap --> g1["every marker resolves"]
    pap --> g2["every ground resolves"]
    pap --> g3["no band escalation"]
    pap --> g4["counter-position present"]

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class inv,cidx,bib code;
    class plan,draft model;
    class intake,g1,g2,g3,g4 gate;
    class pb,pap store;
```

**The drafter cannot introduce evidence, because it has no path to any.** It has no
retrieval tools and no vault access: the claim inventory is the whole world.
Generate-then-cite is made structurally impossible rather than forbidden by instruction.

## Off the pipeline, on its own clock — measures the system, holds back no paper

```mermaid
flowchart LR
    smp["a stratified sample<br/>of finished papers"] --> pkt["the sealed packet<br/>the paper, its cited evidence,<br/>the bibliography. Nothing else."] --> rev["N ≥ 3 reviewers<br/>each from a different training<br/>lab; no tools, structurally"] --> ver["verdicts<br/>four dimensions; coherence<br/>as mean and spread"] --> tr["trusted: false until the<br/>positive control has passed"]
    ctl["the positive control — three planted defects:<br/>a mis-grounded claim · a strawman counter-position ·<br/>a band raised over a thinly covered name"] --> tr

    classDef code fill:#E4EFF0,stroke:#14646A,stroke-width:2px,color:#0F3339;
    classDef model fill:#F5E7EE,stroke:#7C3A5E,stroke-width:2px,color:#3C1B2C;
    classDef gate fill:#FBF4E2,stroke:#8A6B15,stroke-width:2px,stroke-dasharray:6 4,color:#4A3A0B;
    classDef store fill:#ECEDE7,stroke:#8B8F84,stroke-width:1.5px,color:#2A2C28;
    class pkt,ver,ctl code;
    class rev model;
    class tr gate;
    class smp store;
```

## Notes

- **Why a panel at all.** Every property cheap to check is checked on every paper. The
  one none of them reach — whether the argument holds together — is measured, on a
  sample, and gates nothing.
- **Isolation is enforced by the harness that builds the call**, not by anything written
  in the prompt: a model with file tools reads the repository regardless of what its
  instructions say. Isolation you ask for is not isolation.
- **No tools, structurally.** Reviewers dispatch through the plain completion seam, which
  has no `tools` parameter to pass — stronger than a check that can be forgotten.
- **Vendor means the lab that trained the model**, never the API provider that serves it.
  A model id absent from the table is a hard error, never assumed distinct.
- **A plant that cannot be applied is an error, never a skip.** A control that quietly
  plants two defects and then passes is worse than no control at all.
- **The dependency runs one way.** `panel/` learns to read a paper record; the pipeline
  never learns that a panel exists. Nothing under `paper/` may import from `panel/`.
- **Run every brief a paper will draw on inside one pin window.** A Gather run, a name
  merge or a materialize that changes which pages exist all move the corpus pin, and a
  paper across two pins is rejected at intake.
- **Release bar met 2026-08-02:** both papers pass all four gates, 7 new (b) claims,
  $0.12–0.16 a paper.
