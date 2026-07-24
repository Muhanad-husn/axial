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
                                     chunk-shaped canned response (or, if
                                     `AXIAL_STUB_CHUNK_RESPONSE` is set to a
                                     non-empty value, that raw string
                                     verbatim -- issue #100);
                                     `pass_name="tag"`, passed by
                                     src/axial/tag.py, selects a tag-shaped
                                     canned response; `pass_name="artifacts"`,
                                     passed by src/axial/artifacts.py, selects
                                     an artifact-role-shaped canned response
                                     whose `artifact_role` value honors the
                                     `AXIAL_STUB_ARTIFACT_ROLE` fault-injection
                                     seam below; `pass_name="interrogate"`,
                                     passed by src/axial/brief/interrogate.py,
                                     selects an interrogation-shaped canned
                                     response (or, if
                                     `AXIAL_STUB_INTERROGATE_RESPONSE` is set
                                     to a non-empty value, that raw string
                                     verbatim -- issue #252); `pass_name=
                                     "synthesize"`, passed by
                                     src/axial/analyze/synthesis.py, selects a
                                     claim-graph-shaped canned response (or,
                                     if `AXIAL_STUB_SYNTHESIZE_RESPONSE` is
                                     set to a non-empty value, that raw string
                                     verbatim -- issue #256); `pass_name=
                                     "attribution"`, passed by
                                     src/axial/validators/attribution.py,
                                     selects a flagged-claim-ids-shaped canned
                                     response (or, if
                                     `AXIAL_STUB_ATTRIBUTION_RESPONSE` is set
                                     to a non-empty value, that raw string
                                     verbatim -- issue #258); `pass_name=
                                     "counter_position"`, passed by
                                     src/axial/validators/counter_position.py,
                                     selects a verdict-shaped canned response
                                     (or, if
                                     `AXIAL_STUB_COUNTER_POSITION_RESPONSE` is
                                     set to a non-empty value, that raw string
                                     verbatim -- issue #259); `pass_name=
                                     "grounding"`, passed by
                                     src/axial/gates/grounding.py, selects a
                                     verdict-shaped canned response (scripted
                                     per-call via
                                     `AXIAL_STUB_GROUNDING_RESPONSE_SEQUENCE`
                                     -- issue #262); anything else --
                                     including the envelope pass, which never
                                     passes it -- gets the original
                                     envelope-shaped one). Dispatch is
                                     out-of-band (a call
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

import hashlib
import json
import os
import sys
import threading
import time
import tomllib
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml

from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# Slice 02 (issue #28) test/CI-only seam: when set to a non-empty value,
# the stub/record clients' tag-pass response becomes this raw string
# verbatim instead of the default canned tag response, letting a test drive
# a malformed tag payload (e.g. a missing/out-of-list polity) end-to-end
# via subprocess without inventing a second stub client shape. Read at call
# time (not import time) so a test can set/unset it per-subprocess-env.
# Never affects the chunk or envelope canned responses.
STUB_TAG_RESPONSE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE"

# Issue #100 test/CI-only seam: mirrors STUB_TAG_RESPONSE_ENV_VAR above,
# exactly, for the chunk pass instead of the tag pass. When set to a
# non-empty value, the stub/record clients' chunk-pass response becomes this
# raw string verbatim instead of the default canned chunk response, letting
# a test drive a malformed/invalid-escape chunk payload end-to-end via
# subprocess (e.g. tests/test_chunk_invalid_escapes.py). Read at call time
# (not import time), like STUB_TAG_RESPONSE_ENV_VAR. Never affects the tag,
# artifacts, xref, or envelope canned responses.
STUB_CHUNK_RESPONSE_ENV_VAR = "AXIAL_STUB_CHUNK_RESPONSE"

# Issue #104 test/CI-only seam: mirrors STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR
# above, exactly, for the chunk pass instead of the tag pass. A JSON-encoded
# array of raw chunk-pass response strings, each in exactly the shape
# STUB_CHUNK_RESPONSE_ENV_VAR already accepts. When set to a NON-EMPTY JSON
# array, it takes priority over STUB_CHUNK_RESPONSE_ENV_VAR for the
# chunk-pass canned-response dispatch (both `stub` and `record`, since
# `record` delegates to the same dispatch). A FRESH, dedicated per-process,
# 1-indexed counter (`_chunk_pass_call_count`) -- never shared with the
# tag-pass counter -- selects which element answers the Nth such call:
# `sequence[(N - 1) % len(sequence)]`, cycling once the array is exhausted.
# Read fresh (JSON-decoded) from the environment on every call. An unset/
# empty value or an empty JSON array falls through to
# STUB_CHUNK_RESPONSE_ENV_VAR (today's behavior).
STUB_CHUNK_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE"

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

# Issue #102 test/CI-only seam: a JSON-encoded array of raw tag-pass response
# strings, each in exactly the shape `AXIAL_STUB_TAG_RESPONSE` already accepts
# (a complete raw tag-pass response body). When set to a NON-EMPTY JSON array,
# it takes priority over `AXIAL_STUB_TAG_RESPONSE` for the tag-pass-family
# canned-response dispatch (both `stub` and `record`, since `record` delegates
# to the same dispatch). The SAME per-process, 1-indexed counter that already
# drives `AXIAL_STUB_TAG_FAIL_AT` (`_tag_pass_call_count`) selects which
# element answers the Nth such call -- `sequence[(N - 1) % len(sequence)]`,
# cycling once the array is exhausted (a 2-element sequence alternates
# forever). Read fresh (JSON-decoded) from the environment on every call, like
# every other seam here. Fires for EVERY tag-pass-family call -- an original
# per-chunk ask AND a P0-6 bounded correction re-ask alike -- so a test can
# drive "chunk N's first answer is X, its correction answer is Y" end-to-end
# without needing to know the correction re-ask's own prompt wording. An
# unset/empty value or an empty JSON array falls through to
# `AXIAL_STUB_TAG_RESPONSE` (today's behavior).
STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_TAG_RESPONSE_SEQUENCE"

# Issue #98 test/CI-only fault-injection seam: exactly `STUB_TAG_FAIL_AT_ENV_VAR`
# above, mirrored for the artifacts pass instead of the tag pass. When set to
# a positive, 1-indexed base-10 integer N, the Nth artifacts-pass call
# (pass_name == ARTIFACTS_PASS_NAME) any stub/record client makes IN THE
# CURRENT PROCESS raises a `StubInjectedArtifactFailureError` (an `LLMError`
# subclass) instead of returning the canned artifact response; every call
# before the Nth still returns the normal canned response. The counter
# (`_artifact_pass_call_count`) is per-process and never persisted across
# processes. Read fresh from the environment on every call; unset/""/
# non-positive means "never fail" (today's behavior). Honored by the shared
# canned-response dispatch both `stub` and `record` delegate to.
STUB_ARTIFACT_FAIL_AT_ENV_VAR = "AXIAL_STUB_ARTIFACT_FAIL_AT"

# Issue #253 slice 01 test/CI-only seam: the scripted tool-call channel for
# `StubLLMClient`/`RecordLLMClient`'s `complete_with_tools()` (the retrieval
# loop's model-driven tool-use entry point, distinct from `.complete()`'s
# JSON-completion channel above). A JSON-encoded array whose elements are
# each either `{"tool": <name>, "args": {...}}` (the next tool call the
# scripted model issues) or `null` (the model's turn carries no tool call --
# the loop's clean-end signal). Unlike `STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR`
# et al., this is indexed by a counter kept on the CLIENT INSTANCE, not a
# module-level global: the retrieval loop's tests construct their own
# `StubLLMClient`/`RecordLLMClient` in-process (never via subprocess), so a
# process-wide counter would leak state across tests in the same worker --
# an instance counter can't. Cycles once exhausted
# (`sequence[index % len(sequence)]`), mirroring the existing sequence seams'
# own cycling convention. Read fresh from the environment on every call.
# Unset/"" or an empty JSON array is treated as "no tool call" (`None`).
STUB_TOOL_CALLS_ENV_VAR = "AXIAL_STUB_TOOL_CALLS"

SECRETS_PATH_ENV_VAR = "AXIAL_SECRETS_PATH"
# `DEFAULT_PIPELINE_CONFIG_PATH` itself now lives in `axial.paths` (issue
# #249 finding 1), imported above and re-exported here under its original
# name so every existing `from axial.llm import DEFAULT_PIPELINE_CONFIG_PATH`
# caller (`artifacts`, `chunk`, `envelope`, `eval`, `gold`, `ingest`, `tag`,
# `vault`, `drive`, `pipeline_ready`, `polity_canonical`) is unaffected.
DEFAULT_SECRETS_PATH = Path("secrets/secrets.toml")
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

# Model-tier keys read from `[openrouter]` in secrets.toml (issue #23,
# requirement 2); `llm_tier` selects among them.
BUILDING_TIER = "building"
PRODUCTION_HIGH_TIER = "production_high"
PRODUCTION_LOW_TIER = "production_low"
# A fourth, narrower tier (founder-requested model-swap experiment, 2026-07):
# `model_by_pass` needs to route the synthesis pass to a model distinct from
# `production_high` (which `envelope` keeps using), so synthesis gets its own
# named tier rather than repurposing an existing one two other passes share.
PRODUCTION_SYNTHESIS_TIER = "production_synthesis"
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

# Pass name the structural-envelope pass's `.complete()` call identifies
# itself with (see src/axial/envelope.py). Same out-of-band dispatch
# convention as CHUNK_PASS_NAME above -- issue #207 threads this through so
# the per-pass reasoning setting (§7.9) can tell the envelope call apart
# from every other pass.
ENVELOPE_PASS_NAME = "envelope"

# Pass name the holdings-completeness check's single per-source call
# identifies itself with (see src/axial/holdings.py, issue #284, PRD §7.11).
# Same out-of-band dispatch convention as CHUNK_PASS_NAME above.
HOLDINGS_PASS_NAME = "holdings"

# Pass name the brief-interrogation pre-pass's single per-brief call
# identifies itself with (see src/axial/brief/interrogate.py, issue #252,
# PRD §7.2). Same out-of-band dispatch convention as CHUNK_PASS_NAME above --
# naming this constant is also what makes the pass routable through the
# `model_by_pass` / `reasoning_by_pass` / `votes_by_pass` config seams
# (§7.11, TENTATIVE): unnamed here, it simply resolves every one of those to
# its safe default (no model override, reasoning off, single draw), exactly
# like any other pass this module does not single out.
INTERROGATE_PASS_NAME = "interrogate"

# Pass name the router's content-apparatus classification call identifies
# itself with (see src/axial/chunk.py / src/axial/router.py, issue #207,
# PRD §7.8 "Model-backed classification of flagged candidates"). Same
# out-of-band dispatch convention as CHUNK_PASS_NAME above.
CONTENT_APPARATUS_PASS_NAME = "content_apparatus"

# Pass name the stage-3 agentic retrieval loop's tool-calling turns identify
# themselves with (see src/axial/retrieve/loop.py, issue #253, PRD §7.5/§7.6).
# Same out-of-band dispatch convention as CHUNK_PASS_NAME above -- naming
# this constant is what makes the pass routable through the
# `model_by_pass`/`reasoning_by_pass`/`votes_by_pass` config seams (§7.11
# TENTATIVE); slice 01 only wires the name through, it does not choose a
# tier (that is a measured, separate decision per §7.11's own note).
RETRIEVE_PASS_NAME = "retrieve"

# Pass name the stage-4 synthesis pass's single per-brief call identifies
# itself with (see src/axial/analyze/synthesis.py, issue #256, PRD §7.4/
# §7.11). Same out-of-band dispatch convention as CHUNK_PASS_NAME above --
# naming this constant is what makes the pass routable through the
# `model_by_pass`/`reasoning_by_pass` config seams; unlike RETRIEVE_PASS_NAME,
# §7.11 already states a tier for this pass (high, reasoning ON), so it is
# also named in DEFAULT_REASONING_BY_PASS below.
SYNTHESIZE_PASS_NAME = "synthesize"

# Pass name the stage-5 attribution validator's bounded (b)-seam honesty
# check identifies itself with (see src/axial/validators/attribution.py,
# issue #258, PRD §7.9): does a claim marked "b" (tool-infers-across-sources)
# read as though a single source asserted it. Same out-of-band dispatch
# convention as CHUNK_PASS_NAME above -- naming this constant is what makes
# the check routable through `model_by_pass`, which is the whole point: it
# must resolve to a DIFFERENT model than SYNTHESIZE_PASS_NAME, never the
# model that generated the claims it is checking (§7.9, charter §2).
ATTRIBUTION_PASS_NAME = "attribution"

# Pass name the stage-5 counter-position validator's bounded steelman-quality
# check identifies itself with (see src/axial/validators/counter_position.py,
# issue #259, PRD §7.9): does the §7.8 counter-position section state the
# opposing school at its strongest, or a strawman. Same out-of-band dispatch
# convention as ATTRIBUTION_PASS_NAME above -- naming this constant is what
# makes the check routable through `model_by_pass`, and it must resolve to a
# DIFFERENT model than SYNTHESIZE_PASS_NAME, never the model that generated
# the counter-position it is checking (§7.9, charter §2).
COUNTER_POSITION_PASS_NAME = "counter_position"

# Pass name the rung-3 grounding gate's independent judge call identifies
# itself with (see src/axial/gates/grounding.py, issue #262, PRD §10): does a
# kind-"a" claim's cited grounds substantively support the claim's text. Same
# out-of-band dispatch convention as CHUNK_PASS_NAME above -- naming this
# constant is what makes the judge routable through `model_by_pass`, which is
# the whole point: it must resolve to a DIFFERENT model, from a different
# model family, than SYNTHESIZE_PASS_NAME, since the generating model must
# never grade its own output (§10, charter §2). Mirrors ATTRIBUTION_PASS_NAME
# exactly, one pass name per independent judge seam.
GROUNDING_PASS_NAME = "grounding"

# Pass name the rung-3 calibration gate's independent judge call identifies
# itself with (see src/axial/gates/calibration.py, issue #263, PRD §10): does
# a claim hold up as CORRECT given its cited grounds -- the per-claim signal
# the band-wise reliability metric compares against each confidence band's
# stated target. Same out-of-band dispatch convention as GROUNDING_PASS_NAME
# above, including the same self-grading guard: it must resolve to a
# DIFFERENT model than SYNTHESIZE_PASS_NAME.
CALIBRATION_PASS_NAME = "calibration"

# Pass name the rung-3 adversarial-brief red-teaming gate's independent
# premise-correspondence judge call identifies itself with (see
# src/axial/gates/adversarial.py, issue #264, PRD §10): does a premise the
# interrogation pre-pass (INTERROGATE_PASS_NAME) found correspond to the
# seeded brief's declared "answer key" premise. Same out-of-band dispatch
# convention as CHUNK_PASS_NAME above -- naming this constant is what makes
# the judge routable through `model_by_pass`; it must resolve to a DIFFERENT
# model than INTERROGATE_PASS_NAME, since the pass that proposed the
# premises_found being scored must never grade whether its own finding
# corresponds to the seed (§10, charter §2). Mirrors GROUNDING_PASS_NAME
# exactly, one pass name per independent judge seam.
PREMISE_MATCH_PASS_NAME = "premise_match"

# Per-pass model reasoning (§7.9, issue #207): reasoning is ON for the
# structural-envelope pass and the content-apparatus classification gate --
# both small, judgment-heavy, once/rarely-per-source calls -- and OFF
# (unchanged since #147) for the high-volume tag/artifacts/xref calls and
# any pass not named here (the safe default). This is the CODE-LEVEL
# default `OpenRouterClient` falls back to when constructed without an
# explicit `reasoning_by_pass` mapping (e.g. a test building it directly);
# `config/pipeline.yaml`'s own `llm.reasoning_by_pass` block (read by
# `_resolve_reasoning_by_pass` below) is the actual carried-per-pass source
# of truth for a real run and can override any entry here without a code
# change -- mirrors this default exactly today.
# Value is `True`/`False` (reasoning at OpenRouter's implicit default effort,
# or off) or a `str` naming an explicit `reasoning.effort` level ("low",
# "medium", "high", "xhigh", ...) -- added for the founder-requested
# model-swap experiment (2026-07): several models (see `_post_with_deadline`)
# only support a subset of effort levels, so a bare `enabled: true` leaves
# OpenRouter to silently pick among them; naming the level here makes that
# choice explicit and deliberate instead.
DEFAULT_REASONING_BY_PASS: dict[str, bool | str] = {
    ENVELOPE_PASS_NAME: True,
    CONTENT_APPARATUS_PASS_NAME: True,
    HOLDINGS_PASS_NAME: True,
    SYNTHESIZE_PASS_NAME: True,
    TAG_PASS_NAME: False,
    ARTIFACTS_PASS_NAME: False,
    XREF_PASS_NAME: False,
}

# Per-pass MODEL tiering (DEC-26, issue #235) -- the project's first per-pass
# model override, mirroring `DEFAULT_REASONING_BY_PASS`'s own per-pass shape
# exactly, but resolved by `OpenRouterClient` to concrete MODEL NAMES (never
# tier names) before construction, since a tier name alone means nothing
# without the secrets.toml tier->model lookup (`_resolve_model_by_pass`
# below). This is the CODE-LEVEL default `OpenRouterClient` falls back to
# when constructed without an explicit `model_by_pass` mapping (e.g. a test
# building it directly, mirroring `DEFAULT_REASONING_BY_PASS`'s own such
# callers) -- deliberately EMPTY: unlike reasoning (a bool with a safe
# always-correct default), a per-pass model override is a brand-new feature
# with no code-level default of its own, so a pass absent here (or absent
# from config) simply keeps the client's own default configured model.
# `config/pipeline.yaml`'s own `llm.model_by_pass` block (read by
# `_resolve_model_by_pass` below) is the actual carried-per-pass source of
# truth for a real run -- "never hardcoded" (DEC-26): the envelope pass's
# `production_high` override lives there, not here.
DEFAULT_MODEL_BY_PASS: dict[str, str] = {}

# Per-pass best-of-N voting (DEC-31, issue #294): how many times a pass draws
# its per-unit call before majority-voting the result. Mirrors
# `DEFAULT_REASONING_BY_PASS`'s per-pass shape exactly -- this is the
# CODE-LEVEL default, and `config/pipeline.yaml`'s own `llm.votes_by_pass`
# block (read by `_resolve_votes_by_pass` below) is the carried-per-pass
# source of truth, so `N` is never hardcoded at a call site. Only the tag
# pass is named: DEC-31 measured `theory_school` 0.757 -> 0.918 and
# `claim_type` 0.796 -> 0.866 at N=3, past the single-draw intra-annotator
# ceiling. Every pass absent here resolves to `SINGLE_DRAW` -- one draw, no
# voting layer, today's behavior exactly.
DEFAULT_VOTES_BY_PASS: dict[str, int] = {
    TAG_PASS_NAME: 3,
}

# The "no voting" resolution: one draw, no voting layer at all. Every pass
# `DEFAULT_VOTES_BY_PASS`/config does not name resolves to this.
SINGLE_DRAW = 1

# Fault-injection seam (mirroring `AXIAL_FORCE_DOCLING_FAILURE` in
# extract.py): forces the `pass_name=ARTIFACTS_PASS_NAME` canned response to
# carry exactly this string as the returned `artifact_role`, valid or not,
# so tests can drive the schema-validation hard-error path deterministically
# without needing a real model to misbehave. Unset/"" means the default
# in-schema role below applies.
STUB_ARTIFACT_ROLE_ENV_VAR = "AXIAL_STUB_ARTIFACT_ROLE"

# Issue #252 test/CI-only seam: mirrors STUB_TAG_RESPONSE_ENV_VAR above,
# exactly, for the brief-interrogation pass instead of the tag pass. When set
# to a non-empty value, the stub/record clients' interrogate-pass response
# becomes this raw string verbatim instead of the default canned
# interrogation response, letting an acceptance test drive a specific
# `{premises_found, bounds_applied, refusal}` combination end-to-end via
# subprocess (e.g. a contradicted premise, a non-null refusal, or a
# model-emitted `disposition` the deterministic wrapper must discard). Read
# at call time, like every other seam here. Never affects any other pass's
# canned response.
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"

# Issue #256 test/CI-only seam: mirrors STUB_INTERROGATE_RESPONSE_ENV_VAR
# above, exactly, for the stage-4 synthesis pass instead of the interrogate
# pass. When set to a non-empty value, the stub/record clients'
# synthesize-pass response becomes this raw string verbatim instead of the
# default canned synthesis response, letting an acceptance test drive a
# specific claim graph (e.g. one (a)/(b)/(c) claim each, or a claim with
# empty grounds to drive the loud-failure path) end-to-end via subprocess or
# in-process. Read at call time, like every other seam here. Never affects
# any other pass's canned response.
STUB_SYNTHESIZE_RESPONSE_ENV_VAR = "AXIAL_STUB_SYNTHESIZE_RESPONSE"

# Issue #258 test/CI-only seam: mirrors STUB_SYNTHESIZE_RESPONSE_ENV_VAR
# above, exactly, for the stage-5 attribution validator's (b)-seam check
# instead of the synthesis pass. When set to a non-empty value, the
# stub/record clients' attribution-pass response becomes this raw string
# verbatim instead of the default canned response, letting a test script
# which claim_ids the bounded model check flags as voiced-as-a-source. Read
# at call time, like every other seam here. Never affects any other pass's
# canned response.
STUB_ATTRIBUTION_RESPONSE_ENV_VAR = "AXIAL_STUB_ATTRIBUTION_RESPONSE"

# Issue #259 test/CI-only seam: mirrors STUB_ATTRIBUTION_RESPONSE_ENV_VAR
# above, exactly, for the stage-5 counter-position validator's bounded
# steelman-quality check instead of the (b)-seam check. When set to a
# non-empty value, the stub/record clients' counter_position-pass response
# becomes this raw string verbatim instead of the default canned response,
# letting a test script the scripted judge's verdict ("steelman" or
# "strawman"). Read at call time, like every other seam here. Never affects
# any other pass's canned response.
STUB_COUNTER_POSITION_RESPONSE_ENV_VAR = "AXIAL_STUB_COUNTER_POSITION_RESPONSE"

# Issue #262 test/CI-only seam: mirrors STUB_CHUNK_RESPONSE_SEQUENCE_ENV_VAR
# above, exactly, for the rung-3 grounding gate's independent judge call
# instead of the chunk pass. A JSON-encoded array of raw grounding-pass
# response strings (each `{"verdict": "supports"|"does_not_support"}`),
# indexed by a fresh, dedicated, per-process 1-indexed counter
# (`_grounding_pass_call_count`) -- one call per (a) claim being judged, so a
# test scripts "9 supports, 1 does not support" as a 10-element array. Cycles
# once exhausted, like every other sequence seam here. An unset/empty value
# falls back to the default "supports" canned response. Read fresh from the
# environment on every call.
STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_GROUNDING_RESPONSE_SEQUENCE"

# Issue #263 test/CI-only seam: mirrors STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR
# above, exactly, for the rung-3 calibration gate's independent judge call
# instead of the grounding pass. A JSON-encoded array of raw calibration-pass
# response strings (each `{"verdict": "correct"|"incorrect"}`), indexed by a
# fresh, dedicated, per-process 1-indexed counter
# (`_calibration_pass_call_count`) -- one call per claim being judged. Cycles
# once exhausted; an unset/empty value falls back to the default "correct"
# canned response. Read fresh from the environment on every call.
STUB_CALIBRATION_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_CALIBRATION_RESPONSE_SEQUENCE"

# Issue #264 test/CI-only seam: mirrors STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR
# above, exactly, for the brief-interrogation pass instead of the grounding
# judge -- the rung-3 adversarial-brief gate runs the interrogation pre-pass
# once per seeded brief in one process, so a single-string override
# (STUB_INTERROGATE_RESPONSE_ENV_VAR) cannot script "name it on 9, miss it on
# 1" across a run. A JSON-encoded array of raw interrogate-pass response
# strings, indexed by a fresh, dedicated, per-process 1-indexed counter
# (`_interrogate_pass_call_count`). Takes priority over
# STUB_INTERROGATE_RESPONSE_ENV_VAR when both are set, mirroring the chunk/tag
# sequence-over-single-override precedence. Cycles once exhausted. An
# unset/empty value falls back to that single-override (or, if that is also
# unset, the neutral default canned response).
STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE_SEQUENCE"

# Issue #264 test/CI-only seam: mirrors STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR
# above, exactly, for the rung-3 adversarial-brief gate's independent
# premise-correspondence judge call instead of the grounding judge. A
# JSON-encoded array of raw premise_match-pass response strings (each
# `{"verdict": "corresponds"|"does_not_correspond"}`), indexed by a fresh,
# dedicated, per-process 1-indexed counter (`_premise_match_pass_call_count`)
# -- one call per seeded brief whose interrogation result named at least one
# premise, so a test scripts "9 correspond, 1 does not" as an array. Cycles
# once exhausted. An unset/empty value falls back to the conservative
# "does_not_correspond" canned response -- a stub-driven run never invents a
# catch nobody scripted.
STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_PREMISE_MATCH_RESPONSE_SEQUENCE"

# Issue #258 test/CI-only seam: a JSON object mapping pass_name -> model
# name, read fresh from the environment by `StubLLMClient`/`RecordLLMClient`'s
# `model_for_pass` (which otherwise always answers the fixed id "stub"
# regardless of pass_name -- neither test client has any real per-pass model
# tiering to report). This lets a test drive both halves of the (b)-seam
# same-model guard (§7.9: "a check whose configured model equals the
# synthesis model is a config error worth surfacing loudly") end-to-end
# through the CLI: map ATTRIBUTION_PASS_NAME and SYNTHESIZE_PASS_NAME to
# distinct strings to prove the happy path, or to the same string to prove
# the guard fires. A pass_name absent from the mapping (or the env var
# unset/empty) keeps today's fixed "stub" answer -- every existing test
# asserting `model_for_pass(...) == "stub"` is unaffected.
STUB_MODEL_BY_PASS_ENV_VAR = "AXIAL_STUB_MODEL_BY_PASS"

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

# Per-process, 1-indexed counter of chunk-pass canned-response dispatches,
# driving the AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE seam (issue #104). A fresh,
# dedicated counter -- NEVER shared with `_tag_pass_call_count` -- mirroring
# that counter's own module-global, per-process, reset-on-fresh-subprocess
# semantics exactly, but scoped to the chunk pass only.
_chunk_pass_call_count = 0

# Per-process, 1-indexed counter of artifacts-pass canned-response
# dispatches, driving the AXIAL_STUB_ARTIFACT_FAIL_AT fault-injection seam
# (issue #98), mirroring `_tag_pass_call_count` above exactly.
_artifact_pass_call_count = 0

# Per-process, 1-indexed counter of grounding-pass canned-response
# dispatches, driving the AXIAL_STUB_GROUNDING_RESPONSE_SEQUENCE seam (issue
# #262), mirroring `_chunk_pass_call_count` above exactly.
_grounding_pass_call_count = 0

# Per-process, 1-indexed counter of calibration-pass canned-response
# dispatches, driving the AXIAL_STUB_CALIBRATION_RESPONSE_SEQUENCE seam
# (issue #263), mirroring `_grounding_pass_call_count` above exactly.
_calibration_pass_call_count = 0

# Per-process, 1-indexed counter of interrogate-pass canned-response
# dispatches, driving the AXIAL_STUB_INTERROGATE_RESPONSE_SEQUENCE seam
# (issue #264), mirroring `_grounding_pass_call_count` above exactly.
_interrogate_pass_call_count = 0

# Per-process, 1-indexed counter of premise_match-pass canned-response
# dispatches, driving the AXIAL_STUB_PREMISE_MATCH_RESPONSE_SEQUENCE seam
# (issue #264), mirroring `_grounding_pass_call_count` above exactly.
_premise_match_pass_call_count = 0

# Guards every one of the counters above (issue #325 follow-up): a
# bare module-global `count += 1` is not one atomic operation, and
# `run_tag`'s votes loop now fires multiple `complete()` calls against the
# SAME `StubLLMClient`/`RecordLLMClient` instance concurrently (issue #325
# follow-up, best-of-N draws no longer sequential) -- confirmed racy in
# practice, not just in theory: without this lock,
# `tests/ingestion/test_tag_best_of_n.py` failed roughly 1 run in 5 under
# concurrent votes. Real providers (`OpenRouterClient`) never touch these
# counters at all, so this lock never taxes a production call; it exists
# purely to keep the test/CI-only canned-response dispatch (and
# `StubLLMClient`/`RecordLLMClient`'s own `call_count`) correct under
# concurrent draws.
_stub_dispatch_lock = threading.Lock()


class LLMClient(Protocol):
    """A single-method completion interface every provider implements."""

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        """Send `prompt` to the model and return its raw text response.

        `pass_name` identifies which pass is calling (e.g. "chunk") purely
        for the test-only stub/record clients' canned-response dispatch; a
        real provider must accept and ignore it.
        """
        ...

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """Return the model identifier this client would target for
        `pass_name`, without making a completion call (issue #270 slice 02:
        the run-logging seam's per-pass `run.jsonl` record reads this to
        populate the record's `model` field). Every provider already knows
        this value -- this exposes it, it does not add a new client or a
        new config option."""
        ...

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        """Native tool-calling entry point (issue #253 slice 01, PRD
        §7.5/§7.6): send `prompt` plus a `tools` schema (the provider
        function-calling shape `axial.retrieve.tools.tool_specs_for_provider`
        builds) and return the model's requested tool call as
        `{"tool": <name>, "args": <dict>}`, or `None` when this turn carries
        no tool call at all. Added ALONGSIDE `complete()` -- every existing
        `.complete()` caller is unaffected, this is a new, separate entry
        point every provider must also implement.

        `pass_name` is the same out-of-band routing/dispatch seam
        `.complete()` already documents -- a real provider accepts and
        ignores it for anything but per-pass model/reasoning tiering; the
        stub/record test clients use it only to keep call-count bookkeeping
        symmetric with `.complete()` (their scripted tool-call channel does
        not vary by pass, unlike the canned JSON-completion dispatch)."""
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
            # Nested {title, children[]} shape (issue #235; PRD §7.3's
            # amended locked `toc` shape) -- the old flat
            # ["Introduction", "Comparative Cases", "Conclusion"] no longer
            # validates against `axial.envelope.validate_envelope_fields`.
            "toc": [
                {"title": "Introduction", "children": []},
                {"title": "Comparative Cases", "children": ["Case One", "Case Two"]},
                {"title": "Conclusion", "children": []},
            ],
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
    # scope:country-case in empirical_scope, Syria in polity_examples, and
    # (issue #29 slice 03) state/ideology in field, state-formation (+ its
    # own declared formation:bellicist subtag) in claim_type, bellicist in
    # theory_school -- so the stub-driven end-to-end path validates cleanly
    # against the loaded schema (PRD §7.1) and exercises the scope:country-
    # case/polity branch by default (tests/test_tag.py slice 02 seam
    # decision 5) plus every primary+secondary axis's nested shape (slice 03
    # seam decision 9). `polities_touched` (issue #194 slice 05) is a real,
    # free-text many-valued list -- no vocabulary to validate against.
    _CANNED_TAG_RESPONSE = json.dumps(
        {
            "role_in_argument": "role:claim",
            "empirical_scope": "scope:country-case",
            "polity": "Syria",
            "polities_touched": ["Syria"],
            "field": {"primary": "state", "secondary": ["ideology"]},
            "claim_type": {"primary": "state-formation", "subtags": ["formation:bellicist"]},
            "theory_school": {"primary": "bellicist", "status": "candidate"},
        }
    )

    def __init__(self) -> None:
        self.call_count = 0
        # Issue #253 slice 01: a per-INSTANCE counter for the scripted
        # tool-call channel (`STUB_TOOL_CALLS_ENV_VAR`'s own comment
        # explains why this is instance-level, not a module global like the
        # chunk/tag/artifact counters above).
        self._tool_call_index = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        # Locked (see `_stub_dispatch_lock`'s own comment): `call_count` and
        # `_canned_response_for`'s dispatch counters are shared, mutable
        # state a concurrent caller (`run_tag`'s votes loop) can call this
        # from multiple threads at once.
        with _stub_dispatch_lock:
            self.call_count += 1
            return _canned_response_for(pass_name)

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """A fixed, deterministic id -- there is no real model behind this
        client, but the run-logging record still needs a stable non-null
        value to prove a model-bearing pass's `model` field round-trips
        under the stub provider (issue #270 slice 02). Issue #258:
        `STUB_MODEL_BY_PASS_ENV_VAR`, when it names `pass_name`, overrides
        this fixed id -- see that env var's own comment for why."""
        return _model_for_pass_from_stub_mapping(pass_name)

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        """Play back the next element of `STUB_TOOL_CALLS_ENV_VAR`, indexed
        by this instance's own call counter (see that env var's module-level
        comment for why). `tools`/`pass_name` are accepted for interface
        parity with a real provider but do not affect the script."""
        with _stub_dispatch_lock:
            self.call_count += 1
            index = self._tool_call_index
            self._tool_call_index += 1
        return _scripted_tool_call_for(index)


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


def _canned_content_apparatus_response() -> str:
    """The canned response for a content-apparatus classification call
    (identified by `pass_name=CONTENT_APPARATUS_PASS_NAME`, issue #207): a
    `route` value against the same prose/apparatus taxonomy `axial.router`
    already classifies on. Defaults to `"prose"` (keep) -- the conservative,
    never-drop-on-uncertainty default (§7.8) -- so a stub-driven end-to-end
    run never surprises a caller by silently dropping content it didn't ask
    the stub to drop."""
    return json.dumps({"route": "prose"})


def _canned_holdings_response() -> str:
    """The canned response for a holdings-completeness call (identified by
    `pass_name=HOLDINGS_PASS_NAME`, issue #284, §7.11): a `complete`
    verdict -- the no-flag answer -- so a stub-driven end-to-end run never
    invents a partial-holding flag for a fixture nobody asked to flag."""
    return json.dumps(
        {
            "document_kind": "book",
            "claimed_extent": None,
            "claimed_extent_stated_by": None,
            "verdict": "complete",
            "reason": "Stub client: no holdings judgment was made.",
        }
    )


# The default canned response for an interrogate-pass call (§7.2): no
# smuggled premise found, no bound stated, no refusal -- and a model-supplied
# `disposition` deliberately included so a stub-driven run exercises the
# wrapper's "discard the model's own disposition" rule even on the happy
# path (`axial.brief.interrogate.disposition_for` recomputes it regardless
# of what this says).
_CANNED_INTERROGATE_RESPONSE = json.dumps(
    {
        "premises_found": [],
        "bounds_applied": [],
        "refusal": None,
        "disposition": "proceed",
    }
)


def _canned_interrogate_response() -> str:
    """The canned response for an interrogate-pass call (identified by
    `pass_name=INTERROGATE_PASS_NAME`, never by prompt content). A JSON array
    read fresh from `STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR`, indexed by
    the fresh per-process interrogate-pass counter just advanced (issue
    #264: the adversarial-brief gate calls this pass once per seeded brief in
    one process), takes priority over the single-string
    `STUB_INTERROGATE_RESPONSE_ENV_VAR` override so a test can script "name
    it on 9 briefs, miss it on 1" across a run; unset/"" falls back to that
    single override (see its own comment above), which itself falls back to
    the neutral `_CANNED_INTERROGATE_RESPONSE`."""
    global _interrogate_pass_call_count
    _interrogate_pass_call_count += 1
    sequence_raw = os.environ.get(STUB_INTERROGATE_RESPONSE_SEQUENCE_ENV_VAR, "")
    if sequence_raw:
        sequence = json.loads(sequence_raw)
        if sequence:
            return sequence[(_interrogate_pass_call_count - 1) % len(sequence)]
    override = os.environ.get(STUB_INTERROGATE_RESPONSE_ENV_VAR, "")
    return override or _CANNED_INTERROGATE_RESPONSE


_CANNED_PREMISE_MATCH_RESPONSE = json.dumps({"verdict": "does_not_correspond"})


def _canned_premise_match_response() -> str:
    """The canned response for a premise_match-pass call (identified by
    `pass_name=PREMISE_MATCH_PASS_NAME`, issue #264): a JSON array read fresh
    from `STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR`, indexed by the fresh
    per-process premise_match-pass counter just advanced (see that env var's
    own comment for why -- one call per seeded brief whose interrogation
    named at least one premise, so a test scripts a verdict sequence across
    calls); unset/empty falls back to the conservative default
    `"does_not_correspond"` -- a stub-driven run never invents a catch nobody
    scripted."""
    global _premise_match_pass_call_count
    _premise_match_pass_call_count += 1
    sequence_raw = os.environ.get(STUB_PREMISE_MATCH_RESPONSE_SEQUENCE_ENV_VAR, "")
    if sequence_raw:
        sequence = json.loads(sequence_raw)
        if sequence:
            return sequence[(_premise_match_pass_call_count - 1) % len(sequence)]
    return _CANNED_PREMISE_MATCH_RESPONSE


# The default canned response for a synthesize-pass call (§7.4): a single
# empty claim graph. Every real acceptance test drives this pass via
# `STUB_SYNTHESIZE_RESPONSE_ENV_VAR` (an empty claims list on its own proves
# nothing about the shape §7.4 requires), so this default exists only so a
# stub-driven run that never scripts a claim graph doesn't crash.
_CANNED_SYNTHESIZE_RESPONSE = json.dumps({"claims": []})


def _canned_synthesize_response() -> str:
    """The canned response for a synthesize-pass call (identified by
    `pass_name=SYNTHESIZE_PASS_NAME`, never by prompt content): read fresh
    from `STUB_SYNTHESIZE_RESPONSE_ENV_VAR` on every call so a test can
    inject any claim graph end-to-end (see the env var's own comment
    above); unset/"" falls back to the empty `_CANNED_SYNTHESIZE_RESPONSE`."""
    override = os.environ.get(STUB_SYNTHESIZE_RESPONSE_ENV_VAR, "")
    return override or _CANNED_SYNTHESIZE_RESPONSE


_CANNED_ATTRIBUTION_RESPONSE = json.dumps({"flagged_claim_ids": []})


def _canned_attribution_response() -> str:
    """The canned response for an attribution-pass call (identified by
    `pass_name=ATTRIBUTION_PASS_NAME`, issue #258): read fresh from
    `STUB_ATTRIBUTION_RESPONSE_ENV_VAR` on every call so a test can script
    which claim_ids the (b)-seam check flags (see the env var's own comment
    above); unset/"" falls back to flagging nothing -- the conservative
    default, so a stub-driven run never invents a flag nobody scripted."""
    override = os.environ.get(STUB_ATTRIBUTION_RESPONSE_ENV_VAR, "")
    return override or _CANNED_ATTRIBUTION_RESPONSE


_CANNED_COUNTER_POSITION_RESPONSE = json.dumps(
    {"verdict": "steelman", "detail": "Stub client: no judgment was made."}
)


def _canned_counter_position_response() -> str:
    """The canned response for a counter_position-pass call (identified by
    `pass_name=COUNTER_POSITION_PASS_NAME`, issue #259): read fresh from
    `STUB_COUNTER_POSITION_RESPONSE_ENV_VAR` on every call so a test can
    script the steelman-quality judge's verdict (see that env var's own
    comment above); unset/"" falls back to the conservative "steelman"
    default, so a stub-driven run never invents a strawman flag nobody
    scripted."""
    override = os.environ.get(STUB_COUNTER_POSITION_RESPONSE_ENV_VAR, "")
    return override or _CANNED_COUNTER_POSITION_RESPONSE


_CANNED_GROUNDING_RESPONSE = json.dumps({"verdict": "supports"})


def _canned_grounding_response() -> str:
    """The canned response for a grounding-pass call (identified by
    `pass_name=GROUNDING_PASS_NAME`, issue #262): a JSON array read fresh
    from `STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR`, indexed by the fresh
    per-process grounding-pass counter just advanced (see that env var's own
    comment for why -- one call per (a) claim judged, so a test scripts a
    verdict sequence across calls); unset/empty falls back to the
    conservative default `"supports"` -- a stub-driven run never invents a
    failed judgement nobody scripted."""
    global _grounding_pass_call_count
    _grounding_pass_call_count += 1
    sequence_raw = os.environ.get(STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR, "")
    if sequence_raw:
        sequence = json.loads(sequence_raw)
        if sequence:
            return sequence[(_grounding_pass_call_count - 1) % len(sequence)]
    return _CANNED_GROUNDING_RESPONSE


_CANNED_CALIBRATION_RESPONSE = json.dumps({"verdict": "correct"})


def _canned_calibration_response() -> str:
    """The canned response for a calibration-pass call (identified by
    `pass_name=CALIBRATION_PASS_NAME`, issue #263): a JSON array read fresh
    from `STUB_CALIBRATION_RESPONSE_SEQUENCE_ENV_VAR`, indexed by the fresh
    per-process calibration-pass counter just advanced (mirrors
    `_canned_grounding_response` exactly); unset/empty falls back to the
    conservative default `"correct"` -- a stub-driven run never invents a
    failed judgement nobody scripted."""
    global _calibration_pass_call_count
    _calibration_pass_call_count += 1
    sequence_raw = os.environ.get(STUB_CALIBRATION_RESPONSE_SEQUENCE_ENV_VAR, "")
    if sequence_raw:
        sequence = json.loads(sequence_raw)
        if sequence:
            return sequence[(_calibration_pass_call_count - 1) % len(sequence)]
    return _CANNED_CALIBRATION_RESPONSE


def _model_for_pass_from_stub_mapping(pass_name: str | None) -> str:
    """Shared by `StubLLMClient`/`RecordLLMClient`'s `model_for_pass`: honors
    `STUB_MODEL_BY_PASS_ENV_VAR` when set and `pass_name` is one of its keys,
    otherwise falls back to the fixed `"stub"` id both clients have always
    returned (see that env var's own comment for why this exists)."""
    raw = os.environ.get(STUB_MODEL_BY_PASS_ENV_VAR, "")
    if raw:
        mapping = json.loads(raw)
        if pass_name in mapping:
            return mapping[pass_name]
    return "stub"


def _canned_response_for(pass_name: str | None) -> str:
    """Dispatch the canned response by pass: `pass_name == CHUNK_PASS_NAME`
    gets the chunk-shaped canned response, `pass_name == TAG_PASS_NAME` gets
    the tag-shaped canned response (or, if `AXIAL_STUB_TAG_RESPONSE` is set
    to a non-empty value, that raw string verbatim -- read at call time, and
    only for tag-pass calls), `pass_name == ARTIFACTS_PASS_NAME` gets the
    artifact-role-shaped canned response, `pass_name == XREF_PASS_NAME` gets
    the referenced-artifact-ids-shaped canned response, `pass_name ==
    CONTENT_APPARATUS_PASS_NAME` gets the route-shaped canned response
    (issue #207), `pass_name == INTERROGATE_PASS_NAME` gets the
    interrogation-shaped canned response (or, if
    `AXIAL_STUB_INTERROGATE_RESPONSE`/`_SEQUENCE` is set to a non-empty
    value, that raw string/sequence verbatim -- issue #252/#264), `pass_name
    == PREMISE_MATCH_PASS_NAME` gets the correspondence-verdict-shaped canned
    response (issue #264); anything else (the envelope pass,
    `pass_name == ENVELOPE_PASS_NAME`, included) gets the original
    envelope-shaped canned response. Shared by `StubLLMClient` and
    `RecordLLMClient` so `record` is indistinguishable from `stub` for the
    same call."""
    if pass_name == CHUNK_PASS_NAME:
        global _chunk_pass_call_count
        _chunk_pass_call_count += 1
        # Issue #104: a JSON array of raw responses, indexed by the fresh
        # per-process chunk-pass counter just advanced, takes priority over
        # the single-string override so a test can script "this call is
        # malformed, the next one is valid" across a run.
        sequence_raw = os.environ.get(STUB_CHUNK_RESPONSE_SEQUENCE_ENV_VAR, "")
        if sequence_raw:
            sequence = json.loads(sequence_raw)
            if sequence:
                return sequence[(_chunk_pass_call_count - 1) % len(sequence)]
        override = os.environ.get(STUB_CHUNK_RESPONSE_ENV_VAR, "")
        if override:
            return override
        return StubLLMClient._CANNED_CHUNK_RESPONSE
    if pass_name == TAG_PASS_NAME:
        _maybe_fail_tag_call()
        # Issue #102: a JSON array of raw responses, indexed by the same
        # per-process tag-pass counter `_maybe_fail_tag_call` just advanced,
        # takes priority over the single-string override so a test can script
        # "first answer bad, correction answer good" across calls.
        sequence_raw = os.environ.get(STUB_TAG_RESPONSE_SEQUENCE_ENV_VAR, "")
        if sequence_raw:
            sequence = json.loads(sequence_raw)
            if sequence:
                return sequence[(_tag_pass_call_count - 1) % len(sequence)]
        override = os.environ.get(STUB_TAG_RESPONSE_ENV_VAR, "")
        if override:
            return override
        return StubLLMClient._CANNED_TAG_RESPONSE
    if pass_name == ARTIFACTS_PASS_NAME:
        _maybe_fail_artifact_call()
        return _canned_artifact_response()
    if pass_name == XREF_PASS_NAME:
        return _canned_xref_response()
    if pass_name == CONTENT_APPARATUS_PASS_NAME:
        return _canned_content_apparatus_response()
    if pass_name == HOLDINGS_PASS_NAME:
        return _canned_holdings_response()
    if pass_name == INTERROGATE_PASS_NAME:
        return _canned_interrogate_response()
    if pass_name == SYNTHESIZE_PASS_NAME:
        return _canned_synthesize_response()
    if pass_name == ATTRIBUTION_PASS_NAME:
        return _canned_attribution_response()
    if pass_name == COUNTER_POSITION_PASS_NAME:
        return _canned_counter_position_response()
    if pass_name == GROUNDING_PASS_NAME:
        return _canned_grounding_response()
    if pass_name == CALIBRATION_PASS_NAME:
        return _canned_calibration_response()
    if pass_name == PREMISE_MATCH_PASS_NAME:
        return _canned_premise_match_response()
    return StubLLMClient._CANNED_RESPONSE


def _scripted_tool_call_for(call_index: int) -> dict[str, Any] | None:
    """The scripted tool-call channel `StubLLMClient`/`RecordLLMClient`'s
    `complete_with_tools()` both delegate to (mirroring `_canned_response_for`
    being shared by their `.complete()` methods, so `record` stays
    indistinguishable from `stub` for the same call). Reads
    `STUB_TOOL_CALLS_ENV_VAR` fresh from the environment on every call (like
    every other stub seam in this module); an unset/empty value or an empty
    JSON array means "no tool call" (`None`). `call_index` is 0-indexed and
    supplied by the caller's own instance counter -- see that env var's
    module-level comment for why this is per-instance, not per-process."""
    raw = os.environ.get(STUB_TOOL_CALLS_ENV_VAR, "")
    if not raw:
        return None
    sequence = json.loads(raw)
    if not sequence:
        return None
    return sequence[call_index % len(sequence)]


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
        # Issue #253 slice 01: mirrors `StubLLMClient._tool_call_index`
        # exactly (see that attribute's own comment).
        self._tool_call_index = 0

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        # Locked (see `_stub_dispatch_lock`'s own comment): `call_count`,
        # the append below, and `_canned_response_for`'s dispatch counters
        # are all shared, mutable state a concurrent caller can call this
        # from multiple threads at once -- an unlocked interleaved append
        # could also torn-write two prompts into the same line.
        with _stub_dispatch_lock:
            self.call_count += 1
            self._record_path.parent.mkdir(parents=True, exist_ok=True)
            with self._record_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(prompt) + "\n")
            return _canned_response_for(pass_name)

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """Mirrors `StubLLMClient.model_for_pass` exactly -- same fixed id
        (subject to the same `STUB_MODEL_BY_PASS_ENV_VAR` override), since
        this client's completion responses are also indistinguishable from
        the stub's (module docstring)."""
        return _model_for_pass_from_stub_mapping(pass_name)

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        """Delegates to the exact same `_scripted_tool_call_for` dispatch
        `StubLLMClient.complete_with_tools` uses (so `record` is
        indistinguishable from `stub` for this channel too), with the same
        prompt-recording side effect `.complete()` already has."""
        with _stub_dispatch_lock:
            self.call_count += 1
            self._record_path.parent.mkdir(parents=True, exist_ok=True)
            with self._record_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(prompt) + "\n")
            index = self._tool_call_index
            self._tool_call_index += 1
        return _scripted_tool_call_for(index)


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

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        raise RuntimeError(
            "ExplodingLLMClient.complete_with_tools() was invoked -- this "
            "indicates an LLM-backed pass attempted to recompute instead of "
            "reusing a cached result"
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """A fixed id, never raising -- mirrors the class's own contract
        that only `.complete()` is fatal (docstring above)."""
        return "explode"


class LLMError(Exception):
    """Base class for all LLM-client errors (config, transport, response)."""


class LLMConfigError(LLMError, ValueError):
    """Raised for a misconfigured LLM provider: a missing API key or an
    unknown `provider` value. Subclasses `ValueError` too, so existing
    callers that catch `ValueError` for this condition keep working."""


class OpenRouterError(LLMError):
    """Raised when the OpenRouter API returns an error or malformed response."""


class ContentRefusedError(LLMError):
    """Raised when a completion is refused by content moderation
    (`finish_reason == "content_filter"`) and the refusal survives the
    fallback reroute (issue #116): either the configured
    `content_fallback_model` ALSO refused with `content_filter`, or no
    fallback is configured at all (there is then no way to recover a
    refusal by retrying). Unlike `OpenRouterError`, a moderation refusal is
    never transient -- blind-retrying the same prompt against the same
    model cannot change a moderation decision -- so this is a distinct type
    a caller can catch specifically to quarantine just the offending chunk
    instead of failing the whole source (2 fatal `content_filter` events in
    the 2026-07 gold run motivated this; see
    docs/postmortem/gold-run-2026-07/model-tier-decision.md)."""


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


class StubInjectedArtifactFailureError(LLMError):
    """Raised by the shared stub/record canned-response dispatch when the
    `AXIAL_STUB_ARTIFACT_FAIL_AT` seam fires on the Nth artifacts-pass call
    (issue #98, mirroring `StubInjectedTagFailureError` from issue #81).

    A subclass of `LLMError` (never a bare exception) precisely so it
    propagates like a real transport-level failure: unchanged through
    `axial.model_json.complete_json` and caught by
    `axial.artifacts.run_artifacts`'s `except (LLMError, httpx.HTTPError)` ->
    `LLMFailedError` -> `axial.vault.run_vault_write`'s `except
    (ArtifactsError, TagError)` -> `ArtifactClassificationFailedError` -> the
    CLI's `except VaultError` typed-error/non-zero-exit path -- i.e. exactly
    today's mid-artifacts-pass failure contract, not a new branch."""


def _maybe_fail_artifact_call() -> None:
    """Advance the per-process artifacts-pass call counter and, when
    `AXIAL_STUB_ARTIFACT_FAIL_AT` names a positive integer equal to the new
    count, raise `StubInjectedArtifactFailureError` (issue #98's mid-
    artifacts fault seam). Mirrors `_maybe_fail_tag_call` exactly.

    Read fresh from the environment on every call; an unset, empty,
    non-integer, or non-positive value never fails (today's behavior). The
    counter advances for every artifacts-pass dispatch regardless, so the
    "Nth artifacts call" is well-defined independent of whether the seam is
    armed."""
    global _artifact_pass_call_count
    _artifact_pass_call_count += 1
    raw = os.environ.get(STUB_ARTIFACT_FAIL_AT_ENV_VAR, "")
    try:
        fail_at = int(raw)
    except (TypeError, ValueError):
        return
    if fail_at > 0 and _artifact_pass_call_count == fail_at:
        raise StubInjectedArtifactFailureError(
            f"{STUB_ARTIFACT_FAIL_AT_ENV_VAR}={fail_at}: injected artifacts-pass "
            f"failure on artifacts call #{_artifact_pass_call_count} (issue #98 "
            f"fault-injection seam)"
        )


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

# Issue #108: `_REQUEST_TIMEOUT.read` above only bounds a single httpx *read*
# -- a slow-drip stall (or a provider/proxy that emits keep-alive bytes more
# often than every 180s) resets that per-read timer forever, so a stalled
# attempt can hang indefinitely at 0% CPU and the `_MAX_ATTEMPTS` retry
# budget below never gets a chance to fire. `_REQUEST_DEADLINE_SECONDS` is a
# hard, per-attempt WALL-CLOCK ceiling enforced independently of httpx (via a
# watchdog thread in `OpenRouterClient._post_with_deadline`): once it
# elapses, the attempt self-aborts and is treated as a transient failure,
# exactly like an `httpx.ReadTimeout`, and retried within the existing
# budget. Set well above `_REQUEST_TIMEOUT.read` (180s) so a legitimately
# slow-but-progressing real completion is never penalized by this ceiling.
_REQUEST_DEADLINE_SECONDS = 300.0


class _RequestDeadlineExceeded(Exception):
    """Raised internally (issue #108) when a single `complete()` attempt's
    blocking HTTP call outlives `request_deadline_seconds`. Caught inside
    `OpenRouterClient.complete()`'s retry loop and treated as a transient
    failure -- never surfaced to callers directly."""


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
#
# Issue #86 extends the same budget once more to an HTTP 200 whose *body*
# isn't valid JSON at all (a truncated stream or a proxy error page):
# `response.json()` otherwise raises a raw `json.JSONDecodeError`, outside
# the `LLMError`/`httpx` families every caller catches, breaking this
# module's "every error is an LLMError" promise. Retried like any other
# transient failure; a final-attempt failure raises `OpenRouterError` naming
# the decode error plus a truncated body snippet for diagnosability.
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

# Number of leading characters of a refused prompt carried verbatim in a
# content_filter reroute's log line (issue #117), alongside the hash below.
# Not meant to reconstruct the prompt -- just enough to eyeball-match it
# against a known chunk while triaging moderation exposure.
_PROMPT_PREFIX_LEN = 80


def _log_retry(
    pass_name: str | None, attempt: int, trigger: str, *, prompt: str | None = None
) -> None:
    """Emit exactly one structured stderr line for a non-final retried (or
    content_filter-rerouted) `OpenRouterClient.complete()` attempt (issue
    #117). Today these events are silent: a chunk that fails twice then
    succeeds leaves no trace, so moderation exposure and transient-failure
    rates are only ever a lower bound. Bare `print(..., file=sys.stderr)` --
    this repo has no logging framework (see `src/axial/xref.py:334`).

    Carries the pass name, the attempt number and the total attempt budget
    (`_MAX_ATTEMPTS`), and a machine-readable trigger token (an HTTP status,
    an exception class name, or a `finish_reason` value). When `prompt` is
    given (the content_filter reroute path only), also carries a stable
    hash of the refused prompt plus a text prefix, so a fallback model can
    later be validated against real refused chunks.
    """
    line = f"llm_retry pass={pass_name} attempt={attempt}/{_MAX_ATTEMPTS} trigger={trigger}"
    if prompt is not None:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        line += f" prompt_hash={prompt_hash} prompt_prefix={prompt[:_PROMPT_PREFIX_LEN]!r}"
    print(line, file=sys.stderr)


def _raise_for_status_with_body(response: httpx.Response, *, action: str) -> None:
    """Like `response.raise_for_status()`, but on a 4xx/5xx failure wraps the
    resulting `httpx.HTTPStatusError` in `OpenRouterError` carrying a bounded
    snippet of the response body (same `repr(response.text[:300])` pattern
    used a few lines below for a malformed-JSON body). `raise_for_status()`'s
    own message is only the generic status line ("Client error '400 Bad
    Request' for url '...'") -- never the body, which is exactly where a
    provider like OpenRouter puts the actual reason (e.g. a
    context-length-exceeded message). A real synthesis-pass run hit this: an
    oversized prompt drew a 400 whose real cause was invisible without
    reading the body by hand (issue #358)."""
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        snippet = repr(response.text[:300])
        raise OpenRouterError(f"{action} failed: {exc}; body snippet: {snippet}") from exc


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
        request_deadline_seconds: float = _REQUEST_DEADLINE_SECONDS,
        content_fallback_model: str | None = None,
        reasoning_by_pass: dict[str, bool | str] | None = None,
        model_by_pass: dict[str, str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._request_deadline_seconds = request_deadline_seconds
        # Issue #116: the model a `content_filter` refusal reroutes a single
        # completion to. Optional (defaults to `None`, no fallback) so every
        # pre-#116 caller/test that builds `OpenRouterClient` without this
        # kwarg keeps working unchanged.
        self._content_fallback_model = content_fallback_model
        # Per-pass model reasoning (§7.9, issue #207): defaults to
        # `DEFAULT_REASONING_BY_PASS` when not given explicitly, so every
        # pre-#207 caller/test that builds `OpenRouterClient` directly
        # (without plumbing config/pipeline.yaml through) still gets the
        # correct per-pass reasoning setting. `_build_openrouter_client`
        # passes the config-resolved mapping (`_resolve_reasoning_by_pass`)
        # for a real run, so config/pipeline.yaml stays the actual carried-
        # per-pass source of truth (§7.9) rather than this default.
        self._reasoning_by_pass = (
            dict(DEFAULT_REASONING_BY_PASS) if reasoning_by_pass is None else reasoning_by_pass
        )
        # Per-pass model tiering (DEC-26, issue #235): a map of pass_name ->
        # concrete MODEL NAME, resolved (by `_resolve_model_by_pass`, tier
        # name -> secrets.toml model name) BEFORE it ever reaches this
        # constructor -- this client never resolves a tier itself. Defaults
        # to `DEFAULT_MODEL_BY_PASS` (empty) when not given explicitly, so
        # every pre-#235 caller/test that builds `OpenRouterClient` directly
        # keeps sending every pass to `self._model` unchanged, exactly like
        # today.
        self._model_by_pass = (
            dict(DEFAULT_MODEL_BY_PASS) if model_by_pass is None else model_by_pass
        )
        self._client = httpx.Client(
            base_url=base_url, transport=transport, timeout=_REQUEST_TIMEOUT
        )

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """The model this client targets for `pass_name` (issue #270 slice
        02): `self._model_by_pass`'s per-pass override (DEC-26) when
        `pass_name` is named there, else this client's own default
        `self._model`. This is the SAME resolution `_post_with_deadline`
        itself applies to an ordinary (non-`model`-overridden) request --
        kept here as the single source of truth so the two can never drift,
        and exposed so a caller can learn which model a pass would use
        without making a completion call."""
        return self._model_by_pass.get(pass_name, self._model)

    def _post_with_deadline(
        self,
        prompt: str,
        model: str | None = None,
        pass_name: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> httpx.Response:
        """Run the blocking `httpx` POST on a daemon watchdog thread and
        enforce `self._request_deadline_seconds` as a hard wall-clock
        ceiling, independent of httpx's own (per-*read*, not per-call)
        timeout (issue #108).

        If the deadline elapses, raises `_RequestDeadlineExceeded` and
        abandons the watchdog thread rather than joining it -- a genuine
        slow-drip stall (no exception, no partial byte, ever) never returns
        control on its own, so waiting for it to finish would defeat the
        whole point of the ceiling. The thread is a daemon, so an abandoned,
        permanently-blocked attempt can never keep the process alive; each
        retry attempt starts a brand-new thread and a brand-new request, so
        an abandoned attempt can never corrupt a later one.

        `model` (issue #116) overrides EVERYTHING else for this one call,
        including any per-pass model tiering below -- the seam `complete()`
        uses to reroute a `content_filter` refusal to
        `self._content_fallback_model` without duplicating the watchdog
        machinery. When `model` is not given, `pass_name` (DEC-26, issue
        #235) selects this call's target model from `self._model_by_pass`,
        falling back to `self._model` for any pass not named there -- the
        project's first per-pass model override, resolved exactly as
        `reasoning_enabled` is already selected by `pass_name` below.

        `pass_name` (issue #207, §7.9) also selects this call's reasoning
        setting from `self._reasoning_by_pass` (defaulting to `False` for a
        pass not named there -- the safe, unchanged-since-#147 default): a
        `bool` sends `reasoning.enabled` (OpenRouter's implicit default
        effort when `True`), a `str` sends `reasoning.effort` naming an
        explicit level instead (2026-07 model-swap experiment).

        `tools` (issue #253 slice 01) is a purely additive payload field: it
        is included only when the caller passes a non-`None` value
        (`complete_with_tools`), so an ordinary `complete()` call's payload
        is byte-for-byte unchanged from before this parameter existed.
        """
        target_model = model if model is not None else self.model_for_pass(pass_name)
        reasoning_setting = self._reasoning_by_pass.get(pass_name, False)
        # A `str` names an explicit `reasoning.effort` level (2026-07
        # model-swap experiment: several models only support a subset of
        # effort levels -- e.g. "high"/"xhigh", never "medium" -- so leaving
        # `enabled: true` to OpenRouter's implicit "medium" default means it
        # silently picks among the model's supported levels on our behalf).
        # A `bool` keeps the original `reasoning.enabled` shape unchanged.
        reasoning_payload: dict[str, Any] = (
            {"enabled": True, "effort": reasoning_setting}
            if isinstance(reasoning_setting, str)
            else {"enabled": reasoning_setting}
        )
        outcome: dict[str, Any] = {}
        done = threading.Event()
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": _MAX_COMPLETION_TOKENS,
            # Issue #147 (revised per-pass by issue #207, §7.9): the
            # production_low model started being served as a reasoning
            # model, and the added reasoning phase pushed large chunk-echo
            # calls (max_tokens=60000) past the 300s wall-clock request
            # deadline. Reasoning is now a PER-PASS setting
            # (`reasoning_payload`, resolved above from
            # `self._reasoning_by_pass`) -- ON for the envelope/content-
            # apparatus passes, OFF (unchanged) for the high-volume
            # tag/artifacts/xref calls #147 was about. Both the primary
            # model and the content_fallback_model reroute share this one
            # call site via the `model` override above, so this single
            # field covers both.
            "reasoning": reasoning_payload,
        }
        if tools is not None:
            payload["tools"] = tools

        def _run() -> None:
            try:
                outcome["response"] = self._client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=payload,
                )
            except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread below
                outcome["error"] = exc
            finally:
                done.set()

        watchdog = threading.Thread(target=_run, daemon=True)
        watchdog.start()
        if not done.wait(timeout=self._request_deadline_seconds):
            raise _RequestDeadlineExceeded(
                f"attempt exceeded the {self._request_deadline_seconds}s wall-clock "
                "request deadline (issue #108)"
            )
        if "error" in outcome:
            raise outcome["error"]
        return outcome["response"]

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == _MAX_ATTEMPTS
            try:
                response = self._post_with_deadline(prompt, pass_name=pass_name)
            except httpx.TransportError as exc:
                if is_last_attempt:
                    raise
                _log_retry(pass_name, attempt, type(exc).__name__)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            except _RequestDeadlineExceeded as exc:
                if is_last_attempt:
                    raise OpenRouterError(
                        f"request wall-clock deadline of {self._request_deadline_seconds}s "
                        f"exceeded on attempt {attempt}/{_MAX_ATTEMPTS} (issue #108)"
                    ) from exc
                _log_retry(pass_name, attempt, type(exc).__name__)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            if not is_last_attempt and (response.status_code == 429 or response.status_code >= 500):
                _log_retry(pass_name, attempt, str(response.status_code))
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            _raise_for_status_with_body(response, action="API request")
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                if is_last_attempt:
                    snippet = repr(response.text[:300])
                    raise OpenRouterError(
                        f"malformed API response body: {exc}; body snippet: {snippet}"
                    ) from exc
                _log_retry(pass_name, attempt, type(exc).__name__)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            try:
                choice = data["choices"][0]
                content = choice["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise OpenRouterError(f"unexpected OpenRouter response shape: {data!r}") from exc

            # A missing/null finish_reason is accepted as success -- some
            # providers omit it. A present, non-"stop" value is split three
            # ways (issue #116): "length" is a truncated completion, retried
            # same prompt/same model (issue #69, unchanged); "content_filter"
            # is a moderation refusal, NEVER retried same-model -- rerouted
            # to the fallback instead (see `_reroute_content_filter`);
            # "error" (and any other non-"stop" value) is treated as a
            # transient provider fault, retried same model exactly like an
            # empty completion or a transport error.
            finish_reason = choice.get("finish_reason")

            if finish_reason == "content_filter":
                # Not itself part of the retry budget (the primary is never
                # retried on a moderation refusal), but it IS a non-final
                # event the caller never sees without logging (issue #117):
                # log it here, carrying the refused prompt's identity, then
                # hand off to the fallback.
                _log_retry(pass_name, attempt, "content_filter", prompt=prompt)
                return self._reroute_content_filter(prompt, pass_name=pass_name)

            is_empty = content is None or not content.strip()
            is_truncated = finish_reason == "length"
            is_transient_fault = finish_reason is not None and finish_reason not in (
                "stop",
                "length",
            )

            if is_empty or is_truncated or is_transient_fault:
                if is_last_attempt:
                    if is_truncated:
                        raise OpenRouterError(
                            f"completion truncated: finish_reason={finish_reason!r}"
                        )
                    if is_transient_fault:
                        raise OpenRouterError(
                            f"transient provider fault: finish_reason={finish_reason!r}"
                        )
                    raise OpenRouterError("empty completion from provider")
                if is_truncated:
                    trigger = "length"
                elif is_transient_fault:
                    trigger = str(finish_reason)
                else:
                    trigger = "empty_completion"
                _log_retry(pass_name, attempt, trigger)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            return content

        raise AssertionError("unreachable: the retry loop always returns or raises")

    def complete_with_tools(
        self, prompt: str, tools: list[dict[str, Any]], pass_name: str | None = None
    ) -> dict[str, Any] | None:
        """Native tool-calling entry point (issue #253 slice 01, PRD
        §7.5/§7.6): sends `tools` in the `/chat/completions` payload and
        reads `tool_calls` off the response, reusing the SAME
        watchdog/deadline/reasoning/model-by-pass machinery `complete()`
        uses via `_post_with_deadline` -- added ALONGSIDE `complete()`,
        never changing its signature or its payload when `tools` is not
        passed (see `_post_with_deadline`'s own docstring).

        Returns the model's first requested tool call as
        `{"tool": <name>, "args": <parsed-json-object>}`, or `None` when
        this turn carries no tool call at all -- the retrieval loop
        (`axial.retrieve.loop.run_retrieval_loop`) treats that as a clean
        end (retrying a tool-less turn is explicitly out of scope for v0,
        plan `plans/retrieval-loop/01-tool-loop-skeleton.md`'s own
        "out of scope" list). Only the FIRST tool call in a turn is honored
        even if the model requests several in parallel -- the v0 loop is
        single-call-per-step by design (§7.6 logs one trajectory entry per
        call); a later slice can widen this if a real model's tool-use
        pattern needs it.

        Deliberately narrower than `complete()`'s retry policy: transport
        errors, 429/5xx, and the wall-clock deadline retry exactly like
        `complete()` does, but there is no `content_filter` fallback
        reroute here -- no acceptance test drives this path against
        anything but the scripted `stub`/`record` provider (this feature's
        own explicit non-goal: "Any live-LLM test"), so adding untested
        moderation-reroute plumbing here would be speculative robustness,
        not a proven need.

        A response with no `tool_calls` is the clean "no more tool calls"
        end ONLY when `finish_reason` is a genuine clean stop (`"stop"` or
        absent/`None`). A `finish_reason` of `content_filter`, `length`, or
        any other non-stop value with an empty `tool_calls` list is a
        broken/refused/truncated turn masquerading as a clean end -- left
        unguarded, it would silently shorten the §7.6 trajectory instead of
        surfacing the failure, undermining the log's whole audit purpose
        (distinguishing a sound retrieval path from a broken one). Such a
        turn raises a named `LLMError` instead (`ContentRefusedError` for
        `content_filter`, matching `complete()`'s own type for that
        finish_reason; `OpenRouterError` for every other non-stop value) --
        this is NOT the `complete()` content_filter fallback reroute
        (deliberately not built here, see above): the loop just needs the
        failure to be loud, not recovered.
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == _MAX_ATTEMPTS
            try:
                response = self._post_with_deadline(prompt, pass_name=pass_name, tools=tools)
            except httpx.TransportError as exc:
                if is_last_attempt:
                    raise
                _log_retry(pass_name, attempt, type(exc).__name__)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            except _RequestDeadlineExceeded as exc:
                if is_last_attempt:
                    raise OpenRouterError(
                        f"request wall-clock deadline of {self._request_deadline_seconds}s "
                        f"exceeded on attempt {attempt}/{_MAX_ATTEMPTS} (issue #108)"
                    ) from exc
                _log_retry(pass_name, attempt, type(exc).__name__)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            if not is_last_attempt and (response.status_code == 429 or response.status_code >= 500):
                _log_retry(pass_name, attempt, str(response.status_code))
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

            _raise_for_status_with_body(response, action="API request")
            try:
                data = response.json()
            except (json.JSONDecodeError, ValueError) as exc:
                if is_last_attempt:
                    snippet = repr(response.text[:300])
                    raise OpenRouterError(
                        f"malformed API response body: {exc}; body snippet: {snippet}"
                    ) from exc
                _log_retry(pass_name, attempt, type(exc).__name__)
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue
            try:
                choice = data["choices"][0]
                message = choice["message"]
            except (KeyError, IndexError, TypeError) as exc:
                raise OpenRouterError(f"unexpected OpenRouter response shape: {data!r}") from exc

            finish_reason = choice.get("finish_reason")
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                if finish_reason is None or finish_reason == "stop":
                    return None
                if finish_reason == "content_filter":
                    raise ContentRefusedError(
                        "complete_with_tools: model turn refused with "
                        "finish_reason='content_filter' and issued no tool call "
                        "(issue #253 slice 01 review finding)"
                    )
                raise OpenRouterError(
                    "complete_with_tools: model turn ended with "
                    f"finish_reason={finish_reason!r} and issued no tool call "
                    "(issue #253 slice 01 review finding)"
                )

            first = tool_calls[0]
            try:
                function = first["function"]
                name = function["name"]
                raw_arguments = function.get("arguments", "{}")
            except (KeyError, TypeError) as exc:
                raise OpenRouterError(f"malformed tool_call in response: {first!r}") from exc
            try:
                args = (
                    json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
                )
            except json.JSONDecodeError as exc:
                raise OpenRouterError(
                    f"malformed tool_call arguments JSON for {name!r}: {raw_arguments!r}"
                ) from exc
            return {"tool": name, "args": args}

        raise AssertionError("unreachable: the retry loop always returns or raises")

    def _reroute_content_filter(self, prompt: str, pass_name: str | None = None) -> str:
        """Handle a `content_filter` refusal from the primary model (issue
        #116). Blind-retrying the exact same prompt against the exact same
        model cannot change a moderation decision, so the primary is never
        retried for this finish_reason. Instead, issue exactly one
        completion attempt against `self._content_fallback_model` (still
        protected by the same wall-clock deadline as any other attempt via
        `_post_with_deadline`). If that attempt returns `stop`, its content
        is the result. If it ALSO returns `content_filter` -- or no fallback
        is configured at all, since there is then no way to recover a
        refusal -- raise `ContentRefusedError` so the caller can quarantine
        just this chunk instead of failing the whole source.

        `pass_name` (issue #207) is threaded through to `_post_with_deadline`
        unchanged, so the fallback attempt's `reasoning.enabled` value is
        resolved from the SAME per-pass setting as the primary attempt.
        """
        if self._content_fallback_model is None:
            raise ContentRefusedError(
                "primary model refused with finish_reason='content_filter' and no "
                "content_fallback_model is configured to reroute to (issue #116)"
            )
        try:
            response = self._post_with_deadline(
                prompt, model=self._content_fallback_model, pass_name=pass_name
            )
        except httpx.TransportError as exc:
            raise OpenRouterError(
                f"content_fallback_model {self._content_fallback_model!r} request failed: {exc}"
            ) from exc
        except _RequestDeadlineExceeded as exc:
            raise OpenRouterError(
                f"content_fallback_model {self._content_fallback_model!r} request "
                f"exceeded the {self._request_deadline_seconds}s wall-clock deadline "
                "(issue #108)"
            ) from exc
        _raise_for_status_with_body(
            response, action=f"content_fallback_model {self._content_fallback_model!r} request"
        )
        try:
            data = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            snippet = repr(response.text[:300])
            raise OpenRouterError(
                f"malformed content_fallback_model API response body: {exc}; "
                f"body snippet: {snippet}"
            ) from exc
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(
                f"unexpected content_fallback_model OpenRouter response shape: {data!r}"
            ) from exc
        finish_reason = choice.get("finish_reason")
        if finish_reason == "content_filter":
            raise ContentRefusedError(
                "both the primary model and content_fallback_model "
                f"{self._content_fallback_model!r} refused with "
                "finish_reason='content_filter' (issue #116)"
            )

        # The fallback gets exactly one completion attempt -- no retry
        # budget here (per the ratified #116 decision) -- so every other
        # non-"stop" outcome is a terminal failure, not something to retry.
        # Validate it the same way the primary retry loop does, minus the
        # retry: empty content, a truncated ("length") answer, or any other
        # non-"stop" finish_reason ("error", etc.) must raise instead of
        # silently returning `None`/a fragment as if it were a success.
        is_empty = content is None or not content.strip()
        is_truncated = finish_reason == "length"
        is_transient_fault = finish_reason is not None and finish_reason not in (
            "stop",
            "length",
        )
        if is_truncated:
            raise OpenRouterError(
                f"content_fallback_model {self._content_fallback_model!r} completion "
                f"truncated: finish_reason={finish_reason!r} (issue #116)"
            )
        if is_transient_fault:
            raise OpenRouterError(
                f"content_fallback_model {self._content_fallback_model!r} returned "
                f"finish_reason={finish_reason!r} (issue #116)"
            )
        if is_empty:
            raise OpenRouterError(
                "content_filter reroute: fallback model returned an empty completion "
                f"({self._content_fallback_model!r}, issue #116)"
            )
        return content


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
    PRODUCTION_SYNTHESIS_TIER: "production_synthesis",
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


def _resolve_model_for_tier(secrets: dict[str, Any], llm_config: dict[str, Any], tier: str) -> str:
    """Resolve `tier` (one of `TIER_TO_MODEL_KEY`'s three keys) to a concrete
    model name: secrets.toml's tier-named key is PRIMARY, falling back to
    `config/pipeline.yaml`'s `llm.model` and finally the building-tier
    default model, only when secrets.toml doesn't name a model for `tier`
    (e.g. the file is absent entirely). Shared by `_resolve_model` (the
    client's own default model, selected by `llm_tier`) and
    `_resolve_model_by_pass` (DEC-26, issue #235: each per-pass override
    names a tier, not a raw model, and is resolved through this SAME
    machinery) so the two never diverge on what a tier name means.

    A non-`building` tier (`production_high`/`production_low`) whose model
    key is missing from secrets.toml is a misconfiguration, not a case to
    paper over: silently falling through to `DEFAULT_BUILDING_MODEL` there
    would make a run believed to use a paid production model silently use
    the free building model instead. Only the `building` tier keeps the
    fallback chain, so today's no-secrets-file behavior is unchanged.
    """
    model_key = TIER_TO_MODEL_KEY.get(tier)
    if model_key is None:
        raise LLMConfigError(f"unknown model tier: {tier!r}")
    model = secrets.get(model_key) or llm_config.get("model")
    if model:
        return model
    if tier != BUILDING_TIER:
        raise LLMConfigError(
            f"model tier {tier!r} was selected but secrets.toml has no "
            f"{model_key!r} key naming a model for it; set "
            f"'[openrouter].{model_key}' in secrets/secrets.toml"
        )
    return DEFAULT_BUILDING_MODEL


def _resolve_model(secrets: dict[str, Any], llm_config: dict[str, Any]) -> str:
    """Model resolution (issue #23, requirement 2): `llm_tier` selects which
    of the three model-name keys in secrets.toml to use, via
    `_resolve_model_for_tier`; an unset selector defaults to the building
    tier."""
    tier = secrets.get("llm_tier") or DEFAULT_LLM_TIER
    return _resolve_model_for_tier(secrets, llm_config, tier)


def _resolve_reasoning_by_pass(llm_config: dict[str, Any]) -> dict[str, bool | str]:
    """Per-pass model reasoning (§7.9, issue #207): `config/pipeline.yaml`'s
    `llm.reasoning_by_pass` block is the carried-per-pass source of truth --
    "never hardcoded" -- so its entries OVERRIDE `DEFAULT_REASONING_BY_PASS`
    (itself just the same defaults, in code, for a caller/test that builds
    `OpenRouterClient` directly without config plumbing). An absent block or
    absent file leaves the code-level default entirely unchanged. A value may
    be `bool` (on/off at OpenRouter's implicit default effort) or `str` (an
    explicit `reasoning.effort` level) -- see `_post_with_deadline`."""
    merged = dict(DEFAULT_REASONING_BY_PASS)
    configured = llm_config.get("reasoning_by_pass") or {}
    merged.update(configured)
    return merged


def _resolve_votes_by_pass(llm_config: dict[str, Any]) -> dict[str, int]:
    """Per-pass best-of-N voting (DEC-31, issue #294): mirrors
    `_resolve_reasoning_by_pass` exactly -- `config/pipeline.yaml`'s
    `llm.votes_by_pass` block is the carried-per-pass source of truth ("never
    hardcoded"), so its entries OVERRIDE `DEFAULT_VOTES_BY_PASS`. An absent
    block or absent file leaves the code-level default entirely unchanged.
    A pass named in neither resolves to `SINGLE_DRAW` via `votes_for_pass`."""
    merged = dict(DEFAULT_VOTES_BY_PASS)
    configured = llm_config.get("votes_by_pass") or {}
    merged.update(configured)
    return merged


def votes_for_pass(pass_name: str, config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH) -> int:
    """How many times `pass_name` draws its per-unit LLM call before voting
    (issue #294). Unlike `reasoning`/`model`, this setting is consumed by the
    PASS's own loop rather than by the client request, so it is read here
    directly instead of being threaded into `OpenRouterClient` -- the config
    shape and resolver are otherwise identical to the two per-pass settings
    above. A pass named nowhere resolves to `SINGLE_DRAW`."""
    return _resolve_votes_by_pass(_load_pipeline_llm_config(config_path)).get(
        pass_name, SINGLE_DRAW
    )


def _resolve_model_by_pass(secrets: dict[str, Any], llm_config: dict[str, Any]) -> dict[str, str]:
    """Per-pass model tiering (DEC-26, issue #235): mirrors
    `_resolve_reasoning_by_pass` exactly, except `config/pipeline.yaml`'s
    `llm.model_by_pass` block names a TIER per pass (e.g. `envelope:
    production_high`), never a raw model name, so each entry is resolved to
    a concrete model name via `_resolve_model_for_tier` -- the SAME
    secrets.toml tier->model machinery `_resolve_model` itself uses for the
    client's own default model -- before it is handed to `OpenRouterClient`.
    An absent block or absent file yields `DEFAULT_MODEL_BY_PASS` (empty):
    no pass gets an override, and every pass keeps sending requests to the
    client's own default configured model, exactly like before this issue.
    A named tier with no secrets.toml key for it is a misconfiguration and
    raises `LLMConfigError` immediately (the same guard `_resolve_model`
    already enforces for the client's own default model) -- never a silent
    fallback to the free building model."""
    configured = llm_config.get("model_by_pass") or dict(DEFAULT_MODEL_BY_PASS)
    return {
        pass_name: _resolve_model_for_tier(secrets, llm_config, tier)
        for pass_name, tier in configured.items()
    }


def _build_openrouter_client(llm_config: dict[str, Any]) -> OpenRouterClient:
    secrets = _load_openrouter_secrets(_secrets_path())
    base_url = llm_config.get("base_url", DEFAULT_OPENROUTER_BASE_URL)
    api_key = _resolve_api_key(secrets)
    model = _resolve_model(secrets, llm_config)
    # Issue #116: the model a `content_filter` refusal reroutes to. An
    # absent key (the common case today) yields `None` -- no fallback
    # configured, unchanged behavior for anyone who hasn't set it up.
    content_fallback_model = secrets.get("content_fallback_model")
    reasoning_by_pass = _resolve_reasoning_by_pass(llm_config)
    model_by_pass = _resolve_model_by_pass(secrets, llm_config)
    return OpenRouterClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        content_fallback_model=content_fallback_model,
        reasoning_by_pass=reasoning_by_pass,
        model_by_pass=model_by_pass,
    )


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
