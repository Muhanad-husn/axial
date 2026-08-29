"""The argument map's position layer (issue #572, PR 1 of 4): a port of the
scratchpad scripts that ran this pass over the real corpus and were
measured there (`stage1b_extract_positions.py`, `stage1_analyse.py`), not a
redesign. Retrieval in this repo has been rebuilt twice and both times the
corpus stayed addressable only by proper nouns a passage happened to
mention; this groups passages that make the same argument into
**positions**, once, offline, so a question can land on the map instead.

Four steps, run in one command (`axial map build`):

  1. **Select passages** -- every interrogated passage's own `claim`, minus
     abstentions, back matter (both the positional run and, since issue
     #661, a heading check for the front/back matter that run cannot
     reach), and passages that argue nothing at all (`select_passages`).
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

**Forceable, deliberately separate from resume.** The corpus pin is content
only (`compute_corpus_pin`), so a prompt or model-tier change moves nothing
and a plain rerun would resume under the old ledger -- half old prompt, half
new. `run_map_build(force=True)` (`axial map build --force`) moves the
existing `reads.jsonl` aside to a timestamped sibling and re-asks every read
under the pin; the old ledger is never deleted.

**Incremental bagging (issue #677): a new pin reuses the prior pin's own
bags instead of re-fitting the whole corpus.** Measured directly (#623): 3
new books into 31 made every one of 665 reads re-ask, because `bag_passages`
re-clusters every passage from scratch and a global re-fit reshuffles who
sits with whom even where nothing changed. `run_map_build` now persists each
bag's own centroid alongside `map.json` (`bag_state.json`) and, when a later
build's encoder/threshold/library version still match, keeps every already-
seen passage's own bag label unchanged and places a genuinely new passage by
NEAREST CENTROID, under AVERAGE LINKAGE (`_average_linkage_distance`: `1 -
dot(vector, centroid)` against the centroid AS STORED, an unnormalised mean
-- the same criterion `_agglomerative_cluster`'s own average-linkage-under-
cosine fit uses; dividing by the centroid's own norm instead, tried first,
inflates acceptance and was measured to swallow 96.8% of a real delta into
3 residue bags where average linkage swallows 78.1% into 22) at the same
`BAG_DISTANCE_THRESHOLD` a full fit already clusters at -- agglomerative
clustering has no `approximate_predict`, and nearest-centroid at the
existing grain is the honest analogue, not a second hand-tuned constant. A
passage nearest to no existing centroid within that grain falls to a
residue, agglomeratively clustered exactly as a full build would and offset
above the existing maximum label -- existing labels are never renumbered.
`--force` still does a full re-bag.

Each read record also carries its own `members_key` (a hash of its slice's
ordered claims -- the content the model was actually shown, `render_claims_
blind` never renders anything else): a new pin's `reads.jsonl` is seeded,
before any call is made, with the prior pin's own read for every slice whose
composition matches exactly, under `(bag, slice)` (the resume key, keyed on
THIS run's own numbering) so `run_extraction`'s existing resume mechanism
picks the seeded record up and never spends a call on it. A bag that gained
one new member re-cuts every `EXTRACT_SLICE` boundary downstream of it
(`author_spread` rotates one author at a time), so most of a grown bag's
slices still get re-asked -- this seeding recovers the slices genuinely
unaffected, not every slice in an affected bag.

**Stage 2 (issue #572, PR 2 of 4): relations between positions.** The same
command continues past `positions.jsonl` into `relations.jsonl` -- a port
of the scratchpad's own `stage2_relations.py`, already run and measured over
the real corpus, not a redesign. Four rules carry over unchanged from that
measurement:

  1. **No menu of relation types.** The model says how two positions stand
     in its own words and coins its own short label; the shapes that recur
     are named AFTERWARDS from what came back. An engine told to look for
     opposition finds opposition -- measured directly on the scratchpad
     run: opposition came back at only 6.6% precisely because nothing asked
     for it.
  2. **Blind, the same rule as extraction.** No author, no book, no year --
     a relation judged with authorship visible reads agreement and
     disagreement off reputations, and would make the cross-author balance
     this pass itself reports measure its own input rather than the corpus.
  3. **Neighbourhoods, not pairs.** All-pairs over the full position set is
     never done (1.5M+ comparisons at this corpus's scale). Positions are
     grouped into small neighbourhoods of near neighbours -- sized by
     `TARGET_NEIGHBOURHOOD`/`MAX_NEIGHBOURHOOD` below -- and each is read
     once, so cost is one call per neighbourhood, not per pair, and the
     model sees a cluster of related arguments rather than an isolated
     couple.
  4. **"Unrelated" is expected and must stay cheap to say.** Two positions
     that merely share vocabulary have no relation; the prompt says so
     plainly, and a pass that returns a relation for every pair has told us
     nothing.

Relations are keyed on `position_id`, never on the argument sentence
(settled on issue #572): a scratchpad draft of this pass rejoined relations
through a sentence-to-index dictionary, which silently drops any relation
whose sentence is not unique across positions. A relation naming a handle
that was not offered, or naming itself, is dropped, never repaired -- both
classes are counted (`dropped_relations` in `map.json`).
"""

from __future__ import annotations

import collections
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import httpx
import numpy as np

from axial.back_matter import is_evidence_back_matter
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
# Raised 20 -> 40 by issue #623, on this pipeline's own measurement rather than
# a guess: a full build of 1,058 calls ran 98.8 minutes at an EFFECTIVE
# concurrency of 16.7 against a nominal 20 -- 83% utilisation, so the pass was
# waiting on the model with slots to spare, not saturated. The residue pass
# imports this constant and moves with it (`axial.argmap.residue.WORKERS`).
WORKERS = 40

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

# Neighbourhood sizing for the relate pass (stage 2, issue #572): a flat
# clustering at real-corpus scale gave wildly uneven groups -- measured
# sizes 2, 2, 3, 3, 3, 4, 4, 12, 13, 15, 15, **53** on the scratchpad run
# this section ports. A 53-position neighbourhood is 1,378 possible pairs
# in ONE call, which the model cannot weigh (it misses relations from load
# alone) and which alone dominates the "pairs possible" denominator and
# makes the assertion rate look artificially low. So a coarse pass targets
# TARGET_NEIGHBOURHOOD-sized groups, and any group still over
# MAX_NEIGHBOURHOOD is split recursively until none exceeds it.
TARGET_NEIGHBOURHOOD = 8
MAX_NEIGHBOURHOOD = 12

# The pass name `config/pipeline.yaml`'s `llm.reasoning_by_pass` keys off of
# for the relate call, mirroring `PASS_NAME` above.
RELATE_PASS_NAME = "position_relate"

# Mirrors `config/pipeline.yaml`'s `llm.reasoning_by_pass.position_relate`
# entry, recorded in `map.json` the same way `POSITION_EXTRACT_REASONING`
# is -- deciding how two positions actually stand to one another, with no
# menu to pick from, is the same underdetermined judgment call extraction
# makes.
POSITION_RELATE_REASONING = "high"

