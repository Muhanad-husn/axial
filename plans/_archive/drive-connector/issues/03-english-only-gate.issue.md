# feat(drive-connector): English-only language gate — reject-and-log non-English sources [slice 03]

**Spec:** specs/PRODUCT.md#7.10 · §8 P0-11c · **Plan:** plans/drive-connector/03-english-only-gate.md
**Depends on:** #<slice 01 issue>
**Labels:** sub:ingestion-v0, enhancement

## Deliverable
Before a downloaded source is handed to ingestion, the connector detects its
language deterministically from a bounded text probe (`language_probe_chars`
leading characters) using a `langdetect`/`lingua`-style detector. An English
source at or above `language_accept_threshold` passes; any other source is
**rejected before extraction** and logged with a reason naming the detected
language and confidence — never a silent pass-through. The gate runs only on
sources that carry a text layer (scanned / no-text-layer sources are already
rejected at intake, P0-1). Both tunables are read from config, not hardcoded.

## Acceptance criterion
```gherkin
Given a fake Drive client for folder "BOOKS" with two candidates —
      "english.pdf" whose text probe is English prose and
      "french.pdf" whose text probe is French prose
When  `axial drive ingest BOOKS` runs with the fake client and spy ingest injected
Then  "english.pdf" is handed to the ingest callable,
      "french.pdf" is NOT handed to the ingest callable,
      a rejection is logged for "french.pdf" naming the detected language and
      confidence, and the command exits 0 (a recorded skip, not a crash)
```

## Out of scope
- Multi-language corpora / per-language routing (English-only is a hard gate).
- Language detection on scanned sources (rejected upstream at intake).
- Tuning the probe size / threshold on the real corpus (stated starting tunables).

## Notes
- Adds a deterministic language-detection dependency (§12).
- Independent of slice 02; depends only on slice 01.
