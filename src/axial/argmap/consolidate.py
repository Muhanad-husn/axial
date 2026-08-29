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

**Two rules ARE this pass's own, and a blind audit is why.** Twenty-five of
the built variant's most heavily folded positions were read cold against
their own members: 7 wrong, 9 mixed, 9 sound, three or four of them fusing
opposed accounts into one position. Heavily-folded positions are 14.4% of the
map and carry 64.2% of its passages, so that is the part of the map that
matters. Both faults were in `PROMPT`. It merged on rhetorical form -- 32
arguments from 23 books sharing only the shape "some existing account is
inadequate", which at this altitude, where the inputs are already abstract
argument sentences, is what everything looks like -- so sameness is now
asserting the same thing ABOUT THE SAME THING, with the move-versus-claim
distinction named and the writable sentence as its test. And nothing
constrained the sentence standing for a group, which let one position settle a
live dispute between its own members and another assert as fact what its
source attributed to Ibn Khaldun; that sentence must now state only what every
member asserts, and being unable to write one is the signal to split.

**A big enough fold is read again before it counts.** The same twenty-five
judgements, cross-tabulated by how many raw arguments each fold holds, put
every fold of ten or more in the wrong column and none in the sound one,
while below ten the wrong rate is 18% and the median wrong fold is the same
size as the median sound one. The failure is not gradual: past some size a
position stops being a shared claim and becomes a heading. A blunt cap was
rejected -- it cannot tell a genuine large fold from a heading, and it has
nowhere honest to put the members it refuses. So size is a trigger, not a
verdict: a position standing for at least `RE_READ_MEMBERS` raw arguments
goes to one more blind call (`re_read_entry`) that shows those arguments and
the sentence written for them, says that a group this large is usually a
heading, and asks which of them actually assert it. What it does not stand by
comes back in subgroups, each with its own sentence under `SENTENCE_RULE`; a
member is never dropped and never rewritten, so `sum(consolidated_from)`
still closes on the raw positions the category was given. A group it stands
by whole is left exactly as it was, which is how a legitimate 32-member
argument survives. A failed, unparseable or empty answer leaves the position
standing and is counted. It fires once per position per round, in any round,
and never on its own subgroups: the model has just been told the group is
probably a heading, so a subgroup it kept together after that is its
considered answer, and re-asking would spend money arguing with it and
ratchet toward atomisation. The manifest counts what fires, which is how a
bigger sample than n=3 gets collected.

**The trigger is ACCUMULATED size, and a probe is why.** Triggered on the
handles one call named, it fired zero times over
`causal-argument-nationalism-or-identity` -- 158 raw positions, 3 rounds, 9
calls -- while leaving an 11-argument and a 15-argument fold in the output.
Large folds are assembled across rounds out of small entries, so no single
call ever names ten handles. Round 1 is not where they form.

**Which forces a position to say what it is made of.** `FOLDED_FROM_KEY`
carries the raw arguments behind a position, accumulated the way
`consolidated_from` is, and `len(folded_from) == consolidated_from` on
everything this pass emits. It is what the re-read reads, what a split
rebuilds its subgroups from, and what makes the map self-auditable: reading
what a fold was made of used to mean reconstructing it by chunk-id
containment.

**It runs to a fixed point, per category.** A slice's input is capped at
`EXTRACT_SLICE`, the same cap extraction reads a group under: both listings
are one sentence per line under a bare handle, so how many lines one call can
weigh is the same question, and reusing the constant keeps a second,
separately-tuned number out of this module. But one round over slices is not
enough, and the live corpus says so loudly -- on the variant's own extraction
ledger, 8 of 9 categories are cut into 2-9 slices and hold 98.6% of all 2,036
raw positions. One round would reunite only inside a 55-argument window, and
since this pass also stops the embedding merge folding inside a category, two
namings landing in different slices of one category would be reunited by
nothing at all: §6's failure mode moved one level up rather than closed.

So a category is read again. Round 1 consolidates its raw positions in
slices; round 2 consolidates round 1's own output; and so on until one call
reads everything the category has left. `consolidated_from` accumulates
across rounds -- it is how many RAW positions ended in this one, not how many
entries the last round folded -- and every round's slice is keyed by its own
argument content, so a later round gets its own ledger entry for free and a
resumed run replays the whole chain off disk without a call.

Three ways a category stops short of that, all named and counted. A round
returning as many positions as it was given has told us the model will not
fold this set (`STOPPED_NO_PROGRESS`), and another pass over it is money for
nothing. A single-slice round whose one call failed
(`STOPPED_FINAL_ROUND_FAILED`) read nothing, and must not be counted as the
fixed point it resembles. And a category gets at most as many rounds as round 1 needed slices
(`STOPPED_ROUND_CAP`): the loop already terminates without a cap, since a
round that does not shrink the set stops it, so the cap bounds COST against a
model that folds one pair per round, and it is read off the data rather than
picked here. It bounds the multi-slice rounds only -- a round whose output
already fits one slice is always allowed, because that round is one call and
it is the whole point.

**One cost this pass does not pay.** A category whose raw positions all came
from ONE group has nothing to reunite -- there is no second naming of
anything -- and is passed through with no model call at all.

**What survives a call.** Every raw position a surviving entry did not name
is passed through unchanged, with `consolidated_from: 1`. The alternative
-- dropping it, as extraction drops a passage no argument names -- would
discard already-paid extraction work, and a position is the material of the
map in a way a single passage is not.

