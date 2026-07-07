# feat(minimal-ingestion): intake — format & text-layer validation [slice 01]

**Spec:** specs/PRODUCT.md §5 (stage 1), §8 P0-1 · **Plan:** plans/minimal-ingestion/01-intake.md
**Depends on:** none (phase-1 schema-loader merged)
**Labels:** sub:ingestion-v0

## Deliverable

`axial intake <file>` accepts a born-digital `.pdf` or `.docx` that has a real
text layer and exits 0 with a source-metadata stub; it rejects any other
extension and any file with no text layer (scanned/image-only PDF) with a nonzero
exit and a clear logged reason. The pipeline's front door and the corpus boundary
that keeps OCR-less scanned files out (§3 non-goal, §10 "zero silent pass-through").

## Acceptance criterion

```gherkin
Given a born-digital fixture PDF with a text layer and a fixture DOCX with text
When  the user runs `axial intake <fixture>`
Then  it exits 0 and emits a source-metadata stub naming the file and detected format
And   against an image-only/no-text-layer PDF it exits nonzero with a message stating no text layer was found
And   against an unsupported file (e.g. .txt/.png) it exits nonzero naming the rejected extension
```

## Out of scope

Content parsing (slice 02); OCR (permanent non-goal); Google Drive sourcing
(P0-11); author/title/date extraction (arrives with the envelope, slice 04).
