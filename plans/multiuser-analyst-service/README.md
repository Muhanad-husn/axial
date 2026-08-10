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
   URI. A published corpus is that file, baked into a worker image and tagged
   with its pin. (Corrected while building #684: the store is the read-only
   *primitive*, but it is not the whole query surface — see the amendment under
   "The one genuinely hard part" below.)
3. **The binding constraint is money.** ~$0.13 a paper; a thousand academics at
   two a week is ~$1,100/month. Quotas and a content-keyed cache ship on day one
   (#686).

**Built here, not deployed.** The founder is not running this as a service. The
deliverable is a stack an investor can stand up: `docker compose up`, every
setting an environment variable with a documented default, no founder path in the
running service (#691). The operating decisions belong to whoever deploys.

That includes copyright. The papers quote passages from 34 in-copyright books;
reading them on your own machine is private use and serving them to a thousand
readers is publishing. So both citation modes ship — `locator` by default so a
fresh install is safe unconfigured, `passage` behind one config value — and the
deployer picks (#690). Nothing in this layer waits on a founder decision.

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
   analyst is mid-query, and the analyst's results are undisturbed. **Shipped in
   #684** (`axial publish <version>`); see the 2026-08-10 amendment under "The
   one genuinely hard part" for what a snapshot turned out to contain.
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

### Amendment, 2026-08-10: what shipped in #684

**A snapshot is a whole corpus root, not one SQLite file.** The plan and the
issue both assumed the vault markdown was the human view and the store was the
query surface. It is both. `assemble_evidence` quotes every cited passage out of
`<vault>/prose/<chunk_id>.md`, and `get_name` reads the Gather disagreement
section off `<vault>/names/<name>.md` — `notes.db` is the index, the markdown is
the text. So `<snapshots_dir>/<version>/` carries `manifest.json`, `config/`,
`evals/corpus_pin/`, `vault/`, `names/`, `envelopes/` and `map/<map_pin>/`.

**It deliberately does not carry `data/sources/`.** The only thing on the ask
path that needs the raw books is the hash that derives the argument map's
directory name. That is computed once, at publish time on the operator's own
machine, recorded as `map_pin`, and handed to the engine — so a hosted worker
never holds a byte of an in-copyright book.

**Binding is `os.chdir` into the snapshot root, once, at worker process start.**
Threading the snapshot's directories through the engine cannot be made total:
`axial.query.names` resolves the name layer with `default_names_dir()` and no
config path, `run_brief` has no `names_dir` parameter to thread one through, and
the lens and corpus-pin directories are cwd-relative literals. Missing one of
those sites fails silently, by reading the operator's live `data/`. A snapshot
that is a corpus root with relative `paths.*` closes all of them at once, and
matches this plan's own model: rolling a new corpus is a new worker image.
Analyst writes (`analyses/`, `runs/`) are passed explicitly, because they are not
corpus and the snapshot is read-only.

**One pin, one source of truth.** The snapshot ships the pin manifest, so
`resolve_pin_id` inside a bound worker returns the snapshot's own pin. A job
whose run recorded a different pin is failed, not relabelled.

### Amendment, 2026-08-10: what shipped in #686 (quotas and the paper cache)

DEC-65 already named quotas and a content-keyed cache as day-one work, not
deferred; #686 is what they turned out to be.

**Cache key is `(brief_id, corpus_pin)`, not the issue's own third
component.** The issue's prose names `(brief_id, corpus_pin, source
weights)`, but `axial.brief.intake.compute_brief_id` already folds `weights`
(and `lens`) into `brief_id` itself (issue #639) — a separate weights column
would be dead, since two briefs with different weights already compute
different ids and never collide.

**The cache resolves in the worker, not the API.** Only the worker holds the
bound snapshot's own pin (#684's own binding model), so the API stays
pin-free — a cache hit still creates a `queued` job row exactly like a miss,
and `axial.service.worker.run_ask_job` is the one place a lookup happens,
before the engine ever runs.

**A hit crosses the per-principal boundary on purpose, and survives the
originating analyst's directory changing later.** The served paper is
corpus-derived and content-identical for anyone asking the same brief
against the same pin, not analyst A's private work. `axial.service.cache.
PaperCache` materialises a private copy of the finished record under a
shared, principal-free directory at generation time rather than pointing at
analyst A's own `analyses_dir` entry — the cheaper, "just record A's path"
alternative does not meet the bar this plan needs ("must not silently break
if the originating analyst's working set is gone"), so it was not a
cost/robustness trade.

**Quota windows are calendar UTC day and month, read from one environment
variable pair with a documented default** (`AXIAL_QUOTA_ASKS_PER_DAY`/
`_MONTH`, `axial.service.quotas`), matching #691's "every setting is an
env var with a documented default" shape rather than a config file. The
operator raises one analyst's limit with a plain `QuotaStore.set_limits`
call — no admin HTTP surface, no CLI command, per the issue's own scope.
`POST /asks` checks quota before `store.enqueue`, so an over-quota ask
creates no row, and a cache hit never counts against the budget (the row's
own `cached` flag is what a quota window's count excludes).

**Per-analyst spend is queryable via `JobStore.sum_spend_for_principal`,
not a new HTTP surface** — the metrics/usage/export endpoint is #724, out
of this issue's scope. The job row's `cost_usd` stays `None` for an
unpriced model's pass and a real `0.0` for a cache hit; the two are never
allowed to collapse into each other.

### Amendment, 2026-08-10: what shipped in #690 (citation mode)

Two premise corrections turned out to shrink this slice from what the
issue assumed.

**There is no page number anywhere in this system.** Neither `axial.chunk`
nor the extract path persists one; the finest per-note location the corpus
carries is `axial.query.store`'s `notes.section`/`notes.chapter` (chapter
is derived from a source's own table of contents at materialize time,
`axial.materialize.chapter_for_section`). A locator is `{source_id,
author, title, date, chapter, section}` — built from `notes`/`sources`,
never a fabricated page.

**The §7.3 analysis record already carried no passage text.** A claim's
`grounds` and a `counter_position`'s own `grounds` are both `{ref_type,
ref_id}` pointers (`axial.answer.record`, `axial.analyze.synthesis`) — `GET
/asks/{id}/paper` already met `locator` mode's "no book text" bar with the
record untouched, before this issue did anything. `passage` mode is
therefore additive, not `locator` mode subtractive: `axial.service.
citation.render_record_for_serving` attaches a `citation` block to every
`chunk` ground it can resolve (the locator fields, in both modes), with a
`quote` key added only when `AXIAL_CITATION_MODE=passage`. The whole served
surface was checked, not just claim grounds: `interrogation`'s
`premises_found`/`bounds_applied` are the model's own summarizing prose,
`trajectory` entries carry tool names/args/chunk ids, and the SSE event
stream (`GET /asks/{id}/events`) narrates tool actions and counts — none of
it ever carried book text either.

**The API process is not bound to a snapshot the way a worker is (#684's
own binding model), and does not need to be for this.** `axial.query.
reader.get_chunk`/`axial.query.store.connect` both take an explicit
`vault_dir` argument and need no `os.chdir` binding to work correctly — the
narrow read this issue needs was never one of the cwd-relative call sites
`Snapshot.bind`'s own docstring lists. `create_app` takes `vault_dir`
explicitly (`None` by default, a safe no-op); `app()`, the real deployment
entry point, resolves it with `axial.paths.default_vault_dir()` — the same
`config/pipeline.yaml`-relative-to-cwd convention every other read in this
codebase already uses, so `AXIAL_CITATION_MODE=passage` needs no second
setting once #691 mounts a snapshot at the API container's cwd the same
way it will at a worker's.

### Amendment, 2026-08-10: what shipped in #724 (metrics, usage, export)

**An ask is not a paper run — the premise the founder's original #682
comment carried had to be corrected first.** That comment named the
metrics block "straight off the Phase-C record"
(`src/axial/paper/record.py`), but an ask produces a §7.3 analysis record
(`src/axial/answer/record.py`), a different pipeline. `retries` and a
shape band exist only on the Phase-C record; `cost`, `model_by_pass`,
`coverage_map` and `confidence` exist on both, so those four are what
`GET /asks/{id}/paper` now serves beside the record (`{"record": ...,
"metrics": {...}}`, never merged into it) — dropping the two that would
have required chaining a paper draft onto every ~$0.13 ask.

**Tokens needed a new column; cost already had one with no time
window.** `axial.service.jobs.JobStore.sum_spend_for_principal` gained an
optional `since` and `session_id`; a new `tokens` column (same
`ALTER TABLE ... IF NOT EXISTS` idiom `cached`/`cost_usd` already used)
is filled by the worker from the exact `record["cost"]["by_pass"]` dict
`cost_usd` was already reading, never a second pass over the record. Its
own null-preserving rule is identical to `cost_usd`'s: `None` when the
record carried no `cost` block, a real `0` on a cache hit (this job made
no model call). `JobStore.count_since` grew `session_id` and
`exclude_cached=False` for the same reason: `GET /me/usage` needs "asks
made" (every ask) alongside "asks charged against quota" (a cache hit
excluded) — the founder's own naming for why one count must never stand
in for the other. Extending the `JobRunner` seam's own tuple shape from
four elements to five (adding `tokens`) rippled through every stub
`run_job` in `tests/service` — a real but bounded blast radius, not a
second abstraction.

**`GET /me/usage` has no notion of "the current session"**, because the
server has none — `session_id` is a query parameter, and its block is
absent, not an error, when the caller supplies none. It reuses the same
`QuotaStore.limits_for`/`count_since` calendar-UTC-window pair the `429`
path on `POST /asks` already assembles, so `quota["month"].used` is
literally `month_to_date.asks_charged`, not a second query for the same
count.

**Export is one rendering path, three containers.** Markdown is the only
place record content turns into text (`axial.service.export.
render_export_markdown`, reusing §7.10's own `render_markdown` plus this
issue's own metrics appendix); `docx` and `odt` each walk that SAME
markdown string's bounded set of constructs into their own binary
format, never re-reading the record. **The conversion library is
pure Python on both sides, not pandoc**: `docx` via `python-docx`
(already a dependency, for the extract path's own `.docx` reading), `odt`
via `odfpy` (added here, in the new `service` dependency group — pure
Python, no binary, so #691's image carries nothing extra and
`.env.example` needs no new binary path). A five-construct line walk
covers everything either format needs for this issue's own "done when"s,
so pandoc would have bought nothing worth its binary.

**The #690 citation mode's "no book text" bar holds for export by
construction, in both modes, for a reason worth stating plainly:**
`render_markdown` (§7.10) never surfaces a ground's `citation.quote` at
all — that gap predates this issue, in the persisted analyst markdown
answer `axial ask` already writes. Export inherits it rather than fixing
it: a `passage`-mode deployment's exported file carries the same
locator-only grounds a `locator` deployment's does. Verified against the
generated file's own bytes in `tests/service/test_api_export.py`, per the
issue's own instruction, not against the JSON or a UI.

## Explicitly deferred (do NOT build early)

Building these before a real need is the over-engineering tripwire the handbook
warns about. Add each only when something concrete demands it:

- A web UI (build when a non-technical analyst actually needs one).
- Public self-serve sign-up, email verification, abuse protection.
- ~~Per-analyst cost accounting and rate limits~~ — shipped in #686 (quotas
  and per-analyst spend) and #724 (the metrics/usage/export HTTP surface
  over that spend).
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
