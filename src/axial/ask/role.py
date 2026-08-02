"""The two roles `axial`'s CLI can run as (issue #536,
`plans/multiuser-analyst-service/README.md`: "Two roles only... Resist
adding more roles"). The operator runs everything; the analyst's whole
reachable surface is `axial ask` (issue #534) -- read `axial.cli`'s own
`_restrict_parser_to_analyst_role` for how that surface is enforced.

**Self-hosted only, and this module says so rather than pretending
otherwise.** The analyst and the operator are the same person on the same
machine, and the analyst uses the operator's own OpenRouter key (there is
nowhere else for it to come from until a service exists to hold it). Role
here is therefore a *command-line surface restriction*: on one machine it
stops the wrong command from being run by mistake, and it does not stop
someone determined, since both roles share one filesystem and one key. A
real boundary needs the service the plan above describes, where the two
roles are separate callers rather than a flag one process reads about
itself.
"""

from __future__ import annotations

import os

OPERATOR = "operator"
ANALYST = "analyst"
ROLES = frozenset({OPERATOR, ANALYST})

# Mirrors the `AXIAL_SECRETS_PATH`/`AXIAL_LLM_PROVIDER` env-var seam
# convention `axial.llm` already uses for a self-hosted, single-process
# setting: no config file, no interactive prompt, just an env var a shell
# profile or a wrapper script sets once.
ROLE_ENV_VAR = "AXIAL_ROLE"


class InvalidRoleError(Exception):
    """Raised when `AXIAL_ROLE` is set to something outside `ROLES`."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(f"AXIAL_ROLE={value!r} is not one of {sorted(ROLES)}")


def current_role() -> str:
    """The active role for this process: `AXIAL_ROLE`, defaulting to
    `operator` when unset or blank -- the operator role is unchanged from
    before this issue and stays the default (#536's own acceptance)."""
    value = os.environ.get(ROLE_ENV_VAR, "").strip().lower() or OPERATOR
    if value not in ROLES:
        raise InvalidRoleError(value)
    return value
