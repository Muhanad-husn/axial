# Run: the whole #687 client against a live API, worker and corpus

2026-08-12. The second live validation of the analyst client, and the first for
#745 (the paper, the metrics panel, export) and #746 (history, the spend
meters) — both of which had only ever met `web/e2e/mock-service.mjs`. #744's
one live run found four bugs, so this one exists to find out whether the other
two slices have the same base rate.

**Result: the ask, the walk, the paper, the metrics, the meters, the cache path,
both themes, the phone layout and the honest failure are all correct against
the real thing. Two defects, both in history and reattachment, neither in the
parts that were rebuilt after #748.**

## The stack

Same hand-assembly as 2026-08-11 (there is still no compose file — #691):

| Piece | How |
|---|---|
| Postgres | `postgres:16-alpine` in Docker as `axial687-pg`, port 55744 |
| Schemas | `JobStore` / `QuotaStore` / `PaperCache` `.create_schema()` |
| Service | `uvicorn axial.service.api:app --factory`, port 8000 |
| Worker | `live687_worker.py`, bound to `data/snapshots/2026-08-10-v1` |
| Client | `next build && next start` on 3000 (production, not `next dev`) |
| Driver | `drive687.mjs`, Playwright out of `web/node_modules` |

The Chrome extension was not connected, so the client was driven by Playwright
rather than by hand. Every stage screenshots into `shots/` and journals into
`run.jsonl` with an fsync per record.

## The ask

> **Case:** Late Ottoman and Mandate Iraq
> **Question:** Did Ottoman land registration in the Iraqi provinces create the
> landholding class the British Mandate then governed through, or did the
> Mandate make it?

| | |
|---|---|
| State | `done` |
| Cost | **$0.0417** (month to date, across 3 asks, 2 charged) |
| Tokens | **155,992** |
| Duration | **9m 46s** (587s) |
| Events | 38 |
| Claims | 9 — 3 (a) stated, 3 (b) concluded, 3 (c) runs past |
| Confidence | low, capped by a thin coverage map |
| Corpus pin | `sim-2026-07-30` |

## What held

- **The walk renders live.** First event on screen **5.1s** after submit, 38
  events over 9m46s, growing the whole way. This is the exact failure #748 was
  filed for and it is fixed against a real slow stream, not just against a mock.
- **The copy is honest now.** "fifteen minutes or so" against a 9m46s ask —
  #748's second item, closed.
- **The paper.** Nine claims, each with its evidence marker and its locator
  citations, the legend under them. Renders correctly at 1440px and at 390px.
- **The metrics panel.** Collapsed by default, and open it carries cost and
  tokens per pass, model per pass, the coverage map and the confidence
  reasoning. Exactly what `record.py` writes.
- **The spend meters.** `$0.04` in both the session and month-to-date meters
  after the ask; `—` before it, which is `cost_usd: null` rendered rather than a
  false `$0.00`.
- **The cache path.** Re-asking the identical brief returned in **2.2s** with
  one event — "this exact brief has already been answered against this corpus"
  — a `cached · no cost` badge in history, the session meter at **$0.00**, and
  month-to-date unchanged at $0.04. The whole #686 story, correct end to end.
- **Both themes, both directions.** On a dark machine, system resolves dark and
  an explicit Light wins; on a light machine, the reverse. `data-theme` on the
  root and `body` background agree in all six combinations.
- **The phone.** 390×844: `scrollWidth == clientWidth` on the composer screen
  and on the paper screen, so nothing scrolls sideways. The paper is readable.
- **Honest failure.** `taskkill` on uvicorn three events into a live ask put
  "Lost contact with the Axial service" on screen **6.0s** later with the Ask
  button re-enabled. Not a permanent spinner.

## What did not — two defects

### 1. A history row does not say what was asked

Every row reads `DONE · corpus sim-2026 · 12/08/2026, 00:16:01 → 00:25:47 ·
Reopen`. No case, no question. Three asks in the list are distinguishable only
by their timestamps.

`GET /asks` returns `AskStatus`, which has no brief on it, so the client cannot
render one — this is an API gap, not a client one. The brief exists: `page.tsx`
already reads `paperState.paper?.record.brief` when a past ask is reopened, so
it is on the record and only the *list* endpoint omits it.

The `corpus sim-2026` chip makes it worse rather than better: it is
`corpus_pin.slice(0, 8)`, and every pin on this corpus begins `sim-2026`, so
the truncation keeps the constant half and drops the part that varies.

### 2. "Reload this page to pick it up" is a promise the client does not keep

The lost-contact error tells the analyst to reload. Reloading, with the ask
still `running` on the worker and the API back up, gives:

- an empty composer, no walk, no paper — `useAsk` holds the ask in React state
  with nothing persisted, so a reload starts from `askId: null`;
- a `RUNNING` row in history with **no Reopen button**, because `HistoryList`
  offers one only for `state === "done"`.

So the one ask that is still costing money is the one the analyst cannot watch.
Either the copy is wrong or the reattachment is missing; the reattachment is
the thing worth having, since the ask survives the API restart perfectly well
(this run's killed ask kept running on the worker throughout).

## Not a defect: the export downloads that "failed"

Every browser download of the paper reported `download.saveAs: canceled`, in
headless and headed Chromium, through the Next proxy and direct to FastAPI.
That is this machine, not the product: a control probe downloading **four
bytes** from a throwaway `http.Server` cancels identically.

The feature itself is provably correct at the HTTP layer:

| Format | Status | Bytes | Content-Type |
|---|---|---|---|
| `md` | 200 | 8,302 | `text/markdown; charset=utf-8` |
| `docx` | 200 | 39,339 | `application/vnd.openxmlformats-…wordprocessingml.document` |
| `odt` | 200 | 4,256 | `application/vnd.oasis.opendocument.text` |

with `content-disposition: attachment` on all three, and the `.md` carrying the
brief, the claims, the counter-position, the coverage map, the confidence, the
source usage and the metrics — the three things #687 asked a download to carry.

**Consequence for the suite:** a Playwright test that asserts a download cannot
pass on this box. Any export e2e has to assert the response, not the file.

## Observations, not filed

- After a finished ask the walk stays fully expanded above the paper — 38 lines
  between the question and the answer. Deliberate on a running ask; arguable
  once the paper is there.
- Citation chapter titles render as the source's own extracted heading, which
  in `ayubi-1995` is `T H E O T T O M A N S AND T H E MILITARY/IQTA'I
  SYMBIOSIS`. That is corpus data reaching the reader unchanged, which is what
  the client is supposed to do; whether extraction should have normalised it is
  a Phase A question.

## Next steps

- The two defects above, filed against #687.
- #687 closes when they land: everything else in its "Done when" is met, with
  the account half of "a link and an account" belonging to #688.
- #691 would still have saved most of the setup here.
