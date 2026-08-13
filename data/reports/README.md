# Reports

The reader-facing documents about Axial, the prose they are assembled from, and
the scripts that assemble them.

## What is here

| | |
|---|---|
| `axial-report.md` / `.docx` | **The report.** What Axial is, how it works, how it was tested, what it cannot do, two papers in full and the rest indexed — structured as a research paper with an executive summary. Version 2.3. |
| `axial-technical-report.md` / `.docx` | **The engineering companion.** Architecture, measurement discipline, caching, evaluation machinery, and the one-operator agentic process. Hand-written, not generated. Version 1.2. Its `.docx` is built by `build_docx_with_diagrams.py`, not `md_to_docx.py` — the plain converter drops the ten mermaid figures. |
| `axial-coverage-v2.md` | **The library, measured.** What the thirty-five books actually cover, page by page, and where the shelf is thin. Counted mechanically; no model judged anything. |
| `axial-coverage-v1-to-v2-diff.md` | What the four books added on 2026-08-05 changed. |
| `axial-logo.png` | Used by both reports. |
| `names-by-kind/` | **The name layer, counted.** One summary row per name kind, one per interrogation question, and the same per question per source. The row-level tables beside them — every name page, and the substance its member notes carry — are gitignored; rebuild them when you need them. |
| `source/` | The hand-written prose the dossier is built from. **Edit here, never in `axial-report.md`** — that file is generated and any edit to it is lost on the next build. |
| `build/` | The assemblers. No product code depends on them and they depend on no product code. |
| `_archive/` | Superseded versions, kept rather than deleted. |

## Rebuilding the dossier

```
uv run python data/reports/build/build_report_v2.py     # source/ + live artifacts -> axial-report.md
uv run python data/reports/build/md_to_docx.py axial-report
```

The build reads the live corpus for three things — the per-book table in
appendix C from `data/vault/notes.db`, the two papers reproduced in full in
appendices D and E, and the index of every other paper in appendix F, all from
`data/papers/` and `data/analyses/`. So the numbers in those sections track the
corpus, and the prose does not. Adding a paper to the report means adding its id
to `PAPER_FILES` or `FURTHER_PAPERS` in `build_report_v2.py` and rebuilding;
nothing about it is typed by hand.

`build/md_to_docx.py` takes a filename stem, so it renders the coverage report
too (`md_to_docx.py axial-coverage-v2`).

## Rebuilding the name census

```
uv run python data/reports/build/names_by_kind.py     # -> names-by-kind/_index.csv + one CSV per kind
uv run python data/reports/build/answers_census.py    # -> questions.csv, questions-by-source.csv, name-substance.csv
```

Both read only what is already on disk — `data/vault/names.jsonl`, the name
pages, `data/names/`, and `data/answers/`. No model is called and nothing is
re-asked, so either can be re-run at any time for free. Two minutes for the
pair over thirty-five books.

Four states are kept apart per question and never collapsed (§7.15, D7): an
answer, the explicit `not-in-passage` abstention, an empty list — which on a
multi-valued field is an answer, not a refusal — and a missing key, which is a
record that was never asked.

## What may be committed here

This is the one directory where `.gitignore`'s by-filename copyright allow-list
is relaxed to a by-directory one, so the test moves onto whoever adds a file.

**Allowed:** the operator's own prose, counts, prices, model names, source and
chunk ids, section headings, and Axial's own generated output — a rendered paper
is Axial's writing, not a book's.

**Not allowed:** passage text, note bodies, name-page evidence, or any other
verbatim run of a source.
