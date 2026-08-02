"""The argument map's position layer (issue #572, PR 1 of 4): a port of the
scratchpad scripts that ran this pass over the real corpus and were
measured there (`stage1b_extract_positions.py`, `stage1_analyse.py`), not a
redesign. Retrieval in this repo has been rebuilt twice and both times the
corpus stayed addressable only by proper nouns a passage happened to
mention; this groups passages that make the same argument into
**positions**, once, offline, so a question can land on the map instead.

Four steps, run in one command (`axial map build`):

  1. **Select passages** -- every interrogated passage's own `claim`, minus
     abstentions, back matter, and passages that argue nothing at all
     (`select_passages`).
  2. **Bag** -- a local sentence-transformer clusters claims by wording
     similarity, zero model calls (`bag_passages`).
  3. **Extract** -- every bag read in full, in author-spread slices, one
     model call per slice, asking what argument RECURS across passages that
     merely resemble each other (`run_extraction`). Reasoning ON at `high`
     for this pass (`config/pipeline.yaml`'s `llm.reasoning_by_pass.
     position_extract`): deciding how many arguments a bag holds -- and
     refusing to fuse contending ones -- is a judgment call this repo
     already measured a no-reasoning tier failing (a 200-passage bag
     holding two opposed accounts of violence came back as one, "violence
     is shaped by social, strategic and political processes"; with
     reasoning on, the same bag correctly split).
  4. **Merge** -- the same argument gets named from more than one bag; near-
     duplicate namings are folded by argument-sentence similarity
     (`merge_positions`), and each surviving position is stamped with a
     stable `position_id` (`assign_position_ids`).

**Blind, deliberately.** The extraction prompt shows each claim under a bare
handle -- `[p7] <claim>`, never `[p7] (author) <claim>` -- the one
deliberate deviation from the scratchpad run this ports (issue #572 kickoff,
rule 1). Authorship visible during extraction would let it help decide what
meets, which would make the later cross-author balance count measure its
own input rather than the corpus.

**Anti-restatement.** An early draft forced each bag to one argument and
came back nearly 1-for-1 with the passages -- restating them, not finding
what recurs. The prompt instead says explicitly: producing roughly as many
arguments as passages means the task was not done, because a bag was
already grouped by wording resemblance and most of it should share an
argument with something else in it.

**Resumable by construction.** A full build was measured at $0.75 and 45
minutes at 20 workers for 31 sources ($2.53 / ~2.5h extrapolated to 100).
`reads.jsonl` is the resume ledger: every call's result is appended and
flushed the instant it returns, keyed by `(bag, slice)`, and a restart skips
whatever is already on disk -- never held in memory and written once at the
end, so a kill partway through never discards a single paid call.
"""

from __future__ import annotations

import collections
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx
import numpy as np

from axial.checkpoint import append_checkpoint_record, load_checkpoint_records
from axial.envelope import _default_envelopes_dir
from axial.eval.corpus_pin import _build_sources
from axial.extract import TREES_DIR
from axial.interrogate import _default_answers_dir, is_abstention
from axial.llm import LLMClient, LLMError, estimate_cost, get_client
from axial.model_json import ModelJsonError, parse_model_json
from axial.names import load_answer_records, load_back_matter_sections
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH, default_map_dir, default_sources_dir
from axial.pidguard import claim_single_instance

# ---------------------------------------------------------------------------
# Constants -- one block, each carrying the measurement that set it (issue
# #572 kickoff comment). None of these are exposed as CLI flags: they are
# the settled result of the stage-0/stage-1 scratchpad runs over the real
# corpus, not a dial an operator is expected to move per build.
# ---------------------------------------------------------------------------

# The bagging grain (stage 0, issue #572): measured across 0.45/0.55/0.65 on
# the real corpus, 0.55 is the "middle" grain -- 685 positions at 31 sources,
# 63.7% of all passages inside a position spanning 2+ authors, without
# shattering back into one-passage-per-argument (0.45) or fusing contending
# accounts together (0.65).
BAG_DISTANCE_THRESHOLD = 0.55

# Every bag is read in full, never sampled, in author-spread slices of at
# most this many passages (stage 1b): a big bag sampled at 14 of 200 claims
# misses whatever lives in the other 186. 55 is the slice size the measured
# 705-call, $0.47 build ran at.
EXTRACT_SLICE = 55

