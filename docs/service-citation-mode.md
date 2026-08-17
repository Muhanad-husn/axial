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

The **essay** an ask now ends in (issue #784) is rendered through the same
mode, at the same API boundary, and never read off the file the worker
wrote — so a worker resolving `passage` cannot put book text into a
`locator` deployment's response by baking it in first. Its own in-text
citations are book-level (`Vignal 2021, ch. 30`) rather than quoted
passages, so the essay is short in either mode; the quoted passages stay
with the claim list beneath it.

This is what an install resolves to with nothing configured (DEC-72). An
answer that cannot quote the book it argues from is not an answer, and that
cost is not one a default should impose on a deployer who has not been asked.

**Know the size before you decide.** A passage is a whole chunk, not a
sentence. Measured over the 19 answers in this repository's own corpus: 38
quotes per answer, averaging 767 words each, so an answer grows from about
1,400 words to about **31,000** — roughly ×22, and about 95% of what a reader
receives is quoted book text. That number matters to both halves of the
decision below: it is the real exposure you are weighing, and it is also the
size of every markdown, docx and odt file the export route hands out.

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

## Check that `passage` mode is actually live

`passage` mode resolves a citation out of the published snapshot's vault
(`GET /asks/{id}/paper`'s citation resolution reads it relative to the API
process's own cwd, same as everywhere else in this codebase). **If there is
no readable snapshot there, `passage` mode is a silent no-op** — no error, no
warning, answers simply come back with locators only.

The shipped `docker-compose.yml` already mounts the snapshot at the API
container's working directory, so the usual cause is not a missing mount but
an empty or unpublished one: bringing the stack up before running `axial
publish` leaves `AXIAL_SNAPSHOT_HOST_PATH` pointing at a directory with
nothing in it, and every setting still looks correct.

`GET /health` is the check. It reads the snapshot manifest from the same cwd
the citation resolution does, so a `corpus_pin` of `null` means the API
container has no snapshot and `passage` mode is doing nothing. A non-null pin
means the vault is there. See `docs/service-deployment.md` for the mount
itself.
