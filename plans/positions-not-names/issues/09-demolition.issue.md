# refactor(positions-not-names): the name layer and its dependents come out [slice 09]

**Spec:** docs/approach-positions-not-names.md#9-what-this-lets-go-and-when · **Plan:** plans/positions-not-names/09-demolition.md
**Depends on:** slice 08 of this batch — **and slices 06 (founder go), 07 shipped; nothing is deleted until what replaces it is live**
**Labels:** enhancement, sub:analysis-v0
**Closes alongside:** #825

## Deliverable

Everything slices 06–08 made redundant is removed — the name pages as a
structure, the disagreement-manufacturing pass (gather), the name-walking
retrieval loop, the residue pass, the vocabulary measurement apparatus, the
category join and the `map+vocab` arm (#825, absorbed here: `axial brief run
--arm map+vocab` refused as unknown, the four `--vocabulary-*` knobs gone,
the `vocabulary` block out of the answer record, the third arm's spec
paragraphs out with their two measured findings moved, not dropped), and
the eval code nothing remaining reads — leaving the name index as a filter
("where is this discussed", variants folded), the suite green, ruff clean,
and the spec updated in the same branch. The PR body lists every deleted
module with the slice or measurement that made it safe. The definitive
deletion list is drawn up at slice start by reference sweep and recorded in
the plan before the branch is cut.

## Mechanism

Pure subtraction in dependency order, suite green at each step. `eval
layers`, the arm recording, `vocabulary build` and `vocabulary examine`'s
drafting path all stay — they are load-bearing now.

## Acceptance criterion

```gherkin
Given slices 06-08 are merged and the founder's go is recorded
When  the demolition branch is built
Then  the retired CLI surfaces (name-page materialisation, the gather pass,
      the name-walking ask loop, the residue pass) no longer exist as
      commands
And   the kept surface still works: asking where a name is discussed returns
      its passages, spelling variants folded
And   `uv run pytest` is green and `uv run ruff check` is clean with the
      deleted modules' tests removed alongside them
And   the PR body lists every deleted module with the slice that made it safe
```

## Files

```aeo-independence
slice: 09-demolition
edits: src/axial/argmap/vocabulary_join.py
edits: src/axial/argmap/test_vocabulary_join.py
edits: src/axial/argmap/ask.py
edits: src/axial/argmap/test_ask.py
edits: src/axial/answer/record.py
edits: src/axial/brief/sweep.py
edits: src/axial/brief/test_sweep.py
edits: specs/PHASE-B.md
edits: src/axial/gather.py
edits: src/axial/argmap/residue.py
edits: src/axial/argmap/test_residue.py
edits: src/axial/vocabulary.py
edits: src/axial/test_vocabulary.py
edits: src/axial/cli.py
edits: src/axial/test_cli.py
edits: specs/PRODUCT.md
depends-on: 08-retrieval-address-arm
```

## Out of scope

- Deleting `vocabulary examine`'s drafting path or `vocabulary build` (both
  load-bearing); deleting the name index itself (the kept filter,
  permanently); rewriting retrieval docs beyond the spec sections that named
  the deleted machinery.
