"""The stage-3 tool loop: drive an `LLMClient` through the validating
dispatcher over the vault query API, appending one §7.6 trajectory entry per
call (specs/PHASE-B.md §7.5/§7.6, issue #253 slice 01), plus the slice-02
planning layer above it (issue #254, §4/§7.2): `run_planned_retrieval`
composes the step-1 prompt from the brief's case anchor and the §7.2
interrogation result, short-circuits on a `refuse` disposition, and
assembles the deduplicated evidence set once the loop halts.

`run_retrieval_loop` itself stays exactly the slice-01 executor it always
was: `prompt` is supplied verbatim by the caller and only grows with a
plain-text tool-result summary after each step (flagged THIN, carrying its
`result_count`, when that count is below `thin_result_floor` -- new in
slice 02 -- so the model can decide whether to broaden its next query; the
decision itself is the model's, never forced by this loop). The model is
expected to be scripted in every acceptance test for this slice -- see
`axial.llm.StubLLMClient.complete_with_tools` / `AXIAL_STUB_TOOL_CALLS`.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult
from axial.llm import RETRIEVE_PASS_NAME, LLMClient
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.retrieve.dispatcher import dispatch
from axial.retrieve.tools import tool_specs_for_provider

# The stated tunable's code-level fallback (§4 "a bounded step budget, a
# stated tunable") -- used only when `config/pipeline.yaml` (or its
# `retrieve.step_budget` key) is absent; the file is the actual carried
# source of truth, mirroring every other per-pass tunable in this codebase
# (e.g. `axial.llm.DEFAULT_REASONING_BY_PASS`).
DEFAULT_STEP_BUDGET = 10

# The re-query-on-thin threshold's code-level fallback (§4/§7.6, issue
# #254) -- mirrors DEFAULT_STEP_BUDGET's own fallback convention exactly,
# used only when `config/pipeline.yaml` (or its `retrieve.thin_result_floor`
# key) is absent. 3 is a stated starting value; tuning it against the dev
# briefs is explicitly out of this slice's scope (the plan's own "out of
# scope" list).
DEFAULT_THIN_RESULT_FLOOR = 3


def _resolve_step_budget(config_path: Path) -> int:
    if not config_path.is_file():
        return DEFAULT_STEP_BUDGET
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    retrieve_config = document.get("retrieve") or {}
    return int(retrieve_config.get("step_budget", DEFAULT_STEP_BUDGET))


def _resolve_thin_result_floor(config_path: Path) -> int:
    if not config_path.is_file():
        return DEFAULT_THIN_RESULT_FLOOR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    retrieve_config = document.get("retrieve") or {}
    return int(retrieve_config.get("thin_result_floor", DEFAULT_THIN_RESULT_FLOOR))


def is_thin_result(result_count: int, floor: int) -> bool:
    """The §4 thin-result predicate: a `result_count` below `floor` is
    thin; at or above it is not. Pure and total -- the loop uses this to
    decide what feedback to hand the model, never to force a re-query
    itself (that decision stays the model's, per the plan's own
    "a non-thin result does not force a re-query" rule)."""
    return result_count < floor


def run_retrieval_loop(
    client: LLMClient,
    prompt: str,
    *,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
) -> list[dict[str, Any]]:
    """Run the tool loop and return the §7.6 trajectory log: one
    `{step, tool, args, result_ids, result_count}` entry per tool call, in
    call order, `step` 1-indexed with no gaps -- including a step whose
    dispatch failed validation, which still consumes a step and still gets
    an entry (`result_ids: [], result_count: 0`).

    Halts cleanly -- without raising -- in either of two ways:
    - the model's turn carries no tool call AND ended with a genuine clean
      stop (`complete_with_tools` returns `None`) -- a clean end with
      however many entries were logged so far;
    - `step_budget` calls have been made -- a clean bounded return, exactly
      `step_budget` entries, per §4's bounded-step-budget requirement.

    A DISPATCH failure (unknown tool, malformed args) is caught by the
    dispatcher and recorded as a trajectory entry with an empty result --
    the loop always continues past it. A MODEL-CALL failure
    (`complete_with_tools` raising an `axial.llm.LLMError` because the
    provider turn was refused/truncated/faulted with no tool call issued)
    is intentionally left UNCAUGHT here: a broken turn must surface as a
    real failure, never be silently folded into a clean short trajectory
    (§7.6's whole audit purpose is telling a sound retrieval path apart
    from a broken one).

    `step_budget`/`thin_result_floor`, when not given explicitly, are read
    from `config/pipeline.yaml`'s `retrieve.step_budget`/
    `retrieve.thin_result_floor` keys (stated tunables, never hardcoded at
    the call site).
    """
    if step_budget is None:
        step_budget = _resolve_step_budget(config_path)
    if thin_result_floor is None:
        thin_result_floor = _resolve_thin_result_floor(config_path)

    tools = tool_specs_for_provider()
    trajectory: list[dict[str, Any]] = []

    for step in range(1, step_budget + 1):
        print(f"retrieve: turn {step}/{step_budget} starting", file=sys.stderr)
        requested = client.complete_with_tools(prompt, tools, pass_name=RETRIEVE_PASS_NAME)
        if requested is None:
            break

        tool_name = requested.get("tool")
        args = requested.get("args") or {}
        result = dispatch(tool_name, args, vault_dir=vault_dir, envelopes_dir=envelopes_dir)
        print(
            f"retrieve: turn {step}/{step_budget} called {tool_name!r}, {result.count} result(s)",
            file=sys.stderr,
        )

        trajectory.append(
            {
                "step": step,
                "tool": tool_name,
                "args": args,
                "result_ids": result.ids,
                "result_count": result.count,
            }
        )

        # The next turn's prompt carries this step's outcome so a real
        # provider's model can see what happened -- the scripted client
        # ignores prompt content entirely for its OWN choice of next call,
        # but a `record`-provider test can still observe this text (issue
        # #254's own seam). A dispatch error is surfaced verbatim; a THIN
        # result (§4, `is_thin_result`) is flagged explicitly with its
        # `result_count` so the re-query decision is made on that signal,
        # never forced by this loop; a non-thin result carries just its ids,
        # same as slice 01.
        if result.error is not None:
            tool_feedback = result.error
        elif is_thin_result(result.count, thin_result_floor):
            tool_feedback = (
                f"result_ids={result.ids} result_count={result.count} "
                f"(THIN: below the floor of {thin_result_floor} -- consider "
                "a broadened re-query)"
            )
        else:
            tool_feedback = result.ids
        prompt = f"{prompt}\n\n[step {step} result for {tool_name!r}: {tool_feedback}]"

    return trajectory


def compose_retrieval_prompt(brief: Brief, interrogation_result: InterrogationResult) -> str:
    """The slice-02 planning prompt (§4/§7.2, issue #254): the step-1
    prompt is planned from the brief's case anchor and the interrogation
    result's `premises_found`/`bounds_applied`, never from the raw
    `request` alone. States case-as-anchor-not-fence (charter §3) and the
    re-query-on-thin behaviour explicitly, so a real provider's model reads
    the same instruction the scripted acceptance tests exercise."""
    premises_lines = (
        "\n".join(
            f"- {p.premise} (assessment: {p.assessment})"
            for p in interrogation_result.premises_found
        )
        or "(none found)"
    )
    bounds_lines = "\n".join(f"- {b}" for b in interrogation_result.bounds_applied) or "(none)"

    return f"""You are the stage-3 retrieval planner of an analysis engine (specs/PHASE-B.md §4/§7.5/§7.6). Plan retrieval over the vault-query tools for this case.

Case (the retrieval anchor -- it anchors retrieval, it does not fence it; corpus-grounded material about other polities that bears on this case is in scope): "{brief.case}"
Request: "{brief.request}"

Premises found during interrogation:
{premises_lines}

Bounds applied:
{bounds_lines}

Call the vault-query tools to retrieve corpus evidence. When a tool result is flagged THIN (its result_count is below the configured floor), decide whether to broaden your next query before concluding -- a non-thin result does not require a further call."""


@dataclass(frozen=True)
class RetrievalResult:
    """The slice-02 planning layer's own return shape (issue #254): the
    §7.6 trajectory log `run_retrieval_loop` already produces, plus the
    deduplicated `evidence_ids` assembled from it -- the "assembled
    evidence set" the plan's out-of-scope note hands off to stage 4
    (synthesis, P0-4) without ranking or case-scope filtering."""

    trajectory: list[dict[str, Any]]
    evidence_ids: list[str]


def assemble_evidence_ids(trajectory: list[dict[str, Any]]) -> list[str]:
    """Deduplicate chunk/artifact ids across every trajectory entry's
    `result_ids`, preserving first-seen order. The trajectory itself is
    untouched -- every call, including one that returned only ids already
    seen, still has its own entry (§7.6); this is a separate, later
    reduction over it, applying **no** case-scope filter (charter §3,
    P0-3): an id belonging to a chunk whose `polities_touched` excludes the
    case anchor is kept exactly like any other."""
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in trajectory:
        for chunk_id in entry.get("result_ids") or []:
            if chunk_id not in seen:
                seen.add(chunk_id)
                ordered.append(chunk_id)
    return ordered


def run_planned_retrieval(
    client: LLMClient,
    brief: Brief,
    interrogation_result: InterrogationResult,
    *,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
) -> RetrievalResult:
    """The slice-02 planning entry point (issue #254, §4/§5 stage 3): plans
    the step-1 prompt from `brief`/`interrogation_result`
    (`compose_retrieval_prompt`), runs the stage-3 tool loop
    (`run_retrieval_loop`, unchanged from slice 01), and assembles the
    deduplicated evidence set (`assemble_evidence_ids`).

    A `refuse` disposition (§7.2) short-circuits before any model or vault
    call is made: the run is already complete per §7.2's own rule, so the
    trajectory and evidence set are both empty rather than the loop
    spending a single step on a request the interrogation pre-pass already
    declined."""
    if interrogation_result.disposition == "refuse":
        return RetrievalResult(trajectory=[], evidence_ids=[])

    prompt = compose_retrieval_prompt(brief, interrogation_result)
    trajectory = run_retrieval_loop(
        client,
        prompt,
        vault_dir=vault_dir,
        envelopes_dir=envelopes_dir,
        config_path=config_path,
        step_budget=step_budget,
        thin_result_floor=thin_result_floor,
    )
    return RetrievalResult(trajectory=trajectory, evidence_ids=assemble_evidence_ids(trajectory))
