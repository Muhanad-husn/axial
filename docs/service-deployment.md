# Deploying the analyst service

Axial is being built, not deployed (DEC-65): the founder does not run this as
a service, and the infrastructure exists so that whoever invests can stand it
up. This is that infrastructure, in one `docker compose up`.

## The pieces

| Container | What it runs | Reads | Writes |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | — | `jobs`, `job_events`, `quotas`, `profiles`, `paper_cache` |
| `api` | `uvicorn axial.service.api:app --factory` | the mounted snapshot (optional in `locator` mode) | nothing but Postgres |
| `worker` | `python -m axial.service.worker` | the mounted snapshot, the mounted secrets file | Postgres, and a writable volume for analyses/runs/the paper cache |

`docker-compose.yml` builds one image (`Dockerfile`) and runs it as both
`api` and `worker` — the only difference is the container's command. Every
setting either container reads is an environment variable with a documented
default in `.env.example`, which is the complete list: if a setting is not
there, it is not configurable.

## What each piece costs to run

- **Postgres**: a `jobs` row per ask, a handful of `job_events` rows per
  ask, and small `quotas`/`profiles`/`paper_cache` tables. Trivial storage
  and CPU at the scale this was built for (issue #681: hundreds of
  concurrent jobs, not thousands of requests a second).
- **The API**: stateless HTTP. No model call happens on this path — `POST
  /asks` writes a queued row and returns; the model spend is entirely the
  worker's.