# The post-extraction merge threshold (stage 1 analysis): the same argument
# is routinely named from two different bags, and 0.30 is the cosine
# distance the real corpus's raw-to-merged position counts (2,002 -> 1,772)
# were measured at.
MERGE_DISTANCE_THRESHOLD = 0.30

# Concurrent extraction workers (issue #572 kickoff): this pass is I/O-bound
# (network, not CPU), and 20 workers measured 705 calls in 27 minutes wall
# time on the real corpus -- a serial pass would be ~9 hours for the same
# call count at the same per-call latency.
WORKERS = 20

# The pass name `config/pipeline.yaml`'s `llm.reasoning_by_pass` /
# `llm.model_by_pass` key off of, and what every extraction call is tagged
# with for run-logging and cost accounting.
PASS_NAME = "position_extract"

# Mirrors `config/pipeline.yaml`'s `llm.reasoning_by_pass.position_extract`
# entry -- recorded in `map.json` for the manifest's own sake (the LLMClient
# protocol exposes no getter for a pass's resolved reasoning setting); this
# constant does not itself control the call, config does, and the two must
# be kept in sync by hand.
POSITION_EXTRACT_REASONING = "high"

ENCODER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# The six fields §7.15 asks every passage: a passage that abstains on every
# one of them names nothing, cites nothing, and stakes out no position --
# apparatus (bibliography rows, acknowledgements, "this paper relies on
# English-language secondary sources") that happened to also carry a claim
# sentence resembling other passages'. Already-validated exclusion rule
# (issue #572 stage 0), reused here rather than re-derived.
_SILENT_KEYS = ("mechanism", "comparison", "concedes", "assumes", "position_of", "ranges_over")

Encoder = Callable[[Sequence[str]], np.ndarray]


class MapError(Exception):
    """Base class for all argument-map build errors."""


class CorruptReadsLedgerError(MapError):
    """Raised when a line of `reads.jsonl` -- other than a torn final line
    left by a hard kill mid-append (healed, not an error; see
    `axial.checkpoint`) -- is not parseable JSON."""

    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(f"corrupt reads ledger at {path}:{line_no}: {cause}")


@dataclass(frozen=True)
class Passage:
    """One selected, argument-bearing passage: its own chunk id, source id,
    author (the source id's own leading token, e.g. `elcheroth-2017-...` ->
    `elcheroth` -- the same convention `source_id`'s stem already carries,
    see `docs/DECISIONS.md`'s source-id-is-author-year rename), and claim."""

    chunk_id: str
    source_id: str
    author: str
    claim: str


@dataclass(frozen=True)
class ExtractJob:
    """One model call's worth of work: `bag`'s `slice_index`-th slice of at
    most `EXTRACT_SLICE` passages, already author-spread."""

    bag: int
    slice_index: int
    members: tuple[Passage, ...]


def select_passages(answers_dir: Path, trees_dir: Path = TREES_DIR) -> list[Passage]:
    """Every `data/answers/*.jsonl` record that is argument-bearing: has a
    non-abstained `claim`, sits before its own source's back-matter boundary
    (`axial.names.load_back_matter_sections`, the #514/DEC-58 positional
    rule off cached trees), and does not abstain on every one of
    `_SILENT_KEYS`. All three exclusions reuse already-validated rules from
    the name layer -- this function invents no new one."""
    back_matter = load_back_matter_sections(trees_dir)
    rows: list[Passage] = []
    for record in load_answer_records(answers_dir):
        answers = record.get("answers")
        if not isinstance(answers, dict):
            continue
        claim = answers.get("claim")
        if is_abstention(claim) or not isinstance(claim, str) or not claim.strip():
            continue

        source_id = record.get("source_id", "")
        chunk_id = record.get("chunk_id", "")
        cut = back_matter.get(source_id, frozenset())
        tail = chunk_id[len(source_id) + 1 :] if chunk_id.startswith(source_id) else chunk_id
        if tail.split("_", 1)[0] in cut:
            continue

        if all(is_abstention(answers.get(key)) for key in _SILENT_KEYS):
            continue

        rows.append(
            Passage(
                chunk_id=chunk_id,
                source_id=source_id,
                author=source_id.split("-")[0],
                claim=claim.strip(),
            )
        )
    return rows


