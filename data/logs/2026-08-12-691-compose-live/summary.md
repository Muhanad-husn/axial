# Run: #691 the whole stack, from one compose file

2026-08-12. The first time Axial's analyst service came up the way a deployer
would bring it up — `docker compose up`, an image built from the repo, a
published snapshot mounted read-only, and a real ask driven through it to a
paper. Every other `service:` issue built a part; this run is the one that
asks whether the parts stand up together on a machine that has never run
Axial.

**Result: both halves of #691 pass, and the run found two defects that made
the product unusable. Neither was visible from a green test suite — one of
them 500'd every finished ask.**

> **This log is reconstructed from PR #773, not captured live.** The builder
> wrote its scratch logs (`_compose_up*.log`, `_compose_down*.log`,
> `_docker_build.log`, `_jwks_server.log`, `_jwt_token.txt`) into its worktree
> and was told to delete them rather than commit them, which it did; the
> worktree was then removed at cleanup. **`console.log` is unrecoverable and
> this directory does not contain one.** Every figure below is quoted from
> #773's body or was observed directly from this session's own checks against
> the running containers and the built image. Nothing here is inferred. The
> lesson is recorded under "What this cost" — a run log has to be written
> where the run happens, not reconstructed after the worktree dies.

## The stack

First run in the series that did **not** have to be hand-assembled — that is
the whole point of the issue. #687's and #688's logs both note the assembly
tax; this run pays none of it.

| Piece | How |
|---|---|
| Compose project | `691-compose-stack`, one file, three services |
| Postgres | `postgres:16-alpine`, healthchecked before the app containers start |
| API | `uvicorn axial.service.api:app --factory`, port 8000 |
| Worker | same image, `python -m axial.service.worker` as the command override |
| Snapshot | `data/snapshots/2026-08-10-v1`, mounted read-only into **both** containers |
| Corpus pin | `sim-2026-07-30` |
| Config | 18 environment variables, all in `.env.example` |

The snapshot was mounted from the main checkout at `D:/axial`. It was never
copied into the worktree and never entered the repo — `data/` is gitignored,
and no book text appears in any committed file.

## What the run found

### 1. `No module named 'lancedb'`, mid-ask

`axial.query.names.find_names`' tier-4 semantic fallback needs `lancedb` to
read the persisted embedding table and `sentence-transformers` to encode the
query. Both sat behind the `distill` group — build-only — and neither was in
`service`. The ask reached tier 4 and died there.

This is the interesting one, because **the image already contained
`sentence-transformers` 5.6.1**: it arrives transitively through `docling`,
which is in `dependencies` for the ingestion path and has no business in a
shipping service image. The ask path was working by accident and failing the
moment the accident ran out.

Both are now declared in `service`, and the Dockerfile pre-fetches the default
embedding model (`axial.names.DEFAULT_MODEL_NAME`) at build time so the
encoder's `local_files_only=True` never reaches the network mid-ask. Confirmed
by a second live run: the retrieval loop reached tier 4, loaded the encoder
offline, and continued.

### 2. `500` on `GET /asks/{id}/paper`, on every finished ask

The worker writes a job's `result_ref` under its own `AXIAL_WORK_DIR`. The API
container had no access to that filesystem at all — so every ask completed
successfully and then could not be read back. Fixed by mounting the same
`work` volume read-only into the API service. Confirmed by refetching an
already-finished ask's paper after the fix.

Both defects share a shape worth naming: **the API and the worker were only
ever tested in one process.** Split them into two containers and every
implicit shared-filesystem assumption between them becomes a defect. A test
suite that runs both halves in one interpreter cannot see this class of bug,
and neither could a review of the compose file.

## The ask

One ask, end to end, against the real snapshot.

| | |
|---|---|
| Case | `Syria, 1946-1958` |
| Question | Who led the Ba'th party and what did they disagree about with their rivals? |
| Ask id | `fefa26eca44b4ba9973666efccdf9825` |
| Claims | 7 |
| Cost | **$0.0903** |
| Interrogate | `deepseek/deepseek-v4-pro` |
| Synthesize | `openai/gpt-5.6-luna`, lens `political-economy`, 50 evidence items assembled |

`GET /health` returned `{"status":"ok","corpus_pin":"sim-2026-07-30"}` — a
deployer can name the live snapshot without reading logs, which is the third
"done when" bullet.

Both citation modes were exercised against the same finished ask:

- `locator` (the default): `grounds[0].citation` carries source, author, title,
  chapter and section, and **no `quote` key**. No book text in any response.
- `passage`: after flipping `AXIAL_CITATION_MODE` and recreating only the API
  container — no rebuild — `grounds[0].citation.quote` carried the exact
  passage. This closes #690's silent no-op: until the API had the snapshot
  mounted, `passage` resolved nothing and every citation silently stayed a
  locator.

## What this cost

| | |
|---|---|
| Wall clock | ~3h28m, one builder |
| Model spend | $0.09, one ask |
| Compose cycles | 3 full up/down |
| Image | 10.7 GB × 2 (API and worker share one build) |

The wall clock is almost entirely image builds. Two measurements taken from
the built image during this session, both of which became issue #772:

- `torch` is the **CUDA 13.0** build. `torch` is 1.15 GB and the `nvidia`
  libraries beside it are 2.86 GB — **4.01 GB of GPU runtime in a container
  that will never see a GPU.**
- site-packages is 6.64 GB of the 10.7 GB image, because `dependencies`
  carries the whole ingestion stack (`docling`, `unstructured[pdf]`,
  `unstructured-inference`, the Drive client) that the ask path never runs.

Note the direction of travel: fixing defect 1 made the image **bigger**, since
`lancedb` is new weight. #772 must re-measure rather than diff against 10.7 GB.

## Next

- **#772** — the shipping image carries the ask path and nothing else. The
  CPU-only `torch` wheel is the single highest-value line: now that
  `sentence-transformers` is declared rather than inherited, the 4.01 GB of
  CUDA runtime is load-bearing weight, not an accident.
- `docker system prune`. The box was holding ~130 GB across images, build
  cache and volumes before this run added two more images.
- The Dockerfile's model pre-fetch sits **after** `COPY src ./src`, so any
  future edit under `src/` re-downloads the encoder on the next build. Flagged
  in #773 and carried into #772 rather than rebuilt to verify, under the
  no-more-rebuilds directive.
- **Write the log where the run happens.** This one survived only because the
  PR body was unusually complete. The scratch logs were correctly kept out of
  the commit, but they should have been copied into `data/logs/` before the
  worktree was removed, not deleted with it.
