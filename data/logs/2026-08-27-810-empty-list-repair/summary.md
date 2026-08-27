# Repair: the string "[]" stored where an empty list belongs

Issue [#810](https://github.com/Muhanad-husn/axial/issues/810), data half.
2026-08-27. Zero model calls, zero cost, corpus pin unmoved.

## What was wrong

Thirty-eight answer records stored the two-character string `"[]"` as the whole
value of a list-valued field, rather than the empty list `[]`. On disk:

    "arguing_against": "[]"

`_is_blank` in `src/axial/interrogate.py` returns False for it, because
`not "[]".strip()` is False, so it passed through as a real answer.

Note the shape: this is a **scalar string**, not a list containing the string.
An earlier reading of the same count described it as a list element. That was
wrong and is corrected here and in the issue.

## Counts

| Field | Records |
|---|---|
| arguing_against | 17 |
| defines | 15 |
| citations | 4 |
| uses | 2 |
| **total** | **38** |

Across 13 source files. Per-source counts in `run.jsonl`.

## What was done

A regex replacement of `"<field>": "[]"` with `"<field>": []`, applied only to
the six list-valued fields, on the raw file text. Every changed line was then
parsed before and after and compared key by key; a file was refused rather than
written if any value other than the intended field moved. No file was refused.

Editing the raw text rather than re-serialising the records is what keeps every
other byte identical: no key reordering, no whitespace drift, no unicode
re-escaping across 15 MB of answers.

## Verification

    grep -c '": "\[\]"' data/answers/*.jsonl   ->   no matches

## Backup

The 13 files as they stood before the repair are in the session scratchpad at
`backup-810/`. That is session-scoped and will not survive; the durable record
is this log plus git history on the code half.

## What this does not do

It does not stop new bad records being minted. That is the code half of #810,
built test-first on `fix/810-empty-list-as-a-string`.
