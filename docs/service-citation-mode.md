# Citation mode: what a deployer is switching on

The analyst service can show a citation two ways. `AXIAL_CITATION_MODE` picks
one, and it is the deployer's own decision — Axial is being built, not
deployed (DEC-65), so the exposure below belongs to whoever stands the
service up.

## `passage` — the default

Every claim carries the exact passage it was drawn from, quoted in full,
under the claim it grounds — in `GET /asks/{id}/paper`'s JSON, in the
rendered markdown answer (whether served by the API or written to disk by
`axial ask`), and in the markdown/docx/odt download from `GET
/asks/{id}/export`. One resolution, every surface a reader sees.

This is what an install resolves to with nothing configured (DEC-72). An
answer that cannot quote the book it argues from is not an answer, and that
cost is not one a default should impose on a deployer who has not been asked.

## `locator` — one environment variable, no code change

Set `AXIAL_CITATION_MODE=locator`. Every claim then points at the book, the
chapter and the section it rests on, and no quoted text from any book leaves
the service.

This is enough for a reader to check where a claim comes from and go read the
book. It is not enough to check the claim's exact wording without owning the
book yourself.

## The exposure, stated plainly

The papers quote 34 in-copyright academic books. Reading a quoted passage on
your own machine, from a book you own, is private use. Serving that same
passage to a thousand readers over the internet is publishing — same
mechanism, different exposure.

That exposure belongs to whoever runs the service. `passage` mode carries it;
`locator` mode carries none of it and costs the reader the ability to check a
claim's wording. Which trade to make depends on who your readers are and at
what scale you serve them, and nobody but you can make it. Make it
deliberately, and set the variable either way.

## What the mode does not cover

The mode is enforced at the API boundary (`axial.service.api`,
`axial.service.citation`): no request field lets a client ask for `passage`
from a `locator` deployment, and an unrecognised value refuses to start rather
than falling back silently. It says nothing about the raw source files
themselves — those are never copied into a published snapshot in the first
place (see `axial.service.snapshot`'s own docstring).

It also does not reach the sealed reviewer packet
(`axial.panel.packet.build_packet`), which resolves the full text of every
cited chunk itself and always has (§9.4 property 1, DEC-40). That packet is
assembled in memory, is never written to disk, and never leaves the process
that built it.

## The compose deployment needs one more thing: the mount

`passage` mode resolves a citation out of the published snapshot's vault
(`GET /asks/{id}/paper`'s citation resolution reads it relative to the API
process's own cwd, same as everywhere else in this codebase). The `docker
compose` stack (issue #691, `docs/service-deployment.md`) has to mount that
snapshot at the API container's working directory the same way the worker
already binds to one — without that mount, `passage` mode is a silent no-op,
not an error, and answers come back with locators only. See
`docs/service-deployment.md`'s own section on the mount for the full
explanation.
