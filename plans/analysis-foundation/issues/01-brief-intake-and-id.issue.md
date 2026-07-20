# feat(analysis-foundation): brief intake — load, validate, and deterministically id a brief [slice 01]

**Spec:** specs/PHASE-B.md#7.1 · §6 · §8 P0-9 · **Plan:** plans/analysis-foundation/01-brief-intake-and-id.md
**Depends on:** none
**Labels:** sub:analysis-v0, enhancement

## Deliverable
A brief loader reads a versioned brief file into the §7.1 shape
`{brief_id, case, request, lens?}`, validates it, and computes `brief_id` as a
stable deterministic hash over the brief's content — no randomness, no
timestamps, no filename input, so the same content yields the same id on every
run and every machine. `case` and `request` are required non-empty strings;
`lens` is optional. A malformed brief fails with a clear error naming the
offending field. `axial brief show <brief_file>` prints the loaded brief and its
id. This is the Phase-B walking skeleton: it establishes the `src/axial/brief/`
module (§6) and the `axial brief` CLI namespace, and lands 2–3 hand-written
fixture briefs under `config/briefs/dev/` so downstream stages can build before
the founder's 26 questions arrive (P0-11, slice 03). LLM-free by construction:
zero model and zero embedding calls on any path.

## Acceptance criterion
```gherkin
Given a brief file config/briefs/dev/fixture-syria-displacement.yaml carrying
      case: "Syria" and request: "How did displacement reshape local authority?"
When  `axial brief show config/briefs/dev/fixture-syria-displacement.yaml` runs
Then  the command exits 0, prints case "Syria", the request text, and a brief_id
  And running the same command a second time prints the identical brief_id

Given a second brief file whose content is byte-identical to the first but whose
      filename differs
When  `axial brief show` runs on it
Then  the printed brief_id is identical to the first file's brief_id

Given a brief file with a `case` key that is absent or an empty string
When  `axial brief show` runs on it
Then  the command exits non-zero with a logged reason naming `case`, and no
      partially-constructed brief is emitted
```

## Out of scope
- The interrogation pre-pass and interrogation result (§7.2, P0-1) — the first
  Phase-B model call, a later sprint.
- `axial brief run` / `axial brief examine` (P0-9); only read-only `show` lands here.
- Resolving `lens` against `config/lenses/` — `lens` is validated as an optional
  string only (§7.1).
- The founder's 26 dev briefs — slice 03, blocked on the founder.
- Any writing under `data/analyses/`.
