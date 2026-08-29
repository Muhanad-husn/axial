"""The consolidation pass (issue #830, positions-not-names slice 05): a
second model pass over one category's own arguments, asking what recurs
among them.

**Why it exists.** Under `--grouping category` a `claim` category is far
too large for one extraction call, so it is split into `claim x mechanism`
cells and read a cell at a time (issue #829). An argument that runs through
several cells of the same category is then named once per cell and nothing
puts those namings back together -- nothing, that is, except the embedding
merge, which folds by argument-sentence similarity. That would move wording
similarity out of the grouping step and into the merge and make it MORE
load-bearing than it was before the re-forming, which is the disqualifying
failure mode `docs/approach-positions-not-names.md` §6 names. This pass is
what closes it: the same judgment extraction makes, one level up, over
arguments instead of passages.

**It mirrors extraction's mechanics rather than inventing new ones.** Its
own prompt carries extraction's own grouping rules (merge on substance,
split where accounts genuinely conflict, never fuse contending positions
into one sentence); its listing is blind, no author, book or year, the same
rule `render_claims_blind` applies; its resume ledger is appended and
flushed the instant a call returns; and its fault isolation is
`extract_positions_for_slice`'s, exception set included -- an invented
handle is dropped and counted, an entry left with no real handles is
dropped, a failed call is recorded as `error` and never raised.

**One rule of extraction's is deliberately NOT carried over.** Extraction
tells the model that producing roughly as many arguments as passages means
the task was not done, because a wording bag's members were grouped
BECAUSE they resemble each other and most of them should share an argument.
A category is a weaker premise: passages share a kind of claim, not a
wording, and a category holding a dozen genuinely different arguments is an
ordinary outcome rather than a failure. Pressing for merges here would
manufacture the fusion §6 asks this pass to prevent.

**Two costs this pass does not pay.** A category whose raw positions all
came from ONE group has nothing to reunite -- there is no second naming of
anything -- and is passed through with no model call. And a slice's input
is capped at `EXTRACT_SLICE`, the same cap extraction reads a group under:
both listings are one sentence per line under a bare handle, so the number
of lines a single call can weigh is the same question, and reusing the
constant is what keeps a second, separately-tuned number out of this
module. Where a category needs more than one slice, its arguments are
ordered by GROUP in rotation (`group_spread`, the same shape as
`author_spread`) so every slice spans as many of the category's groups as
it can, and the manifest counts those categories (`categories_sliced`) --
namings that land in different slices of one category meet nothing, and
that residue is reported rather than assumed away.

**What survives a call.** Every raw position a surviving entry did not name
is passed through unchanged, with `consolidated_from: 1`. The alternative
-- dropping it, as extraction drops a passage no argument names -- would
discard already-paid extraction work, and a position is the material of the
map in a way a single passage is not.
"""

from __future__ import annotations

import collections
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx

from axial.argmap.build import EXTRACT_SLICE, WORKERS, MapError
from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.llm import LLMClient, LLMError
from axial.model_json import ModelJsonError, parse_model_json

# The pass name `config/pipeline.yaml`'s `llm.reasoning_by_pass` /
# `llm.model_by_pass` key off of, and what every consolidation call is
# tagged with for run-logging and cost accounting -- the same treatment
# `axial.argmap.build.PASS_NAME` gets for extraction.
PASS_NAME = "position_consolidate"

# Mirrors `config/pipeline.yaml`'s `llm.reasoning_by_pass.
# position_consolidate` entry -- recorded in `map.json` for the manifest's
# own sake (the LLMClient protocol exposes no getter for a pass's resolved
# reasoning setting); this constant does not itself control the call, config
# does, and the two must be kept in sync by hand. Same arrangement, and same
# reason, as `POSITION_EXTRACT_REASONING`.
POSITION_CONSOLIDATE_REASONING = "high"

CONSOLIDATION_READS_FILENAME = "consolidation_reads.jsonl"

# The separator `axial.argmap.grouping` builds a group label with
# (`<claim_category>::<mechanism_category>`, or `::(no mechanism)` for the
# claim-only fallback). A group's CATEGORY -- the level this pass
# consolidates at -- is the part before it.
GROUP_LABEL_SEPARATOR = "::"


class CorruptConsolidationLedgerError(MapError):
    """The consolidation-stage sibling of `CorruptReadsLedgerError`, raised
    for a non-torn-tail corrupt line in this pass's own resume ledger
    (`consolidation_reads.jsonl`)."""

    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(f"corrupt consolidation ledger at {path}:{line_no}: {cause}")