- **The worker**: one ask is one full `axial ask` run, ~$0.12-0.16 against
  the tiered models `config/pipeline.yaml`'s `model_by_pass` names (Phase C
  release-bar measurement, `docs/postmortem/`), or free on the `building`
  tier if no `secrets.toml` supplying those tiers is mounted (see
  `.env.example`'s `AXIAL_SECRETS_HOST_PATH`). `AXIAL_WORKER_COUNT` runs
  that many asks concurrently in one container; scale further with
  `docker compose up --scale worker=N`.

Nothing here builds a corpus. `axial publish <version>` (issue #684) and
everything before it — ingest, envelope, interrogate, reconcile, Gather, the
argument map — is the operator's own local tool, run on the operator's own
machine against `data/sources/`, never inside this stack. The compose file
only ever reads a snapshot `axial publish` already produced
(`AXIAL_SNAPSHOT_HOST_PATH`), read-only, and never mounts or copies
`data/sources/` at all.

## What has to be decided before opening this to readers

Two things move real exposure, and both are the deployer's call, not this
repository's:

1. **Citation mode** (issues #690 and #785, `docs/service-citation-mode.md`).
   `passage` — the default — quotes the passage a claim rests on, which is
   what makes an answer checkable. Reading that on your own machine is
   private use; serving it to a thousand readers over the internet is
   publishing. `AXIAL_CITATION_MODE=locator` puts no book text in any
   response, and costs a reader the ability to check a claim's wording. Read
   that doc and decide before opening this to readers.
2. **Public sign-up.** Invitation is Supabase's own switch (issue #763,
   `axial.service.api` module docstring): the service carries no second
   allowlist, so a Supabase project left open to public sign-up is an open
   door this code cannot see or close. Turn public sign-up off in the
   Supabase project before pointing `AXIAL_SUPABASE_JWKS_URL` at it.

`AXIAL_SUPABASE_JWKS_URL` unset is the safe failure direction either way:
every request is `401` until it is set.

## The snapshot mount, and `AXIAL_CITATION_MODE=passage`

`axial.service.snapshot.Snapshot.bind` (issue #684) makes a worker read the
published snapshot mounted at its own working directory — every cwd-relative
read the engine makes (`config/pipeline.yaml`, the vault, the name layer)
resolves inside it. Before this issue, only the worker container was ever
bound this way. The **API** container needs the identical mount at its own
working directory for exactly one reason: `GET /asks/{id}/paper`'s citation
resolution (`axial.service.citation`) and `GET /health`'s corpus-pin report
both read `axial.paths.default_vault_dir()` / the snapshot manifest relative
to the API process's own cwd, the same convention every other read in this
codebase already uses.

`docker-compose.yml` does this by setting the `api` service's `working_dir`
to `AXIAL_SNAPSHOT_DIR` and mounting the same `AXIAL_SNAPSHOT_HOST_PATH`
there read-only — the same variables, the same host path, the worker
already uses.

**Until that mount exists, `passage` mode is a silent no-op** — and since
#785 that is the default, so this is the mount every deployment needs, not
one only an opted-in deployer does. With nothing mounted at the API's cwd,
`render_record_for_serving` finds no vault to resolve a chunk against and
leaves every citation exactly as `locator` mode would have — no error, no
warning, just no passage text. Answers come back citing books they never
quote, and the mount is the fix.

The failure direction here never inverts: a `locator` deployment cannot
accidentally start serving book text, because the untouched record carries
no quote either way. `locator` mode also reads nothing from the vault
regardless of whether one is mounted, so a `locator` API container with the
snapshot mounted stays exactly as correct as one without it.

## Health

`GET /health` returns `{"status": "ok", "corpus_pin": <string or null>}` --
the pin of whatever snapshot is mounted at the API's own cwd, i.e. the same
corpus every worker bound to that same mount is serving. `null` means
nothing is mounted there (the `locator`-only default configuration); it is
not an error. Unauthenticated, so an orchestrator or a deployer's own
uptime check can poll it without a Supabase session.

## The embedding model is baked into the image, not downloaded per ask

`axial.query.names.find_names`'s tier-4 semantic fallback (reached whenever
the earlier exact/alias/fuzzy tiers miss) loads its `sentence-transformers`
encoder with `local_files_only=True` on purpose -- an ask must never reach
the network mid-run for a model weight. Discovered live (issue #691's own
`docker compose up` run failed an ask with `No module named 'lancedb'` on
the first pass, and would have failed again on the encoder once that was
fixed): both `lancedb` and `sentence-transformers` are ask-path
dependencies, not build-only ones, so they moved from the `distill` extra
into `service` (`pyproject.toml`), and `Dockerfile` pre-fetches
`axial.names.DEFAULT_MODEL_NAME` (`sentence-transformers/all-MiniLM-L6-v2`)
at build time. A snapshot whose own `names/similarity_manifest.json` names a
different embedding model needs that model baked into a custom image
instead -- this Dockerfile does not read a snapshot to decide what to
pre-fetch, since the image is built before any snapshot is chosen.

`axial.argmap.build`'s own encoder (`ENCODER_MODEL`, reached by
`run_map_ask_for_brief` whenever a brief lands on a built argument map)
names the identical model but, unlike the tier-4 fallback, does not pass
`local_files_only` itself -- so the image sets `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1` (issue #772) rather than relying on every call
site to opt out of the network individually: with the weights already on
disk from the build-time pre-fetch, both readers are offline by
construction, and a cache miss fails loudly at startup instead of quietly
reaching huggingface.co mid-ask.

## The image carries the ask path, not the ingest path

`pyproject.toml` splits `docling`, `unstructured[pdf]`,
`unstructured-inference` and the two Google Drive packages into their own
`ingest` dependency group (issue #772) -- extraction is operational, run by
the deployer locally from the repo against `data/sources/`, and the
service never touches it. `Dockerfile` asks `uv sync` for
`--no-default-groups --group service`, so none of that stack, and none of
the CUDA runtime PyPI's default `torch` wheel bundles (redirected to the
PyTorch CPU index on Linux, since this container has no GPU), ships in the
image. A bare `uv sync` and CI are unaffected: `ingest` is a
`default-groups` member.

## What this stack does not prove

Real load with many concurrent analysts, real identity-provider redirect
flows under network latency, and multi-host storage are not exercised here
— they get validated by whoever deploys, against a real host (issue #691's
own notes).
