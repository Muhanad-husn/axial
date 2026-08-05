# Plan: Multiuser Analyst Service

**Status:** Started 2026-08-05. Issues #681–#690. See the 2026-08-05 amendment
below, which supersedes parts of the original draft.
**Prerequisite:** met — Phases A, B and C are built.
**Drafted:** 2026-07-23, from a design discussion.

This is a forward-looking plan, written in plain language. When work begins, the
first step is to turn the sequence below into GitHub issues and record the core
decision in `docs/DECISIONS.md` as a `DEC-` row.

---

## Amendment, 2026-08-05: the analyst UI is a real web app, and CLI-first is off

Founder adjudication, recorded as **DEC-65**. Read this before anything below it.

**What is superseded.** Decision 5 ("client is the CLI first") and "Explicitly
deferred: a web UI" no longer hold for the analyst domain. The open question at
the bottom of this plan — *are the first invited analysts technical enough for a
CLI?* — is answered **no**. Academics use the product themselves; the ceiling is
hundreds to thousands of them, not a handful.

**What the two clients are.**

| Domain | Users | Stack |
|---|---|---|
| Operator | 1, local | Streamlit shelling out to the `axial` CLI, tailing `run.jsonl`. No API, no auth, no Docker |
| Analyst | hundreds–thousands, hosted | Next.js + TS + Tailwind + shadcn/ui on Vercel; FastAPI; Postgres job queue with worker processes; Supabase for auth and Postgres |

Streamlit holds a Python process per browser session. That is free at one user
and a thousand processes at a thousand — which is exactly why it is the right
answer on the left and the wrong one on the right.

**What still holds from the original plan.** The two-worlds isolation, the
read-only corpus, the snapshot model, invitation-only access, two roles, rented
login, and steps 2–4 (`RequestContext`, per-principal paths, `can_access`) —
which are still the cheap groundwork that is expensive to retrofit.

**Three things the draft did not know.**