ENCODER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# The six fields §7.15 asks every passage: a passage that abstains on every
# one of them names nothing, cites nothing, and stakes out no position --
# apparatus (bibliography rows, acknowledgements, "this paper relies on
# English-language secondary sources") that happened to also carry a claim
# sentence resembling other passages'. Already-validated exclusion rule
# (issue #572 stage 0), reused here rather than re-derived.
#
# `position` deliberately does NOT join this list (issue #697 considered it
# and left it out). Two reasons, and the first is binding until the backfill
# actually lands: `is_abstention(None)` is `False`, so on a record that has
# no `position` key at all -- every 0.1-era note, 91% of the corpus, until
# #697's backfill runs -- adding `position` here would make the `all(...)`
# check below unsatisfiable for those notes no matter how silent they truly
# are, fail-OPEN rather than fail-closed, and quietly weaken this exclusion
# for most of the corpus the moment this file merges, well before the
# backfill that would make the field meaningful. Second, even once every
# note carries the key, `position` and `position_of` are asked in the same
# call with an explicit instruction to answer `position` even when the
# holder is "the author's own" -- the two abstain together far more often
# than independently, so adding `position` alongside `position_of` here
# would mostly duplicate a signal already in the list rather than add one.
# Revisit once the backfill has actually run against the corpus and the
# correlation can be measured rather than assumed.
_SILENT_KEYS = ("mechanism", "comparison", "concedes", "assumes", "position_of", "ranges_over")

Encoder = Callable[[Sequence[str]], np.ndarray]


class MapError(Exception):
    """Base class for all argument-map build errors."""


# The two grouping modes `run_map_build` takes (issue #829). `GROUPING_BAG`
# is what every build before this slice did and stays the default;
# `GROUPING_CATEGORY` groups by slice 03's chosen `claim x mechanism` split
# and writes beside the default build, under `<pin>` + `CATEGORY_VARIANT_
# SUFFIX`, so the two maps exist at once and can be compared (slice 06).
GROUPING_BAG = "bag"
GROUPING_CATEGORY = "category"
GROUPING_MODES = (GROUPING_BAG, GROUPING_CATEGORY)
CATEGORY_VARIANT_SUFFIX = "-category"


class SchemeVersionMismatchError(MapError):
    """Raised when a category-grouped build finds its own directory already
    holds work grouped under different vocabulary scheme versions. Resuming
    would finish one half of a map under a scheme the other half was never
    asked under -- the ledger is keyed by group label, and a scheme change
    silently re-labels every group. The fix is a fresh variant directory or
    `--force`, both deliberate acts."""

    def __init__(self, column: str, recorded: str, on_disk: str, outdir: Path) -> None:
        self.column = column
        super().__init__(
            f"{outdir} was grouped under {column} scheme {recorded!r}, but "
            f"{column} on disk is now {on_disk!r} -- refusing to resume a "
            "variant build across two schemes"
        )


class CorruptReadsLedgerError(MapError):
    """Raised when a line of `reads.jsonl` -- other than a torn final line
    left by a hard kill mid-append (healed, not an error; see
    `axial.checkpoint`) -- is not parseable JSON."""

    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(f"corrupt reads ledger at {path}:{line_no}: {cause}")


