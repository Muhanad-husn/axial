# 819 — the reverse pass over `data/envelopes/`

Real-corpus validation of `scan_orphaned_envelopes`, the check that would have
caught #816 sixteen days earlier. No model call, nothing written under `data/`,
$0.00.

## What it does

It asks the corpus pin's own precondition without committing to it:
`axial.eval.corpus_pin.unresolvable_sources` — the pin's envelope enumeration
and stem resolution, collected instead of raised. Not a second implementation,
so the check can never disagree with the pin about whether a corpus is
analysable.

## Command

```
uv run axial sources --backend local --check            # the healthy corpus
python -c "cli.main(['sources','--backend','local','--check'])"   # the break
```

The break arm hardlinked 34 of the 35 real sources into `D:/tmp-819-fake-sources`,
omitting `beshara-2011.pdf`, and drove the real CLI entrypoint against it with
only `axial.sources.CORPUS_SOURCES_DIR` repointed — the real `data/envelopes/`
was read as-is, all 35. Hardlinks, so no bytes were copied and `data/sources/`
was never touched; the scratch directory was removed afterwards and
`data/sources/` still holds 35 files.

Full transcripts: `cli-demo.txt` (three arms), `test-run.txt` (suite and lint).

## Result

| arm | envelopes | raw files | orphans | exit | stderr |
|---|---|---|---|---|---|
| real corpus, healthy | 35 | 35 | 0 | 0 | 0 bytes |
| `beshara-2011` withheld | 35 | 34 | 1 | **1** | the block below |

```
error: the corpus pin cannot be computed -- 1 ingested source(s) have no raw file:
name                            status     reason
beshara-2011-8410a9059300       missing    no raw source file found for source_id
                                           'beshara-2011-8410a9059300' under
                                           D:\tmp-819-fake-sources (looked for .docx, .pdf)
```

The break arm named exactly the source that really broke. The healthy arm
printed 35 `done` rows on stdout, **zero bytes on stderr**, and exited 0.

## The check and the pin agree, on the real corpus

```
healthy (35 files)     check: 0 orphan(s)   pin: computes: 9b796b3a6312b329
withheld (34 files)    check: 1 orphan(s)   pin: MissingSourceFileError
```

`9b796b3a6312b329` is the map build already on disk from 2026-08-06 — the real
corpus and the real pin, not a fixture.

## Timings, each measuring one thing

| | |
|---|---|
| the reverse pass alone, healthy corpus | **25.4 ms** |
| the reverse pass alone, withheld arm | **26.9 ms** |
| the whole `axial sources --check` command | 0.61 s |

It hashes nothing — resolution is by filename stem, exactly as the pin does it —
so cost is a directory listing plus one `Path.exists()` per envelope, and does
not scale with corpus bytes.

## What two review passes caught that the green suite did not

1. **The first cut exited 0 on a broken corpus.** `sources_dir: Path =
   CORPUS_SOURCES_DIR` in the signature binds once at import, so the demo's
   repoint of the module constant was ignored and the check read the real
   healthy corpus. Ten green unit tests said nothing — each passes its
   directories explicitly. All three of `scan_local`, `sync_local` and
   `scan_orphaned_envelopes` now resolve at call time, each with a test.
   `sync_local` is the one that writes, so a script repointing the module
   would have scanned a fixture and ingested from the real corpus.
2. **The first predicate was the wrong one.** It matched by full `source_id`,
   i.e. by content hash. The pin resolves by filename **stem**. They disagree
   in exactly one case: replacing a source with corrected bytes moves its
   `source_id` and leaves the old envelope behind under the same stem — the
   pin still computes, but a hash-matching check would report that stale
   envelope `missing` and fail `axial sources` permanently, naming no remedy.
   The predicate is now the pin's own, with six tests asserting the two agree
   including that case.

## What it does not fix

#816 hid for sixteen days because nothing ran the argument-map arm. A check
nobody invokes hides the same way. This makes the break visible to a command
that already exists and is already free; it does not make anyone run it.

## Suite

`uv run pytest` — 2,621 passed (2,598 baseline + 23 new). `uv run ruff check`
clean.
