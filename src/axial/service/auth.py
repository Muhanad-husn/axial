"""Token verification for `current_principal` (issue #763): a Supabase-
issued JWT becomes a verified principal at the API edge, or the request
never reaches a route body.

**JWKS only, no shared-secret path** -- the design call taken at #688's
kickoff and recorded on #763: a Supabase project signs asymmetrically and
publishes its public keys at `<project>/auth/v1/.well-known/jwks.json`, so
`AXIAL_SUPABASE_JWKS_URL` is the one setting this module reads.
`jwt.PyJWKClient` (`pyjwt[crypto]`) fetches and caches that key set,
re-fetching only when an unrecognised `kid` shows up (key rotation, its own
built-in behaviour) -- never a fetch per request. `_jwks_client` caches one
client per URL for the process lifetime on top of that, so the fetch itself
happens at most once per deployment, not once per worker thread.

**Unset means closed, not open.** With no `AXIAL_SUPABASE_JWKS_URL`, every
request is `401` -- a deployer who forgot the setting gets a locked door,
never a shared local account. Unlike `AXIAL_CITATION_MODE`
(`axial.service.citation`'s own module docstring), whose unconfigured value
is a product decision the deployer may reverse, this one has no useful
unconfigured value at all: the safe state here is "nobody gets in."

**The subject's shape is checked here, once** -- carried over from #685/
#688: a Supabase `sub` is a UUID, and `axial.paths.scoped_for_principal`
resolves a principal straight into a filesystem path with no shape check of
its own, on purpose, so there is exactly one place a hostile or malformed
subject is refused rather than two places that would have to agree.
`uuid.UUID`, round-tripped back to its own canonical string, is the whole
check: anything that parses and re-serializes to itself is exactly 36
lowercase hex-and-hyphen characters, which can never be `..`, carry a path
separator, or collide with a Windows-reserved name (`CON`, `NUL`, a
trailing dot or space). A token whose subject fails this is `401`, not a
sanitised principal -- the issue's own line."""

from __future__ import annotations

import os
import uuid
from functools import lru_cache

import jwt
from fastapi import HTTPException

# One setting (issue #688's kickoff call): no legacy HS256 shared-secret
# path, since no Supabase project exists yet that would need one.
JWKS_URL_ENV_VAR = "AXIAL_SUPABASE_JWKS_URL"

# Every Supabase access token for a signed-in user carries this fixed
# audience -- not a second setting, since no deployment would ever need a
# different value here.
_AUDIENCE = "authenticated"

_JWKS_SUFFIX = "/.well-known/jwks.json"

# Issue #767, live 2026-08-12: the verifying machine's clock trailed the
# Supabase project's by 5.0s, so every freshly-issued token's `iat` (and
# `nbf`) landed in the verifier's future and `jwt.decode` refused it --
# every request 401'd, and the web client turns a 401 into a forced
# sign-out, so the whole product looked unusable. 60s is the conventional
# leeway: enough to absorb ordinary drift on a machine with no time daemon,
# not enough to meaningfully extend a token's life (PyJWT applies the same
# leeway to `exp`, so a token still expires at most 60s late).
_CLOCK_SKEW_LEEWAY_SECONDS = 60


def _issuer_from_jwks_url(jwks_url: str) -> str:
    """The `iss` a Supabase project's own tokens carry: the JWKS URL with
    its well-known suffix removed, so `AXIAL_SUPABASE_JWKS_URL` alone
    supplies both settings the issue calls for, not a second env var."""
    return jwks_url[: -len(_JWKS_SUFFIX)] if jwks_url.endswith(_JWKS_SUFFIX) else jwks_url


@lru_cache(maxsize=1)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    """One `PyJWKClient` per JWKS URL, for the process lifetime. Keyed on
    the URL itself (not a bare singleton) so a test that points at its own
    local JWKS (a fresh keypair per test module, module docstring) never
    reuses another test's cached client or key set."""
    return jwt.PyJWKClient(jwks_url)


def _valid_principal_shape(subject: str) -> bool:
    """True only when `subject` parses as a UUID AND its canonical string
    form is itself -- rejecting non-canonical spellings `uuid.UUID` would
    otherwise accept (mixed case, missing hyphens, a `urn:uuid:` prefix)
    that this allowlist has no reason to widen for (module docstring)."""
    try:
        return str(uuid.UUID(subject)) == subject
    except (ValueError, AttributeError, TypeError):
        return False


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="invalid or missing bearer token")


def verify_bearer_token(token: str) -> str:
    """`token`'s own verified subject, or `HTTPException(401)` -- the whole
    identity edge (issue #763's `current_principal`). Fails closed with no
    `AXIAL_SUPABASE_JWKS_URL` configured (module docstring): every request
    is refused rather than falling back to a shared local account."""
    jwks_url = os.environ.get(JWKS_URL_ENV_VAR, "").strip()
    if not jwks_url:
        raise _unauthorized()

    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=[signing_key.algorithm_name],
            audience=_AUDIENCE,
            issuer=_issuer_from_jwks_url(jwks_url),
            leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
        )
    except jwt.PyJWTError as exc:
        # Covers a malformed token, an expired one, a bad signature, a
        # wrong `iss`/`aud`, an unrecognised `kid` after `PyJWKClient`'s own
        # re-fetch, and a JWKS the endpoint could not be reached for --
        # every one of these is the same "not a valid token" to the caller.
        raise _unauthorized() from exc

    subject = payload.get("sub")
    if not isinstance(subject, str) or not _valid_principal_shape(subject):
        raise _unauthorized()
    return subject
