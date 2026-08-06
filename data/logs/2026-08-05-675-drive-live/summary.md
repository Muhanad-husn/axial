# The Drive connector, proven live (#675)

2026-08-05. The first time this connector has ever talked to real Google. Run
from `D:\axial`, main at `29f980d` (PRs #692 and #693 merged).

**Result: the doorway works, and it recognised the corpus it already had.**

## Two runs

### 1. `axial sources --backend drive --check`

Before the rename, against the original Drive filenames. Console: `check.log`.

| | |
|---|---|
| listed / downloaded / language-gated | 34 |
| rejected | 0 |
| errors | 0 |
| downloaded | 209 MB |
| `fetch_state.json` written | **no** |

`--check`'s promise held: it classified without ingesting, and wrote no
fetch-state.

### 2. `axial sources --backend drive` — the real ingest

After the founder deleted the folder's contents and re-uploaded all 34 files
from `data/sources/` (already author-year named). Console: `ingest.log`.

| | |
|---|---|
| sources ingested | **34** |
| **model calls** | **0** |
| failures | **0** |
| extract / envelope / chunk | 34 **skipped** each |
| interrogate / artifacts | ran, found everything done, spent nothing |
| fetch-state entries | 34 |

Corpus after: 34 trees, 34 chunk artifacts, 34 answer files, 34 distinct source
ids. **No duplicates.**

The decisive line: `wedeen-2019-3ae1f7af318d` came back through Drive as exactly
the id the local ingest produced. Same book, same id, other doorway.

## What had to be fixed first

Both found by reading the code before spending, not by running into them.

**#692 — the ingest chain was a rotted copy.** It ran extract → envelope →
chunk → `run_vault_write`; that pass has raised unconditionally since #411, and
the copy never gained `interrogate` (#419) or `artifacts` (#674). Every Drive
candidate would have failed on its last step while missing the two passes that
give a book content at all. It now drives `axial.sources.DEFAULT_INGEST_PASSES`
through `run_pass`, so the done-predicates are consulted — invoking the registry
directly would have skipped them and re-chunked the corpus, reintroducing #672
through the other door.

**#693 — the cache named files by Drive file id**, and `source_id` is
`<filename stem>-<content hash>`, so the same book got two different ids off
identical bytes. This run would have matched nothing, re-ingested all 34 from
scratch (~$35–45), and written a duplicate corpus doubling every name page. The
cache is now `<cache>/<file id>/<drive name>`.

## The naming decision that made it work

Founder decision 2026-08-05: **one naming rule whichever door a book comes
through.** Rather than renaming 34 files in Drive by hand, the folder's contents
were deleted and re-uploaded from `data/sources/`. That is strictly better than
renaming — it makes the bytes identical *by construction*, where renaming leaves
byte-identity to chance and a single differing file would have produced a
duplicate corpus. Verified before the run: all 34 sizes matched local exactly.

Re-uploading gave every file a new Drive id, which is harmless — the id is only
a cache directory now, and the fetch-state manifest was empty.

## Caveat worth keeping

`interrogate` and `artifacts` report `ok`, not `skipped`, because they declare
the ledger done-predicate and the ledger carried no rows for them under this
path. They are internally resumable, which the **0 model calls** confirms. If a
future change makes either expensive to re-invoke, that reporting becomes
misleading — the cheap fix would be moving them to artifact-exists predicates,
as `chunk` moved in #672.

## Files

`check.log` · `ingest.log` · this summary.
