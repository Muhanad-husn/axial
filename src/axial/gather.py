"""Phase A v1 slice 07 (issue #412): Gather -- what the authors at a name
actually disagree about (`specs/PRODUCT.md` §7.18, P0-13).

D12: "Gather cannot blow the context window, by construction. The model
never fetches. Code assembles a fixed packet per name (per member note:
author, year, the one-sentence claim, whose position, who it argues
against -- roughly 400 characters each) under a **hard character budget in
code, not in the prompt**. A name whose packet would exceed the budget is
split into batches, Gather runs per batch, and a short final call merges the
batch findings. Large names are the interesting ones, so batching is a
designed path, not an edge case."

D13: "Gather itself never reads full notes." This module never opens
`data/chunks/` and never touches a note's `chunk_text`. The five packet
fields come from slice 02's already-persisted answer record and slice 06's
source-metadata read; that is the entire model input.

**The budget is two constants, both stated by §7.18 itself.**
`MEMBER_PACKET_CHARS` caps one rendered member (§7.18: "roughly 400
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
`DISAGREEMENT_HEADING` entirely rather than leaving an empty section, so a
re-run can take a section away, not just add one -- but it IS persisted in
`disagreements.jsonl`, so a re-run never re-asks it. Batched names drop null
batch findings before the merge call: an all-null name makes no merge call
at all, and a name with exactly one surviving finding uses it directly
without merging it against nothing. This is the fix for two measured
defects sharing one root cause (`data/logs/2026-07-29-gather-stratified-
sample/`): writing "the authors do not disagree" onto ~15,000 pages a full
pass would touch, and the merge prompt mistaking several such findings for
readings that disagree with EACH OTHER on four of the twenty biggest names
in the sample, including the three largest in the corpus.

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
    is_apparatus_pointer_shaped,
    is_numeral_only_surface,
    load_answer_records,
)
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_vault_dir, split_source_id
from axial.vault import VaultError, bibliographic_value, read_source_meta

# This pass's answer record AND its resume checkpoint, one file, mirroring
# `data/answers/<source_id>.jsonl` (slice 02) exactly -- see the module
# docstring's second output and issue #447.
DEFAULT_DISAGREEMENTS_PATH = DEFAULT_NAMES_DATA_DIR / "disagreements.jsonl"

# §7.18's own packet size: "per member note: author, year, the one-sentence
# claim, position_of, arguing_against -- roughly 400 characters". A rendered
# member is truncated to this, so the block budget below is arithmetic rather
# than a hope: worst case a batch holds `GATHER_PACKET_CHAR_BUDGET //
# MEMBER_PACKET_CHARS` members, whatever a note's answers happen to contain.
MEMBER_PACKET_CHARS = 400

# The hard character budget (D12, P0-13): the largest members block one
# Gather call may carry. A construction limit on request size, exactly like
# `axial.merge_names.DEFAULT_MEMBER_CHAR_BUDGET` -- not a quality knob, not
# tuned, and deliberately never stated in the prompt. 20k characters is 50
# member packets, comfortably inside any model's context alongside the short
# prompt around it.
GATHER_PACKET_CHAR_BUDGET = 20_000

# A disagreement needs two parties. A name only one note ever mentions has
# no second author to disagree with, so no call is spent on it. Definitional,
# not a threshold.
_MIN_MEMBERS = 2

# Bounded concurrent per-name workers. The work is I/O-bound in exactly the
# shape `axial.merge_names` already measured on this provider (issue #416: a
# serial pass over tens of thousands of independent short calls is a
# multi-hour job for a few dollars of spend), and 36 is the value that run
# settled on. Inherited rather than re-derived; `--workers` moves it.
DEFAULT_WORKERS = 36

# The heading Gather owns on a name page. Everything from this line to the
# end of the page is Gather's; `upsert_disagreement_section` replaces it
# wholesale, so a re-run never stacks two sections.
DISAGREEMENT_HEADING = "## What the authors here disagree about"

_ABSTAINED = "(not stated in the passage)"

_GATHER_PROMPT_TEMPLATE = """\
Below are passages from academic books that all name the same thing: {name}.

Each line gives the book's author and year, what the passage claims in one \
sentence, whose position that is, and who or what it argues against.

PASSAGES
{members}

Say what the authors gathered here actually disagree about -- the substance \
of it, in a few sentences, naming who holds which side. Where they do not \
disagree, respond with "disagreement": null instead of inventing a dispute.

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


class DisagreementRecordsCorruptError(GatherError):
    def __init__(self, path: Path, line_no: int, cause: json.JSONDecodeError):
        super().__init__(f"disagreement record {path} is corrupt at line {line_no}: {cause}")


