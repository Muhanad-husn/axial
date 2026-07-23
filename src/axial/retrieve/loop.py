"""The stage-3 tool-loop skeleton: drive an `LLMClient` through the
validating dispatcher over the vault query API, appending one §7.6
trajectory entry per call (specs/PHASE-B.md §7.5/§7.6, issue #253 slice
01).

Retrieval PLANNING (deciding what to call from the interrogation result and
the case anchor, re-querying on a thin result) is out of scope here (slice
02); `prompt` is supplied verbatim by the caller and only grows with a
plain-text tool-result summary after each step, never re-planned. The model
is expected to be scripted in every acceptance test for this slice -- see
`axial.llm.StubLLMClient.complete_with_tools` / `AXIAL_STUB_TOOL_CALLS`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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


def _resolve_step_budget(config_path: Path) -> int:
    if not config_path.is_file():
        return DEFAULT_STEP_BUDGET
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle) or {}
    retrieve_config = document.get("retrieve") or {}
    return int(retrieve_config.get("step_budget", DEFAULT_STEP_BUDGET))


def run_retrieval_loop(
    client: LLMClient,
    prompt: str,
    *,
    vault_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    step_budget: int | None = None,
) -> list[dict[str, Any]]:
    """Run the tool loop and return the §7.6 trajectory log: one
    `{step, tool, args, result_ids, result_count}` entry per tool call, in
    call order, `step` 1-indexed with no gaps -- including a step whose
    dispatch failed validation, which still consumes a step and still gets
    an entry (`result_ids: [], result_count: 0`).

    Halts cleanly, never raising, in either of two ways:
    - the model's turn carries no tool call (`complete_with_tools` returns
      `None`) -- a clean end with however many entries were logged so far;
    - `step_budget` calls have been made -- a clean bounded return, exactly
      `step_budget` entries, per §4's bounded-step-budget requirement.

    `step_budget`, when not given explicitly, is read from
    `config/pipeline.yaml`'s `retrieve.step_budget` key (a stated tunable,
    never hardcoded at the call site).
    """
    if step_budget is None:
        step_budget = _resolve_step_budget(config_path)

    tools = tool_specs_for_provider()
    trajectory: list[dict[str, Any]] = []

    for step in range(1, step_budget + 1):
        requested = client.complete_with_tools(prompt, tools, pass_name=RETRIEVE_PASS_NAME)
        if requested is None:
            break

        tool_name = requested.get("tool")
        args = requested.get("args") or {}
        result = dispatch(tool_name, args, vault_dir=vault_dir, envelopes_dir=envelopes_dir)

        trajectory.append(
            {
                "step": step,
                "tool": tool_name,
                "args": args,
                "result_ids": result.ids,
                "result_count": result.count,
            }
        )

        # The next turn's prompt carries this step's outcome (its error, if
        # dispatch rejected it, else its returned ids) so a real provider's
        # model can see what happened -- the scripted client ignores prompt
        # content entirely, per this slice's own scope (nothing here PLANS
        # off of it).
        tool_feedback = result.error if result.error is not None else result.ids
        prompt = f"{prompt}\n\n[step {step} result for {tool_name!r}: {tool_feedback}]"

    return trajectory