@dataclass(frozen=True)
class ConsolidateJob:
    """One consolidation call's worth of work: `members` raw positions, all
    from `category`, already group-spread and cut to at most
    `EXTRACT_SLICE`.

    `arguments_key` is this slice's content identity -- a hash over its own
    ordered argument sentences, exactly what the model is shown
    (`render_arguments_blind` renders nothing else). It is half of the
    resume key, alongside `category`, because this pass's input is the
    EXTRACTION pass's output: a re-asked or newly-seeded extraction read
    changes the arguments a category holds, and a ledger keyed by category
    and slice number alone would then hand back an answer to a question
    nobody asked."""

    category: str
    arguments_key: str
    members: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ConsolidationPlan:
    """What `build_consolidation_jobs` worked out from the extraction
    ledger: the calls to make, the raw positions that need no call at all
    (`passed_through`, every one of them from a category that spans a single
    group), and the counts the manifest reports about the split."""

    jobs: tuple[ConsolidateJob, ...]
    passed_through: tuple[dict[str, Any], ...]
    categories: int
    categories_passed_through: int
    categories_sliced: int


@dataclass(frozen=True)
class ConsolidationResult:
    """The stage's output: `positions` in exactly the shape
    `merge_positions` already consumes, plus `consolidated_from` and
    `category` on each, and the records that produced them."""

    positions: tuple[dict[str, Any], ...]
    records: tuple[dict[str, Any], ...]
    plan: ConsolidationPlan


def category_of(group_label: Any) -> str:
    """The category a group label belongs to: everything before
    `axial.argmap.grouping`'s own `::` separator, so `<claim>::<mechanism>`
    and the claim-only `<claim>::(no mechanism)` both consolidate at the
    claim category they share. A label with no separator is its own
    category -- this pass never has to decide what a malformed label means,
    it just consolidates at whatever whole label it was given."""
    return str(group_label).split(GROUP_LABEL_SEPARATOR, 1)[0]


