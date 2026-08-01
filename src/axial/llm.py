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
from axial.yaml_loader import SAFE_LOADER

PROVIDER_ENV_VAR = "AXIAL_LLM_PROVIDER"
RECORD_PATH_ENV_VAR = "AXIAL_LLM_RECORD_PATH"

# Issue #100 test/CI-only seam: when set to a non-empty value, the
# stub/record clients' chunk-pass response becomes this raw string verbatim
# instead of the default canned chunk response, letting a test drive a
# malformed/invalid-escape chunk payload end-to-end via subprocess (e.g.
# tests/test_chunk_invalid_escapes.py). Read at call time (not import time).
# Never affects the artifacts or envelope canned responses.
STUB_CHUNK_RESPONSE_ENV_VAR = "AXIAL_STUB_CHUNK_RESPONSE"

# Issue #104 test/CI-only seam: a JSON-encoded array of raw chunk-pass
# response strings, each in exactly the shape STUB_CHUNK_RESPONSE_ENV_VAR
# already accepts. When set to a NON-EMPTY JSON array, it takes priority
# over STUB_CHUNK_RESPONSE_ENV_VAR for the chunk-pass canned-response
# dispatch (both `stub` and `record`, since `record` delegates to the same
# dispatch). A per-process, 1-indexed counter (`_chunk_pass_call_count`)
# selects which element answers the Nth such call: `sequence[(N - 1) %
# len(sequence)]`, cycling once the array is exhausted. Read fresh
# (JSON-decoded) from the environment on every call. An unset/empty value or
# an empty JSON array falls through to STUB_CHUNK_RESPONSE_ENV_VAR (today's
# behavior).
STUB_CHUNK_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE"

# Issue #98 test/CI-only fault-injection seam: when set to
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
# the loop's clean-end signal). Unlike `STUB_CHUNK_RESPONSE_SEQUENCE_ENV_VAR`
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
# A fifth tier (Phase A v1, D14/issue #419), named for the same reason
# `PRODUCTION_SYNTHESIS_TIER` above was: the per-note interrogation pass runs
# on `z-ai/glm-5.2`, which is neither `production_high` (deepseek-v4-pro, the
# envelope pass's model) nor `production_synthesis` (the Phase-B synthesis
# model that happens to be the same model id today). Pointing the new pass at
# either existing tier would couple it to an unrelated pass, so that a later
# swap of one silently moves the other.
PRODUCTION_INTERROGATE_TIER = "production_interrogate"
# Three more tiers (issue #493's two-arm eval, founder direction 2026-07-31),
# named for exactly the reason the two above were. The open-source and
# closed-source arms wire Phase B's four model-calling passes to four
# different models, and three of those passes share a tier today: `interrogate`
# and `retrieve` both sit on `production_high`, and `counter_position_generate`
# rides `production_synthesis`. Splitting them is what makes an arm a
# secrets.toml swap rather than a code change, and it stops an arm's pick from
# dragging a Phase A pass with it -- `envelope` and `gather_eval` keep
# `production_high`, `note_interrogate` keeps `production_interrogate`.
PRODUCTION_BRIEF_INTERROGATE_TIER = "production_brief_interrogate"
PRODUCTION_RETRIEVE_TIER = "production_retrieve"
PRODUCTION_COUNTER_POSITION_TIER = "production_counter_position"

# Phase C's two model-calling passes, one tier each on the same rule
# (specs/PHASE-C.md §7.12). Both must be registered in TIER_TO_MODEL_KEY
# below as well: a tier is three legs, not two -- the constant here, the
# secrets.toml key it names, and the config/pipeline.yaml entry routing a pass
# to it. Naming a tier in config and secrets alone fails with "unknown model
# tier", which is the right failure and a confusing one to meet cold.
PRODUCTION_PAPER_PLAN_TIER = "production_paper_plan"
PRODUCTION_PAPER_DRAFT_TIER = "production_paper_draft"
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

# Pass name an artifact-classification call identifies itself with (see
# src/axial/artifacts.py). Same out-of-band dispatch convention as
# CHUNK_PASS_NAME above.
ARTIFACTS_PASS_NAME = "artifacts"

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

# Pass name the Phase A v1 per-NOTE interrogation pass's single per-note call
# identifies itself with (see src/axial/interrogate.py, issue #419, PRD §7.9/
# §7.15, D6/D14). Named separately from `INTERROGATE_PASS_NAME` immediately
# above -- which belongs to Phase B's brief pre-pass and must not be touched,
# renamed or repointed -- because sharing one name would silently share one
# `model_by_pass`/`reasoning_by_pass` entry between two passes that want
# different models and different reasoning settings (§7.9).
NOTE_INTERROGATE_PASS_NAME = "note_interrogate"

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

# Pass name the stage-4 counter-position GENERATION call identifies itself
# with (see src/axial/analyze/synthesis.py's `generate_counter_position`,
# issue #399, PRD §7.8/§7.11): the second, follow-up synthesis-family call
# that -- only on a mechanically-contested brief -- drafts the §7.8 section
# from a whitelisted pool of the run's own opposing evidence, or discloses
# the corpus as one-sided. Named SEPARATELY from SYNTHESIZE_PASS_NAME (rather
# than reusing it) purely so the stub/record dispatch below can tell the two
# calls apart -- they return differently-shaped canned JSON, and a
# stub-driven test scripting one must never leak into the other. This is
# still the GENERATING model, never an independent judge: it must be free to
# resolve to the SAME model as SYNTHESIZE_PASS_NAME (config routes both to
# `production_synthesis`), unlike COUNTER_POSITION_PASS_NAME below, which is
# the bounded steelman-quality CHECK and must resolve to a DIFFERENT model.
COUNTER_POSITION_GENERATE_PASS_NAME = "counter_position_generate"

# Pass name the stage-5 attribution validator's bounded (b)-seam honesty
# check identifies itself with (see src/axial/validators/attribution.py,
# issue #258, PRD §7.9): does a claim marked "b" (tool-infers-across-sources)
# read as though a single source asserted it. Same out-of-band dispatch
# convention as CHUNK_PASS_NAME above -- naming this constant is what makes
# the check routable through `model_by_pass`, which is the whole point: it
# must resolve to a DIFFERENT model than SYNTHESIZE_PASS_NAME, never the
# model that generated the claims it is checking (§7.9, charter §2).
ATTRIBUTION_PASS_NAME = "attribution"

# Pass name Phase C's stage-2 arc-planning call identifies itself with (see
# src/axial/paper/plan.py, specs/PHASE-C.md §7.2/§7.12): it emits the ordered
# sections, their roles and their assigned claims, and no prose at all, so a
# plan is inspectable before a single drafting dollar is spent. Named
# separately from PAPER_DRAFT_PASS_NAME below for the same reason
# COUNTER_POSITION_GENERATE_PASS_NAME is named separately from
# SYNTHESIZE_PASS_NAME -- the two return differently-shaped JSON, and a
# stub-driven test scripting one must never leak into the other. §7.12 says a
# cheaper tier may suffice here, since this pass emits structure rather than
# prose; that is a config choice, not a code one.
PAPER_PLAN_PASS_NAME = "paper_plan"

