"""`RequestContext` (issue #685, `plans/multiuser-analyst-service/README.md`
step 2): *who is asking* and *which corpus they are reading*, threaded
through the Phase B entry points that used to know neither.

Deliberately two fields, matching the plan's own shape -- not a place to grow
a third. `principal` is a bare string id (the shape `axial.service.jobs.
JobStore` already stores a job under, and what `axial.access.can_access`
checks ownership against); `corpus_pin` is the pin `axial.eval.corpus_pin`
already computes, carried here rather than re-derived, so a caller that knows
which snapshot it is bound to can say so instead of this module reaching back
into `axial.eval.corpus_pin` itself (which is not dependency-light -- see
`axial.paths`'s own module docstring for why that distinction matters).

`DEFAULT_PRINCIPAL` is the single local user every caller gets until real
identity lands (#688): the `axial` CLI never sets `principal` at all, and
`axial.service.api.current_principal` returns this same constant. Every
`default_*_dir` helper in `axial.paths` treats this one value as "unscoped"
(module docstring there), which is what makes today's single-user behaviour
fall out of the general per-principal rule for free rather than needing a
separate code path."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_PRINCIPAL = "local-analyst"


@dataclass(frozen=True)
class RequestContext:
    """Who is asking (`principal`), and, when known, which corpus snapshot
    they are reading (`corpus_pin`). `principal` defaults to
    `DEFAULT_PRINCIPAL` so a context built with no arguments at all is the
    same single local user every caller got before this existed."""

    principal: str = DEFAULT_PRINCIPAL
    corpus_pin: str | None = None
