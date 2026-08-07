# Run: five papers off the Syrian case, and the reports updated to carry them

The two papers in the report's appendices D and E are both on Syria, because the
library is. This run drafted five more from smoke-v7 analysis records that ask
about something else, so the paper set is not one case repeated.

## Command

```
for b in mann-tilly-mechanism-or-rival what-later-accounts-did-to-quasi-states \
         transnistria-dual-dependency somaliland-remittances-instead-of-a-patron \
         sectarianism-manufactured-not-disclosed; do
  .venv/Scripts/axial paper draft config/paper_briefs/dev/$b.yaml
done
```

## Input

Five analysis records copied into `data/analyses/` from
`data/runs/smoke-v7/analyses/<case>/draw0/`, all on corpus pin
`sim-2026-07-30` — the same pin as the S-02 paper of 2026-08-07, so the whole
set is comparable. Five new paper briefs under `config/paper_briefs/dev/`, none
carrying a `title` key, so each paper is named by the shape check (#718).

`data/analyses/fa44475aaaa90a48.json` (S-03) already held a 15-claim record from
an unidentified earlier run under the same `brief_id`; it was replaced with the
12-claim smoke-v7 record so all five stand on one run. The previous file is in
the session scratchpad, not in the repo.

## Result

| Brief | Paper | id | Claims | Books | Conf. | Shape | Cost |
|---|---|---|---:|---:|---|---|---:|
| S-01 Mann vs Tilly | War, Extraction, and the Rent Rupture | `a1039fad4da31320` | 15 | 10 | low | strong | $0.0077 |
| S-03 quasi-states | Material Contests Over Juridical Arrangements | `f5ae5ff2f09766af` | 19 | 4 | medium | strong | $0.0101 |
| S-04 Transnistria | Dual Dependency and the Conversion Gap | `408378f2e286fff2` | 29 | **1** | low | strong | $0.0190 |
| S-05 Somaliland | Viable but Strained Diaspora Statehood | `273aea05df54e2df` | 46 | **1** | low | strong | $0.0188 |
| P3-04 Syria sectarianism | Sectarian Exclusion as Political Order | `5d866ef2ce4971ae` | 22 | 8 | low | strong | $0.0098 |

$0.0654 for the batch. All five `strong` on the shape check, no defects.

**Transnistria and Somaliland each cite exactly one book.** Both resolve to
Caspersen 2012, the only comparative study of unrecognised states on the shelf,
and the shelf holds no monograph on either territory. Every mechanical gate
passes and the shape check rates both `strong`, which is the point worth
recording: the gates measure construction, not evidential sufficiency. This is
the same corpus gap the sealed panel found in the report's section 7.4, visible
here before any reviewer was asked.

**Confidence came out `low` on four of five against records that all say
`medium`.** With the S-02 paper of the same day that is 5 of 6 single-record
papers, so the earlier note asking whether a single-record paper is structurally
penalised by the coverage disclosure now has a denominator worth acting on.

**One retry.** `UnknownDerivationError` on section s4 of the Transnistria paper,
attempt 1 of 3, recovered. Once in 35 draft calls over 34 sections.

**The plan pass is the fat tail.** Same model across five papers: 811 to 6,247
completion tokens, 9s to 95s. The 95s plan was the slowest single call in the
batch by 4× over the slowest draft call, and prompt size does not explain it —
the longest prompt produced a 1,871-token plan in 35s.

## Reports updated

- `data/reports/axial-report.md` → **v2.2**. New **Appendix F**, generated from
  the live records by `build_report_v2.py` (`FURTHER_PAPERS` + a
  `<!--PAPER_INDEX-->` marker), listing all six papers not reproduced in full.
  Old appendices F and G renumbered to G and H. Executive summary and §8 now
  carry the single-source finding.
- `data/reports/axial-technical-report.md` → **v1.1**. New **§8.4** on what a
  paper costs measured across eight, and a limitations entry on widening the
  question set exposing the shelf rather than the engine. The abstract's paper
  cost moved from `$0.12–0.16` to `$0.008–0.20`, which is the measured span of
  the eight records now on disk.
- Both synced to `docs/reports/`; `docs/index.html` panel intro bumped to v2.2.
- The technical `.docx` must be rebuilt with `build_docx_with_diagrams.py` —
  `md_to_docx.py` alone drops all ten mermaid figures and shrinks it from 1.5 MB
  to 87 KB. Noted in `data/reports/README.md` so the next person does not repeat
  it.

## Next steps

- The confidence gap (5 of 6 papers rating below their own source record) is now
  worth an issue rather than another observation.
- Two single-source papers name the acquisition target precisely: a monograph on
  Somaliland and one on Transnistria, or the unrecognised-states questions stay
  unanswerable at any drafting quality.
- None of the six went to the sealed panel. The report says so in Appendix F;
  it should stay true or be re-measured, not quietly widened.
