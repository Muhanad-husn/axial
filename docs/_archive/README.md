# Retired docs

Measurement instruments and outreach paths whose work is done, or whose path is
no longer followed. Retired 2026-08-06. Nothing here is a statement about
current behavior — the specs under `specs/` and the code are. These are kept for
the reasoning they record.

`docs/tdd-evidence/` was deleted rather than archived: 193 terminal transcripts
produced by the v1 role-ceremony harness, which v2 tore out. Nothing writes that
directory and nothing in the repo reads it. Git holds the history.

| File | What it was |
| --- | --- |
| `02-hybrid-tagging-distillation.md` | Eval 2, the cost axis: distilling the tag axes off the LLM. The tag pass is deleted. |
| `03-agentic-trajectory.md` | Eval 3, the process axis. A stub whose stated dependency, a full 24-source re-run, is long past; nothing was built from it. |
| `04-frozen-tag-distribution.md` | The distribution of tags that no longer exist. |
| `hybrid-tagging-classifier.md` | The hybrid classifier exploration, same dead layer. |
| `tag-reliability-best-of-n-external.md` | The plain-language companion to a retired tagging pass. The main note stays at `docs/`: its §2.11 lesson 4 is still applied in `merge_names.py`. |
| `outreach-letter.md` | The letter to academic referees. The real-academic path closed with #250 and #295. |
| `request-gold-labels.md` | A request for labels from an annotator who will never exist. |
| `about-axial.md` | The companion to the outreach letter: how Axial differs from RAG, hybrid RAG, a ChatGPT upload, and web "deep research". Retired 2026-08-06 with the rest of that path. It also describes the v0 product, down to "coded every passage by the kind of claim it makes", so it is wrong twice over. Its argument against retrieval survives in `README.md`. |
| `gold-coder.md` | The gold-labelling dispatch method (DEC-30). The gold set and its scoring harness were deleted with #710; there is nothing left to label. |
| `sim-academic-gold-labelling.md` | The gold-labelling measurement record: inter-annotator agreement on the retired v0 tag axes. Retired 2026-08-06 with the gold set (#710). The live half of that folder stays at `docs/sim-academic/`. |
| `phase-a-rerun-2026-07-24.md` | A run report. `data/logs/<date>-<run>/` owns those now. |

`docs/academic/` is gone as a folder. It existed to brief outside academics, and
with the letter, the label request and `about-axial.md` all retired, the only file
left was the corpus bibliography, which is not about that path at all. It now sits
at [`docs/corpus-bibliography.md`](../corpus-bibliography.md), current at 35
sources.
