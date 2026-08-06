# Reports

The reader-facing documents about Axial, the prose they are assembled from, and
the scripts that assemble them.

## What is here

| | |
|---|---|
| `axial-report.md` / `.docx` | **The dossier.** What Axial is, how it differs from the tools a reader already has, every question it asks, how it was tested, what it cannot do, and both papers in full. Version 2.0. |
| `axial-coverage-v2.md` | **The library, measured.** What the thirty-five books actually cover, page by page, and where the shelf is thin. Counted mechanically; no model judged anything. |
| `axial-coverage-v1-to-v2-diff.md` | What the four books added on 2026-08-05 changed. |
| `axial-logo.png` | Used by both reports. |
| `source/` | The hand-written prose the dossier is built from. **Edit here, never in `axial-report.md`** — that file is generated and any edit to it is lost on the next build. |
| `build/` | The assemblers. No product code depends on them and they depend on no product code. |
| `_archive/` | Superseded versions, kept rather than deleted. |

## Rebuilding the dossier

```
uv run python data/reports/build/build_report_v2.py     # source/ + live artifacts -> axial-report.md
uv run python data/reports/build/md_to_docx.py axial-report
```

The build reads the live corpus for three things — the per-book table in
appendix C from `data/vault/notes.db`, and both papers with their underlying
questions from `data/papers/` and `data/analyses/`. So the numbers in those
sections track the corpus, and the prose does not.

`build/md_to_docx.py` takes a filename stem, so it renders the coverage report
too (`md_to_docx.py axial-coverage-v2`).

## What may be committed here

This is the one directory where `.gitignore`'s by-filename copyright allow-list
is relaxed to a by-directory one, so the test moves onto whoever adds a file.

**Allowed:** the operator's own prose, counts, prices, model names, source and
chunk ids, section headings, and Axial's own generated output — a rendered paper
is Axial's writing, not a book's.

**Not allowed:** passage text, note bodies, name-page evidence, or any other
verbatim run of a source.
