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
kind those ids are. The deduplicated set it assembles is then ordered
source round-robin, not first-seen (issue #517 slice 2): a first-seen order
lets whichever tool the model happened to call first own the evidence set's
own char-budget prefix, which is exactly what let two single-source
`get_name` calls crowd out a later, genuinely cross-source
`where_names_meet` call on a live run. `get_name`'s own page order stays
untouched; only this later reduction reorders.

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

`evidence_set_composition` rides the same channel one level up (issue #542):
after every step, the prompt states what the run's own evidence set now holds
-- how many notes, across how many sources, and which. Replaying seven
persisted brief runs, the assembled prefix synthesis reads changes exactly
when a NEW SOURCE arrives (identical step for step in 6 of the 7), and the
loop could see none of that: it spent a model round trip per turn adding ids
to a set it had no view of. It is composition and nothing else -- never a
budget, a cap or a remaining allowance, because #505's finding is that a cap
the model can SEE gets widened on purpose, and `synthesis.
evidence_char_budget` is exactly such a cap.

`chunk_feedback_metadata` rides the same channel a third way (issue #545):
until now, a successful chunk-valued call's feedback was `result.ids` --
bare id strings, ~200 characters each after DEC-42, with nothing about what
any of them says. The model was choosing what to retrieve, and later which
notes matter most (`synthesis.evidence_char_budget`'s prefix keeps roughly
twenty of whatever the loop assembled), by string alone. `chunk_feedback_
metadata` reads each returned id's own note (`axial.query.reader.get_chunk`)
and renders `"<chunk_id> -- <author> (<year>): <claim>"`, applied uniformly
at the feedback site to every tool whose `ToolSpec.returns_chunk_ids` is
`True` -- `get_name`/`where_names_meet` already carry this for free
(`axial.query.names.NameMember`), but `who_cites`/`who_argues_against`
carry no author/year at all and `query_by_source`/`get_chunk` carry no
metadata whatsoever, so threading each tool's own already-parsed shape
through `ToolResult` would give the model RAGGED feedback -- rich for one
call, bare for the next. Reading the note directly makes every chunk-valued
tool's feedback the same shape; #541/#543's libyaml swap is what makes that
extra read affordable per id (timed in the PR body). Same discipline as
`evidence_set_composition`: states what a returned id's own note holds,
never a cap, a budget or a count of what more would fit, and an abstained
`claim` is marked, never shown as if it were an answer (issue #489).
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
from axial.query import reader
from axial.query.reader import MalformedChunkIdError, is_abstention, source_id_from_chunk_id
from axial.retrieve.dispatcher import dispatch
from axial.retrieve.tools import TOOL_REGISTRY, tool_specs_for_provider
from axial.yaml_loader import SAFE_LOADER

# The stated tunable's code-level fallback (§4 "a bounded step budget, a
# stated tunable") -- used only when `config/pipeline.yaml` (or its
# `retrieve.step_budget` key) is absent; the file is the actual carried
# source of truth, mirroring every other per-pass tunable in this codebase
# (e.g. `axial.llm.DEFAULT_REASONING_BY_PASS`). Kept numerically in sync
# with `config/pipeline.yaml`'s own `retrieve.step_budget` on purpose (a
# fallback that quietly disagreed with the shipped file would be worse than
# either number alone) -- see that key's own comment for the full
# provenance and re-cut history (10 -> 20 by issue #488, 20 -> 14 by issue
# #545).
DEFAULT_STEP_BUDGET = 14

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
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
    retrieve_config = document.get("retrieve") or {}
    return int(retrieve_config.get("step_budget", DEFAULT_STEP_BUDGET))


def _resolve_thin_result_floor(config_path: Path) -> int:
    if not config_path.is_file():
        return DEFAULT_THIN_RESULT_FLOOR
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
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
            # Per-id author/year/claim (issue #545), uniformly for every
            # chunk-valued tool -- see `chunk_feedback_metadata`'s own
            # docstring for why this reads the note directly rather than
            # threading each tool's own already-parsed shape through.
            spec = TOOL_REGISTRY.get(tool_name)
            if spec is not None and spec.returns_chunk_ids:
                metadata = chunk_feedback_metadata(result.ids, vault_dir)
                if metadata is not None:
                    tool_feedback = f"{tool_feedback} notes: {metadata}"
        # What the run has actually assembled so far (issue #542): the loop
        # was spending a model round trip per turn adding ids to a set it
        # could not see. Stated after EVERY step, including a failed one --
        # composition is a fact about the set, not about the call.
        prompt = (
            f"{prompt}\n\n[step {step} result for {tool_name!r}: {tool_feedback}]"
            f"\n[{evidence_set_composition(trajectory)}]"
        )

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


def _source_id_or_empty(chunk_id: str) -> str:
    """`source_id_from_chunk_id(chunk_id)`, or `""` when `chunk_id` does not
    parse -- the same fallback `axial.query.names.where_names_meet` groups
    its own round-robin by (a member whose id fails to parse groups under
    `""`, sorting first): one convention for "which source does this id
    belong to", not a second one invented here."""
    try:
        return source_id_from_chunk_id(chunk_id)
    except MalformedChunkIdError:
        return ""


def _round_robin_by_source(ids: list[str]) -> list[str]:
    """`ids`, grouped by `_source_id_or_empty`, the groups ordered by
    `source_id` ascending, each group's OWN ids kept in their existing
    relative order, then emitted one id per group in rotation until every
    group is exhausted -- the same rotation shape
    `axial.query.names.where_names_meet` already writes, kept as a separate,
    smaller helper rather than a shared one: that function additionally
    sorts each group by `chunk_id`, because a name page's member order is
    not itself meaningful evidence-order, while this reduction must instead
    PRESERVE each id's first-seen call order within its source (see
    `assemble_evidence_ids`) -- sharing the helper would have to bend one of
    the two rules, so it stays two small functions instead of one bent one."""
    groups: dict[str, list[str]] = {}
    for chunk_id in ids:
        groups.setdefault(_source_id_or_empty(chunk_id), []).append(chunk_id)

    group_keys = sorted(groups)
    rotated: list[str] = []
    round_index = 0
    while len(rotated) < len(ids):
        for key in group_keys:
            bucket = groups[key]
            if round_index < len(bucket):
                rotated.append(bucket[round_index])
        round_index += 1
    return rotated


def assemble_evidence_ids(trajectory: list[dict[str, Any]]) -> list[str]:
    """Deduplicate chunk/artifact ids across every trajectory entry's
    `result_ids`, preserving first-seen order, THEN reorder the deduplicated
    set source round-robin rather than leaving it first-seen (issue #517
    slice 2). The trajectory itself is untouched -- every call, including
    one that returned only ids already seen, still has its own entry (§7.6)
    in its own call order; this is a separate, later reduction over it,
    applying **no** case-scope filter (charter §3, P0-3): an id belonging to
    a chunk from a source about a different polity than the case anchor is
    kept exactly like any other.

    **Only chunk/artifact-valued entries contribute (issue #488).** A
    trajectory entry whose tool is not in `TOOL_REGISTRY` (which includes
    `coverage_count`, not registered at all as of issue #505 -- see
    `axial.retrieve.tools`'s module docstring), or whose
    `ToolSpec.returns_chunk_ids` is `False` (`find_names`, `name_neighbors`,
    `get_envelope`), is skipped here: those yield canonical names or a
    `source_id`, never a real passage, and stage 4's evidence set must only
    ever carry ids `get_chunk`/`get_artifact` can resolve.

    **Round-robin, not first-seen (issue #517 slice 2, `_round_robin_by_
    source`).** Measured on a live P3-01 run: the model's 5 `where_names_
    meet` calls assembled 137 notes across 12 sources, but it read two
    single-source `get_name` pages (24 members each, one book) at turns 6
    and 9, before its first intersection at turn 10 -- so a first-seen
    assembly put those 44 one-book notes at the head of the set, and the
    first 25 notes synthesis actually reads (the char-budget prefix) spanned
    3 sources, not 12. Ids are grouped by `source_id`, the groups ordered
    ascending, each group's own ids kept in their existing first-seen order,
    then emitted one id per group in rotation until every group is
    exhausted -- a total order over the deduplicated set. **`get_name`'s own
    page order (§7.5, [FIRM]) and the §7.6 trajectory are both untouched**:
    this reorders only the later, separate reduction over already-
    deduplicated ids, never the page a `get_name` call itself returns or the
    trajectory entries' own `result_ids`."""
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
    return _round_robin_by_source(ordered)


def evidence_set_composition(trajectory: list[dict[str, Any]]) -> str:
    """What the evidence set assembled so far HOLDS, in one sentence: how
    many notes, how many distinct sources, and which sources (issue #542).
    Computed mechanically off the trajectory the loop already has -- no
    model call, no extra vault read -- and appended to each turn's tool
    feedback exactly the way `ToolResult.total`/`.detail` already ride
    beside it.

    **Why sources.** Replaying seven persisted brief runs step by step, the
    assembled prefix synthesis actually reads changes exactly when a new
    SOURCE arrives -- identical step for step in 6 of the 7. Reaching
    another book is the loop's productive act; reaching another note in a
    book it already has is not. The loop could see neither, and spent a
    model round trip per turn adding ids to a set it had no view of.

    **This states composition and nothing else.** No budget, no cap, no
    maximum, no remaining allowance, no prefix boundary -- #505's finding is
    that a cap the model can SEE gets widened on purpose, and
    `synthesis.evidence_char_budget` is exactly such a cap. What the set
    holds is a fact about the corpus reached; what would still fit is a
    target to fill.

    A malformed id contributes to the note count (it is a real member of the
    set) but names no source, the same way `_round_robin_by_source` groups
    it under `""` rather than inventing a source for it."""
    ids = assemble_evidence_ids(trajectory)
    if not ids:
        return "your evidence set is still empty"
    sources = sorted({_source_id_or_empty(chunk_id) for chunk_id in ids} - {""})
    return (
        f"your evidence set holds {len(ids)} notes across {len(sources)} sources: "
        f"{', '.join(sources)}"
    )


def _render_note_claim(value: Any) -> str:
    """One note's raw `claim` answer, rendered for the loop's own tool
    feedback (issue #545): the D7 abstention marker (never shown as if it
    were an answer -- `is_abstention` applied before any answer field
    reaches the model, issue #489's own rule), a plain marker for a note
    with no claim recorded, the free-text claim verbatim otherwise.

    Mirrors `axial.materialize._render_claim`'s exact three-way rule, not
    imported: this module stays outside `axial.materialize`'s import graph,
    which pulls the whole interrogation and clustering stack in to define
    one four-line rendering rule -- the same trade `axial.query.reader.
    _default_envelopes_dir` already makes for `axial.envelope`."""
    if value is None:
        return "(no claim recorded)"
    if is_abstention(value):
        return "(not stated in the passage)"
    if isinstance(value, str):
        return value
    return str(value)


def _chunk_feedback_line(chunk_id: str, vault_dir: Path | None) -> str | None:
    """One id's own feedback line (issue #545): `"<chunk_id> -- <author>
    (<year>): <claim>"`, read straight off the prose note the id names --
    the same shape a name page's own member line already carries
    (`axial.materialize.render_name_page_body`), so a model reading this
    feedback and a founder reading a name page see the same rendering for
    the same note. `author`/`year` are read raw off `source_meta` and
    rendered exactly as held -- `None` included -- never guessed at or
    backfilled, mirroring `axial.query.names._split_member_line`'s own
    "honestly unknown rather than guessed at" rule.

    `None` when `chunk_id` does not resolve to a prose note at all -- an
    artifact id from `get_artifact` reaching this through the same uniform
    call site, or a stale/malformed id -- so the caller skips it rather than
    showing a lookup failure to the model; the bare id itself still reaches
    the model through `result_ids` regardless of whether this resolves."""
    try:
        note = reader.get_chunk(chunk_id, vault_dir=vault_dir)
    except reader.QueryError:
        return None
    source_meta = note.source_meta or {}
    author = source_meta.get("author")
    year = source_meta.get("date")
    return f"{chunk_id} — {author} ({year}): {_render_note_claim(note.claim)}"


def chunk_feedback_metadata(chunk_ids: list[str], vault_dir: Path | None) -> str | None:
    """Per-id feedback metadata for one step's own returned ids (issue
    #545): author, year and the one-sentence claim, one line per id that
    resolves to a prose note, joined `"; "`. `None` when no id in
    `chunk_ids` resolves to one (an all-artifact result, or an empty list).

    **Design pick, measured in the PR body: read the note, uniformly,
    rather than thread each tool's own already-parsed shape through
    `ToolResult`.** `get_name`/`where_names_meet` already return
    `axial.query.names.NameMember`, which carries author/year/claim for
    free; `who_cites`/`who_argues_against` carry no author/year at all
    (`CitationEdge`/`OppositionEdge`); `query_by_source`/`get_chunk` carry
    no metadata whatsoever. Threading each tool's own shape through
    `ToolResult` would give the model RAGGED feedback -- rich for one call,
    bare for the next, with no way to tell "this tool never carries it"
    from "this note has none". Reading the note directly
    (`axial.query.reader.get_chunk`) makes every chunk-valued tool's
    feedback the same shape, at a per-note cost #541/#543's libyaml swap
    made affordable to pay again here.

    Never a §7.6 trajectory field -- this rides beside the trajectory
    exactly the way `ToolResult.total`/`.detail` already do -- and never a
    cap, a budget or a count of what more would fit (issue #542's own rule,
    extended here): it states what EACH returned id's own note holds,
    nothing about the evidence set as a whole."""
    lines = [
        line
        for line in (_chunk_feedback_line(chunk_id, vault_dir) for chunk_id in chunk_ids)
        if line is not None
    ]
    return "; ".join(lines) if lines else None


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
