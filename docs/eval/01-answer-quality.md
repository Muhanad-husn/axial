# Eval 1 — answer quality (output axis)

**Status:** settled. The instrument is specified in
[`specs/PHASE-B.md` §9.4](../../specs/PHASE-B.md); building it is issue #385.
**Depends on:** the rebuilt corpus and a resolved pin. **No academic input** —
#250 and #295 were closed *not planned* on 2026-07-24, and none is coming.

## Question

Given a hard analytical query against a rich corpus, is the product's answer
correct, well-supported, and grounded in the right sources?

## What changed, and why this document was rewritten

This eval was originally designed around an academic who would author hard
cases and adjudicate good answers. That person does not exist and will not.
DEC-40 replaced the human referee with a **sealed-packet peer-reviewer panel**;
DEC-43 scoped that panel as an **offline eval instrument run on a sample**,
not a referee wired into any run. Both are reflected below. The corpus-pin
format this document used to own is now implemented and specified in PHASE-B
§7.12.

Three things the earlier version said are now wrong and are corrected here:

- Academic-authored hard cases are **not** a dependency of this eval.
- There is no **judge-vs-academic agreement sampling**. There is no academic to
  agree with. The positive control replaces it.
- This is **not a per-case referee**. A panel number belongs to a measurement
  run and its stated frame, never to a single analysis.

## The bar: hard cases against a rich corpus

- Retrieval quality only manifests at corpus scale — distractors,
  near-duplicates, and cross-source synthesis only exist when the vault is
  rich. The full corpus is a precondition for this eval to mean anything.
- Anti-Üngör: no softballs the system can already answer (the #115 postmortem
  mistake).
- Cases are sampled **across performance tiers**, not just the good ones. A
  panel run over only strong outputs measures nothing useful.

## The referee: a sealed-packet panel

Specified in full at PHASE-B §9.4. Its seven integrity properties are not
restated here; the four that most change how a number may be read are:

- **A stranger to the repo, sealed by tooling.** The reviewer gets the rendered
  analysis plus the resolved text of every chunk its claims cite, and nothing
  else — enforced by an empty tool registry, never by a prompt instruction.
- **A different vendor**, meaning the training lab, not the API provider.
  Stricter than the different-model-id guard the five rung-3 gates carry.
- **N ≥ 3 reviewers, and the spread is the error bar.** A mean without a spread
  is not reportable.
- **A positive control before any number is trusted.** The panel must first
  catch planted defects: a mis-grounded claim, a strawmanned counter-position,
  and an overconfident band. LLM judges are systematically generous and are
  moved by confident prose. No live positive control exists anywhere in this
  repo today (#323); this is the first.

`expected_answer` in `evals/cases/sim/` is **retired as the primary referee**
and is **never placed in a reviewer packet** — showing a reviewer a pre-written
answer anchors it to that answer (PHASE-B §9.3). `required_citation_source_ids`
keeps its role as a mechanical oracle, used by eval #3 rather than here.

## Where the number may be reported

The refereed tier (PHASE-B §9.2). Every panel number carries a disclosed
ceiling: that the referee is a model panel, how many reviewers ran, which
vendors they came from, the spread across them, the sample scored, and the
corpus pin.

**No number here may ever be reported, aggregated, cited, or promoted as
"measured quality against human expert judgment."** There is no human expert in
this product's loop.

No analysis record and no gate report carries a panel verdict. A brief run
neither triggers a panel nor waits for one.

## Corpus pin

This document originated the format. It is now **implemented** in
`src/axial/eval/corpus_pin.py` and written with `axial pin write <name>`; the
field contract it carries is stated in PHASE-B §7.12. Reused by evals #2 and
#3; two runs are only comparable if their pins match. Source filenames are part
of a pin's identity — see DEC-42 for what that cost when the corpus was
rebuilt.

## Open threads

- How many reviewers past three buy anything measurable.
- How panel verdicts aggregate across a sample into a headline figure without
  hiding the spread.
- Which cases and which model combinations make up a given run's sampling
  frame — set per measurement run, recorded with the result, and in practice
  driven by #362's tier bucketing.

*Closed, not deferred:* the adjudication format (the keyed `answer_kind` shape
of PHASE-B §9.3 is the permanent contract), where cases live
(`evals/cases/sim/`, retained permanently), and the judge-vs-academic
agreement protocol.
