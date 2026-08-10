# Run: the first real-corpus `axial publish` (#684)

Real-corpus validation of the snapshot publisher built for issue #684, run
before the PR was opened. A green suite was not evidence: the run found two
defects the 57-test suite could not see, and settled the wall clock and disk
cost the slice had left unmeasured.

## Command

```
$env:PYTHONPATH="D:\axial\.claude\worktrees\684-corpus-snapshot\src"
uv run --directory D:\axial axial publish 2026-08-10-v1
```

Branch code (`feat/multiuser-analyst-service/684-corpus-snapshot`) run against
the main checkout's `data/`, because `data/` is gitignored and does not exist in
a worktree. `axial.__file__` was verified to resolve into the worktree before
the run, so this measured the branch and not `main`.

Console output: `console.log`.

## Result

| | |
|---|---|
| Elapsed | **92 s** |
| Total | **55,570 files, 959.6 MB** |
| `corpus_pin` | `sim-2026-07-30` |
| `map_pin` | `9b796b3a6312b329` |

| Directory | Files | Size |
|---|---:|---:|
| `vault/` | 55,420 | 213.2 MB |
| `names/` | 29 | **737.0 MB** |
| `map/9b796b3a6312b329/` | 6 | 9.1 MB |
| `config/` | 73 | 0.1 MB |
| `envelopes/` | 35 | 0.2 MB |
| `evals/corpus_pin/` | 6 | 0.0 MB |

**The name layer is 77% of a snapshot, and it is almost entirely LanceDB** — 29
files carrying 737 MB. The 55,420 vault files most of the wall clock goes on are
a fifth of the bytes. A worker image is roughly 1 GB per corpus version, and
that number is set by the embeddings, not by the notes.

**The map pin resolved to the right one of three.** Verified independently
rather than read off publish's own output: `compute_corpus_pin(live envelopes,
live sources)` is `9b796b3a6312b329`, and that is the only one of
`297bcfa93d6974b0 / 3c49f2e5a035fbc3 / 9b796b3a6312b329` under `data/map/` that
was copied.

**The published snapshot binds and reads.** After `Snapshot.bind()`: vault,
names, envelopes, map and `config/lenses` all resolve inside the snapshot;
`sources` correctly does not exist; `resolve_pin_id()` returns
`sim-2026-07-30`; `notes.db` reports 6,842 notes and 47,584 names; the
209-character longest name page opens; and `find_names("Ba'th")` returns
`Ba'th Party` (280 members), `Ba'th regime` (15), `Syrian Ba'ath party` (5).

## What the run caught that the suite could not

**1. `axial publish` published nothing and exited 0.** The `publish` subparser's
positional was named `version`, which writes to the same argparse dest as the
global `--version` flag (`cli.py:194`); `main()` tests that flag before
dispatching any command, so `axial publish 2026-08-10-v1` printed `axial 0.1.0`
and returned success having created no directory. The slice's own tests called
`publish()` directly and never went through `main()`. Fixed by renaming the
positional's dest (`metavar` keeps the surface syntax), and pinned as a class
rather than an instance: a new test walks every subparser and asserts no
subcommand argument shadows a global dest. `publish.version` was the only
instance in the parser.

**2. Publishing then crashed at 148 s on Windows MAX_PATH.** Three
`[WinError 3]`s on name pages. A note's filename is budgeted at write time
against the vault's own directory (`axial.paths.chunk_note_path`), so a longer
staging path pushes correctly-written pages over the limit — the staging name
`.{version}.{uuid4().hex}.tmp` added 33 characters. Fixed twice over: staging is
a fixed, short `.publishing`, and the budget is now checked before any copying
using `axial.paths.path_overage`, the same function the writer budgeted with and
the reader resolves with, so a snapshot that publishes is guaranteed readable.

**Margin on this corpus is 3 characters.** Longest relative path 203
(`vault/names/L'autre et nous- «Scènes et types»….md`), total 247 against a
250 budget. A longer version name or a deeper `--snapshots-dir` is now refused
up front, naming the file and the overage, instead of failing mid-copy.

## Outlier

**The manifest says 31 sources; `data/envelopes/` holds 35.** Not a publish
defect: `evals/corpus_pin/sim-2026-07-30.json` is the corpus's only pin manifest
and predates the three books added in #623. A snapshot published today therefore
carries a pin that under-reports the corpus it contains, and the pin is what
every answer is checkable against.

## Next steps

- Run `axial pin write <name>` before publishing any snapshot that will be
  served to an analyst, so the pin covers all 35 sources.
- The 959.6 MB artifact at `data/snapshots/2026-08-10-v1/` (gitignored) is left
  as this run's evidence and a ready-made snapshot. Delete when unwanted.