def group_spread(members: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """`members` reordered one GROUP at a time in rotation, so any prefix --
    and so every slice `build_consolidation_jobs` cuts -- carries namings
    from as many of the category's groups as it can. `author_spread`'s own
    shape, applied one level up: there, the point is that a slice sees more
    than one book; here, that it sees more than one group, which is the only
    way a repeated naming can be spotted at all."""
    by_group: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for member in members:
        by_group[member["group"]].append(member)
    keys = sorted(by_group)
    out: list[dict[str, Any]] = []
    index = 0
    while len(out) < len(members):
        for key in keys:
            if index < len(by_group[key]):
                out.append(by_group[key][index])
        index += 1
    return out


def _arguments_key(members: Sequence[dict[str, Any]]) -> str:
    """sha256 (first 16 hex chars) over `members`' own argument sentences,
    in order -- the content identity of one consolidation slice, the same
    thing `_members_key` is for an extraction slice."""
    canonical = "\n".join(member["argument"] for member in members)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_consolidation_jobs(reads: Sequence[dict[str, Any]]) -> ConsolidationPlan:
    """Plan the pass from the extraction ledger `reads`.

    Every raw position is tagged with the group it was named in and the
    category that group belongs to. A category whose positions all came from
    one group is passed through with no model call -- there is no second
    naming of anything to reunite. Every other category is group-spread and
    cut into slices of at most `EXTRACT_SLICE`."""
    by_category: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for read in reads:
        category = category_of(read["bag"])
        for position in read["positions"]:
            by_category[category].append(
                {**position, "category": category, "group": str(read["bag"])}
            )

    jobs: list[ConsolidateJob] = []
    passed_through: list[dict[str, Any]] = []
    categories_passed_through = 0
    categories_sliced = 0
    for category in sorted(by_category):
        members = by_category[category]
        if len({member["group"] for member in members}) < 2:
            categories_passed_through += 1
            passed_through.extend(_as_position(member, consolidated_from=1) for member in members)
            continue
        ordered = group_spread(members)
        slices = [
            tuple(ordered[offset : offset + EXTRACT_SLICE])
            for offset in range(0, len(ordered), EXTRACT_SLICE)
        ]
        if len(slices) > 1:
            categories_sliced += 1
        jobs.extend(
            ConsolidateJob(
                category=category, arguments_key=_arguments_key(slice_members), members=slice_members
            )
            for slice_members in slices
        )

    return ConsolidationPlan(
        jobs=tuple(jobs),
        passed_through=tuple(passed_through),
        categories=len(by_category),
        categories_passed_through=categories_passed_through,
        categories_sliced=categories_sliced,
    )


def _as_position(member: dict[str, Any], *, consolidated_from: int) -> dict[str, Any]:
    """One raw position as this stage emits it: `merge_positions`' own input
    shape plus `category` (the embedding merge folds across categories only,
    so it needs to know) and `consolidated_from`. `group` is dropped -- it is
    planning state, not something a position carries onward."""
    return {
        "argument": member["argument"],
        "chunk_ids": member["chunk_ids"],
        "sources": member["sources"],
        "authors": member["authors"],
        "size": member["size"],
        "category": member["category"],
        "consolidated_from": consolidated_from,
    }


PROMPT = """Below are arguments drawn from academic books. Each was named by reading a group of passages, and the groups all sit inside one category of claim -- so the same argument may have been named more than once, in different words, by different readings. Nobody has read these together.

Say which of these are the same argument, and which are genuinely different.

{arguments}

Answer as JSON only, no other text:

{{"arguments": [
   {{"argument": "<one sentence stating this argument, in the listed arguments' own terms>",
    "handles": ["a1", "a4", "a9"]}},
   ...
 ]}}

How to group:

- MERGE aggressively on substance. Two entries arguing that states extract resources through coercion are the same argument whether one says it about France in 1600 and the other about Iraq in 1980, and whether one calls it extraction and the other calls it predation. Different evidence for the same claim is one argument. Different wording for the same claim is one argument. Different century, same claim, one argument.
- SPLIT only where the arguments genuinely conflict or concern different things. Two accounts that locate a cause differently are two arguments -- never fuse contending positions into one sentence saying both matter. If these arguments disagree with each other, that disagreement must survive as separate entries.
- These were grouped because they concern the same KIND of claim, not because they resemble each other in wording. A category holding many genuinely different arguments is an ordinary outcome. Do not merge two arguments because they are about the same thing; merge them only when they assert the same thing.
- Each argument must be CONTESTABLE: something a serious scholar could disagree with. "Violence is shaped by social and political processes" is not an argument, it is a topic wearing an argument's clothes. Do not reach for a wider sentence that covers two arguments at once -- that is the same fusion the second rule forbids.
- Every handle listed must appear in exactly one entry. An argument nothing else here restates gets an entry of its own, keeping its original sentence."""


def render_arguments_blind(
    members: Sequence[dict[str, Any]],
) -> tuple[str, dict[str, dict[str, Any]]]:
    """Render `members` as the consolidation prompt's argument listing,
    BLIND: `[a3] <argument>`, never author, book, or year -- the same rule
    `render_claims_blind` applies to extraction, and for the same reason:
    authorship visible here would let it decide what meets, which would make
    the cross-author balance the map reports measure its own input. Returns
    the listing and the handle -> raw-position map
    `consolidate_category_slice` resolves handles against."""
    handles = {f"a{i + 1}": member for i, member in enumerate(members)}
    listing = "\n".join(f"[{handle}] {member['argument']}" for handle, member in handles.items())
    return listing, handles


def consolidate_category_slice(
    job: ConsolidateJob, client: LLMClient, pass_name: str = PASS_NAME
) -> dict[str, Any]:
    """One model call for `job`. Returns a record: `category`,
    `arguments_key`, `shown` (raw positions offered), `positions` (this
    slice's whole output -- consolidated entries plus every raw position no
    entry named, each carrying `consolidated_from`), `dropped_handles`, and
    -- only on failure -- `error`.

    The record is self-contained on purpose: a resumed run rebuilds the
    stage's positions from the ledger alone, never from the job that
    produced it.

    A handle the model invents is dropped, never repaired, and an entry left
    with no real handles is dropped entirely -- `extract_positions_for_
    slice`'s own contract, exception set included, so one bad call never
    aborts the pass. A failed call passes its whole slice through
    unconsolidated: the extraction work behind those positions is already
    paid for."""
    listing, handles = render_arguments_blind(job.members)
    record: dict[str, Any] = {
        "category": job.category,
        "arguments_key": job.arguments_key,
        "shown": len(job.members),
        "positions": [],
    }
    dropped = 0
    try:
        parsed = parse_model_json(
            client.complete(PROMPT.format(arguments=listing), pass_name=pass_name)
        )
        named_handles: set[str] = set()
        for entry in parsed.get("arguments") or []:
            text = (entry.get("argument") or "").strip()
            offered = entry.get("handles") or []
            real = [handle for handle in offered if handle in handles]
            dropped += len(offered) - len(real)
            if not text or not real:
                continue
            named_handles.update(real)
            placed = [handles[handle] for handle in real]
            chunk_ids = sorted({cid for member in placed for cid in member["chunk_ids"]})
            record["positions"].append(
                {
                    "argument": text,
                    "chunk_ids": chunk_ids,
                    "sources": sorted({s for member in placed for s in member["sources"]}),
                    "authors": sorted({a for member in placed for a in member["authors"]}),
                    "size": len(chunk_ids),
                    "category": job.category,
                    "consolidated_from": len(placed),
                }
            )
        record["positions"].extend(
            _as_position(member, consolidated_from=1)
            for handle, member in handles.items()
            if handle not in named_handles
        )
    except (LLMError, httpx.HTTPError, ModelJsonError, AttributeError, TypeError) as exc:
        # Same fault class, and the same exception set, as extraction: the
        # model returning nothing usable -- including valid JSON shaped as
        # something other than the expected object, where `.get(...)` itself
        # is what fails.
        record["error"] = str(exc)[:200]
        record["positions"] = [
            _as_position(member, consolidated_from=1) for member in job.members
        ]
    record["dropped_handles"] = dropped
    return record


def run_consolidation(
    reads: Sequence[dict[str, Any]],
    *,
    client: LLMClient,
    reads_path: Path,
    pass_name: str = PASS_NAME,
    workers: int = WORKERS,
    log: Callable[[str], None] = print,
) -> ConsolidationResult:
    """Consolidate every category the extraction ledger `reads` spans more
    than one group of, resumable by `(category, arguments_key)` via
    `reads_path`: a restart skips whatever this ledger already carries, and
    a completed category costs no model call.

    The same collecting-thread pattern `run_extraction` uses: calls run
    concurrently (`workers`), every checkpoint write happens on this one
    thread, so a mid-run kill can never race two threads onto the same line
    and every result is durable the instant it returns."""
    plan = build_consolidation_jobs(reads)
    log(
        f"consolidation: {plan.categories} categor(ies), "
        f"{plan.categories_passed_through} spanning one group (no call), "
        f"{len(plan.jobs)} read(s) to make"
    )
    if plan.categories_sliced:
        log(
            f"  {plan.categories_sliced} categor(ies) needed more than one slice at "
            f"EXTRACT_SLICE={EXTRACT_SLICE}: namings in different slices of one "
            "category never met"
        )

    done = {
        (record["category"], record["arguments_key"])
        for record in load_checkpoint_records(reads_path, CorruptConsolidationLedgerError)
    }
    if done:
        log(f"resuming: {len(done)} consolidation read(s) already on disk")
    pending = [job for job in plan.jobs if (job.category, job.arguments_key) not in done]
    log(f"consolidation reads this run: {len(pending)} of {len(plan.jobs)}")

    if pending:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            futures = {
                pool.submit(consolidate_category_slice, job, client, pass_name): job
                for job in pending
            }
            completed = 0
            for future in as_completed(futures):
                record = future.result()
                append_checkpoint_record(reads_path, record)
                completed += 1
                log(f"  consolidated {completed}/{len(pending)} (category {record['category']})")

    # Only the slices this plan actually asked for: a ledger written before
    # an extraction re-ask can still hold a record whose `arguments_key` no
    # category now carries, and folding it in would resurrect positions the
    # current extraction ledger no longer names.
    wanted = {(job.category, job.arguments_key) for job in plan.jobs}
    records = [
        record
        for record in load_checkpoint_records(reads_path, CorruptConsolidationLedgerError)
        if (record["category"], record["arguments_key"]) in wanted
    ]
    positions = [position for record in records for position in record["positions"]]
    positions.extend(plan.passed_through)
    return ConsolidationResult(
        positions=tuple(positions), records=tuple(records), plan=plan
    )


def consolidation_reads_path(outdir: Path) -> Path:
    return Path(outdir) / CONSOLIDATION_READS_FILENAME


def write_consolidation_ledger_aside(outdir: Path, suffix: str) -> int | None:
    """Move this stage's ledger aside under `suffix` for a `--force` run --
    never delete it, a paid ledger stays on disk -- and return how many
    records it held, or `None` when there was nothing to set aside. Mirrors
    what `run_map_build` does for `reads.jsonl` and `relation_reads.jsonl`,
    kept here so the filename and the error class stay in one module."""
    path = consolidation_reads_path(outdir)
    if not path.exists():
        return None
    prior = load_checkpoint_records(path, CorruptConsolidationLedgerError)
    path.replace(Path(outdir) / f"consolidation_reads.{suffix}.jsonl")
    return len(prior)
