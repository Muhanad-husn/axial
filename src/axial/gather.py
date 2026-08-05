"""Phase A v1 slice 07 (issue #412): Gather -- what the authors at a name
actually disagree about (`specs/PRODUCT.md` §7.18, P0-13).

D12: "Gather cannot blow the context window, by construction. The model
never fetches. Code assembles a fixed packet per name (per member note:
author, year, the one-sentence claim, whose position, who it argues
against -- roughly 800 characters each) under a **hard character budget in
code, not in the prompt**. A name whose packet would exceed the budget is
split into batches, Gather runs per batch, and a short final call merges the
batch findings. Large names are the interesting ones, so batching is a
designed path, not an edge case."

D13: "Gather itself never reads full notes." This module never opens
`data/chunks/` and never touches a note's `chunk_text`. The packet fields
come from slice 02's already-persisted answer record and slice 06's
source-metadata read; that is the entire model input.

**The packet has a sixth field only when the note has one (issue #496).**
Frame 0.2 split `position_of` ("whose position is this?") from `position`
("what is that position?"), and the corpus is a permanent mix: 6,148
records were already on disk when the split shipped and are not being
re-interrogated. `build_packets` reads the new field on key presence alone;
`MemberPacket.position` is `None` when the record does not carry it. That
part of the contract is unchanged.

**Issue #500, D1: the bracket is reserved first, and `claim` takes whatever
is left of `MEMBER_PACKET_CHARS`.** The earlier render truncated the whole
line's tail, so whichever field sat last was the one a long packet lost --
measured live, that cost 22.4% of all rendered packets `arguing_against`
entirely, the one clause #490 measured as separating contested names from
uncontested ones. Reserving the bracket (`position_of`; `arguing_against`;
`position`, where present) whole and truncating `claim` into the remainder
means every bracket field survives whenever the packet fits under the cap
at all, and the loss moves to `claim` instead. See `render_packet` for the
arithmetic and the one degenerate case (a bracket that alone exceeds the
cap).

**D1's own premise was wrong at cap 400, and the cap moved to correct it,
same day.** "The bracket fields are short and bounded by construction" was
not measured before D1 shipped, and it is false: over the whole corpus the
bracket alone (`position_of`; `arguing_against`; `position` where present)
runs a median 221 characters against a 400 cap, p90 387, max 978. At 400,
707 notes (11.5%) hit the degenerate fallback -- the bracket alone met or
exceeded the cap before `claim` saw any remainder -- so the fix only took
`arguing_against`'s loss rate from 26.8% to 8.3%, not to zero, and every one
of that remaining 8.3% sits inside the 11.5% degenerate set; outside it,
zero. `MEMBER_PACKET_CHARS` moves to **800** to actually deliver what D1
promised: at 800 the degenerate rate is 0.1% (5 notes) and `arguing_against`
is lost nowhere outside it. The mechanism is unchanged -- reserve the
bracket, `claim` takes the remainder, the degenerate case falls back to
tail truncation -- only the number moves, and it stays one constant.

**This deliberately breaks the pre-0.2 byte-for-byte render guarantee** the
paragraph above used to make: a packet that hits the cap now renders
differently than it did before D1, whether or not it carries `position`,
because the truncation point moved. `GatherJob.key` changes for every
packet that used to be truncated, which is the corpus re-key issue #500
exists to pay for -- see `plans/name-layer-rekey/README.md`. A packet that
never hit the cap is untouched, since there was nothing to truncate either
way.

**The budget is two constants, both stated by §7.18 itself.**
`MEMBER_PACKET_CHARS` caps one rendered member (§7.18: "roughly 800
characters"), and `GATHER_PACKET_CHAR_BUDGET` caps the whole members block
of one call. The per-member cap is what makes the whole-block budget a
guarantee rather than a hope: without it a single pathological claim could
exceed the block budget on its own, and P0-13's observable is "no assembled
Gather prompt exceeds the limit, for any name, at any corpus size". Neither
number appears anywhere in a prompt -- that is D12's own named regression
risk, and `tests/ingestion/test_gather.py` checks for it directly.

**Two shapes of call, one pass name.** A name under the budget is one
`gather` call. A name over it is one `gather` call per batch plus one short
`gather` merge call over those findings -- the merge call carries the batch
findings and no packets at all, so it stays small however large the name is.

**Two outputs, prose and record.**

  1. **The name page** (slice 06's own file, `data/vault/names/`) gains a
     section under `DISAGREEMENT_HEADING`, replacing any section already
     there so a re-run never stacks two. Name-to-name links come from the
     model naming other things, filtered to the canonical names the index
     actually carries: a link to a page that does not exist is not a link.
  2. **The disagreement record** (`data/names/disagreements.jsonl`), one
     JSON record per name, in exactly the convention slice 02's per-note
     answer records set (`data/answers/<source_id>.jsonl`): the pass's
     answer artifact and its resume checkpoint are the same file. Each
     record carries the name, the member notes that fed it (per batch and
     in total), which batch each finding came from, whether the final text
     survived a merge call or came from a single under-budget call, and the
     disagreement text itself.

     This exists because **issue #447 is undecided**: Phase A v1 has no
     measure of quality yet, and every candidate instrument -- founder
     adjudication over a sample, a model panel, self-consistency across
     draws -- needs the same provenance. Writing it now is what keeps a
     later eval from having to re-run the corpus pass to recover where each
     disagreement came from.

**A finding can say "no disagreement" without prose.** The response's
`disagreement` field is nullable: a `null` means the authors gathered here
were read and genuinely do not disagree, distinct from a shape failure
(missing key, empty string), which is still re-asked. A `None` finding is
never written to the page -- `upsert_disagreement_section` removes
`DISAGREEMENT_HEADING` entirely rather than leaving an empty section -- but
it IS persisted in `disagreements.jsonl`, so a re-run never re-asks it. The
write loop selects the newest non-null record for a canonical name, falling
back to the newest record only once every one of them is null (#495): a
later null re-ask of the same name no longer takes an earlier real finding
off the page. Batched names drop null
batch findings before the merge call: an all-null name makes no merge call
at all, and a name with exactly one surviving finding uses it directly
without merging it against nothing. This is the fix for two measured
defects sharing one root cause (`data/logs/2026-07-29-gather-stratified-
sample/`): writing "the authors do not disagree" onto ~15,000 pages a full
pass would touch, and the merge prompt mistaking several such findings for
readings that disagree with EACH OTHER on four of the twenty biggest names
in the sample, including the three largest in the corpus.

**A merge handed real evidence never returns null.** #472 shipped that fix
above and, measured on the same 100-name sample after landing, regressed it:
`_GATHER_PROMPT_TEMPLATE`'s "respond with null instead of inventing a
dispute" made null the cheapest available batch answer (11 of 13 lost
findings, `data/logs/2026-07-29-gather-rerun-after-472/summary.md`), and the
merge step itself discarded real evidence on 2 names (`Syria`, `Michael
Mann`) by returning null even though every finding it was handed was
non-null. The batch prompt now asks for a genuine reading before null is
allowed; the merge step is a code invariant, not a prompt question -- when
`_gather_one`'s merge call is handed two or more surviving findings, its
result is validated (`complete_json`'s own bounded re-ask) and, if the model
still insists on null after that budget, code falls back to the surviving
findings' own text rather than silently dropping evidence the name already
paid for. A null disagreement can still happen, but only through the
all-batches-null path above, where no merge call is made at all.

**A finding that is only the literal word "null" or "none" is a structured
null, not text.** The prompt's own `"disagreement": null` example primes some
completions to echo the token back as a JSON *string* rather than the JSON
literal (measured live on the seeded 100-name sample, on `Russia` among
others), and a bare `"null"` string used to pass `parse_gather_response`'s
validation as a genuine finding. Fixed at that one parse boundary
(`_is_null_token`), which every path -- batch, merge, the single-survivor
shortcut -- already runs through, rather than in the prompt: wording cannot
be trusted not to re-trigger the same priming.

**Every finding is persisted before it is used**, keyed by a content hash of
the name's own rendered packets -- the same content-addressing
`axial.merge_names` uses, and for the same two reasons: this pass costs real
money per name, so an interrupted run must resume; and a changed upstream (a
re-merged alias map, a re-run interrogation) re-asks exactly the names whose
packets actually changed. Re-running `axial names materialize` wipes the
disagreement sections (it rewrites a page whose content differs); re-running
`axial names gather` restores them from the record at zero model cost.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.intake import NOT_ATTEMPTED, SOURCE_META_DIR, UNAVAILABLE
from axial.interrogate import _default_answers_dir, is_abstention
from axial.llm import GATHER_PASS_NAME, LLMClient, get_client
from axial.materialize import (
    MissingNoteContextError,
    load_alias_map,
    load_inventory,
    member_chunk_ids_for_node,
    name_page_paths,
)
from axial.merge_names import DEFAULT_ALIAS_MAP_PATH
from axial.model_json import ModelJsonError, complete_json, parse_model_json
from axial.names import (
    DEFAULT_INVENTORY_PATH,
    DEFAULT_NAMES_DATA_DIR,
    load_answer_records,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_vault_dir, split_source_id
from axial.query.reader import MalformedChunkIdError, source_id_from_chunk_id
from axial.vault import VaultError, bibliographic_value, read_source_meta
from axial.yaml_loader import SAFE_LOADER

# This pass's answer record AND its resume checkpoint, one file, mirroring
# `data/answers/<source_id>.jsonl` (slice 02) exactly -- see the module
# docstring's second output and issue #447.
DEFAULT_DISAGREEMENTS_PATH = DEFAULT_NAMES_DATA_DIR / "disagreements.jsonl"

# §7.18's own packet size: "per member note: author, year, the one-sentence
# claim, position_of, arguing_against, position (frame 0.2 records only) --
# roughly 800 characters". A rendered member is capped at this, so the block
# budget below is arithmetic rather than a hope: worst case a batch holds
# `GATHER_PACKET_CHAR_BUDGET // MEMBER_PACKET_CHARS` members, whatever a
# note's answers happen to contain.
#
# Issue #500, D1: `render_packet` reserves `position_of`, `arguing_against`
# and `position` first and truncates `claim` into whatever is left, rather
# than truncating the whole line's tail. Measured live, the old tail
# truncation cost `arguing_against` entirely in 22.4% of all rendered
# packets -- the one clause #490 measured as separating contested names from
# uncontested ones. Under this render every bracket field survives whenever
# the packet fits under the cap at all; the one degenerate case (a bracket
# that alone exceeds the cap) falls back to the old tail truncation, which
# is unchanged. Still a single constant: `claim`'s share is computed as the
# remainder, not a second tunable.
#
# The 400 this shipped with first was wrong (2026-07-30 correction, same
# day): the bracket is not "short and bounded" in practice -- measured over
# the whole corpus it runs a median 221 characters, p90 387, max 978 -- so
# at 400 the bracket alone met or exceeded the cap on 11.5% of notes (707),
# and D1 only took `arguing_against`'s loss rate from 26.8% to 8.3%, not to
# zero. 800 clears the measured p90 with room, and takes the degenerate
# share to 0.1% (5 notes). Still one constant; only the number moved.
MEMBER_PACKET_CHARS = 800

# The hard character budget (D12, P0-13): the largest members block one
# Gather call may carry. A construction limit on request size, exactly like
# `axial.merge_names.DEFAULT_MEMBER_CHAR_BUDGET` -- not a quality knob, not
# tuned, and deliberately never stated in the prompt. 20k characters is 25
# member packets at the current `MEMBER_PACKET_CHARS` (was 50 at 400;
# #500's cap correction halves the worst-case member count, not the
# guarantee itself), comfortably inside any model's context alongside the
# short prompt around it.
GATHER_PACKET_CHAR_BUDGET = 20_000

# A disagreement needs two parties. A name only one note ever mentions has
# no second author to disagree with, so no call is spent on it. Definitional,
# not a threshold.
_MIN_MEMBERS = 2

# Founder scope decision (2026-07-29, not a tuned heuristic constant): a name
# below this member count is skipped alongside the single-member gate above,
# before a packet is ever assembled or a model call made. Measured on a seeded 100-name stratified sample and the
# live index -- see `config/pipeline.yaml`'s `gather.min_members` comment for
# the full yield curve this number was read off. `_MIN_MEMBERS` above stays
# fixed at 2 (definitional); this is the separate, movable scope cut, always
# read from config via `_resolve_min_gather_members` so it can move in one
# line without touching this file.
DEFAULT_MIN_GATHER_MEMBERS = 10

# Bounded concurrent per-name workers. The work is I/O-bound in exactly the
# shape `axial.merge_names` already measured on this provider (issue #416: a
# serial pass over tens of thousands of independent short calls is a
# multi-hour job for a few dollars of spend), and 36 is the value that run
# settled on. Inherited rather than re-derived; `--workers` moves it.
#
# Raised 36 -> 48 by issue #623 on this pass's own measurement: a corpus pass
# of 2,082 calls ran 103.8 minutes at an EFFECTIVE concurrency of 20.9, and a
# Gather call's summed latency over that run was 2,171 minutes -- by far the
# largest model-latency pool of any pass in the pipeline. It is the wall-clock
# leader, and it was not saturating even the slots it had.
DEFAULT_WORKERS = 48

# The heading Gather owns on a name page. Everything from this line to the
# end of the page is Gather's; `upsert_disagreement_section` replaces it
# wholesale, so a re-run never stacks two sections.
DISAGREEMENT_HEADING = "## What the authors here disagree about"

_ABSTAINED = "(not stated in the passage)"

_GATHER_PROMPT_TEMPLATE = """\
Below are passages from academic books that all name the same thing: {name}.

