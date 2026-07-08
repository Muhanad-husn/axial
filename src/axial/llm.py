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
                                     canned response; anything else --
                                     including the envelope pass, which
                                     never passes it -- gets the original
                                     envelope-shaped one). Dispatch is
                                     out-of-band (a call argument), never
                                     embedded in the prompt text itself, so
                                     no internal marker ever reaches a real
                                     model. This resolves the shared-stub
                                     collision between passes with different
                                     response shapes -- see
                                     tests/test_chunk.py's module docstring,
                                     seam decision 1, and tests/test_tag.py's
                                     seam decision 1.
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
DEFAULT_PIPELINE_CONFIG_PATH = Path("config/pipeline.yaml")
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

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
    # scope:country-case in empirical_scope, Syria in country_list -- so the
    # stub-driven end-to-end path validates cleanly against the loaded
    # schema (PRD §7.1) and exercises the scope:country-case/country branch
    # by default (tests/test_tag.py slice 02 seam decision 5).
    _CANNED_TAG_RESPONSE = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
            "country": "Syria",
        }
    )

    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        self.call_count += 1
        return _canned_response_for(pass_name)


def _canned_response_for(pass_name: str | None) -> str:
    """Dispatch the canned response by pass: `pass_name == CHUNK_PASS_NAME`
    gets the chunk-shaped canned response, `pass_name == TAG_PASS_NAME` gets
    the tag-shaped canned response (or, if `AXIAL_STUB_TAG_RESPONSE` is set
    to a non-empty value, that raw string verbatim -- read at call time, and
    only for tag-pass calls); anything else (the envelope pass, which never
    passes `pass_name`) gets the original envelope-shaped canned response.
    Shared by `StubLLMClient` and `RecordLLMClient` so `record` is
    indistinguishable from `stub` for the same call."""
    if pass_name == CHUNK_PASS_NAME:
        return StubLLMClient._CANNED_CHUNK_RESPONSE
    if pass_name == TAG_PASS_NAME:
        override = os.environ.get(STUB_TAG_RESPONSE_ENV_VAR, "")
        if override:
            return override
        return StubLLMClient._CANNED_TAG_RESPONSE
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
        self._client = httpx.Client(base_url=base_url, transport=transport)

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        response = self._client.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(f"unexpected OpenRouter response shape: {data!r}") from exc


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


def _build_openrouter_client(llm_config: dict[str, Any]) -> OpenRouterClient:
    model = llm_config.get("model", "openrouter/auto")
    base_url = llm_config.get("base_url", DEFAULT_OPENROUTER_BASE_URL)
    api_key_env = llm_config.get("api_key_env", "OPENROUTER_API_KEY")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise LLMConfigError(
            f"OpenRouter provider selected but {api_key_env!r} is not set in the environment"
        )
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
