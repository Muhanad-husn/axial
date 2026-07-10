"""LLM provider clients for API-based inference (PRD §5, §6 llm/).

Every LLM-backed pass in this pipeline (envelope, chunking, tagging, ...)
talks to the model through the single-method `LLMClient` interface here, so
each pass stays agnostic to which provider actually answers the call.

Provider selection (`get_client`) reads `config/pipeline.yaml`'s `llm:`
block for the default provider/model, but honors an environment-variable
override, `AXIAL_LLM_PROVIDER` -- mirroring the `AXIAL_FORCE_DOCLING_FAILURE`
fault-injection convention already established in `src/axial/extract.py`.
Three provider values are test/CI seams, not production providers, and
require no network access:

    AXIAL_LLM_PROVIDER=stub     -> StubLLMClient, a fixture-canned client
                                     used by tests and CI (no network). Its
                                     canned response is pass-aware via the
                                     `pass_name` argument to `.complete()`
                                     (e.g. `pass_name="chunk"`, passed by
                                     src/axial/chunk.py, selects a
                                     chunk-shaped canned response;
                                     `pass_name="tag"`, passed by
                                     src/axial/tag.py, selects a tag-shaped
                                     canned response; `pass_name="artifacts"`,
                                     passed by src/axial/artifacts.py, selects
                                     an artifact-role-shaped canned response
                                     whose `artifact_role` value honors the
                                     `AXIAL_STUB_ARTIFACT_ROLE` fault-injection
                                     seam below; anything else -- including
                                     the envelope pass, which never passes
                                     it -- gets the original envelope-shaped
                                     one). Dispatch is out-of-band (a call
                                     argument), never embedded in the prompt
                                     text itself, so no internal marker ever
                                     reaches a real model. This resolves the
                                     shared-stub collision between passes
                                     with different response shapes -- see
                                     tests/test_chunk.py's module docstring,
                                     seam decision 1, tests/test_tag.py's seam
                                     decision 1, and tests/test_artifacts.py's
                                     module docstring, seam decisions 1-2.
    AXIAL_LLM_PROVIDER=explode  -> ExplodingLLMClient, a poison client whose
                                     `.complete()` raises if ever invoked.
                                     Selecting it is never itself an error --
                                     only calling `.complete()` is fatal. It
                                     is the seam downstream tests use to
                                     prove "no recompute" (PRD §10):
                                     configuring it on a run that should hit
                                     a cache and crashing instead proves the
                                     pass tried to call the LLM again.
    AXIAL_LLM_PROVIDER=record   -> RecordLLMClient. Delegates to the exact
                                     same canned-response dispatch as `stub`
                                     (so its replies are indistinguishable
                                     from `stub`'s for the same prompt/
                                     pass_name), with one side effect: every
                                     prompt received by `.complete()` is
                                     appended, JSON-encoded on its own line,
                                     to the file named by
                                     `AXIAL_LLM_RECORD_PATH` (creating parent
                                     directories as needed). This is the
                                     seam that makes an assembled prompt
                                     observable black-box from a subprocess
                                     test.

The real provider, OpenRouter, is a thin HTTP client behind the same
interface, built with `httpx` (already a transitive dependency of docling;
added here as a direct one since it's imported directly). It accepts and
ignores the `pass_name` argument -- that seam exists only so the
stub/record test clients can pick a canned response, and must never affect
what is actually sent to a real model.

Every error this module can raise is an `LLMError` (or a subclass), so
callers -- e.g. `axial.envelope.run_envelope` -- can catch one type and wrap
it into their own typed error hierarchy instead of letting a bare
`ValueError`/`httpx` exception/traceback escape to the CLI.
`LLMConfigError` (missing API key, unknown provider) also subclasses
`ValueError` for backward compatibility with existing callers.
"""

from __future__ import annotations

import json
import os
import time
import tomllib
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# Slice 02 (issue #28) test/CI-only seam: when set to a non-empty value,
# the stub/record clients' tag-pass response becomes this raw string
# verbatim instead of the default canned tag response, letting a test drive
# a malformed tag payload (e.g. a missing/out-of-list country) end-to-end
# via subprocess without inventing a second stub client shape. Read at call
# time (not import time) so a test can set/unset it per-subprocess-env.
# Never affects the chunk or envelope canned responses.
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"