Each line gives the book's author and year, what the passage claims in one \
sentence, whose position that is, what that position says where it was \
recorded, and who or what it argues against.

PASSAGES
{members}

Read every passage before deciding. Authors who make different claims about \
{name}, hold different positions, or argue against different targets are \
already in disagreement, whether or not either one names the other -- that \
is usually there among this many passages even when no author explicitly \
rebuts another. Say what the disagreement actually is, in a few sentences, \
naming who holds which side. Reach for "disagreement": null only once that \
full reading turns up no such tension anywhere -- not because the \
disagreement takes more than one sentence to state, but because these \
authors genuinely do not differ. null is a last resort, not the default \
answer.

RESPONSE. Reply with ONLY a JSON object, no prose and no markdown fences:
{{"disagreement": "<a few sentences, or null if they do not disagree>", \
"names": ["<other named thing the disagreement runs between>", ...]}}
"""

_MERGE_PROMPT_TEMPLATE = """\
{name} named more passages than one call could read, so they were read in \
separate parts. Below is what each part found. All of them describe the SAME \
set of authors at {name} -- treat them as partial evidence about one name, \
never as competing claims to weigh against each other.

FINDINGS
{findings}

Write one account of what these authors disagree about, drawing on all the \
findings together. If, taken together, the findings show no real \
disagreement among the authors, respond with "disagreement": null.

