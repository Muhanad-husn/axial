"""The stage-3 tool loop: drive an `LLMClient` through the validating
dispatcher over the vault query API, appending one §7.6 trajectory entry per
call (specs/PHASE-B.md §7.5/§7.6, issue #253 slice 01), plus the planning
layer above it (issue #254, §4/§7.2, rewired onto the name layer by issue
#488): `run_planned_retrieval` composes the step-1 prompt from the brief's
case anchor and the §7.2 interrogation result, short-circuits on a `refuse`
disposition, and assembles the deduplicated evidence set once the loop
halts.

`run_retrieval_loop` itself stays exactly the slice-01 executor it always
was: `prompt` is supplied verbatim by the caller and only grows with a
plain-text tool-result summary after each step (flagged THIN, carrying its
`result_count`, when that count is below `thin_result_floor` -- new in
slice 02 -- so the model can decide whether to broaden its next query; the
decision itself is the model's, never forced by this loop). The model is
expected to be scripted in every acceptance test for this slice -- see
`axial.llm.StubLLMClient.complete_with_tools` / `AXIAL_STUB_TOOL_CALLS`.

`assemble_evidence_ids` (issue #488) only collects ids from tools whose
`ToolSpec.returns_chunk_ids` is `True` (`axial.retrieve.tools`): the name
layer's resolution/traversal tools (`find_names`, `name_neighbors`) return
canonical NAMES, not passages, and a name string has no place in the set
stage 4 treats as citable grounds. The §7.6 trajectory itself is untouched
-- every call still gets its own entry with its own `result_ids`, whatever
kind those ids are.

`coverage_count` is not in `TOOL_REGISTRY` at all (issue #505's own
follow-up: a real corpus run's own model chose to call it and flooded that
run's prompt past a million characters by returning all 49,674 canonicals
in one result), so
it never reaches this loop or `assemble_evidence_ids` either -- there is no
tool name for either to skip or collect.

`get_name`/`who_cites`/`who_argues_against`/`where_names_meet` are bounded at
their own `limit` (issue #505: `get_name` on a hub name page returned 962 ids
into one prompt, then got re-sent on every later turn). When a result was
truncated, the per-step tool-result text states the true pre-cap total beside
the capped ids -- `ToolResult.total`, carried the same way `ToolResult.error`
already is, never a sixth §7.6 field -- so the model can deliberately widen
`limit` instead of mistaking a window for the whole corpus.

`find_names`, `get_name` and `where_names_meet` each carry a second
beside-the-trajectory rider, `ToolResult.detail` (issue #517), appended to
the per-step tool-result text exactly like `total`. `find_names` states each
hit's `kind`, `member_count` and `tier` -- the fix for a model that cannot
tell an exact resolution from a weak embedding guess when all it sees is a
bare canonical string. `get_name`/`where_names_meet` state how many distinct
sources the returned members span (`"<N> notes across <M> sources"`): a live
corpus run showed a model told to intersect only a "large" name avoiding the
tool entirely by resolving narrow, one-book names instead, so `compose_
retrieval_prompt`'s step 4 now points at source diversity directly and
`detail` makes it checkable rather than inferred from a name's specificity.
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
from axial.retrieve.tools import TOOL_REGISTRY, tool_specs_for_provider

# The stated tunable's code-level fallback (§4 "a bounded step budget, a
# stated tunable") -- used only when `config/pipeline.yaml` (or its
# `retrieve.step_budget` key) is absent; the file is the actual carried
# source of truth, mirroring every other per-pass tunable in this codebase
# (e.g. `axial.llm.DEFAULT_REASONING_BY_PASS`).
#
# Raised 10 -> 20 by issue #488, and this is a PROVISIONAL headroom
# allowance, not a re-measured bound: the old 10 was tuned against a tool
# set where one `query_by_tag` call could return a large slice of the
# corpus, and the name-layer surface it replaced is narrower per call --
# resolving one name, reading one page, and following one traversal is
# already 3 steps, so a brief comparing two scholars can need 6-10 calls
# before any re-query. Re-proving the real bound happens on the smoke
# briefs, which slice 06 (issue #491) carries after #492 was folded into
# it; until then this number is stated, not asserted.
DEFAULT_STEP_BUDGET = 20

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
    names_dir: Path | None = None,
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

    `names_dir` (issue #488) is forwarded to the dispatcher exactly like
    `vault_dir`/`envelopes_dir`: an optional directory for the name-layer
    tools (`find_names`, `get_name`, `name_neighbors`, `who_cites`,
    `who_argues_against`), defaulting to `None` so a caller passing nothing
    resolves against the query API's own default.
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
        result = dispatch(
            tool_name,
            args,
            vault_dir=vault_dir,
            envelopes_dir=envelopes_dir,
            names_dir=names_dir,
        )
        capped = result.total is not None and result.total > result.count
        progress_suffix = f" ({result.count} of {result.total} total)" if capped else ""
        print(
            f"retrieve: turn {step}/{step_budget} called {tool_name!r}, "
            f"{result.count} result(s){progress_suffix}",
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
        # #254's own seam). A dispatch error is surfaced verbatim. Otherwise
        # up to two independent notes are appended, since a small caller-
        # chosen `limit` can be BOTH below `thin_result_floor` AND capped
        # below `result.total` at once: a THIN note (§4, `is_thin_result`)
        # flags a low `result_count` so the model considers a broadened
        # re-query, and a CAPPED note (issue #505) states the true total
        # beside the ids so the model can deliberately re-ask with a larger
        # `limit` instead of mistaking a window for the whole corpus. A
        # plain result with neither note carries just its ids, same as
        # slice 01.
        if result.error is not None:
            tool_feedback = result.error
        else:
            notes: list[str] = []
            if is_thin_result(result.count, thin_result_floor):
                notes.append(
                    f"THIN: below the floor of {thin_result_floor} -- consider a broadened re-query"
                )
            if capped:
                notes.append(
                    f"{result.count} of {result.total} total -- re-ask with a larger limit for more"
                )
            if notes:
                tool_feedback = (
                    f"result_ids={result.ids} result_count={result.count} ({'; '.join(notes)})"
                )
            else:
                tool_feedback = result.ids
            # `find_names`' own resolution detail (issue #517), the same
            # beside-the-trajectory ride `total` already gets: which tier
            # matched, each hit's kind and member_count, so the model can
            # tell an exact/alias hit from a weak embedding guess instead of
            # re-asking blind.
            if result.detail is not None:
                tool_feedback = f"{tool_feedback} detail: {result.detail}"
        prompt = f"{prompt}\n\n[step {step} result for {tool_name!r}: {tool_feedback}]"

    return trajectory


def compose_retrieval_prompt(brief: Brief, interrogation_result: InterrogationResult) -> str:
    """The planning prompt (§4/§7.2, issue #254; rewired onto the name layer
    by issue #488): the step-1 prompt is planned from the brief's case
    anchor and the interrogation result's `premises_found`/`bounds_applied`,
    never from the raw `request` alone. States case-as-anchor-not-fence
    (charter §3, P0-3) and the re-query-on-thin behaviour explicitly, so a
    real provider's model reads the same instruction the scripted
    acceptance tests exercise -- plus D4's Gather-hint rule (§7.5), stated
    plainly here because the loop is where a disagreement could otherwise
    slip into the evidence set. Step 4 (issue #517) tells the model to
    intersect the case anchor with a BROAD intellectual name, never a narrow
    one, because a live corpus run showed the first wording of this step
    (trigger on page size) fail: told to intersect only a "large" name, the
    model avoided the tool by resolving narrow, one-book names instead --
    `Syrian nationalism` (24 members) is 83.3% one source because only the
    book about Syrian nationalism uses that phrase."""
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

Retrieval is traversal of the name layer, not a conjunction of filters. A good plan:
1. Name the scholars, concepts and polities the brief is actually about, and resolve each one with find_names -- it is tiered (exact, alias, folded, embedding) and reports a genuine resolution failure as an empty result, never the nearest name to hand.
2. For each name that resolves, read who meets there with get_name: its member notes, each with author, year and one-sentence claim.
3. Follow what those notes say. who_argues_against and who_cites surface the author-stated opposition and citation edges those notes themselves carry -- real cross-book traversal, not a guess. name_neighbors surfaces names that co-occur with one you already have.
4. Narrowing the name feels like precision but produces a one-book answer: a name only one author uses returns only that author. Intersect the case anchor with a BROAD intellectual name the brief is about -- a concept, period, institution or scholar, never a narrow phrase -- using where_names_meet(canonical, other): that is where more than one book actually meets. Every result's detail now states how many sources it spans (e.g. "24 notes across 2 sources"); a result drawn from one source cannot support a comparison, so check that number instead of assuming it from how specific the name felt.

get_name may also return a disagreement section another model wrote while reading this corpus (Gather). That text is a POINTER, never evidence: read it only to decide where to look next, then follow that page's own member chunk_ids to the real notes and retrieve those. Nothing you cite may be a disagreement, a name page, or a name string itself -- only a chunk_id or artifact_id resolves as a real ground.

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
    P0-3): an id belonging to a chunk from a source about a different
    polity than the case anchor is kept exactly like any other.

    **Only chunk/artifact-valued entries contribute (issue #488).** A
    trajectory entry whose tool is not in `TOOL_REGISTRY` (which includes
    `coverage_count`, not registered at all as of issue #505 -- see
    `axial.retrieve.tools`'s module docstring), or whose
    `ToolSpec.returns_chunk_ids` is `False` (`find_names`, `name_neighbors`,
    `get_envelope`), is skipped here: those yield canonical names or a
    `source_id`, never a real passage, and stage 4's evidence set must only
    ever carry ids `get_chunk`/`get_artifact` can resolve."""
    seen: set[str] = set()
    ordered: list[str] = []
    for entry in trajectory:
        spec = TOOL_REGISTRY.get(entry.get("tool"))
        if spec is None or not spec.returns_chunk_ids:
            continue
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
    names_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    step_budget: int | None = None,
    thin_result_floor: int | None = None,
) -> RetrievalResult:
    """The planning entry point (issue #254, §4/§5 stage 3; rewired onto the
    name layer by issue #488): plans the step-1 prompt from
    `brief`/`interrogation_result` (`compose_retrieval_prompt`), runs the
    stage-3 tool loop (`run_retrieval_loop`), and assembles the
    deduplicated, chunk-valued evidence set (`assemble_evidence_ids`).

    `names_dir`, when given, is forwarded to every name-layer tool call the
    same way `vault_dir`/`envelopes_dir` already are; `None` (the default)
    resolves against the query API's own default directory.

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
        names_dir=names_dir,
        config_path=config_path,
        step_budget=step_budget,
        thin_result_floor=thin_result_floor,
    )
    return RetrievalResult(trajectory=trajectory, evidence_ids=assemble_evidence_ids(trajectory))
