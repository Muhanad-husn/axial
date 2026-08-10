"""`can_access(principal, role, action, resource)` (issue #685, step 4): a
pure, table-driven policy function in the style of `axial.brief.interrogate.
disposition_for` -- the decision comes from this one place, never from an
accident of how a caller happened to shape a database query.

The two role values, `OPERATOR`/`ANALYST`, are the same two names
`axial.ask.role` already uses for the CLI's own operator/analyst surface
restriction (issue #536; that module's docstring names this exact gap: role
there is "a command-line surface restriction... [a] real boundary needs the
service... where the two roles are separate callers rather than a flag one
process reads about itself" -- this is that boundary). The literals are
repeated here rather than imported: `axial.ask.role` lives inside the
`axial.ask` package, whose `__init__` eagerly imports the whole engine (the
answer/record/LLM stack) to build its own `ask()` seam, and pulling that into
`axial.service.api` (measured: adds ~1.3s to the API's own import, which its
module docstring is explicit stays "small enough that nothing about
retrieval, composition or evidence lives here") for two string constants is
not a trade this module makes. The same repeated-literal call is already
made in `axial.paths` for `NAMES_DIR` versus `axial.names`, for the same
reason.

Two roles, and the plan is explicit: resist a third. An operator can do
anything -- they built and published the corpus, and on their own machine
every analysis directory is already theirs, single-user. An analyst may
always READ the corpus (never write it -- only `axial publish` does that,
and that is the operator's own CLI, never a request this function sees), and
may read or write a `WORK` resource (a saved brief, analysis, run report or
paper) only when they own it -- an id belonging to someone else is refused
here, by ownership, not by a 404 that merely never listed it in a query."""

from __future__ import annotations

from dataclasses import dataclass

# Mirrors `axial.ask.role.OPERATOR`/`.ANALYST` (module docstring: repeated,
# not imported, to keep this module and its callers import-light).
OPERATOR = "operator"
ANALYST = "analyst"

READ = "read"
WRITE = "write"

# The corpus (vault, names, map, envelopes) is global and has no owner; a
# `WORK` resource is one principal's own saved brief/analysis/run/paper.
CORPUS = "corpus"
WORK = "work"


@dataclass(frozen=True)
class Resource:
    """What `can_access` is being asked about. `owner` is always `None` for
    `CORPUS` -- nobody owns the shared corpus -- and is the principal whose
    saved work this is for `WORK`."""

    kind: str
    owner: str | None = None


def can_access(principal: str, role: str, action: str, resource: Resource) -> bool:
    """Whether `principal`, acting as `role` (`axial.ask.role.OPERATOR` or
    `.ANALYST`), may `action` (`READ`/`WRITE`) `resource`. Total and pure --
    the same arguments always return the same answer, and every role/action/
    kind combination is covered explicitly rather than falling through to a
    default."""
    if role == OPERATOR:
        return True
    if role != ANALYST:
        return False
    if resource.kind == CORPUS:
        return action == READ
    return resource.owner == principal
