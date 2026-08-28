# #816: the map arm's missing raw source, restored

**Run:** 2026-08-28, `D:/axial` on `main` at `4b4d977`. Corpus repair, no code
change. Total spend **$0.1198**, all of it the one map-arm draw.

## What was missing

`data/chunks/` held 35 ingested sources, `data/sources/` held 34.
`beshara-2011-8410a9059300` — Beshara, Adel, ed., *The Origins of Syrian
Nationhood*, Routledge 2011, `docs/corpus-bibliography.md` line 35 — had a
structural tree, chunks, an envelope, answers, artifacts and vault pages, but
no raw PDF. `axial.argmap.ask` computes the corpus pin, which hashes every
ingested source's raw file, so the map arm died at the pin while the name arm,
which never computes it, ran green.

The file was not elsewhere on this box: a full search of `D:` and of the user
profile found no `beshara*.pdf`/`.docx` anywhere. Cause of the disappearance
not established; `data/sources/`'s directory mtime is `2026-08-12`, the day of
the compose-live run (#691), but nothing in that run's log names a source move.

## Where the file came from

Google Drive, unrenamed and untouched. `data/drive/fetch_state.json` records
34 Drive file ids with their `md5Checksum`; hashing the 34 local files and
diffing left exactly one Drive id with no local match:

```
<beshara-2011-drive-file-id>  md5=064df9385cb189d12cf31e95946911d8
```

Listing the Drive `Books` folder confirmed it: 35 files, one of them
`beshara-2011.pdf`, `modifiedTime` `2026-07-24T13:15:32Z` — never renamed,
never re-uploaded. Downloaded directly through `axial.drive.DriveClient`
(the `[drive]` service-account credentials in `secrets/secrets.toml`) to a
scratch path, verified there, then copied to `data/sources/beshara-2011.pdf`.
3,086,823 bytes. Nothing under `data/` was deleted, overwritten or re-ingested.

`axial drive ingest` would have been a no-op: `_is_unchanged` skips a candidate
whose recorded `modifiedTime` and `md5Checksum` match the fetch state, before
downloading. All 34 recorded ids match, this one included.

## The pin

Byte-identity, not resemblance, is what makes the repair real. Three checks,
all against values recorded before the file went missing:

| check | recorded | live | |
|---|---|---|---|
| `beshara-2011` content hash, `evals/corpus_pin/sim-2026-07-30.json` | `8410a9059300a22b883d8816d3e5104fa3a1967b5c6ffa3ed33c36dd117bc2ac` | same | match |
| all 31 sources in that committed pin | 31 hashes | 31 hashes | 0 mismatches |
| `compute_corpus_pin(data/envelopes, data/sources)` | `9b796b3a6312b329` (the map build on disk, 2026-08-06, 35 sources) | `9b796b3a6312b329` | match |

Every `data/analyses/*.json` record carries `corpus_pin: "sim-2026-07-30"` —
the manifest name, not a digest — and that manifest's `beshara-2011` entry is
the exact sha256 of the restored bytes. The `source_id` suffix is the first 12
hex of the same digest, which is the third, independent confirmation.

The committed manifest covers 31 sources and the corpus is now 35, so the
whole-manifest digest cannot match and was never the right test; the per-source
hashes are. The live map-arm pin resolves to the existing paid map build, so
the draw below reused it rather than rebuilding.

## The map arm runs

```
uv run axial brief sweep data/logs/2026-08-28-816-map-arm-restore/worklist.txt \
  --draws 1 --sweep-dir data/runs/816-map-check --workers 1 --arm map
```

Detached, `AXIAL_SECRETS_PATH=secrets/secrets.toml`, one brief
(`config/briefs/smoke/S-03.yaml`), one draw.

| | map arm (this run) | name arm (2026-08-28, same brief) |
|---|---|---|
| draw | OK, 344.4s | OK, 690.4s |
| cost | $0.1198, 139,152 tokens | $0.1821, 208,839 tokens |
| `distinct_sources_cited` | 5 | 4 |
| attribution-fidelity | PASS | PASS |
| grounding | PASS | PASS |
| calibration | PASS | PASS |
| synthesis-quality | **FAIL** | PASS |

The pin no longer fails. The one gate that does is `synthesis-quality`:
`counter_position_presence_rate` 1.0 (PASS, threshold 0.95), `steelman_quality`
**0.0** against a 0.9 threshold, n=1. The counter-position is present but is not
an opposing one — its stance reads "Later accounts primarily confirm rather than
extend or contest Jackson's concept of quasi-states", grounded on two chunks
from `jackson-1990` and `caspersen-2012`, with `corpus_one_sided: false`.

That is the map arm's known weak link (the argument-map counter-position, not
the substrate), on n=1, and it is a finding for #809's comparison rather than a
defect in this repair. One draw is the whole budget; it was not re-run.

## Not done, deliberately

- No code change, no commit, no branch. The corpus pin implementation was not
  touched; making the map arm tolerate a missing raw file is a separate question.
- `beshara-2011` was not re-ingested, re-extracted or re-chunked.
- The raw-source completeness check the issue proposes is still unbuilt.