# ---------------------------------------------------------------------------
# The packet: five fields per member note, and nothing else (D13)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemberPacket:
    """One member note's whole contribution to a Gather call. There is no
    sixth field, and there is deliberately no `chunk_text`."""

    chunk_id: str
    author: Any
    year: Any
    claim: str
    position_of: str
    arguing_against: str


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
    `MEMBER_PACKET_CHARS` (§7.18's "roughly 400 characters each"). The cap
    is what makes `GATHER_PACKET_CHAR_BUDGET` a guarantee rather than an
    average."""
    rendered = (
        f"{packet.author} ({packet.year}): {packet.claim} "
        f"[position of: {packet.position_of}; arguing against: {packet.arguing_against}]"
    )
    if len(rendered) > MEMBER_PACKET_CHARS:
        rendered = rendered[: MEMBER_PACKET_CHARS - 1].rstrip() + "…"
    return rendered


def build_packets(
    member_chunk_ids: list[str],
    answers_by_chunk_id: dict[str, dict[str, Any]],
    author_year: dict[str, tuple[Any, Any]],
) -> list[MemberPacket]:
    """One packet per member note that actually has an interrogation answer.
    A member with no answer record contributes nothing -- there are no five
    fields to carry -- rather than a line of markers."""
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
    findings for claims to adjudicate between).

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
    disagree) means no section at all -- not an empty heading. A page that
    previously carried a section and is now null loses it entirely, so a
    re-run can remove a section, not just add one."""
    head = page_text.split(DISAGREEMENT_HEADING)[0].rstrip("\n")
    if disagreement is None:
        return head + "\n"
    return head + "\n\n" + render_disagreement_section(disagreement, links)


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
            prompt = compose_merge_prompt(
                job.canonical, [record["finding"] for record in surviving]
            )
            raw = complete_json(
                client, prompt, pass_name=GATHER_PASS_NAME, validate=parse_gather_response
            )
            disagreement, merge_names = parse_gather_response(raw)
            names = merge_names or names
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


def load_disagreements(path: Path) -> dict[str, dict[str, Any]]:
    """Every recorded disagreement, keyed by `name_key` -- the inverse of
    the append, `{}` before the first run."""
    records = load_checkpoint_records(path, DisagreementRecordsCorruptError)
    return {record["name_key"]: record for record in records}


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

    jobs: list[GatherJob] = []
    skipped_single_member = 0
    skipped_numeral_only = 0
    skipped_apparatus_pointer = 0
    for node in sorted(nodes, key=lambda n: n["canonical"]):
        # Fix (2026-07-29): a bare page number or a plain century
        # (`is_numeral_only_surface`) is locator residue, not a name -- a
        # disagreement page about "13" is not a page anyone asked for. Gated
        # here, at the point this pass asks the model something, so it takes
        # effect on the very next `axial names gather` run with no rebuild
        # of the alias map or the inventory required.
        if is_numeral_only_surface(node["canonical"]):
            skipped_numeral_only += 1
            continue
        # Fix (2026-07-29): a chapter/footnote/endnote/appendix/table/figure
        # POINTER (`is_apparatus_pointer_shaped`) is the same family of
        # residue, gated the same way -- a disagreement page about "Footnote
        # 36" is not a page anyone asked for either.
        if is_apparatus_pointer_shaped(node["canonical"]):
            skipped_apparatus_pointer += 1
            continue
        packets = build_packets(
            member_chunk_ids_for_node(node, inventory), answers_by_chunk_id, author_year
        )
        if len(packets) < _MIN_MEMBERS:
            skipped_single_member += 1
            continue
        batches = split_into_batches(packets)
        jobs.append(GatherJob(node["canonical"], tuple(tuple(batch) for batch in batches)))

    records = load_disagreements(disagreements_path)
    pending = [job for job in jobs if job.key not in records]
    reused = len(jobs) - len(pending)
    to_attempt = pending if limit is None else pending[:limit]

    print(
        f"gather: {len(nodes)} name(s), {skipped_numeral_only} numeral-only surface(s) "
        f"and {skipped_apparatus_pointer} apparatus-pointer surface(s) "
        "gated out (never a name), "
        f"{skipped_single_member} skipped with fewer than "
        f"{_MIN_MEMBERS} member note(s), {len(jobs)} to gather; {reused} already recorded, "
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
                model = record["model"]
                called += 1
                batch_calls += len(record["batches"])
                merge_calls += 1 if record["merged"] else 0

    written = 0
    for job in jobs:
        record = records.get(job.key)
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
        "names_skipped_numeral_only": skipped_numeral_only,
        "names_skipped_apparatus_pointer": skipped_apparatus_pointer,
        "names_skipped_single_member": skipped_single_member,
        "names_gathered": len(jobs),
        "asked": called,
        "reused": reused,
        "failed": failed,
        "batch_calls": batch_calls,
        "merge_calls": merge_calls,
        "pages_written": written,
        "workers": max(workers, 1),
        "limit": limit,
    }