# Pass name Phase C's stage-3 drafting call identifies itself with (see
# src/axial/paper/draft.py, specs/PHASE-C.md §7.2/§7.12). Called ONCE PER
# SECTION rather than once per paper (§4): Phase B measured that ~20 notes
# reach a model however many are supplied (PHASE-B P2-7), so a whole-inventory
# prompt would have a tail nothing reads. This is the pass Phase C's grounding
# and (b)-seam gates re-anchor their self-grading guards to, where Phase B's
# anchor is SYNTHESIZE_PASS_NAME (§10.1) -- so it must be routable, and a
# judge must never resolve to whatever this resolves to.
PAPER_DRAFT_PASS_NAME = "paper_draft"

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

# Pass name the instant-dismissal judge identifies itself with (see
# src/axial/answer/dismissal.py, issue #491, specs/PHASE-B.md §10.0/§9.3):
# did the rendered answer do a thing the case declares disqualifying on
# sight. NOT a sixth rung-3 gate -- §10.0 measures and reports it, and
# promotes it only under §7.13's stated discipline -- but it carries the
# same self-grading guard as GROUNDING_PASS_NAME above and for the same
# reason: it must resolve to a DIFFERENT model than SYNTHESIZE_PASS_NAME,
# since the model that wrote the answer must never rule on whether the
# answer is disqualified.
INSTANT_DISMISSAL_PASS_NAME = "instant_dismissal"

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

# Pass name each sealed-packet peer reviewer identifies itself with (see
# src/axial/panel/, issue #385, specs/PHASE-B.md §9.4, DEC-40/DEC-43). Unlike
# every judge pass above, this one is NOT part of any run: the panel is an
# offline eval instrument scored on a sample, and no production brief run
# ever dispatches it. Its guard is also strictly stronger than the
# GROUNDING/CALIBRATION self-grading guard -- a reviewer must resolve to a
# different VENDOR (training lab) than SYNTHESIZE_PASS_NAME, not merely a
# different model id, because shared training priors survive within a family
# and a family-mate's agreement is weak evidence.
#
# Reviewer N is routed via `model_by_pass["panel_review.<n>"]`, so a panel
# run can put each of its N >= 3 reviewers on a different model through the
# existing config seam without a second dispatch convention.
PANEL_REVIEW_PASS_NAME = "panel_review"

# Pass name the Phase A v1 name-merge pass identifies itself with (§7.9's own
# pass table names it `reconcile`; §7.16 / P0-12, issue #416). It shares only
# the English word with `src/axial/reconcile.py`'s model-free orphan GC, which
# makes no LLM call and therefore has no pass name at all. Same out-of-band
# dispatch convention as CHUNK_PASS_NAME above -- naming this constant is what
# routes the merge call through the `reasoning_by_pass`/`temperature_by_pass`
# config seams, which is the whole point: this pass runs at temperature 1 with
# reasoning high (founder directive, issue #416), and nothing else does.
RECONCILE_PASS_NAME = "reconcile"

# Pass name the Phase A v1 disagreement pass identifies itself with (§7.9's
# own pass table names it `gather`; §7.18 / P0-13, issue #412). Same
# out-of-band dispatch convention as CHUNK_PASS_NAME above -- naming this
# constant is what lets a real run route Gather through the
# `model_by_pass`/`reasoning_by_pass`/`temperature_by_pass` config seams
# without a code change. Both shapes of Gather call (one per batch, plus the
# short merge call over a batched name's findings) carry this same pass
# name: they are the same judgment at two scales, not two passes.
GATHER_PASS_NAME = "gather"

# Pass name the Phase A v1 grounding-eval instrument's own judge call
# identifies itself with (`axial.gather_eval`, issue #478, D15/D17 -- DEC-54:
# "the reference is grounding"). Same out-of-band dispatch convention as
# ATTRIBUTION_PASS_NAME/GROUNDING_PASS_NAME above -- naming this constant is
# what makes the judge routable through `model_by_pass`, and it must resolve
# to a DIFFERENT model than GATHER_PASS_NAME, since the pass that wrote a
# disagreement must never be the pass that judges it grounded (§10, charter
# §2, same self-grading guard as GROUNDING_PASS_NAME).
GATHER_EVAL_PASS_NAME = "gather_eval"

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
    # §7.12: drafting is the judgment-heavy pass, high tier with reasoning ON,
    # for the same reason synthesis is. Arc planning is deliberately absent
    # rather than set False -- it emits structure, and whether it needs
    # reasoning is a measurement nobody has made, so it keeps the client's own
    # default instead of a guess hardcoded here.
    PAPER_DRAFT_PASS_NAME: True,
    # §7.9: OFF by default, matching every other high-volume per-note pass
    # (#147). The 50-output sample gate is where that default is tested; if
    # the sample shows the answers need reasoning, turning it on is a config
    # change, not a code change.
    NOTE_INTERROGATE_PASS_NAME: False,
    ARTIFACTS_PASS_NAME: False,
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

# Per-pass SAMPLING TEMPERATURE (§7.9, issue #416), the third per-pass block,
# mirroring `DEFAULT_MODEL_BY_PASS`'s shape and resolution exactly. Until now
# no request carried a `temperature` field at all, so OpenRouter applied each
# model's own default; the name-merge pass (`RECONCILE_PASS_NAME`) needs an
# explicit 1 (founder directive: merging names is an underdetermined judgment,
# won by sampling rather than by prompt engineering -- `docs/tag-reliability-
# best-of-n.md` §2.11 lesson 4). Deliberately EMPTY here, like
# `DEFAULT_MODEL_BY_PASS`: a pass named neither here nor in
# `config/pipeline.yaml`'s `llm.temperature_by_pass` block sends NO
# `temperature` field, so every other pass's request body is byte-for-byte
# what it was before this block existed. `config/pipeline.yaml` is the
# carried-per-pass source of truth for a real run.
DEFAULT_TEMPERATURE_BY_PASS: dict[str, float] = {}

# Minimal per-model $/1k-token price table (issue #363, benchmark-cost
# support for #362): covers the OpenRouter model ids `config/pipeline.yaml`
# currently routes the brief pipeline's cost-bearing passes (interrogate,
# retrieve, synthesize) to, plus the shared building-tier default. This is
# deliberately NOT a live pricing API or an auto-refreshed table (#363's own
# out-of-scope list -- an over-engineering tripwire) -- a static snapshot is
# enough for a benchmark sweep. Sourced from OpenRouter's public `/models`
# pricing endpoint, re-read 2026-07-31 for issue #493's two-arm eval; $ per
# 1000 tokens. A model id absent here is UNPRICED, not an error:
# `estimate_cost` resolves it to `None` and logs the gap once, never raises
# and never fails a run.
#
# TWO ROWS MOVED between the 2026-07-24 snapshot and this one, both upward:
# `deepseek-v4-flash` 0.000098/0.000196 and `z-ai/glm-5.2`
# 0.0007826/0.0024596. Every cost figure this repo reported before today was
# computed from those, so runs whose synthesis ran on glm-5.2 -- the whole
# smoke history, including the $0.30 budget cut from smoke-v4 -- spent more
# than they reported. The three new rows are the closed-source and
# open-source arms of #493; without them the arms' cost column is null.
PRICE_TABLE_USD_PER_1K: dict[str, dict[str, float]] = {
    "deepseek/deepseek-v4-pro": {"input": 0.000435, "output": 0.00087},
    "deepseek/deepseek-v4-flash": {"input": 0.00014, "output": 0.00028},
    "z-ai/glm-5.2": {"input": 0.00112, "output": 0.00352},
    "openai/gpt-5.4": {"input": 0.0025, "output": 0.015},
    "openai/gpt-5.6-sol": {"input": 0.005, "output": 0.03},
    "moonshotai/kimi-k3": {"input": 0.003, "output": 0.015},
    "nvidia/nemotron-3-ultra-550b-a55b:free": {"input": 0.0, "output": 0.0},
}