def _default_encoder() -> Encoder:
    """The local sentence-transformer encoder, built only when no encoder is
    injected -- so a unit test that injects its own fake never pays
    MiniLM's load cost, and importing this module never requires
    `sentence-transformers` to be installed."""
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(ENCODER_MODEL, device="cpu")

    def encode(texts: Sequence[str]) -> np.ndarray:
        return model.encode(
            list(texts),
            batch_size=256,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

    return encode


ClusterFn = Callable[[np.ndarray], list[int]]


def _agglomerative_cluster(vectors: np.ndarray, threshold: float) -> list[int]:
    """`AgglomerativeClustering(n_clusters=None, distance_threshold=...,
    metric="cosine", linkage="average")` over `vectors`, as one label per
    row -- scikit-learn is imported lazily here, never at module import
    time: it is an optional dependency (`pyproject.toml`'s `distill` group,
    shared with `axial.names`' own HDBSCAN clustering), and mirroring that
    module's own `cluster_fn` injection seam is what lets a unit test group
    vectors deterministically without it installed. A single vector (a bag
    or a merge pool of exactly one) is its own cluster without calling into
    sklearn at all -- it requires at least two samples to fit, and a lone
    item never needed clustering to begin with."""
    if len(vectors) < 2:
        return [0] * len(vectors)
    from sklearn.cluster import AgglomerativeClustering

    labels = AgglomerativeClustering(
        n_clusters=None, distance_threshold=threshold, metric="cosine", linkage="average"
    ).fit_predict(vectors)
    return [int(label) for label in labels]


def bag_passages(
    passages: Sequence[Passage], encode: Encoder, cluster_fn: ClusterFn | None = None
) -> dict[int, list[Passage]]:
    """Group `passages` by their own `claim`'s cosine similarity at
    `BAG_DISTANCE_THRESHOLD`. Zero model calls -- the local encoder only.
    `cluster_fn`, when given, replaces the default agglomerative clustering
    (the `axial.names` injection seam, for tests)."""
    if not passages:
        return {}
    vectors = encode([passage.claim for passage in passages])
    labels = (
        cluster_fn(vectors)
        if cluster_fn is not None
        else _agglomerative_cluster(vectors, BAG_DISTANCE_THRESHOLD)
    )
    bags: dict[int, list[Passage]] = collections.defaultdict(list)
    for label, passage in zip(labels, passages):
        bags[label].append(passage)
    return dict(bags)


def author_spread(members: Sequence[Passage]) -> list[Passage]:
    """`members` reordered one author at a time in rotation, so any prefix
    -- and so every slice `build_jobs` cuts -- carries as many different
    books as it can rather than one book's run of consecutive passages."""
    by_author: dict[str, list[Passage]] = collections.defaultdict(list)
    for member in members:
        by_author[member.author].append(member)
    keys = sorted(by_author)
    out: list[Passage] = []
    index = 0
    while len(out) < len(members):
        for key in keys:
            if index < len(by_author[key]):
                out.append(by_author[key][index])
        index += 1
    return out


def build_jobs(bags: dict[int, list[Passage]]) -> list[ExtractJob]:
    """Every bag read in full, in author-spread slices of at most
    `EXTRACT_SLICE`. A bag with a single member still yields one job of size
    one -- there is no special case: the model is asked about it exactly
    like any other slice, and its answer (an argument, or nothing usable)
    flows through the same placed/unassigned/failed accounting as every
    other job."""
    jobs: list[ExtractJob] = []
    for label, members in sorted(bags.items()):
        ordered = author_spread(members)
        for offset in range(0, len(ordered), EXTRACT_SLICE):
            slice_members = tuple(ordered[offset : offset + EXTRACT_SLICE])
            jobs.append(
                ExtractJob(bag=label, slice_index=offset // EXTRACT_SLICE, members=slice_members)
            )
    return jobs


PROMPT = """Below are passages from academic books, each shown as its own one-sentence claim, labelled with a handle. They were grouped automatically because their wording looked similar; nobody has read them.

Find the arguments running through these passages. Your job is to find what RECURS: several passages making the same claim, often in different words, about different cases, or with different emphasis. Group those together. Then keep genuinely different claims apart.

{claims}

Answer as JSON only, no other text:

{{"arguments": [
   {{"argument": "<one sentence stating this argument, in the passages' own terms>",
    "handles": ["p1", "p4", "p9"]}},
   ...
 ],
 "unassigned": ["<handles that make no argument at all -- bibliography, acknowledgements, notes on how a book is organised, statements of method>"]}}

How to group:

- MERGE aggressively on substance. Two passages arguing that states extract resources through coercion make the same argument whether one says it about France in 1600 and the other about Iraq in 1980, and whether one calls it extraction and the other calls it predation. Different evidence for the same claim is one argument. Different wording for the same claim is one argument. Different century, same claim, one argument.
- SPLIT only where the claims genuinely conflict or concern different things. Two accounts that locate a cause differently are two arguments -- never fuse contending positions into one sentence saying both matter. If these passages disagree with each other, that disagreement must survive as separate entries.
- An argument no other passage shares may stand alone, but this should be the EXCEPTION. If you are producing roughly as many arguments as there are passages, you are restating the passages rather than finding the arguments in them, and you have not done the task. These passages were grouped because they resemble each other; most of them should share an argument with at least one other.
- Each argument must be CONTESTABLE: something a serious scholar could disagree with. "Violence is shaped by social and political processes" is not an argument, it is a topic wearing an argument's clothes. If a set of passages shares only an uncontestable generality, find the real claims underneath it instead.
- Judge what a passage claims, not what it is about. Two passages both concerning the state are not one argument unless they assert something in common about it."""


def render_claims_blind(members: Sequence[Passage]) -> tuple[str, dict[str, Passage]]:
    """Render `members` as the extraction prompt's claim listing, BLIND
    (issue #572 kickoff, rule 1): `[p7] <claim>`, never `[p7] (author)
    <claim>`. Authorship visible here would let it help decide what meets,
    which would make the later cross-author balance count measure its own
    input rather than the corpus. Returns the rendered listing and the
    handle -> passage map `extract_positions_for_slice` resolves handles
    against."""
    handles = {f"p{i + 1}": member for i, member in enumerate(members)}
    listing = "\n".join(f"[{handle}] {member.claim}" for handle, member in handles.items())
    return listing, handles


def extract_positions_for_slice(
    job: ExtractJob, client: LLMClient, pass_name: str = PASS_NAME
) -> dict[str, Any]:
    """One model call for `job`'s slice. Returns a read record: `bag`,
    `slice`, `shown` (passages offered), `positions` (each carrying
    `argument`, `chunk_ids`, `sources`, `authors`, `size`), `unassigned`
    (count of handles the model itself named as making no argument), and --
    only on failure -- `error`.

    A handle the model invents (not among the ones offered) is dropped,
    never repaired: `entry.get("handles")` is filtered through `handles`
    before use, and an argument left with no real handles is dropped
    entirely. A transport failure, a refused/malformed response, or a
    response shaped as something other than the expected object are all
    caught here and recorded as `error` rather than raised -- a single bad
    call must not abort a 700-call paid pass; this is the fault-isolation
    contract issue #572's resumability requirement rests on."""
    listing, handles = render_claims_blind(job.members)
    record: dict[str, Any] = {
        "bag": job.bag,
        "slice": job.slice_index,
        "shown": len(job.members),
        "positions": [],
    }
    try:
        parsed = parse_model_json(
            client.complete(PROMPT.format(claims=listing), pass_name=pass_name)
        )
        for entry in parsed.get("arguments") or []:
            text = (entry.get("argument") or "").strip()
            if not text:
                continue
            placed = [handles[h] for h in (entry.get("handles") or []) if h in handles]
            if not placed:
                continue
            record["positions"].append(
                {
                    "argument": text,
                    "chunk_ids": [member.chunk_id for member in placed],
                    "sources": sorted({member.source_id for member in placed}),
                    "authors": sorted({member.author for member in placed}),
                    "size": len(placed),
                }
            )
        record["unassigned"] = len([h for h in (parsed.get("unassigned") or []) if h in handles])
    except (LLMError, httpx.HTTPError, ModelJsonError, AttributeError, TypeError) as exc:
        # AttributeError/TypeError: the model returned valid JSON shaped as
        # something other than the expected object (e.g. a bare list), so
        # `.get(...)` itself is what fails -- "the model returns nothing
        # usable" from the brief, same fault class as a parse failure.
        record["error"] = str(exc)[:200]
    return record


def run_extraction(
    jobs: Sequence[ExtractJob],
    *,
    client: LLMClient,
    reads_path: Path,
    pass_name: str = PASS_NAME,
    workers: int = WORKERS,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Run every job in `jobs` through one model call each, resumable by
    `(bag, slice)` via `reads_path`: a restart skips whatever this ledger
    already carries. Calls run concurrently (`workers`), but every
    checkpoint write happens on this one collecting thread -- the same
    pattern `axial.merge_names`/`axial.gather` already use -- so a mid-run
    kill can never race two threads onto the same line, and every result is
    durable the instant it returns rather than held in memory.

    Returns every read now on disk for `reads_path`: this run's own results
    plus any earlier run's resumed ones, read back after the pool drains, so
    a caller always reasons about the complete ledger rather than just this
    run's slice of it."""
    done = {
        (record["bag"], record["slice"])
        for record in load_checkpoint_records(reads_path, CorruptReadsLedgerError)
    }
    if done:
        log(f"resuming: {len(done)} read(s) already on disk")
    pending = [job for job in jobs if (job.bag, job.slice_index) not in done]
    log(f"reads to make this run: {len(pending)} of {len(jobs)}")

    if pending:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            futures = {
                pool.submit(extract_positions_for_slice, job, client, pass_name): job
                for job in pending
            }
            completed = 0
            for future in as_completed(futures):
                record = future.result()
                append_checkpoint_record(reads_path, record)
                completed += 1
                log(
                    f"  read {completed}/{len(pending)} "
                    f"(bag {record['bag']} slice {record['slice']})"
                )

    return load_checkpoint_records(reads_path, CorruptReadsLedgerError)


def merge_positions(
    raw_positions: Sequence[dict[str, Any]],
    encode: Encoder,
    cluster_fn: ClusterFn | None = None,
) -> list[dict[str, Any]]:
    """Fold near-duplicate namings of one argument together (stage 1
    analysis, `MERGE_DISTANCE_THRESHOLD`), because the same argument is
    routinely named from two different bags. Each merged record carries
    `argument` (the largest-membership phrasing, ties broken
    alphabetically -- deterministic regardless of arrival order),
    `variants` (every raw phrasing, sorted), the union of `chunk_ids`,
    `sources`, and `authors`, `size` (distinct chunk_ids), and `named_times`
    (how many raw positions folded into this one). Carries no `position_id`
    yet -- see `assign_position_ids`. `cluster_fn`, when given, replaces the
    default agglomerative clustering (for tests)."""
    if not raw_positions:
        return []

    vectors = encode([position["argument"] for position in raw_positions])
    labels = (
        cluster_fn(vectors)
        if cluster_fn is not None
        else _agglomerative_cluster(vectors, MERGE_DISTANCE_THRESHOLD)
    )
    groups: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
    for label, position in zip(labels, raw_positions):
        groups[label].append(position)

    merged: list[dict[str, Any]] = []
    for group in groups.values():
        representative = min(group, key=lambda p: (-p["size"], p["argument"]))
        chunk_ids = sorted({cid for position in group for cid in position["chunk_ids"]})
        merged.append(
            {
                "argument": representative["argument"],
                "variants": sorted(position["argument"] for position in group),
                "chunk_ids": chunk_ids,
                "sources": sorted({s for position in group for s in position["sources"]}),
                "authors": sorted({a for position in group for a in position["authors"]}),
                "size": len(chunk_ids),
                "named_times": len(group),
            }
        )
    return merged


def assign_position_ids(positions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort `positions` into a fully deterministic order -- descending
    `size`, then alphabetically by `argument` as the tiebreaker -- and stamp
    each with a stable `position_id` (`pos-0001`, `pos-0002`, ...) in that
    order. Two runs over identical input assign identical ids regardless of
    thread completion order or clustering label numbering upstream: PRs 2-4
    of issue #572 bind to these ids, so they must not move under a rebuild
    that changed nothing."""
    ordered = sorted(positions, key=lambda p: (-p["size"], p["argument"]))
    return [
        {"position_id": f"pos-{index:04d}", **position}
        for index, position in enumerate(ordered, start=1)
    ]


def compute_corpus_pin(envelopes_dir: Path, sources_dir: Path) -> str:
    """The pin `axial map build` writes its artifact under: a sha256 digest
    (first 16 hex chars) over the corpus's own raw source content --
    `source_id`/`content_hash` pairs, reusing `axial.eval.corpus_pin`'s own
    `_build_sources` (the exact primitive the committed corpus-pin
    manifest's `sources` field is built from) -- and NOTHING else.

    Deliberately narrower than that manifest's full three-field pin: no
    `ingest_code_sha` (a prompt or model-tier tweak to this pass is a code
    change with the SAME sha, and must not force a $0.75, 45-minute rebuild)
    and no `vault_snapshot_hash` (the name layer is downstream of, not input
    to, the position layer -- it does not exist until Materialize runs,
    which itself depends on nothing this pass produces). This is the
    OPPOSITE of the content-keyed decision-log convention `gather`/
    `merge_names` use, where the key covers the rendered prompt so a wording
    change re-asks the corpus (issue #572: a rebuild here must fire on a
    real corpus change and must NOT fire on a prompt or model tweak)."""
    sources = _build_sources(envelopes_dir, sources_dir)
    canonical = json.dumps(sources, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def run_map_build(
    *,
    answers_dir: Path | None = None,
    trees_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    map_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    encode: Encoder | None = None,
    workers: int = WORKERS,
    guard: bool = True,
    pin: str | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run all four steps and write `<map_dir>/<pin>/{positions.jsonl,
    map.json, reads.jsonl}`, returning the manifest also written to
    `map.json`.

    `pin` defaults to `compute_corpus_pin(envelopes_dir, sources_dir)`; a
    caller may pass one explicitly (the seam every other run_* function in
    this codebase exposes for path/id overrides) to build/test without a
    real `data/envelopes/`+`data/sources/` on disk. `encode`/`client`
    default to the real MiniLM encoder and `axial.llm.get_client()`; both
    are injection seams for tests."""
    started = time.monotonic()
    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    if trees_dir is None:
        trees_dir = TREES_DIR
    if envelopes_dir is None:
        envelopes_dir = _default_envelopes_dir(config_path)
    if sources_dir is None:
        sources_dir = default_sources_dir(config_path)
    if map_dir is None:
        map_dir = default_map_dir(config_path)
    if encode is None:
        encode = _default_encoder()
    if pin is None:
        pin = compute_corpus_pin(envelopes_dir, sources_dir)

    outdir = Path(map_dir) / pin
    outdir.mkdir(parents=True, exist_ok=True)
    if guard:
        claim_single_instance(outdir)
    log(f"corpus pin {pin} -> {outdir}")

    passages = select_passages(answers_dir, trees_dir)
    log(f"passages {len(passages)} | authors {len({p.author for p in passages})}")

    bags = bag_passages(passages, encode)
    jobs = build_jobs(bags)
    log(f"bags {len(bags)} | reads {len(jobs)} (every passage shown once)")

    if client is None:
        client = get_client(config_path=config_path)

    reads_path = outdir / "reads.jsonl"
    reads = run_extraction(jobs, client=client, reads_path=reads_path, workers=workers, log=log)

    raw_positions = [position for read in reads for position in read["positions"]]
    errors = [read for read in reads if "error" in read]
    unassigned = sum(read.get("unassigned", 0) for read in reads)
    placed = sum(position["size"] for position in raw_positions)
    log(
        f"raw positions {len(raw_positions)} | placed {placed} | "
        f"unassigned {unassigned} | failed reads {len(errors)}"
    )

    merged = merge_positions(raw_positions, encode)
    stamped = assign_position_ids(merged)
    log(f"merged positions {len(stamped)} (from {len(raw_positions)} raw)")

    with (outdir / "positions.jsonl").open("w", encoding="utf-8") as handle:
        for position in stamped:
            handle.write(json.dumps(position, ensure_ascii=False) + "\n")

    usage = client.usage_for_pass(PASS_NAME)
    model = client.model_for_pass(PASS_NAME)
    cost = (
        estimate_cost(model, usage["prompt_tokens"], usage["completion_tokens"]) if usage else None
    )
    manifest = {
        "corpus_pin": pin,
        "counts": {
            "passages_selected": len(passages),
            "bags": len(bags),
            "reads": len(jobs),
            "raw_positions": len(raw_positions),
            "merged_positions": len(stamped),
            "passages_placed": placed,
            "passages_unassigned": unassigned,
            "failed_reads": len(errors),
        },
        "model": model,
        "reasoning": POSITION_EXTRACT_REASONING,
        "usage": usage,
        "cost_usd": cost,
        "wall_time_sec": time.monotonic() - started,
    }
    (outdir / "map.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if guard:
        (outdir / "RUNNING.pid").unlink(missing_ok=True)
    log(f"wrote {outdir}")
    return manifest
