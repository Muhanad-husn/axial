# The analyst web client

The browser face of the analyst service (`src/axial/service/api.py`). It posts
an ask, streams the walk, and renders what comes back. No logic about
retrieval, composition or evidence lives here.

```
npm install
npm run dev          # http://localhost:3000
```

`AXIAL_API_BASE` is where the service lives, read when the Next server starts
(default `http://127.0.0.1:8000`). The browser only ever calls `/api/*` on this
origin, which `next.config.ts` proxies onto it — so the service needs no CORS
configuration and its address is never baked into the bundle.

This server sends nothing compressed (`compress: false`, issue #748): gzip
buffers, and a buffered `text/event-stream` means the walk of a fourteen-minute
ask arrives fourteen minutes late. Compress the bundle at the CDN or reverse
proxy in front of it instead.

```
npm run lint         # eslint
npm run typecheck    # tsc --noEmit
npm test             # vitest: the SSE reducer and theme resolution
npm run build        # next build
npm run test:e2e     # playwright, against e2e/mock-service.mjs
```

`npm run test:e2e` needs no Postgres and no worker: it builds the app, starts it
against a stand-in service, and drives a real browser through submit → walk →
answer, a resume across a dropped connection, a killed API, and the theme.

The twelve theme custom properties live in `src/app/globals.css`; the approved
design they come from is `design/mockup.html`.