# Per-process set of model ids `estimate_cost` has already logged as
# unpriced -- "logged once" (issue #363), not once per call, since a
# benchmark sweep can call the same unpriced model hundreds of times in one
# run.
_unpriced_models_logged: set[str] = set()


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Dollar cost of one completion under `PRICE_TABLE_USD_PER_1K` (issue
    #363): `None` -- never zero, never a raise -- when `model` is absent
    from the table, so a run against a model nobody has priced yet still
    succeeds; the gap is printed to stderr exactly once per model id per
    process."""
    price = PRICE_TABLE_USD_PER_1K.get(model)
    if price is None:
        if model not in _unpriced_models_logged:
            _unpriced_models_logged.add(model)
            print(
                f"llm_cost_unpriced model={model!r}: no PRICE_TABLE_USD_PER_1K entry, "
                "cost for this model will be null (issue #363)",
                file=sys.stderr,
            )
        return None
    return (prompt_tokens / 1000) * price["input"] + (completion_tokens / 1000) * price["output"]


def _accumulate_usage(
    store: dict[str | None, dict[str, int]], pass_name: str | None, usage: dict[str, Any] | None
) -> None:
    """Fold one completion call's `usage` object (issue #363) into
    `store[pass_name]` in place, creating the entry on first use. `usage`
    absent/falsy (a malformed response, or a test client with nothing to
    report) is a silent no-op -- `usage_for_pass` then correctly reports
    `None` for a pass no call ever supplied tokens for, never a fabricated
    zero. Shared by every `LLMClient` implementation in this module so
    `usage_for_pass`'s accumulation semantics never drift between them."""
    if not usage:
        return
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    entry = store.setdefault(
        pass_name, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    )
    entry["prompt_tokens"] += prompt_tokens
    entry["completion_tokens"] += completion_tokens
    entry["total_tokens"] += total_tokens


# Per-pass best-of-N voting (DEC-31, issue #294): how many times a pass draws
# its per-unit call before majority-voting the result. Mirrors
# `DEFAULT_REASONING_BY_PASS`'s per-pass shape exactly -- this is the
# CODE-LEVEL default, and `config/pipeline.yaml`'s own `llm.votes_by_pass`
# block (read by `_resolve_votes_by_pass` below) is the carried-per-pass
# source of truth, so `N` is never hardcoded at a call site. The mechanism
# itself is reused by other passes' config wiring (e.g.
# `axial.brief.interrogate`'s `votes_by_pass` seam); the tag pass was the
# only entry here (DEC-31 measured `theory_school` 0.757 -> 0.918 and
# `claim_type` 0.796 -> 0.866 at N=3, past the single-draw intra-annotator
# ceiling) and is retired with it (issue #414, D4 -- Phase A v1 is one draw,
# no voting layer). Every pass absent here resolves to `SINGLE_DRAW` -- one
# draw, no voting layer, today's behavior for every current pass.
DEFAULT_VOTES_BY_PASS: dict[str, int] = {}

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

# Issue #252 test/CI-only seam: when set
# to a non-empty value, the stub/record clients' interrogate-pass response
# becomes this raw string verbatim instead of the default canned
# interrogation response, letting an acceptance test drive a specific
# `{premises_found, bounds_applied, refusal}` combination end-to-end via
# subprocess (e.g. a contradicted premise, a non-null refusal, or a
# model-emitted `disposition` the deterministic wrapper must discard). Read
# at call time, like every other seam here. Never affects any other pass's
# canned response.
STUB_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_INTERROGATE_RESPONSE"

# Issue #419 test/CI-only seam: mirrors STUB_INTERROGATE_RESPONSE_ENV_VAR
# above, exactly, for the Phase A per-NOTE interrogation pass
# (`NOTE_INTERROGATE_PASS_NAME`) instead of Phase B's brief pre-pass. When set
# to a non-empty value, the stub/record clients' note_interrogate-pass
# response becomes this raw string verbatim instead of the default canned
# answer record, letting a test drive a specific abstention, a specific
# free/nearest pair, or a deliberate D8 collapse end-to-end. Read at call
# time, like every other seam here. Never affects any other pass's canned
# response -- least of all the identically-shaped-sounding but entirely
# separate `interrogate` pass above.
STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR = "AXIAL_STUB_NOTE_INTERROGATE_RESPONSE"

# Issue #416 test/CI-only seam: mirrors STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR
# above, exactly, for the name-merge pass (`RECONCILE_PASS_NAME`). When set to
# a non-empty value, the stub/record clients' reconcile-pass response becomes
# this raw string verbatim, letting an acceptance test drive a specific set of
# merges end-to-end through the real CLI. Unset, the merge pass gets no canned
# response of its own: there is no honest default, since a merge answer can
# only name surface forms the prompt actually carried, and a stub-driven run
# that scripts nothing merges nothing. Never affects any other pass.
STUB_RECONCILE_RESPONSE_ENV_VAR = "AXIAL_STUB_RECONCILE_RESPONSE"

# Issue #412 test/CI-only seam: mirrors STUB_RECONCILE_RESPONSE_ENV_VAR
# above, exactly, for the Gather pass (`GATHER_PASS_NAME`). When set to a
# non-empty value, the stub/record clients' gather-pass response becomes this
# raw string verbatim, letting an acceptance test drive a specific
# disagreement and a specific set of name-to-name links end to end through
# the real CLI. Unlike the merge pass, Gather HAS an honest default: a
# disagreement statement names no surface form the prompt has to have
# carried, so an unscripted stub run writes a fixed placeholder statement
# with no links. Never affects any other pass.
STUB_GATHER_RESPONSE_ENV_VAR = "AXIAL_STUB_GATHER_RESPONSE"

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

# Issue #399 test/CI-only seam: mirrors STUB_SYNTHESIZE_RESPONSE_ENV_VAR
# above, exactly, for the counter-position GENERATION call
# (`COUNTER_POSITION_GENERATE_PASS_NAME`) instead of the primary claims call.
# When set to a non-empty value, the stub/record clients'
# counter_position_generate-pass response becomes this raw string verbatim
# instead of the default canned response, letting a test script a specific
# `{present, stance, grounds, corpus_one_sided, one_sided_reason}` combination
# end-to-end. Read at call time, like every other seam here. Never affects
# any other pass's canned response.
STUB_COUNTER_POSITION_GENERATE_RESPONSE_ENV_VAR = "AXIAL_STUB_COUNTER_POSITION_GENERATE_RESPONSE"

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

# Issue #491 test/CI-only seam: mirrors STUB_GROUNDING_RESPONSE_SEQUENCE_ENV_VAR
# above, exactly, for the instant-dismissal judge call (§10.0) instead of the
# grounding gate. A JSON-encoded array of raw response strings (each
# `{"verdict": "violation"|"no_violation"}`), indexed by a fresh, dedicated,
# per-process 1-indexed counter -- one call per dismissal criterion judged.
# An unset/empty value falls back to the default "no_violation".
STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE"

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

# Issue #385 test/CI-only seam: a JSON array of raw reviewer verdicts for
# the §9.4 panel, indexed by a dedicated per-process 1-indexed counter
# (`_panel_review_pass_call_count`). One call per (packet, reviewer) pair,
# dispatched strictly sequentially by `axial.panel.review`, so a test scripts
# "reviewer 1 catches it, reviewers 2 and 3 do not" as an array and gets that
# order back. (The counter race of issue #370 needs CONCURRENT dispatch
# against one scripted sequence; this pass has none by construction.) Cycles
# once exhausted. Unset/empty falls back to a clean verdict naming no defect
# -- so a stub-driven positive control FAILS by default, and a test has to
# script the catch rather than inherit one.
STUB_PANEL_REVIEW_RESPONSE_SEQUENCE_ENV_VAR = "AXIAL_STUB_PANEL_REVIEW_RESPONSE_SEQUENCE"

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

# Per-process, 1-indexed counter of chunk-pass canned-response dispatches,
# driving the AXIAL_STUB_CHUNK_RESPONSE_SEQUENCE seam (issue #104). A
# module global so it is shared across both the `stub` and `record` clients
# (which delegate to the same `_canned_response_for` dispatch) and reset
# naturally to zero at the start of every fresh `axial` subprocess.
_chunk_pass_call_count = 0

# Per-process, 1-indexed counter of artifacts-pass canned-response
# dispatches, driving the AXIAL_STUB_ARTIFACT_FAIL_AT fault-injection seam
# (issue #98), mirroring `_chunk_pass_call_count` above exactly.
_artifact_pass_call_count = 0

# Per-process, 1-indexed counter of grounding-pass canned-response
# dispatches, driving the AXIAL_STUB_GROUNDING_RESPONSE_SEQUENCE seam (issue
# #262), mirroring `_chunk_pass_call_count` above exactly.
_grounding_pass_call_count = 0

# Per-process, 1-indexed counter of calibration-pass canned-response
# dispatches, driving the AXIAL_STUB_CALIBRATION_RESPONSE_SEQUENCE seam
# (issue #263), mirroring `_grounding_pass_call_count` above exactly.
_calibration_pass_call_count = 0

# Per-process, 1-indexed counter of instant-dismissal-pass canned-response
# dispatches, driving the AXIAL_STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE seam
# (issue #491), mirroring `_grounding_pass_call_count` above exactly.
_instant_dismissal_pass_call_count = 0

# Per-process, 1-indexed counter of interrogate-pass canned-response
# dispatches, driving the AXIAL_STUB_INTERROGATE_RESPONSE_SEQUENCE seam
# (issue #264), mirroring `_grounding_pass_call_count` above exactly.
_interrogate_pass_call_count = 0

# Per-process, 1-indexed counter of premise_match-pass canned-response
# dispatches, driving the AXIAL_STUB_PREMISE_MATCH_RESPONSE_SEQUENCE seam
# (issue #264), mirroring `_grounding_pass_call_count` above exactly.
_premise_match_pass_call_count = 0

# Per-process, 1-indexed counter of panel-reviewer canned-response
# dispatches, driving the AXIAL_STUB_PANEL_REVIEW_RESPONSE_SEQUENCE seam
# (issue #385), mirroring `_premise_match_pass_call_count` above exactly.
_panel_review_pass_call_count = 0

# Issue #370 built a submission-order slot (`dispatch_slot`/`reserve_tag_
# dispatch_slots`) for a concurrently-dispatched group of calls -- the tag
# pass's best-of-N votes loop was the only concurrent call site any pass
# ever had. Retired with the tag pass (issue #414, D4: Phase A v1 is one
# draw, no voting layer, so nothing dispatches concurrently against this
# module's stub/record clients anymore). A future concurrent caller on
# another counter-backed pass would need to rebuild this seam -- not kept
# speculatively.

# Guards every counter above (issue #325 follow-up): a bare module-global
# `count += 1` is not one atomic operation, and a concurrent pass's votes
# loop could fire multiple `complete()` calls against the SAME
# `StubLLMClient`/`RecordLLMClient` instance at once. Real providers
# (`OpenRouterClient`) never touch these counters at all, so this lock never
# taxes a production call; it exists purely to keep the test/CI-only
# canned-response dispatch (and `StubLLMClient`/`RecordLLMClient`'s own
# `call_count`) correct under concurrent draws, should a future pass need
# them.
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

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        """Return the token usage this client has accumulated so far for
        `pass_name` -- `{"prompt_tokens", "completion_tokens",
        "total_tokens"}`, summed across every `.complete()`/
        `.complete_with_tools()` call tagged with that `pass_name` -- or
        `None` when no call for it has supplied usage yet (issue #363).
        Mirrors `model_for_pass`'s own shape: an accumulator/getter exposed
        on the client, not a return-value change, so no existing
        `.complete()`/`.complete_with_tools()` call site has to change how
        it calls this interface."""
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


# Issue #363 test/CI-only seam: the fixed, deterministic usage
# `StubLLMClient`/`RecordLLMClient` report for every call, since neither
# talks to a real model and so has no real `usage` object to parse. Exists
# only so the accumulation machinery (`_accumulate_usage`,
# `usage_for_pass`) is exercised end-to-end by the existing stub/record
# acceptance-test seam without inventing a third canned-response contract;
# the actual numbers are arbitrary and carry no pricing significance.
_STUB_USAGE_PER_CALL: dict[str, int] = {
    "prompt_tokens": 100,
    "completion_tokens": 50,
    "total_tokens": 150,
}


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

    def __init__(self) -> None:
        self.call_count = 0
        # Issue #253 slice 01: a per-INSTANCE counter for the scripted
        # tool-call channel (`STUB_TOOL_CALLS_ENV_VAR`'s own comment
        # explains why this is instance-level, not a module global like the
        # chunk/artifact counters above).
        self._tool_call_index = 0
        # Issue #363: per-instance accumulator, mirroring `_tool_call_index`
        # above -- there is no real model behind this client, so every call
        # reports the same fixed `_STUB_USAGE_PER_CALL` (see its own
        # comment), folded in via the shared `_accumulate_usage` helper.
        self._usage_by_pass: dict[str | None, dict[str, int]] = {}

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        # Locked (see `_stub_dispatch_lock`'s own comment): `call_count` and
        # `_canned_response_for`'s dispatch counters are shared, mutable
        # state a concurrent caller could call this from multiple threads
        # at once.
        with _stub_dispatch_lock:
            self.call_count += 1
            _accumulate_usage(self._usage_by_pass, pass_name, _STUB_USAGE_PER_CALL)
            return _canned_response_for(pass_name)

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """A fixed, deterministic id -- there is no real model behind this
        client, but the run-logging record still needs a stable non-null
        value to prove a model-bearing pass's `model` field round-trips
        under the stub provider (issue #270 slice 02). Issue #258:
        `STUB_MODEL_BY_PASS_ENV_VAR`, when it names `pass_name`, overrides
        this fixed id -- see that env var's own comment for why."""
        return _model_for_pass_from_stub_mapping(pass_name)

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        """The accumulated fixed `_STUB_USAGE_PER_CALL` usage for
        `pass_name` (issue #363) -- there is no real model behind this
        client, but the accumulation mechanism itself (summing across every
        call tagged with `pass_name`) is exercised exactly as it would be
        under a real provider, e.g. the retrieval loop's several turns."""
        return self._usage_by_pass.get(pass_name)

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
            _accumulate_usage(self._usage_by_pass, pass_name, _STUB_USAGE_PER_CALL)
        return _scripted_tool_call_for(index)


def _canned_artifact_response() -> str:
    """The canned response for an artifacts-pass call (identified by
    `pass_name=ARTIFACTS_PASS_NAME`, never by prompt content): an
    `artifact_role` value, read fresh from `STUB_ARTIFACT_ROLE_ENV_VAR` on
    every call so tests can force an out-of-schema role on demand (see
    tests/test_artifacts.py's module docstring, seam decision 2), plus a
    `field` value (issue #32 slice 02) in a
    `{"primary": <str>, "secondary": [...]}` shape -- real, in-schema
    members of config/domains/syria/schema.yaml's `field` axis, so the
    end-to-end stub path validates cleanly regardless of which
    artifact_role is in play."""
    role = os.environ.get(STUB_ARTIFACT_ROLE_ENV_VAR) or _DEFAULT_STUB_ARTIFACT_ROLE
    return json.dumps(
        {
            "artifact_role": role,
            "field": {"primary": "state", "secondary": ["ideology"]},
        }
    )


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


# The default canned response for a per-note interrogation call (issue #419,
# PRD §7.15): one plausible answer record carrying every answer field frame
# 0.2 asks for, one explicit `not-in-passage` abstention (D7 is the ordinary
# case, not the exception), and free answers that deliberately match NO
# example string in the domain frame -- so the D8 collapse check reads 0
# unless a test scripts a collapse itself, rather than inheriting one from
# this fixture.
_CANNED_NOTE_INTERROGATE_RESPONSE = json.dumps(
    {
        "about": ["the party-state's capture of the bureaucracy"],
        "about_nearest": {"example": "state", "fit": "close"},
        "claim": "the party apparatus, not the army, produced durable rule",
        "claim_nearest": {"example": "state-formation", "fit": "close"},
        "move": "conceding the coup in order to narrow the claim to organisation",
        "move_nearest": {"example": "role:claim", "fit": "loose"},
        "ranges_over": "Syria between the 1963 coup and the late 1970s",
        "ranges_over_nearest": {"example": "scope:country-case", "fit": "close"},
        "stops_holding": "the author says it does not carry past the 1982 rupture",
        "position_of": "the author's own",
        "position": "durable authoritarian rule was built by a party, not by an army",
        "position_nearest": {"example": "bellicist", "fit": "loose"},
        "arguing_against": ["readings of the party as a primarily sectarian vehicle"],
        "names": [
            {"name": "Ba'ath Party", "kind": "institution"},
            {"name": "Syria", "kind": "place"},
        ],
        "citations": [{"cited": "Batatu", "stance": "support", "about": "the officer corps"}],
        "mechanism": "rural recruitment -> party penetration of ministries -> elite displacement",
        "evidence": "officer-corps origin data and the land-reform decrees",
        "comparison": "not-in-passage",
        "defines": ["party-state"],
        "uses": ["infrastructural power"],
        "concedes": "that the initial seizure of power was a conventional military coup",
        "assumes": {"not-in-passage": "the passage states no unspoken premise"},
    }
)


def _canned_note_interrogate_response() -> str:
    """The canned response for a per-note interrogation call (identified by
    `pass_name=NOTE_INTERROGATE_PASS_NAME`, issue #419): read fresh from
    `STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR` on every call so a test can
    inject any answer record end-to-end (see that env var's own comment
    above); unset/"" falls back to the default canned record."""
    override = os.environ.get(STUB_NOTE_INTERROGATE_RESPONSE_ENV_VAR, "")
    return override or _CANNED_NOTE_INTERROGATE_RESPONSE


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


# The default canned reviewer verdict (issue #385, §9.4 property 5): clean
# bands and NO defects. Deliberately the generous answer, so a stub-driven
# positive control fails by default and a test must script every catch --
# inheriting a passing control from a default would defeat the one guard
# that decides whether a panel number is reportable at all.
_CANNED_PANEL_REVIEW_RESPONSE = json.dumps(
    {
        "factual_correctness": "adequate",
        "citation_grounding": "adequate",
        "completeness": "adequate",
        "defects": [],
    }
)


def _canned_panel_review_response() -> str:
    """The canned response for a panel-reviewer call (identified by a
    `pass_name` of `panel_review.<n>`, issue #385): a JSON array read fresh
    from `STUB_PANEL_REVIEW_RESPONSE_SEQUENCE_ENV_VAR`, indexed by the fresh
    per-process counter just advanced (see that env var's own comment)."""
    global _panel_review_pass_call_count
    _panel_review_pass_call_count += 1
    sequence_raw = os.environ.get(STUB_PANEL_REVIEW_RESPONSE_SEQUENCE_ENV_VAR, "")
    if sequence_raw:
        sequence = json.loads(sequence_raw)
        if sequence:
            return sequence[(_panel_review_pass_call_count - 1) % len(sequence)]
    return _CANNED_PANEL_REVIEW_RESPONSE


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


# The default canned response for a counter-position-GENERATION call (issue
# #399): the conservative one-sided disclosure, never a fabricated stance --
# a stub-driven run that never scripts a real opposing position must not
# invent scholarly opposition nobody scripted, the same "never invent a flag
# nobody scripted" convention `_canned_attribution_response` follows.
_CANNED_COUNTER_POSITION_GENERATE_RESPONSE = json.dumps(
    {
        "present": False,
        "stance": None,
        "grounds": [],
        "corpus_one_sided": True,
        "one_sided_reason": "Stub client: no counter-position was scripted.",
    }
)


def _canned_counter_position_generate_response() -> str:
    """The canned response for a counter-position-GENERATION call (identified
    by `pass_name=COUNTER_POSITION_GENERATE_PASS_NAME`, issue #399): read
    fresh from `STUB_COUNTER_POSITION_GENERATE_RESPONSE_ENV_VAR` on every call
    so a test can script a specific §7.8 section end-to-end; unset/"" falls
    back to the conservative one-sided-disclosure default above."""
    override = os.environ.get(STUB_COUNTER_POSITION_GENERATE_RESPONSE_ENV_VAR, "")
    return override or _CANNED_COUNTER_POSITION_GENERATE_RESPONSE


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


_CANNED_INSTANT_DISMISSAL_RESPONSE = json.dumps({"verdict": "no_violation"})


def _canned_instant_dismissal_response() -> str:
    """The canned response for an instant-dismissal judge call (identified
    by `pass_name=INSTANT_DISMISSAL_PASS_NAME`, issue #491): a JSON array
    read fresh from `STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR`,
    indexed by the fresh per-process counter just advanced (mirrors
    `_canned_grounding_response` exactly -- one call per dismissal criterion
    judged, so a test scripts a verdict sequence across calls); unset/empty
    falls back to the conservative default `"no_violation"` -- a stub-driven
    run never invents a violation nobody scripted."""
    global _instant_dismissal_pass_call_count
    _instant_dismissal_pass_call_count += 1
    sequence_raw = os.environ.get(STUB_INSTANT_DISMISSAL_RESPONSE_SEQUENCE_ENV_VAR, "")
    if sequence_raw:
        sequence = json.loads(sequence_raw)
        if sequence:
            return sequence[(_instant_dismissal_pass_call_count - 1) % len(sequence)]
    return _CANNED_INSTANT_DISMISSAL_RESPONSE


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
    gets the chunk-shaped canned response, `pass_name == ARTIFACTS_PASS_NAME`
    gets the artifact-role-shaped canned response, `pass_name ==
    CONTENT_APPARATUS_PASS_NAME` gets the route-shaped canned response
    (issue #207), `pass_name == INTERROGATE_PASS_NAME` gets the
    interrogation-shaped canned response (or, if
    `AXIAL_STUB_INTERROGATE_RESPONSE`/`_SEQUENCE` is set to a non-empty
    value, that raw string/sequence verbatim -- issue #252/#264), `pass_name
    == PREMISE_MATCH_PASS_NAME` gets the correspondence-verdict-shaped canned
    response (issue #264), `pass_name == NOTE_INTERROGATE_PASS_NAME` gets the
    answer-record-shaped canned response (issue #419, a DIFFERENT pass from
    `INTERROGATE_PASS_NAME` above); anything else (the envelope pass,
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
    if pass_name == ARTIFACTS_PASS_NAME:
        _maybe_fail_artifact_call()
        return _canned_artifact_response()
    if pass_name == CONTENT_APPARATUS_PASS_NAME:
        return _canned_content_apparatus_response()
    if pass_name == HOLDINGS_PASS_NAME:
        return _canned_holdings_response()
    if pass_name == INTERROGATE_PASS_NAME:
        return _canned_interrogate_response()
    if pass_name == NOTE_INTERROGATE_PASS_NAME:
        return _canned_note_interrogate_response()
    if pass_name == SYNTHESIZE_PASS_NAME:
        return _canned_synthesize_response()
    if pass_name == ATTRIBUTION_PASS_NAME:
        return _canned_attribution_response()
    if pass_name == COUNTER_POSITION_PASS_NAME:
        return _canned_counter_position_response()
    if pass_name == COUNTER_POSITION_GENERATE_PASS_NAME:
        return _canned_counter_position_generate_response()
    if pass_name == GROUNDING_PASS_NAME:
        return _canned_grounding_response()
    if pass_name == CALIBRATION_PASS_NAME:
        return _canned_calibration_response()
    if pass_name == INSTANT_DISMISSAL_PASS_NAME:
        return _canned_instant_dismissal_response()
    if pass_name == PREMISE_MATCH_PASS_NAME:
        return _canned_premise_match_response()
    if pass_name == RECONCILE_PASS_NAME:
        # No default of its own (see STUB_RECONCILE_RESPONSE_ENV_VAR): a merge
        # answer can only name surface forms the prompt carried, so an
        # unscripted stub run merges nothing rather than inventing merges.
        return os.environ.get(STUB_RECONCILE_RESPONSE_ENV_VAR, "") or json.dumps({"nodes": []})
    if pass_name == GATHER_PASS_NAME:
        return os.environ.get(STUB_GATHER_RESPONSE_ENV_VAR, "") or json.dumps(
            {"disagreement": "stub disagreement", "names": []}
        )
    # Matched by PREFIX, not equality: each of the panel's N reviewers routes
    # under its own `panel_review.<n>` pass name (issue #385) so a real run
    # can put them on different models through `model_by_pass`.
    if pass_name and pass_name.startswith(PANEL_REVIEW_PASS_NAME):
        return _canned_panel_review_response()
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
        # Issue #363: mirrors `StubLLMClient._usage_by_pass` exactly (same
        # fixed `_STUB_USAGE_PER_CALL`, since `record`'s completion
        # responses are indistinguishable from `stub`'s, module docstring).
        self._usage_by_pass: dict[str | None, dict[str, int]] = {}

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
            _accumulate_usage(self._usage_by_pass, pass_name, _STUB_USAGE_PER_CALL)
            return _canned_response_for(pass_name)

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """Mirrors `StubLLMClient.model_for_pass` exactly -- same fixed id
        (subject to the same `STUB_MODEL_BY_PASS_ENV_VAR` override), since
        this client's completion responses are also indistinguishable from
        the stub's (module docstring)."""
        return _model_for_pass_from_stub_mapping(pass_name)

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        """Mirrors `StubLLMClient.usage_for_pass` exactly (issue #363)."""
        return self._usage_by_pass.get(pass_name)

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
            _accumulate_usage(self._usage_by_pass, pass_name, _STUB_USAGE_PER_CALL)
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

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        """Always `None` (issue #363), never raising -- this client never
        completes, so it never has real usage to report."""
        return None


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


class StubInjectedArtifactFailureError(LLMError):
    """Raised by the shared stub/record canned-response dispatch when the
    `AXIAL_STUB_ARTIFACT_FAIL_AT` seam fires on the Nth artifacts-pass call
    (issue #98).

    A subclass of `LLMError` (never a bare exception) precisely so it
    propagates like a real transport-level failure: unchanged through
    `axial.model_json.complete_json` and caught by
    `axial.artifacts.run_artifacts`'s `except (LLMError, httpx.HTTPError)` ->
    `LLMFailedError` -> the CLI's typed-error/non-zero-exit path -- i.e.
    exactly today's mid-artifacts-pass failure contract, not a new branch."""


def _maybe_fail_artifact_call() -> None:
    """Advance the per-process artifacts-pass call counter and, when
    `AXIAL_STUB_ARTIFACT_FAIL_AT` names a positive integer equal to the new
    count, raise `StubInjectedArtifactFailureError` (issue #98's mid-
    artifacts fault seam).

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

# HTTP connection-pool size. httpx's own defaults are 100 concurrent
# connections but only 20 KEPT ALIVE, which is wrong for how every concurrent
# pass here uses this client: one shared client, many small calls in flight
# at once. Above 20 workers the surplus connections are torn down and TLS
# re-handshaked on every call -- silently paying a round trip per request on
# exactly the passes that share one client to avoid that. Measured on the
# 2026-07-28 name-merge pass, which runs 36 workers by default request and
# has a ceiling near 96.
#
# ONE number, not a tuned pair: keep-alive is set equal to the connection
# cap, so every connection the pool opens stays warm. 128 is a ceiling above
# any worker count this codebase asks for, not a tuning parameter -- an idle
# slot costs nothing, so there is no trade-off to tune against.
_POOL_CONNECTIONS = 128
_POOL_LIMITS = httpx.Limits(
    max_connections=_POOL_CONNECTIONS,
    max_keepalive_connections=_POOL_CONNECTIONS,
)


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


def _log_call_request(
    pass_name: str | None,
    model: str,
    prompt: str,
    attempt: int,
    *,
    run_id: str | None = None,
) -> None:
    """Emit one unconditional stderr line right before `OpenRouterClient`
    issues a real outbound HTTP request (deeper visibility than PR #372's
    stage-level lines, needed to sense a hung/slow call in real time during
    a long benchmark sweep, #368/#369). Carries the pass name, the resolved
    model for that pass, and the prompt length in characters -- never the
    prompt text itself (DEC-23 forbids logging source-bearing content). The
    attempt number is included only past the first attempt: `_log_retry`
    already logs WHY a later attempt happens, right after this call's own
    outcome is known; this line is just WHEN the raw call goes out, on
    every attempt, retried or not.

    `run_id` (a sweep draw's `set_run_id`, `OpenRouterClient.__init__`'s
    docstring) is appended only when given, so every pre-existing caller
    that never sets it keeps logging the exact same line as before."""
    attempt_suffix = f" attempt={attempt}/{_MAX_ATTEMPTS}" if attempt > 1 else ""
    run_id_suffix = f" run_id={run_id}" if run_id is not None else ""
    print(
        f"llm_call_request pass={pass_name} model={model}{attempt_suffix} "
        f"prompt_chars={len(prompt)}{run_id_suffix}",
        file=sys.stderr,
    )


def _log_call_response(
    pass_name: str | None,
    model: str,
    *,
    elapsed_seconds: float,
    status_code: int | None = None,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
    run_id: str | None = None,
) -> None:
    """Emit one unconditional stderr line right after `_log_call_request`'s
    matching call returns -- the raw call's own outcome, regardless of
    whether `complete()`/`complete_with_tools()` goes on to retry it (that
    decision is `_log_retry`'s job, logged separately). `error` (an
    exception class name or `"deadline_exceeded"`) is given instead of
    `status_code` when the attempt raised or timed out before any HTTP
    response came back. `finish_reason`/`usage` are best-effort: supplied
    only when the response body parsed as JSON with a `choices`/`usage`
    shape, since a non-2xx or malformed body still deserves a response line
    (status + elapsed) without one. `run_id`, same rule as
    `_log_call_request`'s own: appended only when given."""
    run_id_suffix = f" run_id={run_id}" if run_id is not None else ""
    if error is not None:
        print(
            f"llm_call_response pass={pass_name} model={model} outcome=error "
            f"error={error} elapsed={elapsed_seconds:.2f}s{run_id_suffix}",
            file=sys.stderr,
        )
        return
    line = (
        f"llm_call_response pass={pass_name} model={model} outcome=received "
        f"status={status_code} elapsed={elapsed_seconds:.2f}s"
    )
    if finish_reason is not None:
        line += f" finish_reason={finish_reason}"
    if usage:
        line += (
            f" prompt_tokens={usage.get('prompt_tokens')}"
            f" completion_tokens={usage.get('completion_tokens')}"
            f" total_tokens={usage.get('total_tokens')}"
        )
    line += run_id_suffix
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
        unresolved_model_passes: dict[str, str] | None = None,
        temperature_by_pass: dict[str, float] | None = None,
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
        # Issue #419: passes whose configured tier names no key in this
        # operator's secrets.toml, mapped to the reason. A pass listed here
        # raises `LLMConfigError` when IT is called (`model_for_pass`) --
        # never at construction, which would take every other pass down with
        # it (see `_resolve_model_by_pass`). Empty for every caller that does
        # not supply it.
        self._unresolved_model_passes = dict(unresolved_model_passes or {})
        # Per-pass sampling temperature (§7.9, issue #416): the third per-pass
        # block, resolved from `config/pipeline.yaml` exactly like the two
        # above. Defaults to `DEFAULT_TEMPERATURE_BY_PASS` (empty), so every
        # caller/test that builds `OpenRouterClient` without it -- and every
        # pass not named in config -- keeps sending no `temperature` field at
        # all, which is what every request sent before this issue.
        self._temperature_by_pass = (
            dict(DEFAULT_TEMPERATURE_BY_PASS)
            if temperature_by_pass is None
            else dict(temperature_by_pass)
        )
        # Issue #363: per-pass accumulated token usage, folded in by
        # `_accumulate_usage` from the real `usage` object every OpenRouter
        # response carries (see `.complete()`/`.complete_with_tools()`).
        self._usage_by_pass: dict[str | None, dict[str, int]] = {}
        # Follow-up to #362's benchmark sweep: which brief/run this client
        # instance's calls belong to, carried on every `llm_call_request`/
        # `llm_call_response` line (`_log_call_request`/`_log_call_response`)
        # so per-call API time can be attributed back to a brief, not just a
        # pass. `None` by default (every pre-existing caller/test that builds
        # `OpenRouterClient` without it keeps logging exactly as before -- no
        # `run_id=` field at all, see those functions' docstrings). Set via
        # `set_run_id` rather than the constructor because the one real
        # caller that has this identity to give (`axial.brief.sweep`,
        # `client_factory=get_client` builds a FRESH client per draw) only
        # knows the draw's brief_stem/index AFTER the client already exists.
        self._run_id: str | None = None
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=_REQUEST_TIMEOUT,
            limits=_POOL_LIMITS,
        )

    def set_run_id(self, run_id: str | None) -> None:
        """Bind this client instance's remaining calls to `run_id` (e.g.
        `"<brief_stem>:draw<n>"`) -- see `self._run_id`'s docstring above."""
        self._run_id = run_id

    def model_for_pass(self, pass_name: str | None = None) -> str:
        """The model this client targets for `pass_name` (issue #270 slice
        02): `self._model_by_pass`'s per-pass override (DEC-26) when
        `pass_name` is named there, else this client's own default
        `self._model`. This is the SAME resolution `_post_with_deadline`
        itself applies to an ordinary (non-`model`-overridden) request --
        kept here as the single source of truth so the two can never drift,
        and exposed so a caller can learn which model a pass would use
        without making a completion call.

        A pass whose configured tier could not be resolved against this
        operator's secrets.toml raises `LLMConfigError` here (issue #419),
        carrying the same message tier resolution itself produced -- so the
        misconfiguration is still loud and still never falls back silently
        to a cheaper model, but it takes down only the pass that is actually
        misconfigured."""
        unresolved = self._unresolved_model_passes.get(pass_name)
        if unresolved is not None:
            raise LLMConfigError(unresolved)
        return self._model_by_pass.get(pass_name, self._model)

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        """The token usage accumulated so far for `pass_name` (issue #363):
        `self._usage_by_pass`'s running total, folded in by
        `_accumulate_usage` from every response's real `usage` object
        (`.complete()`, `.complete_with_tools()`, and the content_filter
        fallback reroute all feed the same accumulator). `None` when no
        response tagged with `pass_name` has carried a `usage` object yet."""
        return self._usage_by_pass.get(pass_name)

    def _post_with_deadline(
        self,
        prompt: str,
        model: str | None = None,
        pass_name: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        attempt: int = 1,
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

        `pass_name` (issue #416, §7.9) also selects this call's sampling
        temperature from `self._temperature_by_pass`. A pass named there sends
        a `temperature` field; every other pass sends none at all, exactly as
        before that block existed.

        `tools` (issue #253 slice 01) is a purely additive payload field: it
        is included only when the caller passes a non-`None` value
        (`complete_with_tools`), so an ordinary `complete()` call's payload
        is byte-for-byte unchanged from before this parameter existed.

        `attempt` (real-time per-call logging, #368/#369 benchmark-sweep
        visibility) is purely for `_log_call_request`'s log line -- it never
        affects retry behavior, which stays entirely in `complete()`'s/
        `complete_with_tools()`'s own loops. This is the single choke point
        every real request/response passes through, so it is also the
        single place that logs one line before the request goes out and one
        line when its outcome (success, HTTP error, or timeout) is known --
        never duplicated in `complete()`, `complete_with_tools()`, or
        `_reroute_content_filter()`.
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
        # Issue #416, §7.9: purely additive, exactly like `tools` above -- a
        # pass with no configured temperature sends no `temperature` field, so
        # its body is unchanged and OpenRouter keeps applying the model's own
        # default. Only a pass named in `llm.temperature_by_pass` (today: the
        # name-merge pass, at 1) carries one.
        temperature = self._temperature_by_pass.get(pass_name)
        if temperature is not None:
            payload["temperature"] = temperature

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

        _log_call_request(pass_name, target_model, prompt, attempt, run_id=self._run_id)
        call_started = time.monotonic()
        watchdog = threading.Thread(target=_run, daemon=True)
        watchdog.start()
        if not done.wait(timeout=self._request_deadline_seconds):
            _log_call_response(
                pass_name,
                target_model,
                elapsed_seconds=time.monotonic() - call_started,
                error="deadline_exceeded",
                run_id=self._run_id,
            )
            raise _RequestDeadlineExceeded(
                f"attempt exceeded the {self._request_deadline_seconds}s wall-clock "
                "request deadline (issue #108)"
            )
        elapsed_seconds = time.monotonic() - call_started
        if "error" in outcome:
            _log_call_response(
                pass_name,
                target_model,
                elapsed_seconds=elapsed_seconds,
                error=type(outcome["error"]).__name__,
                run_id=self._run_id,
            )
            raise outcome["error"]
        response = outcome["response"]
        # Best-effort only: a non-2xx or malformed body still gets a
        # response line (status + elapsed) without finish_reason/usage --
        # `complete()`/`complete_with_tools()` are the real parsers and
        # error handlers, this is purely observational (issue #368/#369).
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None
        try:
            data = response.json()
            choices = data.get("choices") or []
            if choices:
                finish_reason = choices[0].get("finish_reason")
            usage = data.get("usage")
        except (json.JSONDecodeError, ValueError, AttributeError):
            pass
        _log_call_response(
            pass_name,
            target_model,
            elapsed_seconds=elapsed_seconds,
            status_code=response.status_code,
            finish_reason=finish_reason,
            usage=usage,
            run_id=self._run_id,
        )
        return response

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == _MAX_ATTEMPTS
            try:
                response = self._post_with_deadline(prompt, pass_name=pass_name, attempt=attempt)
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
            # Issue #363: fold in this attempt's real token usage regardless
            # of whether it is ultimately retried -- a retried attempt still
            # consumed (and was billed for) real tokens, so undercounting it
            # would understate the run's true dollar cost.
            _accumulate_usage(self._usage_by_pass, pass_name, data.get("usage"))
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

        Shares `complete()`'s retry policy for every transient class:
        transport errors, 429/5xx, and the wall-clock deadline retry exactly
        like `complete()` does -- and so does a turn with no `tool_calls`
        whose `finish_reason` is a genuine transient/truncated fault
        (`"length"`, `"error"`, or any other non-stop value besides
        `content_filter`): same same-model retry, same
        `_log_retry`/backoff schedule, and only an `OpenRouterError` naming
        the fault on the last attempt. This was found in production
        (`data/logs/2026-07-23-sim-brief-batch/summary.md`, run `P4-01`): a
        real brief run died on a single `finish_reason='error'` occurrence
        mid-retrieval-loop, an outcome `complete()`'s own retry logic would
        have recovered from -- there is no principled reason the
        tool-calling path should treat that class of fault differently.

        The one deliberate exception is `content_filter`: there is still no
        fallback reroute here -- no acceptance test drives this path against
        anything but the scripted `stub`/`record` provider (this feature's
        own explicit non-goal: "Any live-LLM test"), so adding untested
        moderation-reroute plumbing here would be speculative robustness,
        not a proven need. A moderation decision does not change on retry
        either (matching `complete()`'s own handling), so a `content_filter`
        turn with no `tool_calls` raises `ContentRefusedError` immediately,
        on the first attempt, with no retry at all.

        A response with no `tool_calls` is the clean "no more tool calls"
        end ONLY when `finish_reason` is a genuine clean stop (`"stop"` or
        absent/`None`).
        """
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            is_last_attempt = attempt == _MAX_ATTEMPTS
            try:
                response = self._post_with_deadline(
                    prompt, pass_name=pass_name, tools=tools, attempt=attempt
                )
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
            # Issue #363: mirrors `complete()`'s own accumulation -- every
            # real attempt's tokens are billed, retried or not.
            _accumulate_usage(self._usage_by_pass, pass_name, data.get("usage"))
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
                # Any other non-stop finish_reason ("length", "error", etc.)
                # with no tool_calls is a transient/truncated provider fault,
                # not a refusal -- retry same model exactly like `complete()`'s
                # is_truncated/is_transient_fault branch (see
                # data/logs/2026-07-23-sim-brief-batch/summary.md).
                if is_last_attempt:
                    raise OpenRouterError(
                        "complete_with_tools: model turn ended with "
                        f"finish_reason={finish_reason!r} and issued no tool call "
                        "(issue #253 slice 01 review finding)"
                    )
                _log_retry(pass_name, attempt, str(finish_reason))
                _sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
                continue

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
        # Issue #363: real tokens spent on the fallback model, attributed to
        # `pass_name` like any other call for it. Note this folds fallback
        # usage into the SAME per-pass bucket the primary model's calls use,
        # so a pass's accumulated tokens are priced at its primary model's
        # rate even for the rare reroute -- content_filter refusals are a
        # measured <1% event (docs/postmortem/gold-run-2026-07), so a
        # per-(pass, model) cost split is not worth the added bookkeeping.
        _accumulate_usage(self._usage_by_pass, pass_name, data.get("usage"))
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
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
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
    PRODUCTION_INTERROGATE_TIER: "production_interrogate",
    PRODUCTION_BRIEF_INTERROGATE_TIER: "production_brief_interrogate",
    PRODUCTION_RETRIEVE_TIER: "production_retrieve",
    PRODUCTION_COUNTER_POSITION_TIER: "production_counter_position",
    PRODUCTION_PAPER_PLAN_TIER: "production_paper_plan",
    PRODUCTION_PAPER_DRAFT_TIER: "production_paper_draft",
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


def _resolve_temperature_by_pass(llm_config: dict[str, Any]) -> dict[str, float]:
    """Per-pass sampling temperature (§7.9, issue #416): mirrors
    `_resolve_reasoning_by_pass` exactly -- `config/pipeline.yaml`'s
    `llm.temperature_by_pass` block is the carried-per-pass source of truth,
    so its entries OVERRIDE `DEFAULT_TEMPERATURE_BY_PASS` (empty). An absent
    block or absent file leaves every pass sending no `temperature` field,
    which is what every request sent before this block existed."""
    merged = dict(DEFAULT_TEMPERATURE_BY_PASS)
    configured = llm_config.get("temperature_by_pass") or {}
    merged.update({name: float(value) for name, value in configured.items()})
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


def _resolve_model_by_pass(
    secrets: dict[str, Any], llm_config: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
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

    Returns `(resolved, unresolved)`. A named tier with no secrets.toml key
    for it stays a misconfiguration -- never a silent fallback to the free
    building model -- but it is reported as `unresolved[pass_name] = reason`
    rather than raising here (issue #419). Raising during resolution made
    ONE pass's missing tier key fatal for EVERY pass: `config/pipeline.yaml`
    is shared, so adding a new tiered pass (`note_interrogate` ->
    `production_interrogate`) would break `axial envelope`, `axial brief`
    and everything else until each operator's own gitignored secrets.toml
    gained the key. `OpenRouterClient.model_for_pass` raises the same
    `LLMConfigError`, unchanged, when the pass that actually needs the
    missing tier is called -- loud, with the same message, and scoped to the
    pass that is misconfigured."""
    configured = llm_config.get("model_by_pass") or dict(DEFAULT_MODEL_BY_PASS)
    resolved: dict[str, str] = {}
    unresolved: dict[str, str] = {}
    for pass_name, tier in configured.items():
        try:
            resolved[pass_name] = _resolve_model_for_tier(secrets, llm_config, tier)
        except LLMConfigError as exc:
            unresolved[pass_name] = f"pass {pass_name!r}: {exc}"
    return resolved, unresolved


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
    model_by_pass, unresolved_model_passes = _resolve_model_by_pass(secrets, llm_config)
    temperature_by_pass = _resolve_temperature_by_pass(llm_config)
    return OpenRouterClient(
        api_key=api_key,
        model=model,
        base_url=base_url,
        content_fallback_model=content_fallback_model,
        reasoning_by_pass=reasoning_by_pass,
        model_by_pass=model_by_pass,
        unresolved_model_passes=unresolved_model_passes,
        temperature_by_pass=temperature_by_pass,
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