# Issue #81 test/CI-only fault-injection seam: when set to a positive,
# 1-indexed base-10 integer N, the Nth tag-pass call (pass_name ==
# TAG_PASS_NAME) any stub/record client makes IN THE CURRENT PROCESS raises
# a `StubInjectedTagFailureError` (an `LLMError` subclass) instead of
# returning the canned tag response; every call before the Nth still returns
# the normal canned response. The counter (`_tag_pass_call_count`) is
# per-process and never persisted across processes -- a fresh `axial`
# subprocess starts counting from zero. Read fresh from the environment on
# every call (like STUB_TAG_RESPONSE_ENV_VAR above); unset/""/non-positive
# means "never fail" (today's behavior). Honored by the shared canned-response
# dispatch both `stub` and `record` delegate to, so either provider drives it.
# This is the only existing seam that can let the first K tag calls succeed
# and the (K+1)th fail -- exactly what a mid-tag-pass checkpoint/resume test
# needs (issue #81).
STUB_TAG_FAIL_AT_ENV_VAR = "AXIAL_STUB_TAG_FAIL_AT"

SECRETS_PATH_ENV_VAR = "AXIAL_SECRETS_PATH"
DEFAULT_PIPELINE_CONFIG_PATH = Path("config/pipeline.yaml")
DEFAULT_SECRETS_PATH = Path("secrets/secrets.toml")
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Model-tier keys read from `[openrouter]` in secrets.toml (issue #23,
# requirement 2); `llm_tier` selects among them.
BUILDING_TIER = "building"
PRODUCTION_HIGH_TIER = "production_high"
PRODUCTION_LOW_TIER = "production_low"
DEFAULT_LLM_TIER = BUILDING_TIER

# Fallback model used only when secrets.toml doesn't name one for the
# selected tier (e.g. secrets.toml is entirely absent). Replaces the old
# hardcoded `openrouter/auto` default for the building tier.
DEFAULT_BUILDING_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"

# Pass name a chunking-pass call identifies itself with (see
# src/axial/chunk.py), passed out-of-band as `pass_name` to `.complete()` --
# never embedded in the prompt text -- so the stub/record canned-response
# dispatch below can tell a chunking call apart from an envelope call
# without leaking an internal marker into a real model's prompt.
CHUNK_PASS_NAME = "chunk"

# Pass name a tagging-pass call identifies itself with (see
# src/axial/tag.py), out-of-band exactly like CHUNK_PASS_NAME above -- so the
# stub/record dispatch can tell a tag call apart from both a chunk call and
# an envelope call.
TAG_PASS_NAME = "tag"

# Pass name an artifact-classification call identifies itself with (see
# src/axial/artifacts.py). Same out-of-band dispatch convention as
# CHUNK_PASS_NAME above.
ARTIFACTS_PASS_NAME = "artifacts"

# Pass name a cross-reference-detection call identifies itself with (see
# src/axial/xref.py). Same out-of-band dispatch convention as
# CHUNK_PASS_NAME above.
XREF_PASS_NAME = "xref"

# Fault-injection seam (mirroring `AXIAL_FORCE_DOCLING_FAILURE` in
# extract.py): forces the `pass_name=ARTIFACTS_PASS_NAME` canned response to
# carry exactly this string as the returned `artifact_role`, valid or not,
# so tests can drive the schema-validation hard-error path deterministically
# without needing a real model to misbehave. Unset/"" means the default
# in-schema role below applies.
STUB_ARTIFACT_ROLE_ENV_VAR = "AXIAL_STUB_ARTIFACT_ROLE"

# The default, fixed in-schema `artifact_role` the stub/record canned
# response carries when STUB_ARTIFACT_ROLE_ENV_VAR is unset -- the happy
# path. Must remain a member of config/domains/syria/schema.yaml's
# artifact_role axis (Appendix D).
_DEFAULT_STUB_ARTIFACT_ROLE = "case-study"

# Fault-injection seam (mirroring STUB_ARTIFACT_ROLE_ENV_VAR above): drives
# the `pass_name=XREF_PASS_NAME` canned response's referenced-artifact-id(s)
# on demand, read fresh from the environment on every call. Unset/"" means
# the default: the stub references NO artifact for any chunk (the
# empty/no-references case). Set to a string `S` means the stub references
# exactly `S` for every chunk-level xref call in the run -- a real,
# discovered artifact_id drives the happy path; a syntactically
# artifact-id-shaped but nonexistent string drives the dangling-link path
# (see tests/test_xref.py's module docstring, seam decision 2).
STUB_XREF_TARGET_ENV_VAR = "AXIAL_STUB_XREF_TARGET"

# Per-process, 1-indexed counter of tag-pass canned-response dispatches,
# driving the AXIAL_STUB_TAG_FAIL_AT fault-injection seam (issue #81). A
# module global so it is shared across both the `stub` and `record` clients
# (which delegate to the same `_canned_response_for` dispatch) and reset
# naturally to zero at the start of every fresh `axial` subprocess.
_tag_pass_call_count = 0


class LLMClient(Protocol):
    """A single-method completion interface every provider implements."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        """Send `prompt` to the model and return its raw text response.

        `pass_name` identifies which pass is calling (e.g. "chunk") purely
        for the test-only stub/record clients' canned-response dispatch; a
        real provider must accept and ignore it.
        """
        ...


class StubLLMClient:
    """Fixture-canned client for tests and CI: no network, deterministic
    output. Selected via `AXIAL_LLM_PROVIDER=stub`. Records `call_count` so
    callers/tests can assert how many times it was invoked."""

    _CANNED_RESPONSE = json.dumps(
        {
            "thesis": (
                "State capacity in post-conflict settings depends more on "
                "infrastructural reach than on coercive force alone."
            ),
            "toc": ["Introduction", "Comparative Cases", "Conclusion"],
            "scope": (
                "Comparative, drawing on cases from the post-conflict statebuilding literature."
            ),
            "stated_argument": (
                "Infrastructural power better explains durable post-conflict "
                "order than coercive capacity alone."
            ),
        }
    )

    # Canned response for a chunking-pass call (identified by
    # `pass_name=CHUNK_PASS_NAME`, never by prompt content). Deliberately
    # generic/unrelated to any particular fixture's body text: the chunking
    # pass owns chunk_id/section provenance itself (derived from the
    # source_id and section label, not from the model), so the canned
    # "chunks" here only need to be a well-formed, non-empty array of
    # chunk-text objects for the parser to turn into records.
    _CANNED_CHUNK_RESPONSE = json.dumps(
        {
            "chunks": [
                {"text": "Stub chunk one: a claim and its immediate support."},
                {"text": "Stub chunk two: a second argumentative unit."},
            ]
        }
    )

    # Canned response for a tag-pass call (identified by
    # `pass_name=TAG_PASS_NAME`, never by prompt content). Every value must
    # be a real member of the Syria v0 domain schema's respective axis
    # (config/domains/syria/schema.yaml) -- role:claim in role_in_argument,
    # scope:country-case in empirical_scope, Syria in country_list, and (issue
    # #29 slice 03) state/ideology in field, state-formation (+ its own
    # declared formation:bellicist subtag) in claim_type, bellicist in
    # theory_school -- so the stub-driven end-to-end path validates cleanly
    # against the loaded schema (PRD §7.1) and exercises the scope:country-
    # case/country branch by default (tests/test_tag.py slice 02 seam
    # decision 5) plus every primary+secondary axis's nested shape (slice 03
    # seam decision 9).
    _CANNED_TAG_RESPONSE = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
            "country": "Syria",
            "field": {"primary": "state", "secondary": ["ideology"]},
            "claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]},
            "theory_school": {"primary": "bellicist", "status": "candidate"},
        }
    )

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return _canned_response_for(pass_name)


def _canned_artifact_response() -> str:
    """The canned response for an artifacts-pass call (identified by
    `pass_name=ARTIFACTS_PASS_NAME`, never by prompt content): an
    `artifact_role` value, read fresh from `STUB_ARTIFACT_ROLE_ENV_VAR` on
    every call so tests can force an out-of-schema role on demand (see
    tests/test_artifacts.py's module docstring, seam decision 2), plus a
    `field` value (issue #32 slice 02) in the same
    `{"primary": <str>, "secondary": [...]}` shape `_CANNED_TAG_RESPONSE`
    already uses for the `primary_plus_secondary` cardinality -- real,
    in-schema members of config/domains/syria/schema.yaml's `field` axis, so
    the end-to-end stub path validates cleanly regardless of which
    artifact_role is in play."""
    role = os.environ.get(STUB_ARTIFACT_ROLE_ENV_VAR) or _DEFAULT_STUB_ARTIFACT_ROLE
    return json.dumps(
        {
            "artifact_role": role,
            "field": {"primary": "state", "secondary": ["ideology"]},
        }
    )


def _canned_xref_response() -> str:
    """The canned response for a xref-pass call (identified by
    `pass_name=XREF_PASS_NAME`, never by prompt content): a list of
    referenced artifact ids, read fresh from `STUB_XREF_TARGET_ENV_VAR` on
    every call so tests can drive the happy/dangling/empty reference paths
    deterministically (see tests/test_xref.py's module docstring, seam
    decision 2). Unset/"" yields an empty list (no references); set to a
    string yields a single-element list containing exactly that string."""
    target = os.environ.get(STUB_XREF_TARGET_ENV_VAR) or ""
    referenced = [target] if target else []
    return json.dumps({"referenced_artifact_ids": referenced})


def _canned_response_for(pass_name: str | None) -> str:
    """Dispatch the canned response by pass: `pass_name == CHUNK_PASS_NAME`
    gets the chunk-shaped canned response, `pass_name == TAG_PASS_NAME` gets
    the tag-shaped canned response (or, if `AXIAL_STUB_TAG_RESPONSE` is set
    to a non-empty value, that raw string verbatim -- read at call time, and
    only for tag-pass calls), `pass_name == ARTIFACTS_PASS_NAME` gets the
    artifact-role-shaped canned response, `pass_name == XREF_PASS_NAME` gets
    the referenced-artifact-ids-shaped canned response; anything else (the
    envelope pass, which never passes `pass_name`) gets the original
    envelope-shaped canned response. Shared by `StubLLMClient` and
    `RecordLLMClient` so `record` is indistinguishable from `stub` for the
    same call."""
    if pass_name == CHUNK_PASS_NAME:
        return StubLLMClient._CANNED_CHUNK_RESPONSE
    if pass_name == TAG_PASS_NAME:
        _maybe_fail_tag_call()
        override = os.environ.get(STUB_TAG_RESPONSE_ENV_VAR, "")
        if override:
            return override
        return StubLLMClient._CANNED_TAG_RESPONSE
    if pass_name == ARTIFACTS_PASS_NAME:
        return _canned_artifact_response()
    if pass_name == XREF_PASS_NAME:
        return _canned_xref_response()
    return StubLLMClient._CANNED_RESPONSE


class RecordLLMClient:
    """Test/CI-only client selected via `AXIAL_LLM_PROVIDER=record`: appends
    every prompt it receives, JSON-encoded on its own line, to
    `AXIAL_LLM_RECORD_PATH` (creating parent directories as needed), then
    returns exactly what `StubLLMClient` would return for that same call.
    This makes an assembled prompt observable black-box from a subprocess
    test without inventing a second canned-response contract."""

    def __init__(self, record_path: Path) -> None:
        self._record_path = record_path
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        self._record_path.parent.mkdir(parents=True, exist_ok=True)
        with self._record_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(prompt) + "\n")
        return _canned_response_for(pass_name)


class ExplodingLLMClient:
    """Poison client that raises if its completion method is ever invoked.

    A legitimate production test-seam (like `AXIAL_FORCE_DOCLING_FAILURE` in
    `extract.py`), selected via `AXIAL_LLM_PROVIDER=explode`. Constructing or
    selecting this client must never itself raise -- only `.complete()` is
    fatal, so a run that never calls the LLM completes normally even with
    this provider configured.
    """

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        raise RuntimeError(
            "ExplodingLLMClient.complete() was invoked -- this indicates an "
            "LLM-backed pass attempted to recompute instead of reusing a "
            "cached result"
        )


class LLMError(Exception):
    """Base class for all LLM-client errors (config, transport, response)."""


class LLMConfigError(LLMError, ValueError):
    """Raised for a misconfigured LLM provider: a missing API key or an
    unknown `provider` value. Subclasses `ValueError` too, so existing
    callers that catch `ValueError` for this condition keep working."""


class OpenRouterError(LLMError):
    """Raised when the OpenRouter API returns an error or malformed response."""


class StubInjectedTagFailureError(LLMError):
    """Raised by the shared stub/record canned-response dispatch when the
    `AXIAL_STUB_TAG_FAIL_AT` seam fires on the Nth tag-pass call (issue #81).

    A subclass of `LLMError` (never a bare exception) precisely so it
    propagates like a real transport-level failure: unchanged through
    `axial.model_json.complete_json` (which catches only malformed JSON) and
    caught by `axial.tag.run_tag`'s `except (LLMError, httpx.HTTPError)` ->
    `LLMFailedError` -> `axial.vault.run_vault_write`'s `except TagError` ->
    `TaggingFailedError` -> the CLI's `except VaultError` typed-error/
    non-zero-exit path -- i.e. exactly today's mid-tag failure contract, not
    a new branch."""


def _maybe_fail_tag_call() -> None:
    """Advance the per-process tag-pass call counter and, when
    `AXIAL_STUB_TAG_FAIL_AT` names a positive integer equal to the new count,
    raise `StubInjectedTagFailureError` (issue #81's mid-tag fault seam).

    Read fresh from the environment on every call; an unset, empty,
    non-integer, or non-positive value never fails (today's behavior). The
    counter advances for every tag-pass dispatch regardless, so the "Nth tag
    call" is well-defined independent of whether the seam is armed."""
    global _tag_pass_call_count
    _tag_pass_call_count += 1
    raw = os.environ.get(STUB_TAG_FAIL_AT_ENV_VAR, "")
    try:
        fail_at = int(raw)
    except (TypeError, ValueError):
        return
    if fail_at > 0 and _tag_pass_call_count == fail_at:
        raise StubInjectedTagFailureError(
            f"{STUB_TAG_FAIL_AT_ENV_VAR}={fail_at}: injected tag-pass failure "
            f"on tag call #{_tag_pass_call_count} (issue #81 fault-injection seam)"
        )


# httpx's 5s default read timeout kills a real completion before it starts:
# the envelope pass's prompt carries a whole document, and a model can
# legitimately take minutes to answer it (issue #60). connect/write/pool
# stay tight -- only the read side needs to be generous.
_REQUEST_TIMEOUT = httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)

# Bounded retry (issue #60): a single transient failure -- a read timeout,
# HTTP 429, or a 5xx -- must not abort a multi-hour ingestion run. 3 total
# attempts, short exponential backoff between them. Any other failure (a
# non-retryable 4xx via `raise_for_status`, or a malformed response shape)
# fails immediately, exactly as before this issue. Issue #82 widens the
# caught exception from `httpx.TimeoutException` to its superclass
# `httpx.TransportError`: a raw TCP reset surfaces as `httpx.ReadError` (or
# `ConnectError`/`WriteError`/`RemoteProtocolError`), not a timeout, and is
# exactly as transient.
#
# Issue #66 extends the same budget to a well-shaped HTTP 200 whose
# `content` is empty/whitespace/None: a provider occasionally answers with
# nothing, and that is transient exactly like a timeout or a 5xx -- the
# downstream JSON parser must never see it -- whereas a genuinely malformed
# response shape (missing keys) still fails immediately, unretried.
#
# Issue #69 extends the same budget again to a well-shaped HTTP 200 whose
# `choices[0].finish_reason` is present and not `"stop"` (e.g. `"length"`):
# the completion was cut off mid-output, and a truncated JSON fragment is
# just as unusable to a downstream parser as an empty one -- retryable
# within the same budget, with a final-attempt failure naming the reason. A
# missing/null `finish_reason` is accepted as success: some providers omit
# it, and absence must not be punished.
_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.5, 2.0)

# Explicit, generous `max_tokens` sent with every request (issue #69, raised
# in #74): chunking responses echo whole section text back, and a
# conservative provider default can truncate that long before this budget is
# reached. Measured on the gold corpus: real sections reach ~175KB of text,
# and echoing one back needs ~44k output tokens -- well over the original
# 16384. The `deepseek/deepseek-v4-flash` provider ceiling is 65,536
# (`top_provider.max_completion_tokens` via the OpenRouter models API);
# 60000 leaves headroom under that cap. Sections whose echoed chunking
# response would exceed even this budget are a distinct, out-of-scope
# problem (P1-1, deterministic long-section splitting) -- the #70 typed
# truncation error remains the loud, correct failure for that case.
_MAX_COMPLETION_TOKENS = 60000

# Module-level indirection so tests can patch out the actual sleep (e.g.
# `monkeypatch.setattr(llm, "_sleep", lambda seconds: None)`) instead of
# waiting out the real backoff.
_sleep = time.sleep


class OpenRouterClient:
    """Thin HTTP client for OpenRouter's chat-completions endpoint.

    Built for a mockable transport (`httpx.MockTransport`) so it is unit
    tested without ever making a live network call; only the provider
    factory wires up a real `httpx.Client` transport in production.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_OPENROUTER_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = httpx.Client(
            base_url=base_url, transport=transport, timeout=_REQUEST_TIMEOUT
        )

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == _MAX_ATTEMPTS
            try:
                response = self._client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": self._model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": _MAX_COMPLETION_TOKENS,
                    },
                )
            except httpx.TransportError:
                if is_last_attempt:
                    raise
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            if not is_last_attempt and (response.status_code == 429 or response.status_code >= 500):
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            response.raise_for_status()
            data = response.json()
            try:
                choice = data["choices"][0]
                content = choice["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise OpenRouterError(f"unexpected OpenRouter response shape: {data!r}") from exc

            # A missing/null finish_reason is accepted as success -- some
            # providers omit it -- only a present-and-not-"stop" value (e.g.
            # "length") signals a truncated completion (issue #69).
            finish_reason = choice.get("finish_reason")
            is_empty = content is None or not content.strip()
            is_truncated = finish_reason is not None and finish_reason != "stop"

            if is_empty or is_truncated:
                if is_last_attempt:
                    if is_truncated:
                        raise OpenRouterError(
                            f"completion truncated: finish_reason={finish_reason!r}"
                        )
                    raise OpenRouterError("empty completion from provider")
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            return content

        raise AssertionError("unreachable: the retry loop always returns or raises")


def _forced_provider() -> str | None:
    """Read the `AXIAL_LLM_PROVIDER` env override; unset/"" means no override."""
    provider = os.environ.get(PROVIDER_ENV_VAR, "")
    return provider or None


def _load_pipeline_llm_config(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> dict[str, Any]:
    """Read the `llm:` block from `config/pipeline.yaml`; an absent file or
    block yields an empty dict so defaults apply."""
    if not config_path.is_file():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    return document.get("llm", {}) or {}


def _secrets_path() -> Path:
    """Resolve the path to read `[openrouter]` secrets from: the
    `AXIAL_SECRETS_PATH` env override when set/non-empty, else
    `secrets/secrets.toml` relative to the repo root -- mirroring the
    `AXIAL_LLM_PROVIDER` / `AXIAL_LLM_RECORD_PATH` env-var seam convention
    already used in this module (issue #23, requirement 4)."""
    override = os.environ.get(SECRETS_PATH_ENV_VAR, "")
    return Path(override) if override else DEFAULT_SECRETS_PATH


def _load_openrouter_secrets(secrets_path: Path) -> dict[str, Any]:
    """Read the `[openrouter]` table from `secrets_path`; an absent file or
    table yields an empty dict so the env-var/default fallbacks apply.

    A syntactically invalid TOML file is a configuration error, not a
    transport/parsing detail that should escape as a raw
    `tomllib.TOMLDecodeError` -- every error this module raises must be an
    `LLMError` (module docstring), so it is re-raised as `LLMConfigError`,
    mirroring `_resolve_api_key`'s error style.
    """
    if not secrets_path.is_file():
        return {}
    with secrets_path.open("rb") as handle:
        try:
            document = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise LLMConfigError(f"secrets file '{secrets_path}' is not valid TOML: {exc}") from exc
    return document.get("openrouter", {}) or {}


# Maps an `llm_tier` selector value to the secrets.toml key naming that
# tier's model (issue #23, requirement 2). "building" maps to
# "building_model" rather than to itself so the key mirrors the other two
# ("production_high", "production_low"), which are already model-name keys.
TIER_TO_MODEL_KEY = {
    BUILDING_TIER: "building_model",
    PRODUCTION_HIGH_TIER: "production_high",
    PRODUCTION_LOW_TIER: "production_low",
}


def _resolve_api_key(secrets: dict[str, Any]) -> str:
    """API key resolution order (issue #23, requirement 1): secrets.toml's
    `api_key` is PRIMARY; `OPENROUTER_API_KEY` is the fallback used only
    when the file is absent or lacks the key; neither present is a hard
    `LLMConfigError`."""
    api_key = secrets.get("api_key") or os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise LLMConfigError(
            "OpenRouter provider selected but no API key was found: set "
            "'[openrouter].api_key' in secrets/secrets.toml or the "
            "OPENROUTER_API_KEY environment variable"
        )
    return api_key


def _resolve_model(secrets: dict[str, Any], llm_config: dict[str, Any]) -> str:
    """Model resolution (issue #23, requirement 2): `llm_tier` selects which
    of the three model-name keys in secrets.toml to use; an unset selector
    defaults to the building tier. Falls back to `config/pipeline.yaml`'s
    `llm.model`, and finally to the building-tier default model, only when
    secrets.toml doesn't name a model for the selected tier (e.g. the file
    is absent entirely).

    A non-`building` tier (`production_high`/`production_low`) whose model
    key is missing from secrets.toml is a misconfiguration, not a case to
    paper over: silently falling through to `DEFAULT_BUILDING_MODEL` there
    would make a run believed to use a paid production model silently use
    the free building model instead. Only the `building` tier keeps the
    fallback chain, so today's no-secrets-file behavior is unchanged.
    """
    tier = secrets.get("llm_tier") or DEFAULT_LLM_TIER
    model_key = TIER_TO_MODEL_KEY.get(tier)
    if model_key is None:
        raise LLMConfigError(f"unknown llm_tier: {tier!r}")
    model = secrets.get(model_key) or llm_config.get("model")
    if model:
        return model
    if tier != BUILDING_TIER:
        raise LLMConfigError(
            f"llm_tier {tier!r} was selected but secrets.toml has no "
            f"{model_key!r} key naming a model for it; set "
            f"'[openrouter].{model_key}' in secrets/secrets.toml"
        )
    return DEFAULT_BUILDING_MODEL


def _build_openrouter_client(llm_config: dict[str, Any]) -> OpenRouterClient:
    secrets = _load_openrouter_secrets(_secrets_path())
    base_url = llm_config.get("base_url", DEFAULT_OPENROUTER_BASE_URL)
    api_key = _resolve_api_key(secrets)
    model = _resolve_model(secrets, llm_config)
    return OpenRouterClient(api_key=api_key, model=model, base_url=base_url)


def get_client(config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> LLMClient:
    """Build the configured `LLMClient`.

    Provider resolution order: the `AXIAL_LLM_PROVIDER` env override, then
    `config/pipeline.yaml`'s `llm.provider`, defaulting to `"openrouter"`.
    """
    llm_config = _load_pipeline_llm_config(config_path)
    provider = _forced_provider() or llm_config.get("provider", "openrouter")

    if provider == "stub":
        return StubLLMClient()
    if provider == "explode":
        return ExplodingLLMClient()
    if provider == "record":
        record_path_str = os.environ.get(RECORD_PATH_ENV_VAR)
        if not record_path_str:
            raise LLMConfigError(
                f"record provider selected but {RECORD_PATH_ENV_VAR!r} is not "
                f"set in the environment"
            )
        return RecordLLMClient(Path(record_path_str))
    if provider == "openrouter":
        return _build_openrouter_client(llm_config)
    raise LLMConfigError(f"unknown LLM provider: {provider!r}")