RESPONSE. Reply with ONLY a JSON object, no prose and no markdown fences:
{{"disagreement": "<a few sentences, or null if they do not disagree>", \
"names": ["<other named thing the disagreement runs between>", ...]}}
"""


class GatherError(Exception):
    """Base class for all gather errors."""


class GatherResponseError(GatherError):
    """Raised when a response is not usable as a disagreement finding -- a
    shape failure, so it is re-askable within `complete_json`'s own bounded
    budget."""


class _MergeNullDespiteEvidenceError(GatherResponseError):
    """Internal to `_gather_one`'s merge step. Raised by the merge call's own
    `validate` when the response parses fine but is null anyway, even though
    the merge was handed at least one real batch finding. A subclass of
    `GatherResponseError` so `complete_json` re-asks it exactly like any
    other content-shaped failure, but caught ONLY around the merge call
    itself (never by the outer per-name handler) so a genuinely malformed
    merge response still fails the whole name exactly as before -- only the
    specific "null against real evidence" shape gets the code fallback
    below."""


class DisagreementRecordsCorruptError(GatherError):
    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        super().__init__(f"disagreement record {path} is corrupt at line {line_no}: {cause}")


# ---------------------------------------------------------------------------
# The packet: five fields per member note, six under frame 0.2, and nothing
# else (D13)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemberPacket:
    """One member note's whole contribution to a Gather call. There is no
    seventh field, and there is deliberately no `chunk_text`."""

    chunk_id: str
    author: Any
    year: Any
    claim: str
    position_of: str
    arguing_against: str
    # `None` means the note's answer record carries no `position` key at all
    # -- it was interrogated under frame 0.1, before the split (issue #496).
    # Structurally distinct from an abstention and from an empty answer, both
    # of which are strings `_render_answer` produced. An absent `position`
    # renders as nothing, so the packet hashes exactly as it did before the
    # field existed. Last and defaulted so every existing positional
    # construction keeps working.
    position: str | None = None


def _render_answer(value: Any) -> str:
    """One answer field, rendered for a packet line: the free answer
    verbatim when there is one, a plain marker for D7's explicit abstention
    or a missing answer -- never a guess. A list answer (`arguing_against`)
    is joined; an empty list is a real answer ("nobody"), not an
    abstention."""
    if value is None or is_abstention(value):
        return _ABSTAINED
    if isinstance(value, list):
        parts = [
            part if isinstance(part, str) else json.dumps(part, ensure_ascii=False)
            for part in value
        ]
        return ", ".join(parts) if parts else "(nobody named)"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


# Fix (2026-07-29, gather stratified sample): `axial.vault.bibliographic_
# value` deliberately renders the `unavailable`/`not_attempted` sentinels as
# themselves -- correct for a note's own frontmatter, where a visible gap
# beats a blank that reads like an answer. A Gather packet is not
# frontmatter: it hands the value to the model as if it were a person, and
# the model wrote "the 'unavailable (2000)' author" into a disagreement (2 of
# 100 sampled entries). This is the one place that sentinel is caught before
# it reaches a prompt.
_SOURCE_ID_YEAR_TOKEN = re.compile(r"-\d{4}$")


def _author_fallback_from_source_id(source_id: str) -> str:
    """A readable stand-in for `author` when the source-metadata record's own
    field is a sentinel. `source_id` is `<author>-<year>-<hash12>` by
    construction (`axial.envelope.compute_source_id`), so its own stem is a
    real, legible name -- never invented, and the one piece of provenance
    that cannot itself be missing, since no note reaches Gather without a
    source_id. `heydemann-2000-66701ffbb36c` -> `Heydemann`."""
    stem, _hash12 = split_source_id(source_id)
    stem = _SOURCE_ID_YEAR_TOKEN.sub("", stem)
    return stem.replace("-", " ").title()


def render_packet(packet: MemberPacket) -> str:
    """How ONE member note appears in the prompt, capped at
    `MEMBER_PACKET_CHARS` (§7.18's "roughly 800 characters each"). The cap
    is what makes `GATHER_PACKET_CHAR_BUDGET` a guarantee rather than an
    average.

    `position` is emitted only when the packet carries one -- read on KEY
    PRESENCE (issue #496), never on truthiness or `frame_version`. That part
    of the pre-0.2 contract is unchanged.

    **The bracket is reserved first; `claim` takes whatever is left (issue
    #500, D1).** Measured over the live corpus, the old tail-truncation
    render (whichever field fell last in the string lost the most) cost
    22.4% of all rendered packets `arguing_against` entirely -- the one
    clause #490 measured as separating contested names from uncontested
    ones (1.9x-2.4x lift), which Phase B's contestedness derivation reads.
    `claim` is the field that actually runs long (median 245 of a 483-char
    untruncated packet), and the bracket is NOT reliably short: measured
    live it runs a median 221 characters, p90 387, max 978. So every
    bracket field is rendered in full and `claim` alone is truncated into
    the remainder of `MEMBER_PACKET_CHARS`. This is a single arithmetic
    split, not a second tunable: no per-field budget is stated anywhere,
    only `claim`'s share is computed as what is left after the fixed parts.

    **The one degenerate case:** a bracket long enough that, combined with
    `author`/`year`, it alone meets or exceeds the cap -- there is no
    remainder to give `claim` at all. That falls back to the pre-D1 render
    (the whole line assembled, then the tail truncated), which introduces
    nothing new. At the cap this shipped with first, 400, that path fired
    on 11.5% of the corpus (the bracket's own p90 sits close to 400), which
    is why the cap moved to 800 the same day: it clears the measured p90
    with room, taking the degenerate share to 0.1%.

    This deliberately breaks the pre-0.2 byte-for-byte guarantee this
    docstring used to state: a packet that hits the cap now renders
    different bytes than it used to, whether or not it carries `position`,
    because the truncation point moved from the end of the bracket to
    inside `claim`. That is the corpus re-key issue #500 exists to pay for,
    not an accident -- `GatherJob.key` changes for every packet that used to
    be truncated, and `disagreements.jsonl` is re-decided once, in slice 03
    of the name-layer-rekey sprint. A packet that never hit the cap renders
    the same bytes it always did, because there was nothing to truncate
    either way."""
    bracket = [
        f"position of: {packet.position_of}",
        f"arguing against: {packet.arguing_against}",
    ]
    if packet.position is not None:
        bracket.append(f"position: {packet.position}")
    head = f"{packet.author} ({packet.year}): "
    tail = f" [{'; '.join(bracket)}]"

    claim_budget = MEMBER_PACKET_CHARS - len(head) - len(tail)
    if claim_budget < 1:
        # Degenerate: the bracket (plus author/year) alone leaves no room
        # for any of `claim`. Fall back to the pre-D1 whole-line render, tail
        # truncated -- unchanged from before this issue.
        rendered = f"{head}{packet.claim}{tail}"
    else:
        claim = packet.claim
        if len(claim) > claim_budget:
            claim = claim[: claim_budget - 1].rstrip() + "…"
        rendered = f"{head}{claim}{tail}"

    if len(rendered) > MEMBER_PACKET_CHARS:
        rendered = rendered[: MEMBER_PACKET_CHARS - 1].rstrip() + "…"
    return rendered


def build_packets(
    member_chunk_ids: list[str],
    answers_by_chunk_id: dict[str, dict[str, Any]],
    author_year: dict[str, tuple[Any, Any]],
) -> list[MemberPacket]:
    """One packet per member note that actually has an interrogation answer.
    A member with no answer record contributes nothing -- there are no
    fields to carry -- rather than a line of markers.

    `position` is read on KEY PRESENCE, never on truthiness or on the
    record's `frame_version` (issue #496): a record that carries the key with
    an abstention in it renders that abstention like any other field, and a
    record written before the key existed gets `None`, which renders
    nothing at all."""
    packets: list[MemberPacket] = []
    for chunk_id in member_chunk_ids:
        record = answers_by_chunk_id.get(chunk_id)
        if record is None:
            continue
        answers = record.get("answers") or {}
        author, year = author_year.get(record.get("source_id"), (None, None))
        packets.append(
            MemberPacket(
                chunk_id=chunk_id,
                author=author,
                year=year,
                claim=_render_answer(answers.get("claim")),
                position_of=_render_answer(answers.get("position_of")),
                arguing_against=_render_answer(answers.get("arguing_against")),
                position=(_render_answer(answers["position"]) if "position" in answers else None),
            )
        )
    return packets


def split_into_batches(
    packets: list[MemberPacket], budget: int = GATHER_PACKET_CHAR_BUDGET
) -> list[list[MemberPacket]]:
    """`packets` split into as few batches as fit under `budget` rendered
    characters each -- one batch (one call) for a name under the budget,
    several for a large name. Order-preserving and deterministic. Because
    every member is capped at `MEMBER_PACKET_CHARS`, a batch can never be
    over budget on a single member."""
    batches: list[list[MemberPacket]] = []
    current: list[MemberPacket] = []
    size = 0
    for packet in packets:
        cost = len(render_packet(packet)) + 1
        if current and size + cost > budget:
            batches.append(current)
            current, size = [], 0
        current.append(packet)
        size += cost
    if current:
        batches.append(current)
    return batches


def compose_gather_prompt(canonical: str, packets: list[MemberPacket]) -> str:
    """One batch's prompt: the name, its member packets, and the judgment
    being asked for. The budget that decided how many packets are here is
    NOT stated (D12) -- how much goes in front of the model at once is this
    module's business, not the model's."""
    members = "\n".join(f"- {render_packet(packet)}" for packet in packets)
    return _GATHER_PROMPT_TEMPLATE.format(name=repr(canonical), members=members)


def compose_merge_prompt(canonical: str, findings: list[str]) -> str:
    """The short final call over a batched name: the batch FINDINGS only,
    never the packets they came from, so this call's size is bounded by the
    number of batches rather than by the size of the name."""
    rendered = "\n".join(f"{index}. {finding}" for index, finding in enumerate(findings, start=1))
    return _MERGE_PROMPT_TEMPLATE.format(name=repr(canonical), findings=rendered)


# Characters `_is_null_token` strips from both ends before comparing -- plain
# whitespace plus a stray layer of quote marks a completion sometimes wraps
# a literal token in (e.g. the model echoing `"null"` as a JSON *string*
# rather than emitting JSON `null`). `str.strip` removes these repeatedly
# from each end only, so a legitimate finding that merely contains the word
# in its middle is never touched.
_NULL_TOKEN_STRIP_CHARS = " \t\r\n'\""


def _is_null_token(text: str) -> bool:
    """True when `text` is nothing but the word "null" or "none",
    case-insensitively, once surrounding whitespace and quote marks are
    stripped -- and only then. Fix (2026-07-29): re-run of this same fix on
    the seeded 100-name sample measured 3 records whose `"disagreement"`
    was the JSON *string* `"null"` rather than the JSON literal -- the
    batch prompt's own `"disagreement": null` example priming a completion
    to echo the token back as quoted text (`Russia` at 429 members among
    them). `parse_gather_response` used to accept that string as a genuine
    finding. Caught here, at the one parse boundary every path (batch,
    merge, the single-survivor shortcut) already goes through, rather than
    in the prompt -- wording cannot be trusted not to re-trigger the same
    priming."""
    return text.strip(_NULL_TOKEN_STRIP_CHARS).lower() in ("null", "none")


def parse_gather_response(raw: str) -> tuple[str | None, list[str]]:
    """Parse one response into `(disagreement, names)`. `disagreement` is
    `None` when the finding is a structured null -- the authors gathered
    here genuinely do not disagree -- and a non-empty string otherwise.
    Raises `GatherResponseError` on a shape failure -- not an object, a
    missing `disagreement` key, or a present-but-empty string -- which is
    response noise rather than a judgment, and so is re-asked by
    `complete_json`. A `None` disagreement is never a shape failure: it is
    the one way a finding has to say "no disagreement" without prose (the
    root cause behind a merge call mistaking several "they do not disagree"
    findings for claims to adjudicate between). A disagreement that is
    nothing but the literal word "null" or "none" (`_is_null_token`) is
    normalized to `None` here too -- a JSON *string* saying "null" is the
    same judgment as JSON `null`, not a real finding.

    `names` is whatever the model named; it is NOT trusted as a link here.
    `resolve_links` filters it against the index at write time, so a
    re-merged index re-filters without re-asking anything."""
    try:
        data = parse_model_json(raw)
    except ModelJsonError as exc:
        raise GatherResponseError(f"gather response was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GatherResponseError("gather response must be a JSON object")
    if "disagreement" not in data:
        raise GatherResponseError("gather response carried no 'disagreement' key")
    disagreement = data["disagreement"]
    if disagreement is not None:
        if not isinstance(disagreement, str) or not disagreement.strip():
            raise GatherResponseError("gather response carried an empty 'disagreement' string")
        disagreement = disagreement.strip()
        if _is_null_token(disagreement):
            disagreement = None
    raw_names = data.get("names")
    names = [
        name for name in (raw_names if isinstance(raw_names, list) else []) if isinstance(name, str)
    ]
    return disagreement, names


def resolve_links(names: list[str], canonical: str, index: set[str]) -> list[str]:
    """The name-to-name links for one disagreement: the names the model
    referred to, kept only where the index already carries that canonical
    (§7.18: "where the disagreement runs between two names the index already
    carries"). A link to a page that does not exist is not a link, and a
    name never links to itself."""
    links: list[str] = []
    for name in names:
        if name in index and name != canonical and name not in links:
            links.append(name)
    return links


# ---------------------------------------------------------------------------
# The write: onto slice 06's own page, replacing rather than stacking
# ---------------------------------------------------------------------------


def render_disagreement_section(disagreement: str, links: list[str]) -> str:
    lines = [DISAGREEMENT_HEADING, "", disagreement]
    if links:
        lines += ["", "**Runs between:** " + ", ".join(f"[[{link}]]" for link in links)]
    return "\n".join(lines) + "\n"


def upsert_disagreement_section(page_text: str, disagreement: str | None, links: list[str]) -> str:
    """`page_text` with Gather's section replaced (or appended when there is
    none). Everything from `DISAGREEMENT_HEADING` to the end of the page is
    Gather's own, so a re-run rewrites it in place rather than stacking a
    second section under the first.

    `disagreement is None` (the authors gathered here genuinely do not
    disagree, or no non-null record survives for this name) means no section
    at all -- not an empty heading. This function still clears whatever it
    is handed; it is `run_gather`'s write loop that decides what that is,
    and it selects the newest non-null record for a canonical, falling back
    to the newest record only once every one of them is null (#495) -- so a
    genuine finding is no longer displaced by a later null re-ask of the
    same name."""
    head = page_text.split(DISAGREEMENT_HEADING)[0].rstrip("\n")
    if disagreement is None:
        return head + "\n"
    return head + "\n\n" + render_disagreement_section(disagreement, links)


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _source_ids_of(chunk_ids: list[str]) -> frozenset[str]:
    """The distinct `source_id`s `chunk_ids` resolve to (issue #677's
    `units_asked_touching_new`), mirroring `axial.merge_names._source_ids_
    of` -- a malformed chunk_id simply contributes nothing."""
    ids: set[str] = set()
    for chunk_id in chunk_ids:
        try:
            ids.add(source_id_from_chunk_id(chunk_id))
        except MalformedChunkIdError:
            continue
    return frozenset(ids)


@dataclass(frozen=True)
class GatherJob:
    """One name's whole Gather unit of work: the member packets, already
    split into the batches the budget allows."""

    canonical: str
    batches: tuple[tuple[MemberPacket, ...], ...]

    @property
    def chunk_ids(self) -> list[str]:
        return [packet.chunk_id for batch in self.batches for packet in batch]

    @property
    def key(self) -> str:
        """Content hash of this name's own rendered packets -- the record's
        key. Content-addressed on purpose: a name whose packets are
        unchanged reuses its recorded finding, and one whose membership or
        whose members' answers changed is re-asked, without anyone tracking
        which upstream run produced what."""
        payload = json.dumps(
            [[render_packet(packet) for packet in batch] for batch in self.batches],
            ensure_ascii=False,
            sort_keys=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _gather_one(
    job: GatherJob, client: LLMClient
) -> tuple[GatherJob, dict[str, Any] | None, str | None]:
    """Gather one name. Runs on a worker thread.

    Returns `(job, record, failure_reason)`: `record` is the disagreement
    record to persist, or `None` on a content-shaped failure. Only content
    failures are caught here -- a transport-level failure propagates and is
    fatal, exactly as in `axial.merge_names._decide_batch`. This function
    NEVER writes to disk; the single result-collecting thread does the
    append, which is what keeps resumability intact under concurrency."""
    started = time.monotonic()
    batch_records: list[dict[str, Any]] = []
    names: list[str] = []
    try:
        for index, batch in enumerate(job.batches, start=1):
            prompt = compose_gather_prompt(job.canonical, list(batch))
            raw = complete_json(
                client, prompt, pass_name=GATHER_PASS_NAME, validate=parse_gather_response
            )
            finding, batch_names = parse_gather_response(raw)
            batch_records.append(
                {
                    "batch": index,
                    "chunk_ids": [packet.chunk_id for packet in batch],
                    "finding": finding,
                }
            )
            # A null finding has no names to link -- there is no disagreement
            # for a linked name to run between.
            if finding is not None:
                names.extend(batch_names)

        # Null findings are dropped before the merge step (§7.18): a batch
        # that found nothing carries no evidence for the merge call to read.
        # If every batch came back null, the name itself is null and no
        # merge call is made at all. If exactly one batch found something,
        # that finding IS the name's disagreement -- merging a single
        # reading against nothing is not a merge. Only two or more surviving
        # findings are actually merged.
        surviving = [record for record in batch_records if record["finding"] is not None]
        if not surviving:
            disagreement = None
            merged = False
        elif len(surviving) == 1:
            disagreement = surviving[0]["finding"]
            merged = False
        else:
            findings = [record["finding"] for record in surviving]
            prompt = compose_merge_prompt(job.canonical, findings)

            def _validate_merge(raw: str, _findings: list[str] = findings) -> None:
                # Same shape check every response gets (`parse_gather_
                # response` itself re-asks on a missing key or an empty
                # string); on top of it, the invariant (§7.18, this fix):
                # the merge was handed at least one real finding, so a null
                # result here is never an honest reading and gets the same
                # bounded re-ask as any other content-shaped failure.
                merged_disagreement, _names = parse_gather_response(raw)
                if merged_disagreement is None:
                    raise _MergeNullDespiteEvidenceError(
                        f"merge response was null against {len(_findings)} "
                        "surviving batch finding(s)"
                    )

            try:
                raw = complete_json(
                    client, prompt, pass_name=GATHER_PASS_NAME, validate=_validate_merge
                )
                disagreement, merge_names = parse_gather_response(raw)
                names = merge_names or names
            except _MergeNullDespiteEvidenceError:
                # complete_json already re-asked up to its own bounded
                # budget and the model still insists real evidence merges to
                # nothing. There is no honest reading under which two
                # genuine disagreements combine to null, so code -- not
                # another model call -- makes the record whole rather than
                # silently dropping evidence this name already paid for: the
                # surviving findings themselves, joined, become the
                # disagreement.
                disagreement = " ".join(findings)
            merged = True
    except (ModelJsonError, GatherResponseError) as exc:
        return job, None, str(exc)

    record = {
        "name_key": job.key,
        "canonical": job.canonical,
        # Issue #447's provenance: which member notes fed this disagreement,
        # in total and per batch, and whether the text on the page survived
        # a merge call or came straight from one under-budget call.
        "chunk_ids": job.chunk_ids,
        "batches": batch_records,
        "merged": merged,
        "disagreement": disagreement,
        "names": names,
        "pass": GATHER_PASS_NAME,
        "model": client.model_for_pass(GATHER_PASS_NAME),
        "gathered_at": _utc_now(),
    }
    print(
        f"gather: {job.canonical!r} answered ({len(job.batches)} batch(es)) "
        f"in {time.monotonic() - started:.1f}s",
        file=sys.stderr,
    )
    return job, record, None


def _resolve_min_gather_members(config_path: Path) -> int:
    """Read `gather.min_members` from `config_path`, falling back to
    `DEFAULT_MIN_GATHER_MEMBERS` when the file or the key is absent -- the
    same config-then-fallback shape every other pipeline tunable uses (e.g.
    `axial.retrieve.loop._resolve_step_budget`)."""
    if not config_path.is_file():
        return DEFAULT_MIN_GATHER_MEMBERS
    with config_path.open("r", encoding="utf-8") as handle:
        document = yaml.load(handle, Loader=SAFE_LOADER) or {}
    gather_config = document.get("gather") or {}
    return int(gather_config.get("min_members", DEFAULT_MIN_GATHER_MEMBERS))


def load_disagreements(path: Path) -> dict[str, dict[str, Any]]:
    """Every recorded disagreement, keyed by `name_key` -- the inverse of
    the append, `{}` before the first run."""
    records = load_checkpoint_records(path, DisagreementRecordsCorruptError)
    return {record["name_key"]: record for record in records}


def _select_by_canonical(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per canonical name, the record the write loop should read: the newest
    non-null record, falling back to the newest record when every one of
    them is null (#495). `records` must already be in file order, oldest
    first -- `load_checkpoint_records`'s own return -- since "newest" is a
    file-order question a dict keyed by `name_key` cannot answer: one
    canonical can carry more than one packet hash (an upstream re-render
    changes the hash without changing the canonical), and Python keeps a
    key's ORIGINAL insertion position on overwrite, which throws file order
    away entirely."""
    newest_any: dict[str, dict[str, Any]] = {}
    newest_non_null: dict[str, dict[str, Any]] = {}
    for record in records:
        canonical = record["canonical"]
        newest_any[canonical] = record
        if record["disagreement"] is not None:
            newest_non_null[canonical] = record
    return {**newest_any, **newest_non_null}


def load_gather_context(
    answers_dir: Path, source_meta_dir: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, tuple[Any, Any]]]:
    """The two lookups `build_packets` needs: every note's persisted answer
    record, keyed by `chunk_id`, and each source's author/year off slice
    06's source metadata, keyed by `source_id`. Factored out of `run_gather`
    (issue #478) so the grounding eval (`axial.gather_eval`) can reconstruct
    the exact packet Gather saw from a disagreement record's own
    `chunk_ids`, through the same lookup, rather than re-deriving it."""
    answers_by_chunk_id = {
        record["chunk_id"]: record
        for record in load_answer_records(answers_dir)
        if "answers" in record
    }
    author_year: dict[str, tuple[Any, Any]] = {}
    for record in answers_by_chunk_id.values():
        source_id = record.get("source_id")
        if source_id is None or source_id in author_year:
            continue
        try:
            source_meta = read_source_meta(source_id, source_meta_dir)
        except VaultError as exc:
            raise MissingNoteContextError(
                source_id, "source-metadata record", "axial ingest"
            ) from exc
        author = bibliographic_value(source_meta, "author")
        if author in (UNAVAILABLE, NOT_ATTEMPTED):
            author = _author_fallback_from_source_id(source_id)
        author_year[source_id] = (author, bibliographic_value(source_meta, "date"))
    return answers_by_chunk_id, author_year


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------


def run_gather(
    *,
    alias_map_path: Path | None = None,
    inventory_path: Path | None = None,
    answers_dir: Path | None = None,
    source_meta_dir: Path | None = None,
    vault_dir: Path | None = None,
    disagreements_path: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    limit: int | None = None,
    workers: int = DEFAULT_WORKERS,
) -> dict[str, Any]:
    """Gather every name the index carries: write what its authors disagree
    about onto its slice 06 name page, and a per-name disagreement record to
    `disagreements_path` (§7.18, D12).

    Reads slice 05's alias map, slice 04's inventory and slice 02's answer
    records; never reads `data/chunks/` (D13). One call per name under the
    budget; one call per batch plus a short merge call over a name above it.
    Every record is appended as it is produced, on the single
    result-collecting thread, so an interrupted run resumes from exactly
    what is on disk and a re-run over unchanged packets makes no model call
    at all.

    `client`, when given, is used by every worker; otherwise one real client
    is built here and shared the same way.

    **Issue #677: `units_total`/`units_reused`/`units_asked`/`units_asked_
    touching_new`.** `units_total` is `len(jobs)` (every name in scope, past
    the member-count gates); `units_reused` is how many of those already had
    a disagreement record on disk BEFORE this run's own worker pool started
    (the `reused` count already returned under `"reused"`, computed the
    moment `pending` is); `units_asked` is `units_total - units_reused`,
    i.e. `len(pending)`. `units_asked_touching_new` is the subset of
    `pending` whose own member `chunk_ids` touch a source absent from
    EVERY disagreement record already on disk at the start of this run --
    `disagreements.jsonl` is read for this directly (issue #678: a
    disagreement record already carries the `chunk_ids` it was written
    from), so no separate manifest is needed to answer "which sources has a
    prior run of this pass already seen". Empty (a first-ever run, nothing
    recorded yet) means every asked name counts as touching new.
    """
    answers_dir = (
        Path(answers_dir) if answers_dir is not None else _default_answers_dir(config_path)
    )
    source_meta_dir = Path(source_meta_dir) if source_meta_dir is not None else SOURCE_META_DIR
    vault_dir = Path(vault_dir) if vault_dir is not None else default_vault_dir(config_path)
    alias_map_path = Path(alias_map_path) if alias_map_path is not None else DEFAULT_ALIAS_MAP_PATH
    inventory_path = Path(inventory_path) if inventory_path is not None else DEFAULT_INVENTORY_PATH
    disagreements_path = (
        Path(disagreements_path) if disagreements_path is not None else DEFAULT_DISAGREEMENTS_PATH
    )

    nodes = load_alias_map(alias_map_path)
    inventory = load_inventory(inventory_path)
    index = {node["canonical"] for node in nodes}
    page_paths = name_page_paths(vault_dir, nodes)

    answers_by_chunk_id, author_year = load_gather_context(answers_dir, source_meta_dir)

    min_gather_members = _resolve_min_gather_members(config_path)

    jobs: list[GatherJob] = []
    skipped_single_member = 0
    skipped_below_min_members = 0
    for node in sorted(nodes, key=lambda n: n["canonical"]):
        # Issue #508: the numeral-only and apparatus-pointer gates that used
        # to sit here are gone. Both predicates now cut at inventory time
        # (`axial.names.iter_name_occurrences`), so no such surface reaches
        # the alias map and no such node reaches this loop.
        packets = build_packets(
            member_chunk_ids_for_node(node, inventory), answers_by_chunk_id, author_year
        )
        if len(packets) < _MIN_MEMBERS:
            skipped_single_member += 1
            continue
        # Founder scope decision (2026-07-29): a name below the configured
        # member count is not asked about -- skipped here, before a packet
        # is assembled or a model call made, same as the gates above. See
        # `DEFAULT_MIN_GATHER_MEMBERS`'s own comment for the measured yield
        # curve behind the cut.
        if len(packets) < min_gather_members:
            skipped_below_min_members += 1
            continue
        batches = split_into_batches(packets)
        jobs.append(GatherJob(node["canonical"], tuple(tuple(batch) for batch in batches)))

    records = load_disagreements(disagreements_path)
    pending = [job for job in jobs if job.key not in records]
    reused = len(jobs) - len(pending)
    to_attempt = pending if limit is None else pending[:limit]

    # Issue #677: the four `units_*` counters, computed from `records` --
    # the ledger's own state loaded above, before this run's `--limit` trims
    # `pending` down to `to_attempt`, let alone before a single call goes
    # out. `prev_source_ids` is every source id ANY disagreement record
    # already on disk was written from (issue #678: the record's own
    # `chunk_ids` already carries this, so no new manifest is needed).
    prev_source_ids: set[str] = set()
    for record in records.values():
        prev_source_ids.update(_source_ids_of(record.get("chunk_ids") or []))

    units_total = len(jobs)
    units_reused = reused
    units_asked = units_total - units_reused
    units_asked_touching_new = sum(
        1
        for job in pending
        if not prev_source_ids or not _source_ids_of(job.chunk_ids).issubset(prev_source_ids)
    )

    # Every record ever appended for this name, oldest first -- the write
    # loop below selects from this per canonical, not per the current job
    # key, so an earlier finding a later re-render re-asked as null is not
    # lost (#495). `records` above stays keyed by `name_key`; it is the
    # resume path's own lookup and untouched.
    ordered_records = load_checkpoint_records(disagreements_path, DisagreementRecordsCorruptError)

    print(
        f"gather: {len(nodes)} name(s), "
        f"{skipped_single_member} skipped with fewer than "
        f"{_MIN_MEMBERS} member note(s), {skipped_below_min_members} skipped below the "
        f"configured {min_gather_members}-member scope threshold, {len(jobs)} to gather; "
        f"{reused} already recorded, "
        f"{len(to_attempt)} to ask now ({len(pending) - len(to_attempt)} more pending) "
        f"across {max(workers, 1)} worker(s)",
        file=sys.stderr,
    )

    called = 0
    failed = 0
    batch_calls = 0
    merge_calls = 0
    model: str | None = None
    if to_attempt:
        # Built once, here, and shared by every worker -- so a misconfigured
        # provider fails before any thread starts.
        if client is None:
            client = get_client(config_path=config_path)
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
            futures = {executor.submit(_gather_one, job, client): job for job in to_attempt}
            for future in as_completed(futures):
                job = futures[future]
                _job, record, failure_reason = future.result()
                if record is None:
                    print(f"gather: {job.canonical!r} failed: {failure_reason}", file=sys.stderr)
                    failed += 1
                    continue
                append_checkpoint_record(disagreements_path, record)
                records[job.key] = record
                ordered_records.append(record)
                model = record["model"]
                called += 1
                batch_calls += len(record["batches"])
                merge_calls += 1 if record["merged"] else 0

    by_canonical = _select_by_canonical(ordered_records)

    written = 0
    for job in jobs:
        record = by_canonical.get(job.canonical)
        path = page_paths.get(job.canonical)
        if record is None or path is None or not path.is_file():
            continue
        links = resolve_links(record.get("names") or [], job.canonical, index)
        current = path.read_text(encoding="utf-8")
        text = upsert_disagreement_section(current, record["disagreement"], links)
        if text != current:
            path.write_text(text, encoding="utf-8")
            written += 1

    return {
        "pass": GATHER_PASS_NAME,
        "model": model,
        "vault_dir": str(vault_dir),
        "disagreements_path": str(disagreements_path),
        "names": len(nodes),
        "names_skipped_single_member": skipped_single_member,
        "names_skipped_below_min_members": skipped_below_min_members,
        "min_gather_members": min_gather_members,
        "names_gathered": len(jobs),
        "asked": called,
        "reused": reused,
        "failed": failed,
        "units_total": units_total,
        "units_reused": units_reused,
        "units_asked": units_asked,
        "units_asked_touching_new": units_asked_touching_new,
        "batch_calls": batch_calls,
        "merge_calls": merge_calls,
        "pages_written": written,
        "workers": max(workers, 1),
        "limit": limit,
    }
