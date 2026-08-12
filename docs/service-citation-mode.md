# Citation mode: what a deployer is switching on

The analyst service can show a citation two ways. `AXIAL_CITATION_MODE` picks
one, and it is the deployer's own decision, not the founder's — Axial is being
built, not deployed (DEC-65), so the exposure below belongs to whoever stands
the service up.

## `locator` — the default, no configuration needed

Every claim points at the book, the chapter and the section it rests on. No
quoted text from any book ever leaves the service. A fresh install is safe
unconfigured.

This is enough for a reader to check where a claim comes from and go read the
book. It is not enough to check the claim's exact wording without owning the
book yourself.

## `passage` — one environment variable, no code change

Set `AXIAL_CITATION_MODE=passage`. Every claim now also carries the exact
passage it was drawn from, quoted in full — in `GET /asks/{id}/paper`'s JSON,
in the rendered markdown answer (whether served by the API or written to disk
by `axial ask`), and in the markdown/docx/odt download from `GET
/asks/{id}/export`. One resolution, every surface an analyst reads.

## The tradeoff

The papers quote 34 in-copyright academic books. Reading a quoted passage on
your own machine, from a book you own, is private use. Serving that same
passage to a thousand readers over the internet is publishing — same
mechanism, different exposure, and the exposure belongs to whoever runs the
service, not whoever built it.

`locator` mode carries none of that exposure: it never puts book text in an
API response. `passage` mode is more useful to a reader checking a claim
closely, and it is the thing to turn on only once you have made your own
decision about quoting these books at whatever scale your service reaches.

## What it does not cover

The mode is enforced at the API boundary (`axial.service.api`,
`axial.service.citation`): no request field lets a client ask for `passage`
from a `locator` deployment, and an unrecognised value refuses to start rather
than falling back silently. It says nothing about the raw source files
themselves — those are never copied into a published snapshot in the first
place (see `axial.service.snapshot`'s own docstring).

## The compose deployment needs one more thing: the mount

`passage` mode resolves a citation out of the published snapshot's vault
(`GET /asks/{id}/paper`'s citation resolution reads it relative to the API
process's own cwd, same as everywhere else in this codebase). The `docker
compose` stack (issue #691, `docs/service-deployment.md`) has to mount that
snapshot at the API container's working directory the same way the worker
already binds to one — without that mount, flipping `AXIAL_CITATION_MODE=
passage` is a silent no-op, not an error. See
`docs/service-deployment.md`'s own section on the mount for the full
explanation.