1. **The endpoints are jobs, not request/response.** An ask is ~3 minutes and an
   ingest is hours. The job row carries a `kind` so chat mode
   ([milestone 5](https://github.com/Muhanad-husn/axial/milestone/5)) is a second
   kind, not a second system.
2. **"The one genuinely hard part" is mostly already built.**
   `src/axial/query/store.py` already opens the corpus read-only over a SQLite
   URI. A published corpus is that one file, baked into a worker image and tagged
   with its pin.
3. **The binding constraint is money.** ~$0.13 a paper; a thousand academics at
   two a week is ~$1,100/month against no revenue. Quotas and a content-keyed
   cache ship on day one (#686).

**One decision blocks going public** (#690): the papers quote passages from 34
in-copyright books. Private use and publishing are the same mechanism at
different exposure.

---

## Amendment, 2026-07-25: the operator domain gets a UI too

Recorded from a design discussion, not committed scope. Everything below this
section predates it and is otherwise unchanged.

The plan as drafted says the operator world is out of scope and stays exactly as
it is today. That is no longer the intent. The product is two domains, each with
its own interface, over a shared foundation:

- **Operator domain.** A UI that lets a non-technical operator run the corpus
  build: ingest sources, resolve quarantines and candidate decisions, and monitor
  pipeline performance. This is a face on capability the CLI already has, not new
  pipeline capability.
- **Analyst domain.** A copilot over a published, read-only corpus. This is the
  analyst world the rest of this plan describes.

**CLI-first still holds, and now covers both domains.** The rule is unchanged: the
service is the durable part, the client is cheap and swappable, and a CLI exercises
the service as thoroughly as a UI would. Neither UI starts before its CLI surface
is stable.

**What this does not change:** the two-worlds isolation, the read-only corpus, the
snapshot model, and the build sequence in steps 1–7. The operator UI is not
scheduled and gets its own plan when it starts. Until then, "Explicitly deferred"
below still governs the analyst web UI.

---

## What we're building, in one sentence

A small, read-only service that lets a few invited analysts log in and query the
shared corpus — nothing more.

## The mental model: two separate worlds

The most important idea. These two never touch each other's insides.

- **Operator world (Phase A) — unchanged.** You, on your own machine, build the
  corpus exactly as you do today. No login, no server, no changes. When a corpus
  is finished, you *publish* it: copy the finished, read-only corpus up to the
  shared server as a versioned snapshot.
- **Analyst world (the new thing).** A service that only *reads* a published
  corpus. Analysts log in, send a case and request, and get answers back. It
  cannot build, edit, or touch Phase A. It only connects and queries.

Everything in this plan is about that second world. The operator world is out of
scope.

## Decisions already made

Settled in discussion, so we don't re-litigate them when we start:

1. **Tenancy:** many analysts, one shared corpus (not one corpus per person).
2. **Corpus is read-only** to analysts. Only the operator produces corpora.
3. **Access is by invitation.** No public sign-up page. You add an analyst's
   email by hand; they get access. You always know exactly who is in.
4. **Two roles only:** *analyst* (log in, query own work) and *operator* (builds
   and publishes corpora). Resist adding more roles.
5. **Client is the CLI first.** Analysts use a command-line tool with a login
   token. A real web UI comes later, as a swap-in on top of the same service —
   the hard part (the service) is built once and reused.
6. **Login is rented, never hand-built.** We use a managed auth service so we
   never see or store passwords ourselves.

## Why building the CLI first wastes nothing

Picture two layers:

- **The service** — the login check, each analyst's saved work, and the
  read-only connection to the corpus. This is the durable, valuable part.
- **The client** — whatever the analyst types into. A CLI is one client; a web
  page is another. Both call the same service underneath.

The client is cheap and swappable; the service is where the value lives. A CLI
exercises the service just as thoroughly as a web page would, for a fraction of
the effort. When we later build a real UI, we bolt it onto a service that already
works. Nothing gets thrown away except a few hundred lines of terminal client.

## The free stack

To build and simulate the whole thing on a laptop, the shopping list is short:

- **Docker** — runs the analyst service locally exactly the way it would run
  hosted, so we can test everything before paying for or setting up any real
  host. The corpus is mounted into the container as a read-only volume, which
  also mirrors how a published snapshot behaves in production.
- **Supabase (free tier)** — one service that handles login (Google sign-in *and*
  email/password, both out of the box) and gives us a small database to store
  each analyst's briefs and results. Because Supabase does the login, we never
  build or store credentials. (Google's Firebase is an equivalent alternative;
  we start with Supabase because it also hands us the database we'll want.)
- **GitHub** — code and automated testing, already in use.
- **A free hosting tier later** (Google Cloud Run, Render, or Railway) — only
  needed once we outgrow the laptop. Not part of the initial build.

For invited analysts on the CLI, the simplest login is a **personal access
token**: you invite someone, the service issues their token, they paste it into
their config once, and every command after that is authenticated. No browser
step. Google and email/password login stay in reserve for the future web UI.

## What changes in the existing code, and what's new

Good news: the Phase B core barely changes. Auth is a layer *in front of* it.

**Reuse three existing seams:**

- `src/axial/paths.py` — already the single place that resolves where data lives.
  The working-set directories (briefs, analyses) become *per-analyst*; the corpus
  directories stay global and read-only. This one file carries most of the change.
- A new small `RequestContext` object — carries *who is asking* (the principal)
  and *which corpus version* they are reading. Threaded through the Phase B entry
  points. It already needed to exist; auth just supplies its value instead of a
  default.
- `corpus_pin` (already built) — records which corpus version an analysis ran
  against. This is what makes a shared corpus trustworthy: you can always say who
  ran what against which snapshot.

**Build new, kept out of `src/` core:**

- A thin **service layer** (the boundary analysts connect to) with an **auth
  middleware** at its edge that turns a token into "this is verified analyst X."
  The Phase B core never sees a password — only a resolved principal.
- A tiny **`can_access(principal, resource)`** policy: a pure, table-driven
  function, the same style as `disposition_for`. Analyst reads the corpus; reads
  and writes only their own work. Nothing fancier.

## The build sequence

Each step is a milestone with a plain "done when" check. Turn each into one or
more GitHub issues when starting.

1. **Write it down.** Record the core decision (this plan's "Decisions already
   made") in `docs/DECISIONS.md`. *Done when:* a `DEC-` row exists.
2. **Add identity to the request path.** Introduce `RequestContext{principal,
   corpus_version}` and thread it through the Phase B entry points, defaulting to
   a single local user so nothing changes yet. *Done when:* the pipeline runs
   exactly as before, but every request now carries a "who."
3. **Scope the working set per analyst.** Make `paths.py` resolve briefs and
   analyses under a per-principal location; leave the corpus global and
   read-only. *Done when:* two different principals get separate saved work, same
   corpus.
4. **Add the access policy.** The `can_access` function plus an ownership check,
   so one analyst cannot read another's work. *Done when:* a test proves analyst
   A cannot see analyst B's analyses.
5. **Stand up the thin service + rented login.** A small service with Supabase
   auth at the edge; the CLI becomes a token-carrying client. *Done when:* an
   invited analyst logs in from the CLI and runs a query end to end.
6. **Publish corpora as immutable snapshots.** The one real engineering piece —
   see below. *Done when:* an operator can publish a new corpus version while an
   analyst is mid-query, and the analyst's results are undisturbed.
7. **Simulate it all in Docker locally.** Package the service in a container with
   the corpus as a read-only volume and Supabase for login. *Done when:* the full
   flow — invite, log in, query — works against the local container.

Steps 1–4 are the cheap, reversible groundwork that is expensive to retrofit
later. Steps 5–7 are the real service build.

## The one genuinely hard part: immutable corpus snapshots

Many analysts reading the corpus at once is safe, because it is read-only. The
one dangerous moment is the operator publishing a *new* corpus while analysts are
mid-query.

The clean fix: a publish produces a **new versioned snapshot** rather than
changing the live one. Each query pins to a snapshot when it starts and reads
that snapshot to the end. Old snapshots retire once no query is using them. The
corpus is already content-addressed, which makes this natural. This is the real
engineering; everything else is plumbing.

## Explicitly deferred (do NOT build early)

Building these before a real need is the over-engineering tripwire the handbook
warns about. Add each only when something concrete demands it:

- A web UI (build when a non-technical analyst actually needs one).
- Public self-serve sign-up, email verification, abuse protection.
- Per-analyst cost accounting and rate limits (enabled by having identities, but
  not required day one).
- More than the two roles.
- Sharing or collaboration between analysts.
- One-corpus-per-tenant (a different product; not this plan).

## What local Docker does *not* prove

The local simulation is a correctness rig, not a scale rig. It faithfully proves
the boundary, the login plumbing, the access policy, and the read-only snapshot
model. It does *not* prove real load with many concurrent analysts, real
identity-provider redirect flows, network latency, or multi-host storage. Those
get validated later against a real host.

## Open questions to settle when we start

Answer these at kickoff, not now:

- Are the first invited analysts technical enough for a CLI, or does the web UI
  need to come sooner than planned?
- Where does the published corpus physically live in production (which storage),
  and how does the operator's "publish" step actually move it there?
- How long do we keep old corpus snapshots before retiring them?
- Do analysts ever need to compare results across two corpus versions, or always
  the latest?
