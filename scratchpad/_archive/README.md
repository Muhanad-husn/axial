# Retired measurement instruments

One-off scripts written to answer a question that has since been answered.
Retired 2026-08-06. They are kept because the method is often worth rereading
even when the number is settled, but none of them is wired to anything and
none is expected to run again against the current corpus.

Every one of these predates changes to the code it measures. Treat a rerun as
a rewrite, not a rerun.

| Script | Measured |
| --- | --- |
| `measure_504.py` | #504, the name-layer rekey |
| `validate_490.py` | #490 |
| `validate_498.py` | #498, acronym merge |
| `validate_500.py` | #500 |
| `validate_508.py` | #508 |
| `validate_511.py` | #511 |
| `validate_677.py` | #677 slice A, incremental fit |
| `validate_677b.py` | #677 slice B, incremental map bags |
| `validate_677c.py` | #677 slice C, reuse counters |
| `validate_677c_discriminate.py` | #677 slice C, the discriminating arm |

The instruments still at the top of `scratchpad/` were kept deliberately by
`84edec8` (the #695 and #700 instruments) and `c453df6` (the corpus-shape
counter behind the 35-book report). Those are live. Do not retire them here
without the same kind of decision.