**The echo is deliberate, and it was measured.** `PROMPT` requires every
handle to appear in exactly one entry, so a call folding two of fifty-five
arguments retypes all fifty-five. That is expensive in emitted tokens -- the
first real-corpus pass ran 2.4M completion tokens against 400k prompt, with
13% of attempts hitting the client's 600s deadline -- and the obvious fix,
asking for the merges alone, was built and is WORSE. Probed on
`methodological-preconditions` (98 raw positions, same input, same model):
merges-only spent 15,972 completion tokens a call against the echo prompt's
8,000-13,000, with one call at 42,909 over 418s, and it folded 98 -> 66
where the echo prompt reached 51 and converged. The model spends far more
reasoning deciding what to merge when it is not walking the whole list, and
walking it is apparently what makes it weigh every argument. The echo costs
emitted tokens and buys both reasoning economy and folding, so it stays. Do
not re-propose removing it without re-measuring on that category.

**A resume announces its bill, and gives up on a read that cannot pass.**
Retrying a read whose ledger record carries `error` changes that category's
arguments, which changes the `arguments_key` every later round is keyed on,
so the whole downstream chain is re-asked at full price -- observed live, a
resume of a completed 188-call pass silently starting round 2 again. Before
the first call, a resumed run logs how many reads it will retry, which
categories they touch, and how many later reads that will cost, and the
manifest records the actuals. And a read that has failed as many times as
`axial.llm.MAX_ATTEMPTS` -- the client's own budget, not a number chosen
here -- is abandoned rather than retried forever, so a slice that exceeds
the deadline on every attempt stops costing thirty minutes per restart.
`--force` remains the only way to ask it again.
"""

from __future__ import annotations

import collections
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx

from axial.argmap.build import EXTRACT_SLICE, WORKERS, MapError
from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.llm import MAX_ATTEMPTS, LLMClient, LLMError
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

# How a category's consolidation ended. Only `STOPPED_CONVERGED` means the
# last round was a single call over everything the category had left -- the
# state this pass claims to reach. The other two are named, counted and
# logged rather than hidden, because a category that stops short still holds
# namings nothing reunited.
STOPPED_CONVERGED = "converged"
STOPPED_NO_PROGRESS = "no_progress"
STOPPED_ROUND_CAP = "round_cap"
# A single-slice round whose one call failed. It looks exactly like a
# converged round from the outside -- one job, and its slice comes back as
# positions -- but the call read nothing and the slice merely passed
# through. `categories_converged` is the number this manifest offers as the
# answer, so it must not count this (issue #830, review).
STOPPED_FINAL_ROUND_FAILED = "final_round_failed"

# Where a position was named, for `unit_spread`'s rotation: the extraction
# group in round 1, the slice that produced it in every later round. Planning
# state only -- `_as_position` strips it before anything downstream sees it.
UNIT_KEY = "unit"

# The RAW positions a position stands for, accumulated across rounds the way
# `consolidated_from` accumulates -- one record per raw position, each with
# its own argument sentence, chunk ids, sources and authors.
# `len(folded_from) == consolidated_from` on everything this pass emits.
#
# It exists because the map has to be self-auditable: reading what a fold was
# made of meant reconstructing it by chunk-id containment, which works and
# should not be necessary. It is also what makes the re-read possible at all
# -- the call is shown these sentences, and a split rebuilds its subgroups
# from these chunk ids. Sentences alone would leave a subgroup with no honest
# way to claim its own chunks, sources and size.
#
# `merge_positions` writes `variants` afterwards for a related but different
# thing: the CONSOLIDATED sentences one embedding cluster folded. The two do
# not collide and neither replaces the other.
FOLDED_FROM_KEY = "folded_from"

# The handles a consolidated entry named, recorded on the entry inside its
# ledger record. Planning state, like `UNIT_KEY`: no position carries it out
# of the round it was written in. It survives only to rebuild
# `FOLDED_FROM_KEY` on a ledger written before that field existed
# (`_as_round_position`), so an already-paid pass can be resumed and re-read
# without buying its consolidation calls again.
HANDLES_KEY = "handles"


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
    """One consolidation call's worth of work: `members` positions, all from
    `category`, all from the same `round`, already unit-spread and cut to at
    most `EXTRACT_SLICE`.

    `arguments_key` is this slice's content identity -- a hash over its own
    ordered argument sentences, exactly what the model is shown
    (`render_arguments_blind` renders nothing else). It is half of the resume
    key, alongside `category`, because this pass's input is another pass's
    output: round 1 reads the EXTRACTION pass's arguments and round n reads
    round n-1's, so a re-asked extraction read or a differently-folded
    earlier round changes the question, and a ledger keyed by category and
    slice number alone would hand back an answer to a question nobody
    asked. `round` is recorded on the read rather than keyed on, for the
    same reason: two rounds with byte-identical listings are the same
    question, and the answer already on disk is the right one."""

    category: str
    round: int
    arguments_key: str
    members: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class CategoryOutcome:
    """How one category's consolidation ended: how many raw positions it
    started from, how many it finished with, how many slices round 1 needed,
    how many rounds it took, and which of the four `STOPPED_*` reasons ended
    it. Only `STOPPED_CONVERGED` means one call read everything the category
    had left; the other three are a category whose whole set was never
    reunited, and the manifest counts them separately so that stays visible.

    `round_one_slices` is what "was this category ever too big for one call"
    is answered from. Rounds cannot answer it: a category cut into four
    slices that folds nothing stops after ONE round (issue #830, review)."""

    category: str
    raw_positions: int
    final_positions: int
    round_one_slices: int
    rounds: int
    stopped: str


@dataclass(frozen=True)
class ConsolidationResult:
    """The stage's output: `positions` in exactly the shape
    `merge_positions` already consumes, plus `consolidated_from` and
    `category` on each; the ledger records that produced them; and one
    `CategoryOutcome` per category that took at least one round.

    The last three are what a RESUME cost. `reads_retried` counts reads that
    carried an `error` and were asked again; `reads_reasked_after_retry`
    counts reads in a later round of the same category that had to be asked
    again because the retry changed their input; `reads_abandoned` counts
    reads that have now failed as many times as the client itself would
    attempt a call and will never be asked again without `--force`. On a
    first run all three are zero."""

    positions: tuple[dict[str, Any], ...]
    records: tuple[dict[str, Any], ...]
    outcomes: tuple[CategoryOutcome, ...]
    categories: int
    categories_passed_through: int
    reads_retried: int = 0
    reads_reasked_after_retry: int = 0
    reads_abandoned: int = 0
    re_reads: tuple[dict[str, Any], ...] = ()


def category_of(group_label: Any) -> str:
    """The category a group label belongs to: everything before
    `axial.argmap.grouping`'s own `::` separator, so `<claim>::<mechanism>`
    and the claim-only `<claim>::(no mechanism)` both consolidate at the
    claim category they share. A label with no separator is its own category
    -- this pass never has to decide what a malformed label means, it just
    consolidates at whatever whole label it was given."""
    return str(group_label).split(GROUP_LABEL_SEPARATOR, 1)[0]


def unit_spread(members: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """`members` reordered one UNIT at a time in rotation, so any prefix --
    and so every slice `build_round_jobs` cuts -- carries namings from as
    many units as it can. `author_spread`'s own shape, applied one level up:
    there, the point is that a slice sees more than one book; here, that it
    sees more than one place the same argument could have been named from,
    which is the only way a repeated naming can be spotted at all.

    A unit is the extraction group in round 1 and the slice that produced a
    position in every later round. Spreading improves the odds that two
    namings of one argument share a call; it is the rounds, not this, that
    make them eventually share one."""
    by_unit: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for member in members:
        by_unit[member[UNIT_KEY]].append(member)
    keys = sorted(by_unit)
    out: list[dict[str, Any]] = []
    index = 0
    while len(out) < len(members):
        for key in keys:
            if index < len(by_unit[key]):
                out.append(by_unit[key][index])
        index += 1
    return out


def _arguments_key(members: Sequence[dict[str, Any]]) -> str:
    """sha256 (first 16 hex chars) over `members`' own argument sentences,
    in order -- the content identity of one consolidation slice, the same
    thing `_members_key` is for an extraction slice."""
    canonical = "\n".join(member["argument"] for member in members)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def partition_by_category(
    reads: Sequence[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], int]:
    """Split the extraction ledger `reads` into the categories that need
    consolidating and the positions that need no model call at all.

    Every raw position is tagged with the category it belongs to and the
    unit it was named in (its extraction group). A category whose positions
    all came from one group is passed through -- there is no second naming of
    anything to reunite. Returns the categories still to consolidate, the
    passed-through positions, and how many categories were passed through."""
    by_category: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for read in reads:
        category = category_of(read["bag"])
        for position in read["positions"]:
            by_category[category].append(
                {
                    **position,
                    "category": category,
                    "consolidated_from": position.get("consolidated_from", 1),
                    UNIT_KEY: str(read["bag"]),
                }
            )

    to_consolidate: dict[str, list[dict[str, Any]]] = {}
    passed_through: list[dict[str, Any]] = []
    categories_passed_through = 0
    for category in sorted(by_category):
        members = by_category[category]
        if len({member[UNIT_KEY] for member in members}) < 2:
            categories_passed_through += 1
            passed_through.extend(_as_position(member) for member in members)
        else:
            to_consolidate[category] = members
    return to_consolidate, passed_through, categories_passed_through


def build_round_jobs(
    category: str, members: Sequence[dict[str, Any]], round_number: int
) -> list[ConsolidateJob]:
    """One round's calls for `category`: `members` unit-spread and cut into
    slices of at most `EXTRACT_SLICE`. A round that yields exactly one job
    has read everything the category has left -- the state this pass exists
    to reach."""
    ordered = unit_spread(members)
    return [
        ConsolidateJob(
            category=category,
            round=round_number,
            arguments_key=_arguments_key(ordered[offset : offset + EXTRACT_SLICE]),
            members=tuple(ordered[offset : offset + EXTRACT_SLICE]),
        )
        for offset in range(0, len(ordered), EXTRACT_SLICE)
    ]


def _as_position(member: dict[str, Any]) -> dict[str, Any]:
    """One position as this stage emits it: `merge_positions`' own input
    shape plus `category` (the embedding merge folds across categories only,
    so it needs to know), `consolidated_from` and `folded_from`. The unit
    key and the handles are dropped -- planning state, not something a
    position carries onward.

    `folded_from` is emitted even on a position that was never folded, where
    it holds that position alone. The redundancy buys one invariant with no
    exceptions: every position this pass emits says what it is made of, and
    the list is exactly as long as the count."""
    return {
        "argument": member["argument"],
        "chunk_ids": member["chunk_ids"],
        "sources": member["sources"],
        "authors": member["authors"],
        "size": member["size"],
        "category": member["category"],
        "consolidated_from": member.get("consolidated_from", 1),
        FOLDED_FROM_KEY: _members_of(member),
    }


# The one constraint on the sentence a group is given, written once and used
# by BOTH calls in this pass. The blind audit found the consolidation
# prompt's group sentence adjudicating between its own members, and a
# re-read that split a heading but wrote its subgroups' sentences under
# looser rules would put the same fault back at the split. One string, so
# the two prompts cannot drift.
SENTENCE_RULE = (
    "THE SENTENCE YOU WRITE for a group states only what every argument in the group asserts. "
    "It never takes a side no member takes, never settles a disagreement between members, never "
    "widens into a generality that would also cover arguments outside the group, and never drops "
    "an attribution -- an argument reporting what a named thinker holds is a different argument "
    "from one asserting the same thing as fact. If you cannot write one sentence every member of "
    "a group would accept, that group is not one argument: split it."
)

def _members_of(position: dict[str, Any]) -> list[dict[str, Any]]:
    """The RAW positions `position` stands for. One that was folded carries
    them; one that was not stands for itself.

    A member is the raw argument sentence plus the provenance a split needs
    to rebuild a subgroup correctly. This is why the field holds records
    rather than bare sentences: without the chunk ids there is no honest way
    to give a subgroup its own chunks, sources, authors and size."""
    folded = position.get(FOLDED_FROM_KEY)
    if folded:
        return list(folded)
    member = {key: position[key] for key in ("argument", "chunk_ids", "sources", "authors")}
    raw = int(position.get("consolidated_from", 1))
    if raw > 1:
        # A position off a ledger written before this field existed, whose
        # handles could not be resolved either: the provenance is gone but
        # the raw count is not, and nothing here may lose it.
        member["consolidated_from"] = raw
    return [member]


def _pool(text: str, placed: Sequence[dict[str, Any]], category: str) -> dict[str, Any]:
    """One entry as a call writes it: `text` standing for the `placed`
    members, pooling the raw positions behind them. Shared by the
    consolidation call and the re-read so a subgroup is built exactly the
    way the entry it came out of was."""
    members = [member for position in placed for member in _members_of(position)]
    chunk_ids = sorted({cid for member in members for cid in member["chunk_ids"]})
    return {
        "argument": text,
        "chunk_ids": chunk_ids,
        "sources": sorted({s for member in members for s in member["sources"]}),
        "authors": sorted({a for member in members for a in member["authors"]}),
        "size": len(chunk_ids),
        "category": category,
        # RAW positions folded in, accumulated across rounds -- a round-2
        # entry folding five round-1 entries of five reads 25, not 5.
        "consolidated_from": sum(member.get("consolidated_from", 1) for member in members),
        FOLDED_FROM_KEY: members,
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
- Two arguments are the same argument only when they assert THE SAME THING ABOUT THE SAME THING. These were grouped because they share a KIND of claim, not a wording, so a category holding many genuinely different arguments is an ordinary outcome. Being about the same thing is not enough. Neither is sharing a rhetorical move: criticising an existing account, rejecting mono-causality, describing something as proceeding in stages, calling something complex or context-specific are moves, not claims, and two arguments making the same move about different objects -- irrigation and despotism, oil rents, national identity, a revolution -- stay apart. The test: if the sentence you would write does not name what the argument is about, you are merging a move rather than a claim. Do not merge.
- """ + SENTENCE_RULE + """
- Each argument must be CONTESTABLE: something a serious scholar could disagree with. "Violence is shaped by social and political processes" is not an argument, it is a topic wearing an argument's clothes.
- Every handle listed must appear in exactly one entry. An argument nothing else here restates gets an entry of its own, keeping its original sentence."""


# How many handles an entry must name before it is read again. Twenty-five
# of the built variant's most heavily folded positions were judged blind
# against their own members, cross-tabulated by how many raw arguments each
# fold holds:
#
#     fold size     wrong  mixed  sound
#     10 or more        3      0      0
#     under 10          4      9      9
#
# Every fold of ten or more was judged wrong; none survived. Below ten the
# wrong rate is 18%, and the median wrong fold (5) is the same size as the
# median sound one (4) -- size does not separate them there, so a re-read
# would be bought for nothing. The failure is not gradual: past some size an
# entry stops being a shared claim and becomes a heading. The worst case
# folded 32 arguments from 23 books into "Existing explanations are flawed
# because they impose simplistic, narrow, mono-causal, or anachronistic
# frameworks."
#
# n=3 above the line. The signal is clean but small, and 10 is a measured
# STARTING POINT to be revisited against a bigger sample, not a settled
# constant. The manifest counts what it triggers, which is how a bigger
# sample gets collected.
RE_READ_MEMBERS = 10

# What a re-read's ledger key is prefixed with. A consolidation slice's
# `arguments_key` is bare hex, so the two key spaces cannot collide and both
# calls can share one ledger.
RE_READ_KEY_PREFIX = "reread:"

RE_READ_PROMPT = """One reading of a longer list of arguments put the arguments below into a single group, and wrote this one sentence to stand for all of them:

{sentence}

A group this large is usually not one shared claim. It is a heading: a rhetorical shape several different arguments happen to share -- criticising an existing account, rejecting a single cause, calling something complex or context-specific -- while the arguments under it are about different things. Your job is to find the real claims inside it.

{arguments}

Read each argument against that sentence and ask whether it actually asserts it. Keep together only arguments that assert the same thing about the same thing. An argument that does not assert the group's claim goes into a group of its own, or with whichever others it does share a claim with. If every one of these arguments really does assert that sentence, this is a real group and not a heading -- say so, by returning them all as one group.

Answer as JSON only, no other text:

{{"groups": [
   {{"argument": "<one sentence stating what this group asserts, in the listed arguments' own terms>",
    "handles": ["a1", "a4"]}},
   ...
 ]}}

- """ + SENTENCE_RULE + """
- Every handle listed above must appear in exactly one group. Never drop an argument and never rewrite one: an argument nothing else here shares a claim with gets a group of its own, keeping its original sentence."""


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
    """One model call for `job`. Returns a record: `category`, `round`,
    `arguments_key`, `shown` (positions offered), `positions` (this
    slice's whole output -- consolidated entries plus every raw position no
    entry named, each carrying `consolidated_from`), `dropped_handles`, and
    -- only on failure -- `error`.

    The record is self-contained on purpose: a resumed run rebuilds the
    stage's positions from the ledger alone, never from the job that
    produced it.

    `dropped_handles` covers two classes, both dropped and never repaired: a
    handle the model invents, and a handle it names in a second entry after
    an earlier one already claimed it. An entry left with no real handles is
    dropped entirely -- `extract_positions_for_slice`'s own contract,
    exception set included, so one bad call never aborts the pass. A failed
    call is re-asked on the next run rather than standing as a completed
    one, until it has failed as many times as the client itself would
    attempt a call (`_ask_round`). A failed call passes its whole slice
    through unconsolidated: the extraction work behind those positions is
    already paid for."""
    listing, handles = render_arguments_blind(job.members)
    record: dict[str, Any] = {
        "category": job.category,
        "round": job.round,
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
            # A handle belongs to exactly one entry: the prompt says so and
            # nothing enforced it, so a model naming `a2` twice put it in
            # two positions, each summing its raw count and each carrying
            # its chunk ids -- and it compounded round over round, on the
            # number this pass is judged by. First surviving entry wins.
            real: list[str] = [
                handle
                for index, handle in enumerate(offered)
                if handle in handles
                and handle not in named_handles
                and handle not in offered[:index]
            ]
            dropped += len(offered) - len(real)
            if not text or not real:
                continue
            named_handles.update(real)
            record["positions"].append(
                {
                    **_pool(text, [handles[handle] for handle in real], job.category),
                    # Which members this entry stands for. It is what the
                    # re-read resolves back to argument sentences, and it is
                    # on the ledger so a resumed run can find the
                    # over-threshold entries without re-asking anything.
                    HANDLES_KEY: real,
                }
            )
        record["positions"].extend(
            _as_position(member)
            for handle, member in handles.items()
            if handle not in named_handles
        )
    except (LLMError, httpx.HTTPError, ModelJsonError, AttributeError, TypeError) as exc:
        # Same fault class, and the same exception set, as extraction: the
        # model returning nothing usable -- including valid JSON shaped as
        # something other than the expected object, where `.get(...)` itself
        # is what fails.
        record["error"] = str(exc)[:200]
        record["positions"] = [_as_position(member) for member in job.members]
    record["dropped_handles"] = dropped
    return record


@dataclass(frozen=True)
class ReReadJob:
    """One re-read call's worth of work: a consolidated `entry` that named
    at least `RE_READ_MEMBERS` handles, and the `members` it named.

    `arguments_key` is the entry's own content identity -- a hash over its
    members' argument sentences in order, under `RE_READ_KEY_PREFIX` so it
    cannot collide with a consolidation slice's key in the same ledger. It is
    the entry's content and not the slice's, because a re-read is a question
    about this entry alone: two slices that fold the same members into the
    same entry are asking the same question, and a resumed run replays the
    answer rather than buying it twice."""

    category: str
    round: int
    arguments_key: str
    entry: dict[str, Any]
    members: tuple[dict[str, Any], ...]


def _re_read_key(members: Sequence[dict[str, Any]]) -> str:
    """The ledger key for a re-read of an entry standing for `members`."""
    return RE_READ_KEY_PREFIX + _arguments_key(members)


def position_re_read_job(
    category: str, position: dict[str, Any], round_number: int
) -> ReReadJob | None:
    """The re-read `position` needs, or `None` when it is under the
    threshold or has nothing to show.

    The trigger is ACCUMULATED size -- how many raw arguments the position
    now stands for -- and a probe is why. Triggered instead on the handles
    one call named, it fired zero times over
    `causal-argument-nationalism-or-identity` (158 raw positions, 3 rounds,
    9 calls) while leaving an 11-argument and a 15-argument fold in the
    output. Large folds are assembled ACROSS rounds out of small entries, so
    no single call ever names ten handles; round 1 is not where they form.
    Accumulated size is also the quantity the audit measured and the one
    that reaches the map.

    A position with no recorded members cannot be re-read -- there is
    nothing to put in front of the model -- which can only happen on a
    ledger written before `FOLDED_FROM_KEY` existed and whose handles could
    not be resolved either. The round loop says so rather than passing over
    it in silence."""
    if int(position.get("consolidated_from", 1)) < RE_READ_MEMBERS:
        return None
    members = tuple(_members_of(position))
    if len(members) < 2:
        return None
    return ReReadJob(
        category=category,
        round=round_number,
        arguments_key=_re_read_key(members),
        # The unit is this round's planning state; it must not travel to
        # disk inside the entry a stood-by re-read hands back.
        entry={key: value for key, value in position.items() if key != UNIT_KEY},
        members=members,
    )


def re_read_entry(
    job: ReReadJob, client: LLMClient, pass_name: str = PASS_NAME
) -> dict[str, Any]:
    """One re-read call. Returns a record shaped like a consolidation read's
    -- `category`, `round`, `arguments_key`, `shown`, `positions`,
    `dropped_handles`, `error` on failure -- plus `split`, so the manifest
    does not have to infer it, and `kind`, so the shared ledger says which
    call wrote a line.

    `positions` is what replaces the entry in the round's output. Three
    outcomes:

    - The call returns one group naming every member: a legitimate large
      fold. The ORIGINAL entry stands, sentence and all -- there is nothing
      to change, and rewriting a sentence a call that saw every member
      already wrote would buy a difference nobody asked for.
    - It returns more than one group, or one that leaves members out: the
      position is split. Each group becomes a position under `_pool`, and
      every member no group named becomes a position of its own keeping its
      own sentence, exactly as an unnamed handle does in the consolidation
      call. Members are redistributed, never invented and never dropped, so
      `sum(consolidated_from)` over the round is unchanged.
    - The call fails, is unparseable, or names no usable group at all: the
      original entry stands unchanged and the failure is counted. A nothing
      answer must not be allowed to atomise a fold."""
    listing, handles = render_arguments_blind(job.members)
    record: dict[str, Any] = {
        "category": job.category,
        "round": job.round,
        "arguments_key": job.arguments_key,
        "kind": "re_read",
        "shown": len(job.members),
        "split": False,
        "positions": [job.entry],
    }
    dropped = 0
    try:
        parsed = parse_model_json(
            client.complete(
                RE_READ_PROMPT.format(sentence=job.entry["argument"], arguments=listing),
                pass_name=pass_name,
            )
        )
        named_handles: set[str] = set()
        groups: list[tuple[str, list[dict[str, Any]]]] = []
        for group in parsed.get("groups") or []:
            text = (group.get("argument") or "").strip()
            offered = group.get("handles") or []
            real = [
                handle
                for index, handle in enumerate(offered)
                if handle in handles
                and handle not in named_handles
                and handle not in offered[:index]
            ]
            dropped += len(offered) - len(real)
            if not text or not real:
                continue
            named_handles.update(real)
            groups.append((text, [handles[handle] for handle in real]))
        if not groups:
            record["error"] = "the re-read named no usable group"
        elif len(groups) == 1 and len(named_handles) == len(job.members):
            # Stood by: a real group, not a heading. Left exactly as it was.
            pass
        else:
            record["split"] = True
            record["positions"] = [_pool(text, placed, job.category) for text, placed in groups]
            record["positions"].extend(
                _pool(member["argument"], [member], job.category)
                for handle, member in handles.items()
                if handle not in named_handles
            )
    except (LLMError, httpx.HTTPError, ModelJsonError, AttributeError, TypeError) as exc:
        # The consolidation call's own fault class and exception set.
        record["error"] = str(exc)[:200]
        record["split"] = False
        record["positions"] = [job.entry]
    record["dropped_handles"] = dropped
    return record


@dataclass
class _ResumeTally:
    """What a resume of this pass cost, accumulated across its rounds.

    `retry_round` is the working state the other three are counted from: the
    round in which a category first had a read retried. Anything that
    category is asked in a LATER round is a re-ask caused by that retry --
    the retry's answer differs from the error record's pass-through, so the
    later round's `arguments_key` changes and the answer already on disk for
    it no longer applies."""

    retried: int = 0
    reasked: int = 0
    abandoned: int = 0
    retry_round: dict[str, int] = field(default_factory=dict)


def _attempts(record: dict[str, Any]) -> int:
    """How many times this failed read has been asked. A record written
    before the count existed stands for one attempt, so a live ledger's
    failures still get their remaining tries rather than being abandoned on
    sight."""
    return int(record.get("attempts", 1))


def _is_retryable(record: dict[str, Any] | None) -> bool:
    """A failed read still worth asking again: it has not yet failed as many
    times as the client itself would attempt one call."""
    return record is not None and "error" in record and _attempts(record) < MAX_ATTEMPTS


def _announce_resume_spend(
    jobs: Sequence[ConsolidateJob],
    reads_path: Path,
    log: Callable[[str], None],
) -> None:
    """Before the first call of a resumed run, say what retrying its failed
    reads will cost.

    A retry is not one call. The retried read comes back different from the
    error record's pass-through, so that category's later rounds are asked a
    different question, their `arguments_key` changes, and every answer
    already on disk for them stops applying -- the whole downstream chain is
    re-asked at full price. That is right, and it happened silently once
    (issue #830): a resume of a completed 188-call pass began re-asking round
    2 with no warning that it was about to spend anything. The figure is an
    upper bound, since the retry's own answer is not known until it is
    made."""
    ledger = load_checkpoint_records(reads_path, CorruptConsolidationLedgerError)
    if not ledger:
        return
    by_key = {(record["category"], record["arguments_key"]): record for record in ledger}
    retrying = [
        job for job in jobs if _is_retryable(by_key.get((job.category, job.arguments_key)))
    ]
    if not retrying:
        return
    from_round = {job.category: job.round for job in retrying}
    downstream = sum(
        1
        for record in ledger
        if record["category"] in from_round
        and int(record.get("round", 1)) > from_round[record["category"]]
    )
    log(
        f"consolidation resume: {len(retrying)} failed read(s) to re-ask in "
        f"{', '.join(sorted(from_round))}; a retry changes those categories' "
        f"arguments, so {downstream} later call(s) already on disk -- reads and "
        f"re-reads alike -- will be asked again; this run will spend up to "
        f"{len(retrying) + downstream} call(s)"
    )


def _ask_round(
    jobs: Sequence[ConsolidateJob],
    *,
    client: LLMClient,
    reads_path: Path,
    pass_name: str,
    workers: int,
    log: Callable[[str], None],
    tally: _ResumeTally,
) -> dict[tuple[str, str], dict[str, Any]]:
    """Make one round's calls and return every record now on disk, keyed by
    `(category, arguments_key)`. A slice already on the ledger costs no call:
    the same resume mechanism `run_extraction` has, and the reason a killed
    pass never re-asks a completed category.

    The same collecting-thread pattern too -- calls run concurrently
    (`workers`), every checkpoint write happens on this one thread, so a
    mid-run kill can never race two threads onto the same line and every
    result is durable the instant it returns."""
    done = {
        (record["category"], record["arguments_key"]): record
        for record in load_checkpoint_records(reads_path, CorruptConsolidationLedgerError)
    }
    # An error record is not a completed call, so it is re-asked (issue
    # #830, review). Left permanent it is worse than a lost call: a failed
    # slice passes its members through unchanged, which can trip the
    # no-progress rule and end the category, and every restart would replay
    # the same error and end it identically -- only `--force`, at full
    # price, could recover. The resume contract is never re-ask a COMPLETED
    # call.
    #
    # But a read can fail in a way no retry fixes: one live slice exceeded
    # the client's 600s deadline on all three of its attempts, and re-asking
    # error records then meant every future resume spent thirty minutes
    # rediscovering it. A read that has already failed as many times as the
    # client would attempt one call is abandoned instead -- counted, its
    # members still passing through unchanged, and re-askable only under
    # `--force`.
    pending: list[ConsolidateJob] = []
    abandoned_before = tally.abandoned
    for job in jobs:
        prior = done.get((job.category, job.arguments_key))
        if prior is not None and "error" not in prior:
            continue
        if prior is None:
            # A read this category was never asked, in a round after one of
            # its reads was retried: the retry is what changed the input,
            # and this is the downstream price of it.
            if tally.retry_round.get(job.category, job.round) < job.round:
                tally.reasked += 1
            pending.append(job)
        elif _is_retryable(prior):
            tally.retried += 1
            tally.retry_round.setdefault(job.category, job.round)
            pending.append(job)
        else:
            tally.abandoned += 1
    retries = sum(1 for job in pending if (job.category, job.arguments_key) in done)
    log(
        f"  round reads: {len(pending)} of {len(jobs)} "
        f"({retries} retrying an earlier failure, "
        f"{tally.abandoned - abandoned_before} abandoned)"
    )

    if pending:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            futures = {
                pool.submit(consolidate_category_slice, job, client, pass_name): job
                for job in pending
            }
            completed = 0
            for future in as_completed(futures):
                record = future.result()
                key = (record["category"], record["arguments_key"])
                if "error" in record:
                    # Attempts accumulate on the ledger record, so the next
                    # resume can tell a transient blip from a read that
                    # cannot pass.
                    record["attempts"] = _attempts(done[key]) + 1 if key in done else 1
                append_checkpoint_record(reads_path, record)
                done[key] = record
                completed += 1
                log(f"  consolidated {completed}/{len(pending)} (category {record['category']})")
    return done


def _ask_re_reads(
    jobs: Sequence[ReReadJob],
    *,
    client: LLMClient,
    reads_path: Path,
    pass_name: str,
    workers: int,
    log: Callable[[str], None],
    records: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """Make this round's re-read calls and add their records to `records`,
    the same `(category, arguments_key)` map `_ask_round` returns.

    One phase per round, across every category at once, so the pool stays as
    wide for the re-reads as it was for the reads that raised them. Same
    resume rule too: a completed re-read on the ledger costs no call, a
    failed one is asked again until it has failed as many times as the
    client would attempt a call, and every checkpoint write happens on this
    thread. The key is content-addressed over the position's members, so a
    position re-read in one round and left alone in the next is replayed
    rather than re-asked."""
    pending: list[ReReadJob] = []
    seen: set[tuple[str, str]] = set()
    for job in jobs:
        key = (job.category, job.arguments_key)
        if key in seen:
            # Two entries of identical members are one question.
            continue
        prior = records.get(key)
        if prior is not None and not _is_retryable(prior):
            continue
        seen.add(key)
        pending.append(job)
    if not jobs:
        return
    log(
        f"  round re-reads: {len(pending)} of {len(jobs)} position(s) "
        f"standing for {RE_READ_MEMBERS}+ raw arguments"
    )
    if not pending:
        return

    with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
        futures = {pool.submit(re_read_entry, job, client, pass_name): job for job in pending}
        for future in as_completed(futures):
            record = future.result()
            key = (record["category"], record["arguments_key"])
            if "error" in record:
                record["attempts"] = _attempts(records[key]) + 1 if key in records else 1
            append_checkpoint_record(reads_path, record)
            records[key] = record


def _as_round_position(entry: dict[str, Any], job: ConsolidateJob) -> dict[str, Any]:
    """`entry` as one of this round's output positions: the handles it named
    stripped, and the raw positions it stands for attached.

    A call records that provenance itself (`_pool`), so the attaching does
    nothing on a fresh run. It exists for a ledger written before the field
    did: such a record carries the handles the entry named but not the
    members behind them, and those are rebuilt here from the job that
    produced it. The rebuild chains -- round 2's job members are round 1's
    output positions, which came through here too -- so an already-paid pass
    resumes with its full provenance and can be re-read without buying its
    consolidation calls again. A record written before either field has
    neither, and the position stands for itself."""
    position = {key: value for key, value in entry.items() if key != HANDLES_KEY}
    if position.get(FOLDED_FROM_KEY):
        return position
    _listing, handles = render_arguments_blind(job.members)
    placed = [handle for handle in (entry.get(HANDLES_KEY) or []) if handle in handles]
    if placed:
        position[FOLDED_FROM_KEY] = [
            member for handle in placed for member in _members_of(handles[handle])
        ]
    return position


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
    than one group of, ITERATING each category to a fixed point.

    A round reads the category in slices of at most `EXTRACT_SLICE`; the next
    round reads that round's own output, and so on, until one call reads
    everything the category has left (`STOPPED_CONVERGED`). Rounds are driven
    across all categories at once, so the worker pool stays as wide in round
    n as it was in round 1.

    Three ways a category stops short. A round that comes back with as many
    positions as it was given (`STOPPED_NO_PROGRESS`) has told us the model
    will not fold this set, and another pass over it is money for nothing. A
    single-slice round whose one call failed (`STOPPED_FINAL_ROUND_FAILED`)
    read nothing and is not a fixed point, however much it looks like one.
    And a category gets at most as many multi-slice rounds as round 1 needed
    slices (`STOPPED_ROUND_CAP`): the loop already terminates without a cap,
    since every continuing round strictly shrinks the set, so this bounds
    COST against a model that folds one pair per round rather than bounding
    correctness. The bound is read off the data -- a category read in nine
    slices gets nine rounds -- and is not a number picked here. A round whose
    output already fits one slice is never denied: that round is one call and
    it is the whole point.

    A resumed run says up front what its retries will cost, and gives up on a
    read that has failed as many times as the client itself would attempt one
    (`_announce_resume_spend`, `_ask_round`). Both figures reach the manifest."""
    to_consolidate, passed_through, categories_passed_through = partition_by_category(reads)
    categories = len(to_consolidate) + categories_passed_through
    log(
        f"consolidation: {categories} categor(ies), "
        f"{categories_passed_through} spanning one group (no call), "
        f"{len(to_consolidate)} to consolidate"
    )

    raw_counts = {category: len(members) for category, members in to_consolidate.items()}
    active = dict(to_consolidate)
    caps: dict[str, int] = {}
    finished: dict[str, list[dict[str, Any]]] = {}
    outcomes: list[CategoryOutcome] = []
    used: dict[tuple[str, str], dict[str, Any]] = {}
    used_re_reads: dict[tuple[str, str], dict[str, Any]] = {}
    tally = _ResumeTally()
    round_number = 0

    while active:
        round_number += 1
        jobs_by_category = {
            category: build_round_jobs(category, active[category], round_number)
            for category in sorted(active)
        }
        jobs = [job for category_jobs in jobs_by_category.values() for job in category_jobs]
        if round_number == 1:
            # Before a single call is made, and only when there is something
            # to warn about.
            _announce_resume_spend(jobs, reads_path, log)
        log(f"consolidation round {round_number}: {len(jobs)} read(s) over {len(jobs_by_category)}")
        records = _ask_round(
            jobs,
            client=client,
            reads_path=reads_path,
            pass_name=pass_name,
            workers=workers,
            log=log,
            tally=tally,
        )

        # This round's output for every category, before the re-read. The
        # trigger is a position's ACCUMULATED size, so it cannot be applied
        # until the round's entries are assembled into positions.
        assembled: dict[str, list[dict[str, Any]]] = {}
        for category, category_jobs in jobs_by_category.items():
            outputs: list[dict[str, Any]] = []
            for index, job in enumerate(category_jobs):
                record = records[(job.category, job.arguments_key)]
                used[(job.category, job.arguments_key)] = record
                # The unit a later round spreads by: which slice of THIS
                # round produced the position.
                unit = f"r{round_number}s{index}"
                outputs.extend(
                    {**_as_round_position(entry, job), UNIT_KEY: unit}
                    for entry in record["positions"]
                )
            assembled[category] = outputs

        # The re-read sits HERE: after the round's positions exist and
        # before the stopping rules read them. It cannot go inside the slice
        # call -- that runs on a worker thread, and every ledger write in
        # this pass happens on the collecting thread so a kill can never
        # race two threads onto one line. One phase over every category at
        # once is what keeps the pool as wide as the round's own, and it
        # fires in ANY round, which is the whole point: a fold reaches ten
        # raw arguments by accumulating over rounds, not inside one call.
        over_threshold = [
            (category, position)
            for category, outputs in assembled.items()
            for position in outputs
            if int(position.get("consolidated_from", 1)) >= RE_READ_MEMBERS
        ]
        re_read_jobs = [
            re_read_job
            for category, position in over_threshold
            if (re_read_job := position_re_read_job(category, position, round_number)) is not None
        ]
        if len(re_read_jobs) < len(over_threshold):
            log(
                f"  {len(over_threshold) - len(re_read_jobs)} position(s) at "
                f"{RE_READ_MEMBERS}+ raw arguments carry no recorded members "
                f"and cannot be re-read"
            )
        _ask_re_reads(
            re_read_jobs,
            client=client,
            reads_path=reads_path,
            pass_name=pass_name,
            workers=workers,
            log=log,
            records=records,
        )

        still: dict[str, list[dict[str, Any]]] = {}
        for category, category_jobs in jobs_by_category.items():
            outputs = []
            for position in assembled[category]:
                # The key is a pure function of the position's own members,
                # so it is recomputed rather than carried from the jobs
                # above -- which is also what lets a resumed run find a
                # completed re-read from the ledger alone, and what stops a
                # position re-read in round 2 and untouched in round 3 being
                # asked again.
                re_read_job = position_re_read_job(category, position, round_number)
                re_read = (
                    records.get((category, re_read_job.arguments_key))
                    if re_read_job is not None
                    else None
                )
                if re_read is None:
                    outputs.append(position)
                    continue
                used_re_reads[(category, re_read["arguments_key"])] = re_read
                outputs.extend(
                    {**subgroup, UNIT_KEY: position[UNIT_KEY]}
                    for subgroup in re_read["positions"]
                )
            caps.setdefault(category, len(category_jobs))
            round_failed = any(
                "error" in records[(job.category, job.arguments_key)] for job in category_jobs
            )

            if len(category_jobs) == 1:
                stopped = STOPPED_FINAL_ROUND_FAILED if round_failed else STOPPED_CONVERGED
            elif len(outputs) >= len(active[category]):
                # Counted AFTER the re-read, so a round that folds a little
                # and splits more reads as no progress and ends the
                # category. That is the right reading -- the set did not
                # shrink -- and it is what keeps the loop finite now that a
                # round can grow one.
                stopped = STOPPED_NO_PROGRESS
            elif len(outputs) <= EXTRACT_SLICE:
                # The next round is ONE call over everything left, which is
                # the state this pass exists to reach. The cap bounds the
                # multi-slice rounds; it never denies the converging one.
                still[category] = outputs
                continue
            elif round_number >= caps[category]:
                stopped = STOPPED_ROUND_CAP
            else:
                still[category] = outputs
                continue

            finished[category] = outputs
            outcomes.append(
                CategoryOutcome(
                    category=category,
                    raw_positions=raw_counts[category],
                    final_positions=len(outputs),
                    round_one_slices=caps[category],
                    rounds=round_number,
                    stopped=stopped,
                )
            )
            log(
                f"  {category}: {raw_counts[category]} raw -> {len(outputs)} "
                f"over {round_number} round(s) ({stopped})"
            )
        active = still

    positions = [
        _as_position(position) for category in sorted(finished) for position in finished[category]
    ]
    positions.extend(passed_through)
    return ConsolidationResult(
        positions=tuple(positions),
        records=tuple(used.values()),
        outcomes=tuple(sorted(outcomes, key=lambda outcome: outcome.category)),
        categories=categories,
        categories_passed_through=categories_passed_through,
        reads_retried=tally.retried,
        reads_reasked_after_retry=tally.reasked,
        reads_abandoned=tally.abandoned,
        re_reads=tuple(used_re_reads.values()),
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
