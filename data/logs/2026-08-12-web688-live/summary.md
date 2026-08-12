# Run: #688 sign-in against a real Supabase project

2026-08-12. The first live run for #688 — a real Supabase project, a real
invited account, a real token verified at the API edge. Both slices (#763 the
service edge, #764 the client) had only ever met locally-minted JWTs and a mock
service, and #687's live run is the standing evidence that a fast mock cannot
express the real thing.

**Result: all three of #688's "done when" bullets pass, and the run found one
defect that made the product unusable — five seconds of clock drift refused
every token, silently.**

## The stack

Hand-assembled again (#691 would still have saved most of this):

| Piece | How |
|---|---|
| Supabase | project `vmxqopfarajgqcrjrszk`, West EU (Paris), free plan, Data API off |
| Postgres | `postgres:16-alpine` as `axial688-pg`, port 55688 |
| Schemas | `JobStore` / `QuotaStore` / `PaperCache` / **`ProfileStore`** `.create_schema()` |
| Service | `uvicorn axial.service.api:app --factory`, port 8000, `AXIAL_SUPABASE_JWKS_URL` set |
| Worker | `live688_worker.py`, snapshot `2026-08-10-v1`, pin `sim-2026-07-30` |
| Client | `next build && next start` on 3000, built with the project URL + publishable key |
| Driver | the Chrome extension, driving the real browser; the founder typed every password |

Accounts, all created through the dashboard with public sign-up **off**:

| | UID | Used for |
|---|---|---|
| analyst A | `0a549b0e-8fca-407a-a786-92213b146f0b` | unused (password lost) |
| analyst B | `fdb6b798-8ac4-41c7-9012-535c668ddd65` | the ask |
| analyst C | `2ec028a3-69c6-4962-91a9-826bc58633b1` | the isolation and expiry probes |

## The defect that mattered: 5 seconds of clock drift locks everyone out (#767)

The first four sign-in attempts looked like nothing happened at all — the form
came back empty, no error. Supabase's own auth log told the real story:

```
06:36:55  Login
06:36:55  /token   | request completed
06:36:55  /logout  | request completed
```

Sign-in **succeeded** every time. The service then refused the token:

```
ImmatureSignatureError: The token is not yet valid (iat)
```

`verify_bearer_token` calls `jwt.decode` with no `leeway`, and this machine's
clock trails the Supabase project by **5.0 seconds**, so every freshly-issued
token is future-dated from the verifier's point of view. `api.ts` reads any 401
as a dead token and forces a local sign-out, so the analyst is thrown back to
the sign-in form with nothing on screen explaining why.

Fixed locally with `leeway=60` on `jwt.decode`; filed as **#767** for a proper
PR with regression tests. Everything below was measured with that fix in place.

**Two things this teaches beyond the one line of code.** A 401 from a clock
problem and a 401 from a forged token are indistinguishable to the client, and
both end as a silent sign-out — worth deciding whether the client should say
anything before dropping a session. And no test could have caught this: the
suite mints its own tokens with its own clock.

## Done when — all three

**1. An invited analyst signs in and runs an ask end to end.** Signed in as
analyst B with email/password, submitted a fresh brief, watched the walk stream
and the paper render.

| | |
|---|---|
| Case / question | Late Ottoman and Mandate Iraq — did Ottoman conscription and tax reform build the machinery the Mandate inherited, or did the Mandate build its own? |
| State | `done` |
| Cost | **$0.0739** |
| Tokens | 323,315 |
| Duration | **9m 42s** |
| Claims | 12, confidence medium |
| Corpus pin | `sim-2026-07-30` |

Both spend meters read `$0.07` afterwards, the history row carried the case and
the question (the #761 fix, live), and a full page reload kept the session —
#764's "stay signed in" bullet.

**2. An analyst sees only their own work, including by direct URL.** Signed out
of B, signed in as analyst C, and called every ask-scoped endpoint with C's own
verified token against B's ask id:

| Request | Result |
|---|---|
| `GET /asks` | `200 []` |
| `GET /asks/<B's id>` | `404 no ask with id …` |
| `GET /asks/<B's id>/paper` | `404` |
| `GET /asks/<B's id>/export?format=md` | `404` |
| `GET /asks/<B's id>/events` | `404` |

404 rather than 403 — it does not leak that the ask exists.

**3. An expired or forged token is refused at the edge.** Three cases, all
401 before any route body ran:

| Token | Result |
|---|---|
| none | `401 missing bearer token` |
| forged HS256, well-formed UUID `sub` | `401 invalid or missing bearer token` |
| genuine, 105s past `exp` | `401` on `/asks`, `/me/profile` and `/asks/<id>` |

The expired case was measured by dropping the project's token lifetime to 300s,
forcing a refresh, waiting it out, then probing (lifetime restored to 3600s
after). It also confirms the 60s leeway does not swallow real expiry.

## What is not covered

- **Google sign-in.** The provider is off: it needs a Google Cloud OAuth client,
  which is founder-only setup. The client's Google button is rendered even with
  the provider disabled, so clicking it produces Supabase's error rather than a
  hidden button. Email/password proves the whole token → principal → scoped
  history path; Google would only prove the provider hookup.
- **The operator role.** Two roles are named in #688; only analyst was exercised.

## Also found: the environment, twice

Neither is a product defect, both belong in #691's deployment notes:

- `uv sync` alone installs neither `pyjwt` nor `uvicorn` — the API dies at import
  with `ModuleNotFoundError: No module named 'jwt'`. It needs `--group service`.
- `uv sync --group service` then *prunes* `lancedb`, and the first live ask died
  mid-retrieval with `No module named 'lancedb'`. The working incantation is
  `uv sync --group service --group distill --group dev`.

The client handled that failure honestly: the walk stayed on screen, the row went
to `FAILED`, and the error was shown rather than swallowed — though what it shows
the analyst is a raw Python `ModuleNotFoundError`.

## Second pass, same day: Google sign-in

The first pass proved the chain with email/password. #688's first bullet says
Google, literally, so the run continued once #767 had merged (PR #768, squashed
as `d0c08a2`).

Setup, all of it by hand in the founder's own Google Cloud project
(`rich-stratum-429021-u4`, publishing status Testing, audience External, the
founder's address already the one test user):

| Step | Value |
|---|---|
| OAuth client | Web application, named `Axial (Supabase)` |
| Authorized redirect URI | `https://vmxqopfarajgqcrjrszk.supabase.co/auth/v1/callback` |
| Authorized JS origins | none — the server-side code flow does not use them |
| Supabase | Google provider enabled, client ID set, secret pasted by the founder |
| Site URL | `http://localhost:3000`, already the implicit redirect allowlist |

**The Google identity linked to the existing invited user rather than making a
new one.** `muhanad.a.husn@gmail.com` was analyst A — the account whose password
was lost in the first pass. After the Google sign-in that same row,
`0a549b0e-8fca-407a-a786-92213b146f0b`, reads `Email, Google` under Providers and
picked up the display name. The user count stayed at three, which is the
invitation-only rule holding under a second provider: Google authenticated the
person, it did not enrol them.

Then a real ask, submitted through the browser under that identity:

> **Case:** Mandate Syria and Lebanon
> **Question:** Did the French Mandate's confessional administrative divisions
> create Lebanon's sectarian political order, or did they formalise arrangements
> the late Ottoman period had already produced?

| | |
|---|---|
| Ask | `b820cef3122f46f2b6ab71e78b85e959` |
| Principal | `0a549b0e-8fca-407a-a786-92213b146f0b` (the Google sign-in) |
| State | `done`, `cached=false` |
| Cost | **$0.1522** |
| Tokens | **644,108** |
| Duration | **8m 52s** (532s) |
| Claims | 9 — 4 (a) stated, 3 (b) concluded, 2 (c) runs past |
| Sources used | 4 |
| Corpus pin | `sim-2026-07-30` |

The walk streamed the whole way, including the intake fork-check declining every
fork under its declared policy; the paper rendered with its markers, legend,
metrics panel and export; both meters read **$0.15**, matching the recorded cost.
History showed **one** row — this analyst's own ask, with its case and question —
and none of analyst B's. So the second and third bullets hold for a Google
principal too, not only the email/password one.

**All three of #688's "done when" bullets are now met as written.**

## Not covered

- **The operator role.** Two roles are named in #688; only analyst was exercised.
- **A second Google account.** Isolation between two *Google* identities was not
  tested; it was tested between two email/password ones, and the principal is the
  same Supabase `sub` either way.
- The consent screen still carries the founder's existing Cloud project branding,
  and the app is in Testing with a 100-user cap. Real deployment needs its own
  project, its own branding and a publish decision — #691 territory.

## Next steps

- **#688** closes: every bullet is met live.
- **#691** — the env notes above, the invitation-only switch this run exercised
  (`disable_signup: true`), and the Google client setup recorded here.