class CorruptRelationsLedgerError(MapError):
    """The relate-stage sibling of `CorruptReadsLedgerError`, raised for a
    non-torn-tail corrupt line in the relate stage's own resume ledger
    (`relation_reads.jsonl`)."""

    def __init__(self, path: Path, line_no: int, cause: Exception):
        self.path = path
        self.line_no = line_no
        self.cause = cause
        super().__init__(f"corrupt relation reads ledger at {path}:{line_no}: {cause}")


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
    most `EXTRACT_SLICE` passages, already author-spread.

    `bag` is the group's own identity, and what that is depends on the
    grouping mode: a wording bag's integer label under `GROUPING_BAG`, a
    category cell's own label string (`<claim>::<mechanism>`) under
    `GROUPING_CATEGORY` (issue #829). It is only ever used as half of the
    `(bag, slice)` resume key and printed in the progress log, so both types
    work unchanged -- and both survive the JSON round-trip through
    `reads.jsonl` as themselves."""

    bag: int | str
    slice_index: int
    members: tuple[Passage, ...]


def select_passages(answers_dir: Path, trees_dir: Path = TREES_DIR) -> list[Passage]:
    """Every `data/answers/*.jsonl` record that is argument-bearing: has a
    non-abstained `claim`, sits before its own source's back-matter boundary
    (`axial.names.load_back_matter_sections`, the #514/DEC-58 positional
    rule off cached trees), is not itself a non-substantive front/back-matter
    section by heading (`axial.back_matter.is_evidence_back_matter`, issue
    #661), and does not abstain on every one of `_SILENT_KEYS`.

    **Two back-matter exclusions, deliberately, because they catch different
    shapes (issue #661).** The positional rule cuts the CONTIGUOUS run
    starting at a book's index/bibliography anchor -- exactly what #511
    measured and exactly what keeps interleaved, per-chapter endnotes IN,
    since those are not part of that terminal run. The heading rule catches
    what the positional one cannot reach by construction: a front-matter
    acknowledgments page (nowhere near the terminal run) and a per-chapter
    endnotes section (interleaved, not terminal) -- the same two shapes
    issue #661's own live defect was grounded on. Both reuse already-
    validated rules; neither is invented here."""
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
        section = record.get("section")
        if is_evidence_back_matter(section if isinstance(section, str) else ""):
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


# ---------------------------------------------------------------------------
# Issue #677: persisting and reusing bag state, so a later pin places its new
# passages into the SAME bags a full fit already found instead of re-fitting
# the whole corpus. Mirrors `axial.names`'s own fit-persistence pattern
# (`_write_fit_artifact`/`_read_fit_artifact`/`_manifest_reusable`), adapted
# to agglomerative clustering, which has no `approximate_predict`: nearest-
# centroid at the same `BAG_DISTANCE_THRESHOLD` a full fit already clusters
# at is the honest analogue, not a second, hand-tuned constant. `run_map_
# build` is the only caller of everything in this section.
# ---------------------------------------------------------------------------

BAG_STATE_FILENAME = "bag_state.json"


def _bag_state_path(outdir: Path) -> Path:
    return outdir / BAG_STATE_FILENAME


def _load_json_or_none(path: Path) -> dict[str, Any] | None:
    """A tolerant JSON read: `None` when `path` does not exist or fails to
    parse, either way meaning "cannot be trusted, fall back". Shared by
    `bag_state.json` and, for reading a prior pin's own `source_ids`,
    `map.json` -- both are plain JSON objects a torn or absent file should
    never crash over."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _bag_state_reusable(state: dict[str, Any] | None) -> bool:
    """Whether a persisted bag state's own config matches this run's
    encoder/threshold/library version, and its shape is intact -- the things
    that have to hold for a prior centroid to mean the same thing here that
    it meant when it was written. `False` means `run_map_build` never
    attempts nearest-centroid assignment at all, and re-bags globally."""
    if not state:
        return False
    config = state.get("config")
    if not isinstance(config, dict):
        return False
    if not isinstance(state.get("assignments"), dict) or not isinstance(
        state.get("centroids"), dict
    ):
        return False
    return (
        config.get("encoder") == ENCODER_MODEL
        and config.get("bag_distance_threshold") == BAG_DISTANCE_THRESHOLD
        and config.get("sklearn_version") == _sklearn_version()
    )


def _sklearn_version() -> str:
    """The installed scikit-learn version, or a stable sentinel when it is
    not installed at all. `scikit-learn` is an optional dependency
    (`pyproject.toml`'s `distill` group) that `_agglomerative_cluster`
    itself only ever lazy-imports when it actually clusters 2+ vectors --
    recording a version here must not force it to be present just to
    persist or read back bag state for a run whose bags never needed a real
    fit (a one-passage corpus, or a test's injected `_agglomerative_cluster`
    monkeypatch)."""
    try:
        import sklearn
    except ImportError:
        return "not-installed"
    return sklearn.__version__


def _bag_centroids(
    bags: dict[int, list[Passage]], vectors_by_chunk_id: dict[str, np.ndarray]
) -> dict[int, np.ndarray]:
    """Each bag's own centroid -- the mean of its members' embedding
    vectors. The nearest-centroid assignment target a later incremental
    build compares a new passage's vector against."""
    return {
        label: np.mean(
            np.stack([vectors_by_chunk_id[member.chunk_id] for member in members]), axis=0
        )
        for label, members in bags.items()
    }


def _bag_passages_with_centroids(
    passages: Sequence[Passage], encode: Encoder
) -> tuple[dict[int, list[Passage]], dict[int, np.ndarray]]:
    """`bag_passages`'s own clustering, but paying for exactly one `encode`
    call and returning each bag's centroid alongside it -- the full-rebag
    path `run_map_build` takes when there is no reusable prior bag state.
    Duplicates `bag_passages`' own clustering call rather than reusing it
    directly, because `bag_passages` discards its vectors once labelled and
    a second `encode` call over the same claims is the one cost this module
    already measured as too expensive to repeat (module docstring)."""
    if not passages:
        return {}, {}
    vectors = [np.asarray(v, dtype=np.float64) for v in encode([p.claim for p in passages])]
    labels = _agglomerative_cluster(np.stack(vectors), BAG_DISTANCE_THRESHOLD)
    bags: dict[int, list[Passage]] = collections.defaultdict(list)
    for label, passage in zip(labels, passages):
        bags[label].append(passage)
    vectors_by_chunk_id = {passage.chunk_id: vector for passage, vector in zip(passages, vectors)}
    return dict(bags), _bag_centroids(dict(bags), vectors_by_chunk_id)


def _write_bag_state(
    path: Path, bags: dict[int, list[Passage]], centroids: dict[int, np.ndarray]
) -> None:
    """Persist this build's own bag assignment and centroids so a LATER pin
    can place its new passages into THIS pin's clustering instead of
    re-bagging the whole corpus. `config` records exactly what a later run
    must match before trusting this file (`_bag_state_reusable`)."""
    assignments = {member.chunk_id: label for label, members in bags.items() for member in members}
    state = {
        "config": {
            "encoder": ENCODER_MODEL,
            "bag_distance_threshold": BAG_DISTANCE_THRESHOLD,
            "sklearn_version": _sklearn_version(),
        },
        "assignments": assignments,
        "centroids": {str(label): centroid.tolist() for label, centroid in centroids.items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_category_group_state(
    path: Path, groups: Mapping[str, list[Passage]], scheme_versions: Mapping[str, str]
) -> None:
    """The category-grouped build's own `bag_state.json` (issue #829).

    It exists for two readers already on disk. `axial.argmap.purity._load_
    bag_assignments` and `axial.argmap.grouping.compute_grouping_report`
    both take this file as the passage universe of a built map, and slice
    06 measures the variant directory through them. That is why the
    assignment values are INTEGERS -- `_load_bag_assignments` calls
    `int(...)` on each one, and a raw label string would raise there -- with
    the labels themselves kept alongside in `group_labels`, indexed by the
    same numbering.

    Its `assignments` hold only the passages that reached a GROUP, so on the
    real corpus its key count is 5,993 against 6,010 selected -- the 17
    ungrouped ones are absent. That is what a file recording group
    membership should say, but it means neither reader above can be used to
    count selected passages: `map grouping-report` prints 5,993 for this
    pin, and anything measuring coverage against that number understates
    the loss. `passages_selected` in `map.json` is the honest denominator.

    It can never be mistaken for a bag fit to reuse: `_bag_state_reusable`
    requires `config.encoder`/`bag_distance_threshold`/`sklearn_version`,
    and this config carries none of them, because none of them decided
    anything here. `centroids` is written empty for the same reason -- a
    category cell has no centroid, and an incremental build has nothing to
    place a new passage against.

    `scheme_versions` is written here rather than only in `map.json`
    because this file lands BEFORE the first model call and `map.json` only
    after the last one: a run killed halfway leaves the ledger and this,
    and `_check_scheme_versions` needs something to compare against in
    exactly that case."""
    ordered = sorted(groups)
    index_by_label = {label: index for index, label in enumerate(ordered)}
    state = {
        "config": {
            "grouping": GROUPING_CATEGORY,
            "scheme_versions": dict(scheme_versions),
        },
        "assignments": {
            member.chunk_id: index_by_label[label]
            for label, members in groups.items()
            for member in members
        },
        "group_labels": {str(index): label for label, index in index_by_label.items()},
        "centroids": {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False) + "\n", encoding="utf-8")


def _check_scheme_versions(
    outdir: Path, scheme_versions: Mapping[str, str], *, force: bool
) -> None:
    """Refuse to resume a category-grouped build under a scheme it was not
    started under (issue #829).

    There is nothing to compare against on a FIRST run -- no prior state
    exists, and the build simply records what it grouped under. The refusal
    is meaningful on a re-run: the group labels the resume ledger is keyed
    by are category ids, so a scheme change re-labels every group, and
    finishing the ledger would produce a map half-asked under each scheme.
    Compared against `bag_state.json` rather than `map.json` because that
    file is written before the first call and covers a killed run too.

    `force` skips the check, because it is exactly the deliberate act this
    refusal asks for: it sets the whole prior ledger aside and re-asks every
    group under the scheme now on disk."""
    if force:
        return
    state = _load_json_or_none(_bag_state_path(outdir))
    recorded = (state or {}).get("config", {}).get("scheme_versions")
    if not isinstance(recorded, dict):
        return
    for column, version in sorted(scheme_versions.items()):
        if recorded.get(column, version) != version:
            raise SchemeVersionMismatchError(column, recorded[column], version, outdir)


def _average_linkage_distance(vector: np.ndarray, centroid: np.ndarray) -> float:
    """The distance a candidate point's placement against `centroid` must
    clear -- the SAME criterion `_agglomerative_cluster`'s own average
    linkage under cosine fits bags with, not the cosine distance to the
    centroid's own direction. For unit vectors `m_i` and their unnormalised
    mean `centroid = (1/n) * sum_i(m_i)`, the mean distance from `vector` to
    every member of the bag is:

        (1/n) * sum_i(1 - vector.m_i) = 1 - vector.((1/n) * sum_i(m_i))
                                       = 1 - vector.centroid

    So this is exactly `1 - dot(vector, centroid)`, using `centroid` AS
    STORED (an unnormalised mean, `norm(centroid) < 1` in general --
    measured over this corpus's real bags, median 0.839, min 0.713).
    Dividing by `norm(centroid)` (plain cosine distance to the centroid's
    own direction, tried first) inflates acceptance: at `BAG_DISTANCE_
    THRESHOLD=0.55` it accepts a `dot() >= 0.378` point instead of the
    `dot() >= 0.45` average linkage itself demands -- measured to swallow
    96.8% of a real 535-passage delta into 3 residue bags, where average
    linkage swallows 78.1% into 22. Three new bags for three new books was
    never plausible; twenty-two is."""
    return 1.0 - float(np.dot(vector, centroid))


def _incremental_bag_passages(
    passages: Sequence[Passage], encode: Encoder, prior_state: dict[str, Any]
) -> tuple[dict[int, list[Passage]], dict[int, np.ndarray], int]:
    """Group `passages` into bags, keeping every already-seen passage's own
    prior bag label unchanged (issue #677) instead of re-fitting globally.
    A brand-new passage (its `chunk_id` absent from `prior_state`) is placed
    into the bag whose centroid it is nearest to BY AVERAGE LINKAGE
    (`_average_linkage_distance` -- the same criterion `_agglomerative_
    cluster`'s own average-linkage-under-cosine fit uses, not cosine
    distance to the centroid's own direction), PROVIDED that distance is
    within `BAG_DISTANCE_THRESHOLD` -- the same grain a full fit already
    clusters at, reused rather than a second, hand-tuned constant; a new
    passage nearest to no existing bag within that grain falls to a
    residue, agglomeratively clustered exactly as a full build would and
    offset above the existing maximum label -- existing labels are never
    renumbered.

    Returns the resulting bags, each bag's own centroid (an accepted bag's
    updated by a running weighted mean -- this pass never retains an
    already-seen passage's own vector, only the centroid it was folded
    into; an unaffected bag's is untouched), and how many passages were
    genuinely new work (needed an embedding + placement)."""
    prior_assignments: dict[str, int] = {
        chunk_id: int(label) for chunk_id, label in prior_state["assignments"].items()
    }
    prior_centroids: dict[int, np.ndarray] = {
        int(label): np.asarray(vector, dtype=np.float64)
        for label, vector in prior_state["centroids"].items()
    }
    prior_bag_sizes = collections.Counter(prior_assignments.values())

    known = [passage for passage in passages if passage.chunk_id in prior_assignments]
    new = [passage for passage in passages if passage.chunk_id not in prior_assignments]

    bags: dict[int, list[Passage]] = collections.defaultdict(list)
    for passage in known:
        bags[prior_assignments[passage.chunk_id]].append(passage)

    centroids = dict(prior_centroids)
    if new:
        new_vectors = [np.asarray(v, dtype=np.float64) for v in encode([p.claim for p in new])]

        accepted_vectors_by_label: dict[int, list[np.ndarray]] = collections.defaultdict(list)
        residue: list[tuple[Passage, np.ndarray]] = []
        for passage, vector in zip(new, new_vectors):
            best_label, best_distance = None, None
            for label, centroid in prior_centroids.items():
                distance = _average_linkage_distance(vector, centroid)
                if best_distance is None or distance < best_distance:
                    best_label, best_distance = label, distance
            if best_label is not None and best_distance <= BAG_DISTANCE_THRESHOLD:
                bags[best_label].append(passage)
                accepted_vectors_by_label[best_label].append(vector)
            else:
                residue.append((passage, vector))

        for label, vectors in accepted_vectors_by_label.items():
            prior_size = prior_bag_sizes.get(label, 0)
            prior_centroid = prior_centroids.get(label, np.zeros_like(vectors[0]))
            total = prior_size + len(vectors)
            centroids[label] = (prior_centroid * prior_size + np.sum(vectors, axis=0)) / total

        if residue:
            residue_vectors = np.stack([vector for _passage, vector in residue])
            residue_labels = _agglomerative_cluster(residue_vectors, BAG_DISTANCE_THRESHOLD)
            offset = max(prior_assignments.values(), default=-1) + 1
            residue_vectors_by_label: dict[int, list[np.ndarray]] = collections.defaultdict(list)
            for (passage, vector), raw_label in zip(residue, residue_labels):
                label = offset + raw_label
                bags[label].append(passage)
                residue_vectors_by_label[label].append(vector)
            for label, vectors in residue_vectors_by_label.items():
                centroids[label] = np.mean(np.stack(vectors), axis=0)

    return dict(bags), centroids, len(new)


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


def build_jobs(
    bags: Mapping[int, list[Passage]] | Mapping[str, list[Passage]],
) -> list[ExtractJob]:
    """Every bag read in full, in author-spread slices of at most
    `EXTRACT_SLICE`. A bag with a single member still yields one job of size
    one -- there is no special case: the model is asked about it exactly
    like any other slice, and its answer (an argument, or nothing usable)
    flows through the same placed/unassigned/failed accounting as every
    other job.

    A category-grouped build (issue #829) passes label-keyed groups here
    instead of integer-keyed bags; `sorted` orders either kind, since one
    build's keys are all of one type."""
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


def _members_key(members: Sequence[Passage]) -> str:
    """sha256 (first 16 hex chars) over `members`' own claim texts, in
    order -- the content identity of one extraction slice (issue #677).
    Two slices with the SAME ordered claims were shown the exact same blind
    prompt (`render_claims_blind` never renders author, book, chunk id or
    anything else), so the model's answer for one is a valid stand-in for
    the other regardless of which bag/slice number either happens to land
    at under whichever pin's own numbering produced it. `run_map_build`
    uses this both to record what a read was actually asked about and to
    seed a later pin's ledger from a matching earlier one
    (`_seed_reads_from_prior_pin`)."""
    canonical = "\n".join(member.claim for member in members)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def extract_positions_for_slice(
    job: ExtractJob, client: LLMClient, pass_name: str = PASS_NAME
) -> dict[str, Any]:
    """One model call for `job`'s slice. Returns a read record: `bag`,
    `slice`, `members_key` (issue #677: a hash of the slice's own ordered
    claims, the content identity `_seed_reads_from_prior_pin` matches a
    later pin's job against), `shown` (passages offered), `positions` (each
    carrying `argument`, `chunk_ids`, `sources`, `authors`, `size`),
    `unassigned` (count of handles the model itself named as making no
    argument), and -- only on failure -- `error`.

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
        "members_key": _members_key(job.members),
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
    unit_word: str = "bag",
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Run every job in `jobs` through one model call each, resumable by
    `(bag, slice)` via `reads_path`: a restart skips whatever this ledger
    already carries.

    `unit_word` is what the per-read progress line calls a job's grouping
    unit (issue #829). It is "bag" by default and "group" under category
    grouping, because printing "bag" while `--grouping category` runs names
    the OTHER value of the flag the operator just set, and reads as the flag
    having been ignored. Calls run concurrently (`workers`), but every
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
                    f"({unit_word} {record['bag']} slice {record['slice']})"
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


@dataclass(frozen=True)
class Neighbourhood:
    """One neighbourhood of near-neighbour positions to read in a single
    relate call. `key` is a stable hash of this neighbourhood's own sorted
    `position_ids` -- deliberately NOT derived from a clustering label or
    from split order, either of which a reclustering (a rebuild over a
    slightly different position set) could shuffle. The resume ledger is
    keyed by `key`, so it must depend only on the neighbourhood's own
    membership, never on how that membership was arrived at."""

    key: str
    position_ids: tuple[str, ...]


def _neighbourhood_key(position_ids: Sequence[str]) -> str:
    canonical = "|".join(sorted(position_ids))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


CountClusterFn = Callable[[np.ndarray, int], list[int]]


def _agglomerative_cluster_by_count(vectors: np.ndarray, n_clusters: int) -> list[int]:
    """`AgglomerativeClustering(n_clusters=n_clusters, metric="cosine",
    linkage="average")` over `vectors` -- the count-based sibling of
    `_agglomerative_cluster`'s own distance-threshold clustering, needed
    here because neighbourhood sizing targets a GROUP COUNT
    (`TARGET_NEIGHBOURHOOD`), not a similarity radius. `n_clusters<=1` (one
    neighbourhood covers everything) or `n_clusters>=len(vectors)` (every
    row is already its own cluster) both need no real clustering call --
    scikit-learn is imported lazily and only when an actual split is
    required, mirroring `_agglomerative_cluster`'s own single-vector
    shortcut."""
    if n_clusters <= 1:
        return [0] * len(vectors)
    if n_clusters >= len(vectors):
        return list(range(len(vectors)))
    from sklearn.cluster import AgglomerativeClustering

    labels = AgglomerativeClustering(
        n_clusters=n_clusters, metric="cosine", linkage="average"
    ).fit_predict(vectors)
    return [int(label) for label in labels]


def build_neighbourhoods(
    positions: Sequence[dict[str, Any]],
    encode: Encoder,
    cluster_fn: CountClusterFn | None = None,
) -> list[Neighbourhood]:
    """Group merged `positions` into neighbourhoods of near neighbours by
    their own `argument` sentence's cosine similarity, for one relate call
    per neighbourhood rather than one per pair.

    `positions` is sorted by `position_id` FIRST, before encoding or
    clustering -- so neighbourhood membership, and therefore every
    `Neighbourhood.key`, depends only on which positions exist, never on
    the order they arrived in (`assign_position_ids`'s own arrival-order
    independence would otherwise be undone one step downstream). A coarse
    pass targets `TARGET_NEIGHBOURHOOD`-sized groups; any group still over
    `MAX_NEIGHBOURHOOD` is split recursively (a flat clustering at this
    corpus's scale produced a 53-position group -- see the module
    docstring) until every neighbourhood is at most `MAX_NEIGHBOURHOOD`.
    Singletons are skipped -- a neighbourhood of one position has nothing
    to relate it to. `cluster_fn`, when given, replaces the default
    count-based agglomerative clustering (the same injection seam
    `bag_passages`/`merge_positions` expose, for tests)."""
    ordered = sorted(positions, key=lambda p: p["position_id"])
    if len(ordered) < 2:
        return []

    vectors = encode([position["argument"] for position in ordered])
    cluster = cluster_fn if cluster_fn is not None else _agglomerative_cluster_by_count

    def split(indices: list[int]) -> list[list[int]]:
        if len(indices) <= MAX_NEIGHBOURHOOD:
            return [indices]
        n_groups = max(2, round(len(indices) / TARGET_NEIGHBOURHOOD))
        labels = cluster(vectors[indices], n_groups)
        pieces: dict[int, list[int]] = collections.defaultdict(list)
        for offset, label in enumerate(labels):
            pieces[int(label)].append(indices[offset])
        out: list[list[int]] = []
        for piece in pieces.values():
            # A split that fails to shrink anything would recurse forever.
            out.extend(split(piece) if len(piece) < len(indices) else [piece])
        return out

    n_groups = max(1, round(len(ordered) / TARGET_NEIGHBOURHOOD))
    labels = cluster(vectors, n_groups)
    coarse: dict[int, list[int]] = collections.defaultdict(list)
    for index, label in enumerate(labels):
        coarse[int(label)].append(index)

    neighbourhoods: list[Neighbourhood] = []
    for members in coarse.values():
        for piece in split(sorted(members)):
            if len(piece) < 2:
                continue
            ids = tuple(sorted(ordered[i]["position_id"] for i in piece))
            neighbourhoods.append(Neighbourhood(key=_neighbourhood_key(ids), position_ids=ids))
    neighbourhoods.sort(key=lambda n: n.key)
    return neighbourhoods


RELATE_PROMPT = """Below are arguments drawn from a body of academic work. They were placed together because their wording resembles one another; nobody has read them, and resemblance is not a relationship.

Say how these arguments actually stand to one another.

{positions}

Answer as JSON only, no other text:

{{"relations": [
   {{"from": "a3", "to": "a7",
     "relation": "<a short label you choose for how a3 stands to a7 -- your own words, two or three words>",
     "says": "<one sentence saying what that relationship actually is>"}},
   ...
 ]}}

Rules:

- **There is no list of allowed relations.** Do not pick from a menu and do not reach for opposition by default. Say what is actually there: one may support another, sharpen it, restate it in stronger terms, borrow its mechanism for a different purpose, apply it where the first never looked, depend on something the first denies, qualify its scope, explain why it fails, or contradict it outright. Coin whatever label fits. If the same shape recurs, use the same words for it.
- **Direction matters.** "a3 qualifies a7" is not the same as "a7 qualifies a3". Put them in the order the relationship runs.
- **Most pairs have no relationship, and saying so costs nothing.** These arguments were grouped by wording, so many merely share a subject. Two arguments about the state are unrelated unless one bears on the other. Omit those pairs entirely -- do not invent a relation to fill the list.
- Only relate arguments listed here, by their handles. Do not invent handles."""


def render_positions_blind(
    neighbourhood: Neighbourhood, by_id: dict[str, dict[str, Any]]
) -> tuple[str, dict[str, str]]:
    """Render `neighbourhood`'s own positions as the relate prompt's
    listing, BLIND: `[a3] <argument>`, never author, book, or year -- the
    same rule `render_claims_blind` applies to extraction. Returns the
    rendered listing and the handle -> `position_id` map
    `relate_neighbourhood` resolves handles against."""
    handles = {f"a{i + 1}": position_id for i, position_id in enumerate(neighbourhood.position_ids)}
    listing = "\n".join(f"[{handle}] {by_id[pid]['argument']}" for handle, pid in handles.items())
    return listing, handles


def relate_neighbourhood(
    neighbourhood: Neighbourhood,
    by_id: dict[str, dict[str, Any]],
    client: LLMClient,
    pass_name: str = RELATE_PASS_NAME,
) -> dict[str, Any]:
    """One model call for `neighbourhood`. Returns a read record:
    `neighbourhood` (its own key), `positions` (members offered),
    `relations` (each carrying `from_position_id`, `to_position_id`, the
    model's own `relation` label stripped and lowercased, and `says`),
    `dropped` (a relation naming a handle that was not offered, or naming
    itself, is dropped, never repaired -- both classes are counted here,
    never repaired or silently ignored), and -- only on failure -- `error`.

    Mirrors `extract_positions_for_slice`'s own fault-isolation contract: a
    transport failure, a refused/malformed response, or a response shaped
    as something other than the expected object are all caught here and
    recorded as `error` rather than raised, so one bad call never aborts
    the whole relate pass."""
    listing, handles = render_positions_blind(neighbourhood, by_id)
    record: dict[str, Any] = {
        "neighbourhood": neighbourhood.key,
        "positions": len(neighbourhood.position_ids),
        "relations": [],
    }
    dropped = 0
    try:
        parsed = parse_model_json(
            client.complete(RELATE_PROMPT.format(positions=listing), pass_name=pass_name)
        )
        for entry in parsed.get("relations") or []:
            src, dst = entry.get("from"), entry.get("to")
            if src not in handles or dst not in handles or src == dst:
                dropped += 1
                continue
            record["relations"].append(
                {
                    "from_position_id": handles[src],
                    "to_position_id": handles[dst],
                    "relation": (entry.get("relation") or "").strip().lower(),
                    "says": entry.get("says", ""),
                }
            )
    except (LLMError, httpx.HTTPError, ModelJsonError, AttributeError, TypeError) as exc:
        record["error"] = str(exc)[:200]
    record["dropped"] = dropped
    return record


def run_relations(
    neighbourhoods: Sequence[Neighbourhood],
    by_id: dict[str, dict[str, Any]],
    *,
    client: LLMClient,
    reads_path: Path,
    pass_name: str = RELATE_PASS_NAME,
    workers: int = WORKERS,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Run every neighbourhood in `neighbourhoods` through one relate call
    each, resumable by `Neighbourhood.key` via `reads_path` -- the same
    collecting-thread pattern `run_extraction` uses: calls run concurrently
    (`workers`), but every checkpoint write happens on this one collecting
    thread, so a mid-run kill can never race two threads onto the same
    line, and every result is durable the instant it returns.

    Returns every read now on disk for `reads_path`: this run's own results
    plus any earlier run's resumed ones, read back after the pool drains."""
    done = {
        record["neighbourhood"]
        for record in load_checkpoint_records(reads_path, CorruptRelationsLedgerError)
    }
    if done:
        log(f"resuming: {len(done)} neighbourhood(s) already read")
    pending = [n for n in neighbourhoods if n.key not in done]
    log(f"neighbourhoods to read this run: {len(pending)} of {len(neighbourhoods)}")

    if pending:
        with ThreadPoolExecutor(max_workers=max(workers, 1)) as pool:
            futures = {
                pool.submit(relate_neighbourhood, n, by_id, client, pass_name): n for n in pending
            }
            completed = 0
            for future in as_completed(futures):
                record = future.result()
                append_checkpoint_record(reads_path, record)
                completed += 1
                log(f"  read {completed}/{len(pending)} (neighbourhood {record['neighbourhood']})")

    return load_checkpoint_records(reads_path, CorruptRelationsLedgerError)


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


def _force_aside_suffix() -> str:
    """A stable, lexically sortable suffix for a forced-aside reads ledger:
    UTC to microsecond precision, so two `--force` runs seconds apart -- or
    a test doing both in the same process -- never collide and overwrite
    each other's set-aside ledger."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def _prior_pin_dir(map_dir: Path, current_pin: str) -> Path | None:
    """The most recently written sibling pin directory under `map_dir` (by
    its own `map.json` mtime), excluding `current_pin` -- "the newest prior
    pin" issue #677 seeds a new pin's bag state and reads ledger from.
    `None` when `map_dir` does not exist or holds no other completed pin
    (`map.json` is written last, at the very end of a build, so a directory
    without one was never a completed build to seed from).

    A category variant directory (issue #829) is never a candidate. It is a
    sibling under the same `map_dir` and it does carry a `map.json`, so
    without this it would be the newest "prior pin" the moment it is built --
    and a later default rebuild would then seed its ledger from reads asked
    over category groups. A real pin is a 16-character hex digest, so it can
    never end in this suffix.

    That exclusion reaches the second caller too: `axial.argmap.purity.
    resolve_map_pin_dir` resolves a bare `axial map purity`/`map
    grouping-report` through here, so those keep measuring the DEFAULT build
    once a variant exists beside it. Reading the variant is `--pin
    <pin>-category`, which bypasses this resolution entirely."""
    root = Path(map_dir)
    if not root.is_dir():
        return None
    candidates = [
        child
        for child in root.iterdir()
        if child.is_dir()
        and child.name != current_pin
        and not child.name.endswith(CATEGORY_VARIANT_SUFFIX)
        and (child / "map.json").is_file()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda child: (child / "map.json").stat().st_mtime_ns)


def _seed_reads_from_prior_pin(
    jobs: Sequence[ExtractJob],
    reads_path: Path,
    prior_reads_path: Path,
    log: Callable[[str], None],
) -> None:
    """Seed `reads_path` with a prior pin's own read record for every job in
    `jobs` whose slice composition (`_members_key`) exactly matches one --
    issue #677: adding books should not re-ask a slice whose content did not
    change. Only ever adds a record for a `(bag, slice)` not already on
    `reads_path` (an in-progress resume of THIS pin is left untouched), and
    the seeded record's own `bag`/`slice` fields are rewritten to the
    CURRENT job's numbering -- `run_extraction`'s resume lookup stays keyed
    by `(bag, slice)`, unchanged; only how that ledger gets pre-populated is
    new. A prior record carrying no `members_key` (written before this
    issue) is simply never a match, the same "no reusable state" fallback
    every other guard in this module takes."""
    if not prior_reads_path.is_file():
        return
    prior_records = load_checkpoint_records(prior_reads_path, CorruptReadsLedgerError)
    prior_by_key = {
        record["members_key"]: record for record in prior_records if record.get("members_key")
    }
    if not prior_by_key:
        return

    already_done = {
        (record["bag"], record["slice"])
        for record in load_checkpoint_records(reads_path, CorruptReadsLedgerError)
    }
    seeded = 0
    for job in jobs:
        if (job.bag, job.slice_index) in already_done:
            continue
        prior = prior_by_key.get(_members_key(job.members))
        if prior is None:
            continue
        seeded_record = dict(prior)
        seeded_record["bag"] = job.bag
        seeded_record["slice"] = job.slice_index
        append_checkpoint_record(reads_path, seeded_record)
        seeded += 1
    if seeded:
        log(
            f"map: seeded {seeded} read(s) from {prior_reads_path.parent.name}'s own "
            "matching slice(s)"
        )


def run_map_build(
    *,
    answers_dir: Path | None = None,
    trees_dir: Path | None = None,
    envelopes_dir: Path | None = None,
    sources_dir: Path | None = None,
    map_dir: Path | None = None,
    vocabulary_dir: Path | None = None,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
    encode: Encoder | None = None,
    workers: int = WORKERS,
    guard: bool = True,
    pin: str | None = None,
    force: bool = False,
    grouping: str = GROUPING_BAG,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run both stages -- positions, then relations -- and write
    `<map_dir>/<pin>/{positions.jsonl, relations.jsonl, map.json,
    reads.jsonl, relation_reads.jsonl}`, returning the manifest also
    written to `map.json`. One command builds the whole map: there is no
    second subcommand, and each stage is independently resumable and
    independently `--force`-able under the same pin.

    `pin` defaults to `compute_corpus_pin(envelopes_dir, sources_dir)`; a
    caller may pass one explicitly (the seam every other run_* function in
    this codebase exposes for path/id overrides) to build/test without a
    real `data/envelopes/`+`data/sources/` on disk. `encode`/`client`
    default to the real MiniLM encoder and `axial.llm.get_client()`; both
    are injection seams for tests.

    `force` (default off, so no existing caller's behaviour changes): the
    corpus pin alone is deliberately blind to a prompt or model-tier change
    (`compute_corpus_pin`'s own docstring), so a rebuild after one of those
    would otherwise *resume* from a stale ledger and produce a map that is
    half old prompt, half new. `force` moves each stage's own existing
    ledger (`reads.jsonl`, and separately `relation_reads.jsonl`) aside to a
    timestamped sibling -- never deletes it, a paid ledger stays on disk --
    and re-asks every read under this pin. The founder's chosen escape
    hatch for a prompt change is one whole rebuild by hand; this is what
    that rebuild fires.

    **Issue #677: a corpus change that moves the pin does not re-bag or
    re-ask everything.** When `map_dir` holds a completed prior pin whose
    own persisted bag state (`bag_state.json`) matches this run's encoder,
    `BAG_DISTANCE_THRESHOLD`, and installed scikit-learn version, this run
    keeps every already-seen passage's own bag label and places a new one
    by nearest centroid (`_incremental_bag_passages`) instead of re-fitting
    the whole corpus; a bag centroid no new passage is nearest to is never
    touched. `reads.jsonl` is then seeded, before any call is made, with
    the prior pin's own read for every slice whose ordered claims match
    exactly (`_seed_reads_from_prior_pin`), so `run_extraction`'s existing
    `(bag, slice)` resume skips those with no model call. `force=True`
    skips both -- a full re-bag is always available and never automatic.

    **Issue #829: `grouping=GROUPING_CATEGORY` builds the re-formed map
    beside the default one.** Step 2 groups by slice 03's chosen `claim x
    mechanism` split plus the claim-only fallback (`axial.argmap.grouping.
    load_category_grouping`) instead of wording similarity, and everything
    downstream -- author-spread slicing, the blind render, the extraction
    call, the resume ledger, the merge -- is the same code over a different
    grouping. The variant writes to `<pin>-category/`, never `<pin>/`, and
    it consults no prior pin at all: neither for bag state (a category cell
    has no centroid to place against) nor for seeded reads (a prior pin's
    reads are the DEFAULT build's, and seeding from them would silently
    reproduce the very map this variant exists to be compared against).
    Stage 2, relations, is skipped -- it is slice 07's, and the variant's
    manifest carries no relations block."""
    started = time.monotonic()
    if grouping not in GROUPING_MODES:
        raise MapError(f"unknown grouping {grouping!r} (expected one of {GROUPING_MODES})")
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

    category_grouped = grouping == GROUPING_CATEGORY
    outdir = Path(map_dir) / (f"{pin}{CATEGORY_VARIANT_SUFFIX}" if category_grouped else pin)
    outdir.mkdir(parents=True, exist_ok=True)
    if guard:
        claim_single_instance(outdir)
    log(f"corpus pin {pin} | grouping {grouping} -> {outdir}")

    passages = select_passages(answers_dir, trees_dir)
    log(f"passages {len(passages)} | authors {len({p.author for p in passages})}")

    ungrouped_chunk_ids: tuple[str, ...] = ()
    scheme_versions: dict[str, str] = {}
    if category_grouped:
        # Imported here, not at module scope: `axial.argmap.grouping` imports
        # this module for its own constants and clustering seam, so a
        # top-level import either way is a cycle.
        from axial.argmap.grouping import load_category_grouping

        by_chunk_id = {passage.chunk_id: passage for passage in passages}
        grouped = load_category_grouping(by_chunk_id.keys(), vocabulary_dir=vocabulary_dir)
        scheme_versions = grouped.scheme_versions
        _check_scheme_versions(outdir, scheme_versions, force=force)
        bags = {
            group.label: [by_chunk_id[chunk_id] for chunk_id in group.chunk_ids]
            for group in grouped.result.groups
        }
        ungrouped_chunk_ids = grouped.result.ungrouped_chunk_ids
        prior_pin_dir = None
        schemes = ", ".join(
            f"{column} {version}" for column, version in sorted(scheme_versions.items())
        )
        log(
            f"groups {len(bags)} (claim x mechanism, schemes {schemes}; "
            f"{len(ungrouped_chunk_ids)} passage(s) reached no group)"
        )
        _write_category_group_state(_bag_state_path(outdir), bags, scheme_versions)
    else:
        # Issue #677: `--force` always re-bags globally (the founder's chosen
        # escape hatch), so a forced run never even looks for a prior pin.
        prior_pin_dir = None if force else _prior_pin_dir(Path(map_dir), pin)
        prior_bag_state = (
            _load_json_or_none(_bag_state_path(prior_pin_dir))
            if prior_pin_dir is not None
            else None
        )
        if prior_bag_state is not None and not _bag_state_reusable(prior_bag_state):
            log(
                f"map: prior bag state at {prior_pin_dir} does not match this run's "
                "encoder/threshold/library version -- falling back to a full re-bag"
            )
            prior_bag_state = None

        if prior_bag_state is not None:
            bags, centroids, new_count = _incremental_bag_passages(
                passages, encode, prior_bag_state
            )
            log(
                f"bags {len(bags)} (incremental against {prior_pin_dir.name}: "
                f"{new_count} new passage(s) placed, {len(passages) - new_count} kept "
                "their prior bag)"
            )
        else:
            bags, centroids = _bag_passages_with_centroids(passages, encode)
            log(f"bags {len(bags)} (full re-bag)")

        _write_bag_state(_bag_state_path(outdir), bags, centroids)

    unit_word = "group" if category_grouped else "bag"
    jobs = build_jobs(bags)
    # Issue #829: "every passage shown once" read as a coverage guarantee,
    # printed one line under "17 passage(s) reached no group". It only ever
    # meant that no passage appears in two reads.
    log(
        f"reads {len(jobs)} over {len(bags)} {unit_word}(s) "
        f"(no passage appears in more than one read)"
    )

    if client is None:
        client = get_client(config_path=config_path)

    reads_path = outdir / "reads.jsonl"
    if force and reads_path.exists():
        prior = load_checkpoint_records(reads_path, CorruptReadsLedgerError)
        aside_path = outdir / f"reads.{_force_aside_suffix()}.jsonl"
        reads_path.replace(aside_path)
        log(
            f"--force: set aside {len(prior)} prior read(s) to {aside_path.name}; "
            f"re-asking all {len(jobs)} read(s) under this pin"
        )
    elif prior_pin_dir is not None:
        _seed_reads_from_prior_pin(jobs, reads_path, prior_pin_dir / "reads.jsonl", log)

    # The four #677 counters: computed from the ledger's own state right
    # before `run_extraction` spends a single call, so "reused" always means
    # "already on disk, whether by this pin's own resume or by a prior
    # pin's seeded match" and "asked" is exactly what `run_extraction`'s own
    # `pending` list is about to work through.
    already_on_disk = {
        (record["bag"], record["slice"])
        for record in load_checkpoint_records(reads_path, CorruptReadsLedgerError)
    }
    prior_source_ids: set[str] = set()
    if prior_pin_dir is not None:
        prior_manifest = _load_json_or_none(prior_pin_dir / "map.json")
        if prior_manifest is not None:
            prior_source_ids = set(prior_manifest.get("source_ids", []))
    units_total = len(jobs)
    units_reused = sum(1 for job in jobs if (job.bag, job.slice_index) in already_on_disk)
    units_asked_touching_new = sum(
        1
        for job in jobs
        if (job.bag, job.slice_index) not in already_on_disk
        and (
            not prior_source_ids
            or any(member.source_id not in prior_source_ids for member in job.members)
        )
    )

    reads = run_extraction(
        jobs,
        client=client,
        reads_path=reads_path,
        workers=workers,
        unit_word=unit_word,
        log=log,
    )

    raw_positions = [position for read in reads for position in read["positions"]]
    errors = [read for read in reads if "error" in read]
    # Issue #829 (review): `failed_reads` counts READS, so the manifest's
    # passage arithmetic did not close -- selected minus ungrouped minus
    # placed minus unassigned left a remainder a reader could only guess
    # was the failed reads' own passages. This is that remainder, named:
    # every passage shown in a read that came back with an error.
    passages_in_failed_reads = sum(read.get("shown", 0) for read in errors)
    unassigned = sum(read.get("unassigned", 0) for read in reads)
    # Issue #829: two different numbers, both named. `placed_slots` sums
    # member slots over RAW positions, so a passage named in two raw
    # positions of the same read counts twice -- on the live build that read
    # 6,070 against 6,010 selected, as if more passages were placed than were
    # shown. `placed_distinct` is the honest figure: how many passages reach
    # a position at all, and it is the same set the merge writes to
    # `positions.jsonl`, since merging only unions chunk ids.
    placed_slots = sum(position["size"] for position in raw_positions)
    placed_distinct = len(
        {chunk_id for position in raw_positions for chunk_id in position["chunk_ids"]}
    )
    log(
        f"raw positions {len(raw_positions)} | placed slots {placed_slots} | "
        f"distinct passages placed {placed_distinct} of {len(passages)} selected | "
        f"unassigned {unassigned} | "
        f"failed reads {len(errors)} ({passages_in_failed_reads} passage(s))"
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

    # ------------------------------------------------------------------
    # Stage 2: relations between positions (issue #572, PR 2 of 4).
    # ------------------------------------------------------------------
    # Skipped entirely for a category-grouped variant (issue #829):
    # relations over the variant are slice 07's, and asking them here
    # would spend a paid pass on a map the consolidation pass has not
    # run over yet. The manifest then carries no relations block at all.
    relations_manifest: dict[str, Any] | None = None
    if not category_grouped:
        by_id = {position["position_id"]: position for position in stamped}
        neighbourhoods = build_neighbourhoods(stamped, encode)
        singletons = len(stamped) - sum(len(n.position_ids) for n in neighbourhoods)
        log(
            f"neighbourhoods {len(neighbourhoods)} (positions {len(stamped)}, "
            f"target size {TARGET_NEIGHBOURHOOD}, max {MAX_NEIGHBOURHOOD}, "
            f"{singletons} singleton(s) skipped)"
        )

        relation_reads_path = outdir / "relation_reads.jsonl"
        if force and relation_reads_path.exists():
            prior_relation_reads = load_checkpoint_records(
                relation_reads_path, CorruptRelationsLedgerError
            )
            relation_aside_path = outdir / f"relation_reads.{_force_aside_suffix()}.jsonl"
            relation_reads_path.replace(relation_aside_path)
            log(
                f"--force: set aside {len(prior_relation_reads)} prior relation read(s) to "
                f"{relation_aside_path.name}; re-asking all {len(neighbourhoods)} "
                "neighbourhood(s) under this pin"
            )
        relation_reads = run_relations(
            neighbourhoods,
            by_id,
            client=client,
            reads_path=relation_reads_path,
            workers=workers,
            log=log,
        )

        flat_relations = [relation for read in relation_reads for relation in read["relations"]]
        failed_relation_reads = [read for read in relation_reads if "error" in read]
        dropped_relations = sum(read.get("dropped", 0) for read in relation_reads)
        pairs_possible = sum(
            read["positions"] * (read["positions"] - 1) // 2
            for read in relation_reads
            if "error" not in read
        )
        distinct_labels = len({relation["relation"] for relation in flat_relations})
        cross_author_relations = sum(
            1
            for relation in flat_relations
            if set(by_id[relation["from_position_id"]]["authors"])
            != set(by_id[relation["to_position_id"]]["authors"])
        )
        log(
            f"relations {len(flat_relations)} of {pairs_possible} possible pairs "
            f"(dropped {dropped_relations}, failed reads {len(failed_relation_reads)}, "
            f"distinct labels {distinct_labels}, cross-author {cross_author_relations})"
        )

        with (outdir / "relations.jsonl").open("w", encoding="utf-8") as handle:
            for relation in flat_relations:
                handle.write(json.dumps(relation, ensure_ascii=False) + "\n")

        relation_usage = client.usage_for_pass(RELATE_PASS_NAME)
        relation_model = client.model_for_pass(RELATE_PASS_NAME)
        relation_cost = (
            estimate_cost(
                relation_model, relation_usage["prompt_tokens"], relation_usage["completion_tokens"]
            )
            if relation_usage
            else None
        )
        # Nested rather than mixed into the manifest's own fields -- this
        # manifest describes both stages, and nothing here overwrites the
        # position stage's own counts/usage/cost.
        relations_manifest = {
            "counts": {
                "neighbourhoods_read": len(relation_reads),
                "failed_reads": len(failed_relation_reads),
                "relations_asserted": len(flat_relations),
                "pairs_possible": pairs_possible,
                "distinct_labels": distinct_labels,
                "cross_author_relations": cross_author_relations,
                "dropped_relations": dropped_relations,
            },
            "model": relation_model,
            "reasoning": POSITION_RELATE_REASONING,
            "usage": relation_usage,
            "cost_usd": relation_cost,
        }

    manifest = {
        "corpus_pin": pin,
        # Issue #677: which sources this pin's own passages came from --
        # what a LATER pin reads back (`prior_source_ids` above) to decide
        # whether an asked read is "touching new" material or just a
        # re-cut slice of books already seen.
        "source_ids": sorted({passage.source_id for passage in passages}),
        "counts": {
            "passages_selected": len(passages),
            # Issue #829 (review): under category grouping these units are
            # vocabulary cells, not wording bags. Same key in both manifests
            # made `bags 660 -> 176` read as one quantity changing when the
            # two are read side by side, which is the defect
            # `passages_placed` was already split to avoid. A mode emits
            # only its own name.
            ("groups" if category_grouped else "bags"): len(bags),
            "reads": len(jobs),
            # Issue #677: how much of this run's own reads work was
            # actually new. `units_total` is `reads` again, kept alongside
            # it under the name the issue's own acceptance bar names;
            # `units_reused` is how many needed no model call this run
            # (already on disk, whether by this pin's own resume or a
            # prior pin's seeded match), `units_asked` is what
            # `run_extraction` actually had to call the model for, and
            # `units_asked_touching_new` is the subset of those touching a
            # source absent from the previous pin's own manifest (or every
            # asked read, when there is no previous pin to compare against).
            "units_total": units_total,
            "units_reused": units_reused,
            "units_asked": units_total - units_reused,
            "units_asked_touching_new": units_asked_touching_new,
            "raw_positions": len(raw_positions),
            "merged_positions": len(stamped),
            # Issue #829: the old single `passages_placed` was the slot sum
            # under a name that read as a passage count. Both figures are
            # kept, each saying which it is, and neither reuses the
            # ambiguous name.
            "passages_placed_slots": placed_slots,
            "passages_placed_distinct": placed_distinct,
            # A handle the model itself named as making no argument -- NOT
            # `passages_ungrouped`, which is a passage that reached no group
            # to be shown in at all (issue #829).
            "passages_unassigned": unassigned,
            "passages_ungrouped": len(ungrouped_chunk_ids),
            "failed_reads": len(errors),
            # `failed_reads` is a count of READS. This is the passages they
            # were shown, so `passages_selected - passages_ungrouped -
            # passages_placed_distinct - passages_unassigned -
            # passages_in_failed_reads` closes without a reader dividing
            # anything (issue #829 review).
            "passages_in_failed_reads": passages_in_failed_reads,
        },
        # Issue #829: what step 2 grouped by, and -- for a category-grouped
        # build -- the vocabulary scheme versions it grouped under.
        # `scheme_versions` is empty under `GROUPING_BAG`, which consults no
        # vocabulary at all.
        "grouping": {"mode": grouping, "scheme_versions": scheme_versions},
        "model": model,
        "reasoning": POSITION_EXTRACT_REASONING,
        # `ENCODER_MODEL` (issue #572, PR 3 of 4): the position-argument
        # sentences below are only comparable to a question's own vectors if
        # both were embedded by the same model. Recorded as the constant
        # itself, not introspected from `encode` -- like `reasoning` above,
        # an injected callable (a test's fake encoder, or any future
        # override) exposes no identity to read back, so this names the
        # encoder the DEFAULT build path carries; a caller who injects a
        # different one is responsible for knowing it no longer matches what
        # this field claims.
        "encoder": ENCODER_MODEL,
        "usage": usage,
        "cost_usd": cost,
        "wall_time_sec": time.monotonic() - started,
    }
    if relations_manifest is not None:
        manifest["relations"] = relations_manifest
    (outdir / "map.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if guard:
        (outdir / "RUNNING.pid").unlink(missing_ok=True)
    log(f"wrote {outdir}")
    return manifest
