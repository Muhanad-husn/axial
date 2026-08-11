# Run: the #744 web client against a live API, worker and corpus

2026-08-11. The first time the analyst client (#744, merged as PR #747) met the
real service instead of `web/e2e/mock-service.mjs`. One real ask, submitted from
a browser, against a real FastAPI service, a real worker bound to a published
snapshot, and a real model.

**Result: the ask worked perfectly and the client did not. The walk — the one
feature #744 is named for — renders nothing, in production as well as dev,
because Next gzips the event stream. Filed as #748.**

## The stack

| Piece | How |
|---|---|
| Postgres | `postgres:16-alpine` in Docker, port 55744 |
| Schemas | `JobStore` / `QuotaStore` / `PaperCache` `.create_schema()` |
| Service | `uvicorn axial.service.api:app --factory`, port 8000 |
| Worker | `scratchpad/live744_worker.py`, bound to `data/snapshots/2026-08-10-v1` |
| Client | `next dev` on 3000; `next start` on 3100/3200 for the production reading |

There is no compose file yet (#691), so this was assembled by hand. Two things
that bit and are worth writing down:

- **`uv sync --group service` REMOVES the other groups.** It took out
  `scikit-learn`, `sentence-transformers` and `unidecode`, which the retrieval
  path needs. `uv sync --all-groups` is the correct call.
- **Build the `LLMClient` before `Snapshot.bind()`.** `bind()` is an `os.chdir`
  into the snapshot root, and `get_client()` resolves `config/pipeline.yaml` and
  `secrets/secrets.toml` relative to cwd. Set `AXIAL_SECRETS_PATH` absolutely as
  a second belt.

## The ask

> **Case:** Syria under the French Mandate and the early Ba'th
> **Question:** Did the French Mandate's administrative practices shape the
> Ba'th party's later strategies of rule, or is that continuity read backward?

| | |
|---|---|
| State | `done` |
| Cost | **$0.1355** |
| Tokens | **363,011** |
| Duration | **14m 9s** (849s) |
| Events | 37 |
| Claims | 15 — 7 (a), 5 (b), 3 (c) |
| Corpus pin | `sim-2026-07-30` |
| Models | interrogate/retrieve `deepseek-v4-pro`, synthesize `gpt-5.6-luna`, counter-position `glm-5.2`, fork-check `deepseek-v4-flash` |

Every claim carried grounds. `GET /asks/{id}/paper` served 78,811 bytes as
`{record, metrics}` with the metrics block exactly as #724 specified — a good
real payload for #745 to render against, rather than a hand-written fixture.

**14m 9s, not the "about three minutes" the question box promises.** That copy
is item 2 on #748.

## The bug

The screen sat on `Queued · 41s` with an empty walk while the database already
held 17 events. Console: `ERR_INCOMPLETE_CHUNKED_ENCODING`.

Next compresses responses by default, including the `text/event-stream` proxied
through the `/api/*` rewrite. gzip buffers, so nothing reaches the client until
the stream closes.

Measured on the **production build**, same ask, same moment:

| Request | 25–30s of a live ask |
|---|---|
| `Accept-Encoding: gzip, deflate, br` (every browser) | **10 bytes, 0 events** |
| `Accept-Encoding: identity` | 9,103 bytes, 31 events |
| `compress: false` + browser-shaped | **9,887 bytes, 37 events** |

### Two things that hid it

- **The mock answers in under a second**, so gzip flushes at stream close and
  every event arrives at once. The e2e suite passes with or without the fix.
  Only a stream that stays open and goes quiet exposes this.
- **`curl` sends no `Accept-Encoding` unless asked.** The first reading here was
  "production is fine, this is a dev-only cut" — wrong, and wrong in the
  direction that would have shipped it. `--compressed` reversed the conclusion.

The dev server additionally cuts the stream at ~30–35s (`curl` exit 18,
`CURLE_PARTIAL_FILE`), which is a separate and much smaller problem hiding
behind the first one.

## What this says about testing this layer

A mock that is fast is not a stand-in for a service that is slow. Every timing
property of this client — the walk, the resume, the retry budget, the elapsed
clock — is invisible to a stand-in that finishes before the first render. #748's
deliverable is a stand-in that **goes quiet mid-stream**, not the one-line config
change.

## Next steps

- #748 fixes the compression, the copy, and the `next dev` file pollution, with
  a regression test proven to fail without the fix.
- Re-run this exact validation against the fix, on the live stack, before #745
  starts.
- #691 (one compose file, documented env) would have saved most of the setup
  above.
