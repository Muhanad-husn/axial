"""`axial map compare` (issue #831): the structural verdict on whether the
re-formed map earned slices 07-09 (`docs/approach-positions-not-names.md`
§13).

Two map builds side by side -- the default (bag-grouped) build and the
category-grouped variant -- plus, optionally, a forced replicate of the
variant that supplies the error bar. Five metrics decide; everything else
printed is context.

    D1  book-spread ratio, size-matched: mean distinct `source_id` per
        position over the same figure under a seeded permutation of that
        build's OWN placed pool into positions of identical sizes.
    D2  held-out `position`-axis purity, size-matched: the modal `position`
        category's share of a position's CATEGORISED members, over the same
        null. The axis is built and never grouped on (issue #838).
    D3  member coherence: mean cosine of a position's members' `claim` texts
        to that position's own centroid, MiniLM `all-MiniLM-L6-v2`, band by
        band, each band against its own null.
    D4  passages reaching no position: `passages_selected` minus the DISTINCT
        chunk ids in `positions.jsonl`.
    D5  a blind paired hand-sample. Not computed here and never will be.

Zero model calls and zero network apart from the encoder D3 needs, which is
the same local sentence-transformer every other stage builds.

**Why D4 is counted the way it is.** `build.py` logs `placed` as the sum of
member slots over RAW positions -- 6,070 against 6,010 selected on the live
build, so "selected minus placed" prints -60. Positions overlap (issue #822:
344 of 5,596 placed chunks sit in 2-5 positions), so member slots are not
passages and never were. D4 subtracts the distinct chunk ids, and every
share printed anywhere below names the denominator it is a share of.

**Why an absent field is not a mismatch.** The identity check refuses on a
corpus pin, an answers pin or a vocabulary scheme version that DIFFERS
between the builds. A field recorded on one side and absent on the other is
reported as "not recorded" and does not refuse: a bag-grouped build
legitimately carries no `grouping` block at all, and neither build's
`map.json` carries an answers pin today. Refusing on absence would refuse
the exact pair this command exists to compare.

**Where the source and the claim text come from.** A position record lists
its `chunk_ids` and the SET of its `sources`, never the mapping between
them, and it carries no claim text at all. Both come from the built
`claim` vocabulary column (`chunk_id`, `source_id`, `value`), which D2
already needs its sibling `position` column for. No chunk-id string
parsing: the mapping is on disk, exactly, in a file this command reads
anyway."""

from __future__ import annotations

import collections
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from axial.argmap.build import ENCODER_MODEL, Encoder, _default_encoder
from axial.argmap.grouping import _load_json_or_none, _read_assignment_records
from axial.argmap.vocabulary_join import NoVocabularyError
from axial.vocabulary import ASSIGNMENTS_FILENAME, MANIFEST_FILENAME, ROOT_LEVEL, VOCABULARY_DIR

# The size bands issue #831 states D1 and D3 in. Sizes below 2 have no book
# spread and no centroid to be coherent around, so they are context (the
# single-passage share) and never a band. The top band is open-ended rather
# than closed at 48: 48 is the default build's own largest position, not a
# rule, and a variant position larger than that must land somewhere.
SIZE_BANDS: tuple[tuple[int, int | None, str], ...] = (
    (2, 2, "2"),
    (3, 5, "3-5"),
    (6, 10, "6-10"),
    (11, None, "11+"),
)

# D2's assignment-instability floor, measured 2026-08-29 by drawing the
# `position` column a second time under a second model and recomputing D2's
# baseline over both draws: 0.7597 (deepseek-v4-flash) against 0.7266
# (gpt-5.6-luna), roughly twice the permutation null's own trial spread of
# 0.016-0.017 (`data/logs/2026-08-29-position-draw-b/`). A measurement, not
# a tuned constant -- and a parameter of `compute_comparison` rather than a
# CLI flag, because re-measuring it is a paid pass, not a preference.
D2_ASSIGNMENT_INSTABILITY_FLOOR = 0.0331

# The margin every claim must clear over the measured replicate gap. A
# chosen margin, stated as one in issue #831: the smallest multiple that
# keeps a claim outside the interval a single replicate can resolve, and
# stricter than #809's "inside its own draw spread" test, which this feature
# has already failed once.
MARGIN_FACTOR = 2.0

DEFAULT_SEED = 831
DEFAULT_TRIALS = 20

# Reporting only, quoted next to the verdict per the approach doc's §6 noise
# policy. None of these three moves a verdict; what binds D2 is
# `D2_ASSIGNMENT_INSTABILITY_FLOOR` above, which was derived from the third.
NOISE_NOTES: tuple[str, ...] = (
    "`claim` assignment disagreement ~23% at n=100 (#826)",
    "`position` two-model agreement 73.8% where assigned (n=84), 70.0% overall (#838)",
    "`position` full-column label agreement 73.0% where both draws assigned, n=5,581 (#831)",
)

PASSED = "passed"
FAILED = "failed"
NOT_RESOLVED = "not resolved at this sample"
NOT_COMPUTED = "not computed"

NOT_RECORDED = "not recorded"


class CompareError(Exception):
    """Base class for every error `axial.argmap.compare` raises."""


class NoBuildError(CompareError):
    """Raised when a directory handed to `map compare` is not a completed
    map build -- no `map.json`, or no `positions.jsonl`. Named, with the
    path and the missing file, rather than a traceback: the fix is a
    directory argument pointing at a real build."""

    def __init__(self, path: Path, missing: str) -> None:
        self.path = path
        self.missing = missing
        super().__init__(f"{path} is not a completed map build -- no {missing}")


class IdentityMismatchError(CompareError):
    """Raised when the builds disagree on the corpus pin, the answers pin or
    a vocabulary scheme version. Names the field and every value recorded
    for it, per build, because the whole point of the refusal is telling the
    reader WHICH one differs (issue #831's acceptance criterion)."""

    def __init__(self, field: str, values: Mapping[str, str]) -> None:
        self.field = field
        self.values = dict(values)
        rendered = ", ".join(f"{label} {value}" for label, value in self.values.items())
        super().__init__(
            f"the builds disagree on {field}: {rendered} -- `map compare` only puts two "
            "builds side by side when they were built over the same material"
        )


# ---------------------------------------------------------------------------
# Reading a build off disk
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    """One selected passage, as the built vocabulary columns record it:
    which book it came from, its own `claim` sentence, and its category on
    the held-out `position` axis. Any of the three can be absent -- a
    passage the column never reached is missing, never zero."""

    source_id: str | None
    claim: str | None
    position_category: str | None


@dataclass(frozen=True)
class Build:
    """One map build's artifacts, read and nothing more."""

    path: Path
    label: str
    manifest: dict[str, Any]
    positions: tuple[tuple[str, ...], ...]
    reads: tuple[dict[str, Any], ...]
    group_state: frozenset[str] | None

    @property
    def counts(self) -> Mapping[str, Any]:
        counts = self.manifest.get("counts")
        return counts if isinstance(counts, dict) else {}

    @property
    def corpus_pin(self) -> str | None:
        value = self.manifest.get("corpus_pin")
        return value if isinstance(value, str) else None

    @property
    def answers_pin(self) -> str | None:
        value = self.manifest.get("answers_pin")
        return value if isinstance(value, str) else None

    @property
    def grouping_mode(self) -> str | None:
        grouping = self.manifest.get("grouping")
        if not isinstance(grouping, dict):
            return None
        mode = grouping.get("mode")
        return mode if isinstance(mode, str) else None

    @property
    def scheme_versions(self) -> dict[str, str]:
        grouping = self.manifest.get("grouping")
        if not isinstance(grouping, dict):
            return {}
        versions = grouping.get("scheme_versions")
        if not isinstance(versions, dict):
            return {}
        return {str(k): str(v) for k, v in versions.items()}


def load_build(path: Path, label: str) -> Build:
    """`path`'s `map.json`, `positions.jsonl`, `reads.jsonl` and group
    state. `reads.jsonl` and `bag_state.json` are optional -- the first
    only sharpens D4's breakdown, the second only D2's of-selected base --
    but a build with no manifest or no positions is not a build."""
    root = Path(path)
    manifest = _load_json_or_none(root / "map.json")
    if manifest is None:
        raise NoBuildError(root, "map.json")
    positions_path = root / "positions.jsonl"
    if not positions_path.is_file():
        raise NoBuildError(root, "positions.jsonl")

    positions: list[tuple[str, ...]] = []
    for line in positions_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        chunk_ids = record.get("chunk_ids")
        if isinstance(chunk_ids, list) and chunk_ids:
            positions.append(tuple(str(chunk_id) for chunk_id in chunk_ids))

    reads: list[dict[str, Any]] = []
    reads_path = root / "reads.jsonl"
    if reads_path.is_file():
        for line in reads_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                reads.append(record)

    state = _load_json_or_none(root / "bag_state.json")
    assignments = (state or {}).get("assignments")
    group_state = frozenset(str(k) for k in assignments) if isinstance(assignments, dict) else None

    return Build(
        path=root,
        label=label,
        manifest=manifest,
        positions=tuple(positions),
        reads=tuple(reads),
        group_state=group_state,
    )


def _column_level(column_dir: Path, level: int | None) -> int:
    manifest = _load_json_or_none(column_dir / MANIFEST_FILENAME)
    if manifest is None:
        raise NoVocabularyError(column_dir.name, column_dir)
    return level if level is not None else int(manifest.get("max_level", ROOT_LEVEL))


def load_passages(vocabulary_dir: Path, level: int | None = None) -> dict[str, Passage]:
    """`chunk_id -> Passage` off the two built columns this command reads:
    `claim` for each passage's own source and claim sentence, `position` for
    the held-out axis. Raises `NoVocabularyError` naming a column that has
    never been built, the same failure `map purity` and `map
    grouping-report` both name rather than a stack trace.

    Reuses `axial.argmap.grouping`'s own assignment reader rather than
    keeping a fourth private copy of it in the package (`purity`,
    `grouping` and `vocabulary_join` already each have one); the extra field
    this command needs -- `source_id` -- is read here."""
    root = Path(vocabulary_dir)

    claim_dir = root / "claim"
    claim_level = _column_level(claim_dir, level)
    source_by_chunk: dict[str, str] = {}
    claim_by_chunk: dict[str, str] = {}
    for record in _read_assignment_records(claim_dir / ASSIGNMENTS_FILENAME):
        if int(record.get("level", ROOT_LEVEL)) != claim_level:
            continue
        chunk_id = str(record.get("chunk_id", ""))
        source_id = record.get("source_id")
        if isinstance(source_id, str) and source_id:
            source_by_chunk[chunk_id] = source_id
        value = record.get("value")
        if isinstance(value, str) and value.strip():
            claim_by_chunk[chunk_id] = value

    position_dir = root / "position"
    position_level = _column_level(position_dir, level)
    category_by_chunk: dict[str, str] = {}
    for record in _read_assignment_records(position_dir / ASSIGNMENTS_FILENAME):
        if int(record.get("level", ROOT_LEVEL)) != position_level:
            continue
        category_id = record.get("category_id")
        if isinstance(category_id, str) and category_id:
            category_by_chunk[str(record.get("chunk_id", ""))] = category_id

    chunk_ids = set(source_by_chunk) | set(claim_by_chunk) | set(category_by_chunk)
    return {
        chunk_id: Passage(
            source_id=source_by_chunk.get(chunk_id),
            claim=claim_by_chunk.get(chunk_id),
            position_category=category_by_chunk.get(chunk_id),
        )
        for chunk_id in chunk_ids
    }


# ---------------------------------------------------------------------------
# The size-matched permutation null
# ---------------------------------------------------------------------------


def band_of(size: int) -> str | None:
    """`size`'s band label, or `None` for a single-passage position -- which
    has no book spread and no centroid, and is reported as a context share
    instead of scored."""
    for low, high, label in SIZE_BANDS:
        if size >= low and (high is None or size <= high):
            return label
    return None


def permute_positions(
    positions: Sequence[Sequence[str]], seed: int
) -> list[tuple[str, ...]]:
    """`positions` re-drawn: this build's own placed pool dealt into
    positions of IDENTICAL sizes, seeded so two runs at one seed give one
    figure twice.

    The pool is the flat list of member SLOTS, not the distinct chunk ids --
    positions overlap (issue #822), and a null that dropped the duplicates
    would not have enough material to fill the same sizes. A permuted
    position can therefore hold one chunk twice, exactly as a real one can
    hold a chunk that another position also holds."""
    pool = [chunk_id for position in positions for chunk_id in position]
    random.Random(seed).shuffle(pool)
    drawn: list[tuple[str, ...]] = []
    cursor = 0
    for position in positions:
        drawn.append(tuple(pool[cursor : cursor + len(position)]))
        cursor += len(position)
    return drawn


# ---------------------------------------------------------------------------
# The metrics
# ---------------------------------------------------------------------------


def _distinct_sources(position: Sequence[str], passages: Mapping[str, Passage]) -> int:
    return len(
        {
            passages[chunk_id].source_id
            for chunk_id in position
            if chunk_id in passages and passages[chunk_id].source_id
        }
    )


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _coherence(position: Sequence[str], vectors: Mapping[str, np.ndarray]) -> float | None:
    """Mean cosine of a position's members to the position's own centroid,
    over the members that HAVE a `claim` text. A member with none is missing
    -- it is left out of the centroid and out of the mean, never counted as
    a zero. Fewer than two vectored members leaves nothing to be coherent
    about, and the position is not scored."""
    rows = [vectors[chunk_id] for chunk_id in position if chunk_id in vectors]
    if len(rows) < 2:
        return None
    matrix = np.array(rows, dtype=float)
    centroid = matrix.mean(axis=0)
    centroid_norm = float(np.linalg.norm(centroid))
    if centroid_norm == 0.0:
        return None
    return float((matrix @ centroid).mean() / centroid_norm)


def _purity(position: Sequence[str], passages: Mapping[str, Passage]) -> tuple[int, int]:
    """`(modal category count, categorised member count)` for one position.
    Uncategorised members are not in the denominator -- D2 decides over
    categorised members, and a position with none of them is excluded and
    counted rather than scored zero."""
    categories = [
        passages[chunk_id].position_category
        for chunk_id in position
        if chunk_id in passages and passages[chunk_id].position_category
    ]
    if not categories:
        return 0, 0
    counts = collections.Counter(categories)
    return max(counts.values()), len(categories)


@dataclass(frozen=True)
class BandStat:
    """One size band of one build: D1 and D3 observed against this build's
    own size-matched null, plus the cross-book rate the approach doc allows
    to be printed only next to that null."""

    label: str
    positions: int
    slots: int
    sources_observed: float | None
    sources_null: float | None
    cross_book_observed: float | None
    cross_book_null: float | None
    coherence_positions: int
    coherence_observed: float | None
    coherence_null: float | None

    @property
    def ratio(self) -> float | None:
        if self.sources_observed is None or not self.sources_null:
            return None
        return self.sources_observed / self.sources_null


@dataclass(frozen=True)
class PurityStat:
    """D2 for one build."""

    scored_positions: int
    excluded_positions: int
    excluded_uncategorised: int
    member_weighted: float | None
    per_position_mean: float | None
    null: float | None
    categorised_of_selected: int
    selected: int
    universe: int | None
    selected_outside_universe: int | None
    categorised_of_placed: int
    placed: int

    @property
    def lift(self) -> float | None:
        if self.member_weighted is None or not self.null:
            return None
        return self.member_weighted / self.null


@dataclass(frozen=True)
class UnplacedStat:
    """D4 for one build."""

    selected: int
    placed_distinct: int
    slots: int
    unplaced: int
    share: float | None
    unassigned: int | None
    in_failed_reads: int | None
    ungrouped: int | None


@dataclass(frozen=True)
class ContextStat:
    """Reported, never deciding (issue #831). Fewer, larger positions and a
    lower single-passage share follow from 113-207 extraction calls
    replacing 679, not from quality."""

    positions: int
    slots: int
    size_p25: float | None
    size_median: float | None
    size_p75: float | None
    single_passage_positions: int
    single_passage_position_share: float | None
    single_passage_slot_share: float | None
    cross_book_positions: int
    banded_positions: int
    cross_book_position_share: float | None
    cross_book_slot_share: float | None
    cross_book_passage_share: float | None
    reads: int | None
    units_asked: int | None
    units_reused: int | None
    cost_usd: float | None
    wall_time_sec: float | None
    consolidation_folds: int | None
    consolidation_folds_per_position: float | None
    embedding_folds: int | None
    embedding_folds_per_position: float | None


@dataclass(frozen=True)
class BuildStats:
    build: Build
    bands: tuple[BandStat, ...]
    purity: PurityStat
    unplaced: UnplacedStat
    context: ContextStat
    missing_source: int
    missing_claim: int
    plurality_band: str | None

    @property
    def label(self) -> str:
        return self.build.label

    def band(self, label: str) -> BandStat | None:
        for band in self.bands:
            if band.label == label:
                return band
        return None


def _quantile(values: Sequence[int], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(fraction * len(ordered))) - 1))
    return float(ordered[index])


def _fold_block(block: Any) -> tuple[int | None, float | None]:
    """`(folds, folds per final position)` out of a manifest fold block.
    `map.json` nests the consolidation pass's figures under `counts` and
    keeps the embedding merge's at the block's own top level, so both
    shapes are read. The two are never added: they are two stages, and a
    single raw-to-merged pair hides which one did the work (issue #830)."""
    if not isinstance(block, dict):
        return None, None
    counts = block.get("counts") if isinstance(block.get("counts"), dict) else block
    folds = counts.get("folds")
    per_position = counts.get("folds_per_final_position")
    return (
        int(folds) if isinstance(folds, (int, float)) else None,
        float(per_position) if isinstance(per_position, (int, float)) else None,
    )


def compute_build_stats(
    build: Build,
    passages: Mapping[str, Passage],
    vectors: Mapping[str, np.ndarray],
    *,
    seed: int,
    trials: int,
) -> BuildStats:
    """Every figure `map compare` prints for one build, over one seeded set
    of `trials` size-matched permutations shared by D1, D2 and D3 -- one
    null, three readings of it."""
    positions = build.positions
    sizes = [len(position) for position in positions]
    slots = sum(sizes)
    placed_distinct = {chunk_id for position in positions for chunk_id in position}

    banded: dict[str, list[Sequence[str]]] = collections.defaultdict(list)
    for position in positions:
        label = band_of(len(position))
        if label is not None:
            banded[label].append(position)

    null_sources: dict[str, list[float]] = collections.defaultdict(list)
    null_cross: dict[str, list[float]] = collections.defaultdict(list)
    null_coherence: dict[str, list[float]] = collections.defaultdict(list)
    null_purity: list[float] = []
    for trial in range(trials):
        drawn = permute_positions(positions, seed + trial)
        drawn_bands: dict[str, list[Sequence[str]]] = collections.defaultdict(list)
        for position in drawn:
            label = band_of(len(position))
            if label is not None:
                drawn_bands[label].append(position)
        for label, group in drawn_bands.items():
            counts = [_distinct_sources(position, passages) for position in group]
            null_sources[label].append(statistics.fmean(counts))
            null_cross[label].append(statistics.fmean([1.0 if c >= 2 else 0.0 for c in counts]))
            scores = [
                score
                for score in (_coherence(position, vectors) for position in group)
                if score is not None
            ]
            if scores:
                null_coherence[label].append(statistics.fmean(scores))
        modal_total = 0
        categorised_total = 0
        for position in drawn:
            modal, categorised = _purity(position, passages)
            if categorised >= 2:
                modal_total += modal
                categorised_total += categorised
        if categorised_total:
            null_purity.append(modal_total / categorised_total)

    bands: list[BandStat] = []
    for _low, _high, label in SIZE_BANDS:
        group = banded.get(label, [])
        if not group:
            continue
        counts = [_distinct_sources(position, passages) for position in group]
        scores = [
            score
            for score in (_coherence(position, vectors) for position in group)
            if score is not None
        ]
        bands.append(
            BandStat(
                label=label,
                positions=len(group),
                slots=sum(len(position) for position in group),
                sources_observed=_mean(counts),
                sources_null=_mean(null_sources.get(label, [])),
                cross_book_observed=_mean([1.0 if c >= 2 else 0.0 for c in counts]),
                cross_book_null=_mean(null_cross.get(label, [])),
                coherence_positions=len(scores),
                coherence_observed=_mean(scores),
                coherence_null=_mean(null_coherence.get(label, [])),
            )
        )

    # D2.
    scored = 0
    excluded = 0
    excluded_uncategorised = 0
    modal_total = 0
    categorised_total = 0
    per_position: list[float] = []
    for position in positions:
        modal, categorised = _purity(position, passages)
        if categorised < 2:
            excluded += 1
            if categorised == 0:
                excluded_uncategorised += 1
            continue
        scored += 1
        modal_total += modal
        categorised_total += categorised
        per_position.append(modal / categorised)

    selected = int(build.counts.get("passages_selected", 0) or 0)
    universe = sorted(build.group_state) if build.group_state is not None else None
    categorised_of_selected = (
        sum(
            1
            for chunk_id in universe
            if chunk_id in passages and passages[chunk_id].position_category
        )
        if universe is not None
        else 0
    )
    purity = PurityStat(
        scored_positions=scored,
        excluded_positions=excluded,
        excluded_uncategorised=excluded_uncategorised,
        member_weighted=(modal_total / categorised_total) if categorised_total else None,
        per_position_mean=_mean(per_position),
        null=_mean(null_purity),
        categorised_of_selected=categorised_of_selected,
        selected=selected,
        universe=len(universe) if universe is not None else None,
        selected_outside_universe=(selected - len(universe)) if universe is not None else None,
        categorised_of_placed=sum(
            1
            for chunk_id in placed_distinct
            if chunk_id in passages and passages[chunk_id].position_category
        ),
        placed=len(placed_distinct),
    )

    # D4. Never a sum of position sizes -- see the module docstring.
    unassigned = sum(int(read.get("unassigned", 0) or 0) for read in build.reads) or None
    in_failed_reads = (
        sum(int(read.get("shown", 0) or 0) for read in build.reads if "error" in read)
        if build.reads
        else None
    )
    ungrouped = build.counts.get("passages_ungrouped")
    unplaced = UnplacedStat(
        selected=selected,
        placed_distinct=len(placed_distinct),
        slots=slots,
        unplaced=selected - len(placed_distinct),
        share=((selected - len(placed_distinct)) / selected) if selected else None,
        unassigned=unassigned,
        in_failed_reads=in_failed_reads,
        ungrouped=int(ungrouped) if isinstance(ungrouped, (int, float)) else None,
    )

    single_passage = [position for position in positions if len(position) == 1]
    banded_positions = [position for position in positions if band_of(len(position)) is not None]
    cross_book = [
        position for position in banded_positions if _distinct_sources(position, passages) >= 2
    ]
    cross_book_chunks = {chunk_id for position in cross_book for chunk_id in position}
    consolidation_folds, consolidation_per = _fold_block(build.manifest.get("consolidation"))
    embedding_folds, embedding_per = _fold_block(build.manifest.get("embedding_merge"))
    cost = build.manifest.get("cost_usd")
    wall = build.manifest.get("wall_time_sec")
    context = ContextStat(
        positions=len(positions),
        slots=slots,
        size_p25=_quantile(sizes, 0.25),
        size_median=_quantile(sizes, 0.5),
        size_p75=_quantile(sizes, 0.75),
        single_passage_positions=len(single_passage),
        single_passage_position_share=(len(single_passage) / len(positions)) if positions else None,
        single_passage_slot_share=(len(single_passage) / slots) if slots else None,
        cross_book_positions=len(cross_book),
        banded_positions=len(banded_positions),
        cross_book_position_share=(
            (len(cross_book) / len(banded_positions)) if banded_positions else None
        ),
        cross_book_slot_share=(
            (sum(len(position) for position in cross_book) / slots) if slots else None
        ),
        cross_book_passage_share=(
            (len(cross_book_chunks) / len(placed_distinct)) if placed_distinct else None
        ),
        reads=_int_or_none(build.counts.get("reads")),
        units_asked=_int_or_none(build.counts.get("units_asked")),
        units_reused=_int_or_none(build.counts.get("units_reused")),
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        wall_time_sec=float(wall) if isinstance(wall, (int, float)) else None,
        consolidation_folds=consolidation_folds,
        consolidation_folds_per_position=consolidation_per,
        embedding_folds=embedding_folds,
        embedding_folds_per_position=embedding_per,
    )

    slots_by_band = collections.Counter(
        {label: sum(len(position) for position in group) for label, group in banded.items()}
    )
    plurality_band = slots_by_band.most_common(1)[0][0] if slots_by_band else None

    return BuildStats(
        build=build,
        bands=tuple(bands),
        purity=purity,
        unplaced=unplaced,
        context=context,
        missing_source=sum(
            1
            for chunk_id in placed_distinct
            if chunk_id not in passages or not passages[chunk_id].source_id
        ),
        missing_claim=sum(1 for chunk_id in placed_distinct if chunk_id not in vectors),
        plurality_band=plurality_band,
    )


def _int_or_none(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceCoverage:
    """How much of one book the `position` column carried a category for,
    over the passages either build placed. Printed per draw and never as a
    fixed corpus fact: draw A refused on `vignal-2021`/`batatu-1999`/
    `tilly-1978`, draw B refused on none of the three and concentrated on
    three different books with empty overlap (issue #831, D2's correction 2).
    A property of the corpus would appear in both draws; this does not."""

    source_id: str
    categorised: int
    placed: int

    @property
    def share(self) -> float | None:
        return self.categorised / self.placed if self.placed else None


def position_coverage_by_source(
    builds: Sequence[BuildStats], passages: Mapping[str, Passage]
) -> tuple[SourceCoverage, ...]:
    """`position`-column coverage per book over every passage any build
    placed, worst-covered first -- the reading #838 got wrong twice by
    quoting one draw's landing places as structural."""
    placed = {
        chunk_id
        for stat in builds
        for position in stat.build.positions
        for chunk_id in position
    }
    totals: dict[str, int] = collections.Counter()
    categorised: dict[str, int] = collections.Counter()
    for chunk_id in placed:
        passage = passages.get(chunk_id)
        if passage is None or not passage.source_id:
            continue
        totals[passage.source_id] += 1
        if passage.position_category:
            categorised[passage.source_id] += 1
    rows = [
        SourceCoverage(source_id, categorised.get(source_id, 0), total)
        for source_id, total in totals.items()
    ]
    return tuple(sorted(rows, key=lambda row: (row.share or 0.0, row.source_id)))


@dataclass(frozen=True)
class Verdict:
    metric: str
    status: str
    reason: str


@dataclass(frozen=True)
class ComparisonReport:
    baseline: BuildStats
    variant: BuildStats
    replicate: BuildStats | None
    seed: int
    trials: int
    instability_floor: float
    vocabulary_dir: Path
    d1_gap: float | None
    d2_gap: float | None
    replicate_gap_usable: bool
    position_coverage: tuple[SourceCoverage, ...]
    verdicts: tuple[Verdict, ...]

    @property
    def overall(self) -> str:
        statuses = {verdict.status for verdict in self.verdicts}
        if FAILED in statuses:
            return "no-go on slices 07-09"
        if NOT_RESOLVED in statuses:
            return NOT_RESOLVED
        return "structural bar met on D1-D4; D5 (the blind hand-sample) still outstanding"


def _d1_verdict(
    baseline: BuildStats,
    variant: BuildStats,
    d1_gap: float | None,
    gap_usable: bool,
) -> Verdict:
    band_label = variant.plurality_band
    if band_label is None:
        return Verdict("D1", NOT_COMPUTED, "the variant has no position of size 2 or more")
    variant_band = variant.band(band_label)
    baseline_band = baseline.band(band_label)
    if variant_band is None or variant_band.ratio is None:
        return Verdict("D1", NOT_COMPUTED, f"no ratio for the plurality band {band_label}")
    if baseline_band is None or baseline_band.ratio is None:
        return Verdict(
            "D1",
            NOT_COMPUTED,
            f"the baseline has no position in the plurality band {band_label} to compare against",
        )

    fallen = [
        band.label
        for band in variant.bands
        if band.ratio is not None
        and (other := baseline.band(band.label)) is not None
        and other.ratio is not None
        and band.ratio < other.ratio
    ]
    if variant_band.ratio < MARGIN_FACTOR * baseline_band.ratio:
        return Verdict(
            "D1",
            FAILED,
            f"{variant_band.ratio:.3f} in the plurality band {band_label} is under "
            f"{MARGIN_FACTOR:g}x the baseline's {baseline_band.ratio:.3f}",
        )
    if fallen:
        return Verdict(
            "D1", FAILED, f"the ratio falls against the baseline in band(s) {', '.join(fallen)}"
        )

    gap = variant_band.ratio - baseline_band.ratio
    if not gap_usable or d1_gap is None:
        return Verdict(
            "D1",
            NOT_RESOLVED,
            f"clears {MARGIN_FACTOR:g}x the baseline in band {band_label} and falls in no band, "
            "but the replicate gap was not measured",
        )
    if MARGIN_FACTOR * d1_gap >= gap:
        return Verdict(
            "D1",
            NOT_RESOLVED,
            f"the gap {gap:.3f} does not exceed {MARGIN_FACTOR:g}x the replicate gap {d1_gap:.3f}",
        )
    return Verdict(
        "D1",
        PASSED,
        f"{variant_band.ratio:.3f} against {MARGIN_FACTOR:g}x the baseline's "
        f"{baseline_band.ratio:.3f} in the plurality band {band_label}; no band falls; the gap "
        f"{gap:.3f} exceeds {MARGIN_FACTOR:g}x the replicate gap {d1_gap:.3f}",
    )


def _d2_verdict(
    baseline: BuildStats,
    variant: BuildStats,
    d2_gap: float | None,
    gap_usable: bool,
    floor: float,
) -> Verdict:
    observed = variant.purity.member_weighted
    reference = baseline.purity.member_weighted
    if observed is None or reference is None:
        return Verdict("D2", NOT_COMPUTED, "one build has no position with 2+ categorised members")
    lift = variant.purity.lift
    if lift is not None and lift <= 1.0:
        return Verdict("D2", FAILED, f"lift {lift:.3f} is at or below 1.00")
    gap = observed - reference
    if gap <= floor:
        return Verdict(
            "D2",
            FAILED,
            f"{observed:.4f} clears the baseline's {reference:.4f} by {gap:.4f}, which does not "
            f"exceed the {floor:.4f} assignment-instability floor",
        )
    if not gap_usable or d2_gap is None:
        return Verdict(
            "D2",
            NOT_RESOLVED,
            f"the gap {gap:.4f} clears the {floor:.4f} instability floor, but the replicate gap "
            "was not measured",
        )
    if MARGIN_FACTOR * d2_gap >= gap:
        return Verdict(
            "D2",
            NOT_RESOLVED,
            f"the gap {gap:.4f} does not exceed {MARGIN_FACTOR:g}x the replicate gap {d2_gap:.4f}",
        )
    reason = (
        f"{observed:.4f} over the baseline's {reference:.4f} by {gap:.4f}, clearing both the "
        f"{floor:.4f} instability floor and {MARGIN_FACTOR:g}x the replicate gap {d2_gap:.4f}"
    )
    if lift is not None:
        reason += f"; lift {lift:.3f}"
    return Verdict("D2", PASSED, reason)


def band_floor(band: BandStat) -> float | None:
    """D3's floor for one band: the midpoint between the BASELINE build's own
    value in that band and that band's permutation null. On the default
    build's 11-48 band -- 0.791 observed, 0.537 null -- that is 0.664."""
    if band.coherence_observed is None or band.coherence_null is None:
        return None
    return (band.coherence_observed + band.coherence_null) / 2


def _d3_verdict(baseline: BuildStats, variant: BuildStats) -> Verdict:
    breaches: list[str] = []
    unfloored: list[str] = []
    checked = 0
    for band in variant.bands:
        if band.coherence_observed is None:
            continue
        reference = baseline.band(band.label)
        floor = band_floor(reference) if reference is not None else None
        if floor is None:
            unfloored.append(band.label)
            continue
        checked += 1
        if band.coherence_observed < floor:
            breaches.append(f"{band.label} {band.coherence_observed:.3f} < {floor:.3f}")
    if breaches:
        return Verdict("D3", FAILED, "breaches the band floor at " + "; ".join(breaches))
    if not checked:
        return Verdict("D3", NOT_COMPUTED, "no band has a floor on the baseline to check against")
    note = (
        f" (no baseline floor for band(s) {', '.join(unfloored)})" if unfloored else ""
    )
    return Verdict("D3", PASSED, f"at or above the baseline/null midpoint in every band{note}")


def _d4_verdict(baseline: BuildStats, variant: BuildStats) -> Verdict:
    observed = variant.unplaced.share
    reference = baseline.unplaced.share
    if observed is None or reference is None:
        return Verdict("D4", NOT_COMPUTED, "a build records no passages_selected")
    if observed > reference:
        return Verdict(
            "D4",
            FAILED,
            f"{observed:.1%} of selected rises above the baseline's {reference:.1%}",
        )
    return Verdict(
        "D4", PASSED, f"{observed:.1%} of selected does not rise above the baseline's {reference:.1%}"
    )


def compute_comparison(
    baseline_dir: Path,
    variant_dir: Path,
    replicate_dir: Path | None = None,
    *,
    vocabulary_dir: Path | None = None,
    level: int | None = None,
    seed: int = DEFAULT_SEED,
    trials: int = DEFAULT_TRIALS,
    encode: Encoder | None = None,
    instability_floor: float = D2_ASSIGNMENT_INSTABILITY_FLOOR,
) -> ComparisonReport:
    """The full comparison (issue #831). `baseline_dir` is the default
    build, `variant_dir` the re-formed one, `replicate_dir` the variant's
    forced replicate -- which supplies the error bar every margin is quoted
    against, and without which D1 and D2 report "not resolved at this
    sample" rather than assuming a gap.

    Raises `NoBuildError` for a directory that is not a build,
    `IdentityMismatchError` when the builds disagree on the corpus pin, the
    answers pin or a vocabulary scheme version, and `NoVocabularyError` when
    the `claim` or `position` column has never been built.

    `encode` defaults to the local sentence-transformer encoder
    (`axial.argmap.build._default_encoder`), constructed only when D3
    actually has text to embed."""
    builds = [load_build(Path(baseline_dir), "A"), load_build(Path(variant_dir), "B")]
    if replicate_dir is not None:
        builds.append(load_build(Path(replicate_dir), "C"))
    check_identity(builds)

    vocab_root = Path(vocabulary_dir) if vocabulary_dir is not None else VOCABULARY_DIR
    passages = load_passages(vocab_root, level)

    placed = {
        chunk_id for build in builds for position in build.positions for chunk_id in position
    }
    texts = {
        chunk_id: passages[chunk_id].claim
        for chunk_id in sorted(placed)
        if chunk_id in passages and passages[chunk_id].claim
    }
    vectors: dict[str, np.ndarray] = {}
    if texts:
        resolved_encode = encode if encode is not None else _default_encoder()
        matrix = np.asarray(resolved_encode(list(texts.values())), dtype=float)
        vectors = {
            chunk_id: row / norm
            for (chunk_id, row) in zip(texts, matrix)
            if (norm := float(np.linalg.norm(row))) > 0.0
        }

    stats = [
        compute_build_stats(build, passages, vectors, seed=seed, trials=trials)
        for build in builds
    ]
    baseline, variant = stats[0], stats[1]
    replicate = stats[2] if len(stats) > 2 else None

    d1_gap: float | None = None
    d2_gap: float | None = None
    gap_usable = False
    if replicate is not None:
        reused = replicate.context.units_reused
        gap_usable = reused == 0
        band_label = variant.plurality_band
        variant_band = variant.band(band_label) if band_label else None
        replicate_band = replicate.band(band_label) if band_label else None
        if (
            variant_band is not None
            and replicate_band is not None
            and variant_band.ratio is not None
            and replicate_band.ratio is not None
        ):
            d1_gap = abs(variant_band.ratio - replicate_band.ratio)
        if (
            variant.purity.member_weighted is not None
            and replicate.purity.member_weighted is not None
        ):
            d2_gap = abs(variant.purity.member_weighted - replicate.purity.member_weighted)

    verdicts = (
        _d1_verdict(baseline, variant, d1_gap, gap_usable),
        _d2_verdict(baseline, variant, d2_gap, gap_usable, instability_floor),
        _d3_verdict(baseline, variant),
        _d4_verdict(baseline, variant),
        Verdict(
            "D5",
            NOT_COMPUTED,
            "a blind paired hand-sample: 12 positions per build, size-stratified, shuffled, "
            "judged before the labels are revealed",
        ),
    )

    return ComparisonReport(
        baseline=baseline,
        variant=variant,
        replicate=replicate,
        seed=seed,
        trials=trials,
        instability_floor=instability_floor,
        vocabulary_dir=vocab_root,
        d1_gap=d1_gap,
        d2_gap=d2_gap,
        replicate_gap_usable=gap_usable,
        position_coverage=position_coverage_by_source(stats, passages),
        verdicts=verdicts,
    )


def check_identity(builds: Sequence[Build]) -> None:
    """Refuse when the builds disagree on the corpus pin, the answers pin or
    any vocabulary scheme version, naming which one differs.

    ABSENT IS NOT A MISMATCH. A field is compared over the builds that
    RECORD it, and a field recorded by fewer than two of them is not
    compared at all. The default build carries no `grouping` block and
    neither build's `map.json` carries an answers pin, so any other reading
    would refuse the exact pair this command exists to compare (issue #831,
    normalisation rule (d))."""

    def compare_field(field: str, values: Mapping[str, str]) -> None:
        if len(set(values.values())) > 1:
            raise IdentityMismatchError(field, values)

    compare_field(
        "the corpus pin",
        {b.label: b.corpus_pin for b in builds if b.corpus_pin is not None},
    )
    compare_field(
        "the answers pin",
        {b.label: b.answers_pin for b in builds if b.answers_pin is not None},
    )
    columns = sorted({column for build in builds for column in build.scheme_versions})
    for column in columns:
        compare_field(
            f"the `{column}` vocabulary scheme version",
            {
                build.label: build.scheme_versions[column]
                for build in builds
                if column in build.scheme_versions
            },
        )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _num(value: float | None, places: int = 2) -> str:
    return f"{value:.{places}f}" if value is not None else "n/a"


def _pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _int(value: int | None) -> str:
    return str(value) if value is not None else NOT_RECORDED


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]], indent: str = "  ") -> list[str]:
    columns = [list(column) for column in zip(headers, *rows)] if rows else [[h] for h in headers]
    widths = [max(len(cell) for cell in column) for column in columns]
    return [
        indent + "  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip()
        for row in [headers, *rows]
    ]


def _all_stats(report: ComparisonReport) -> list[BuildStats]:
    stats = [report.baseline, report.variant]
    if report.replicate is not None:
        stats.append(report.replicate)
    return stats


def format_comparison_report(report: ComparisonReport) -> str:
    """Render `ComparisonReport` as a human-readable report -- every number
    issue #831's acceptance criterion asks for, and no share without the
    denominator it is a share of."""
    stats = _all_stats(report)
    lines: list[str] = [
        "axial map compare -- A is the baseline (the default build), B is the variant"
        + (", C is B's forced replicate" if report.replicate is not None else ""),
        f"seed {report.seed}, {report.trials} permutation trial(s) per null; "
        f"vocabulary {report.vocabulary_dir}",
        "",
        "IDENTITY (a field absent on one side is reported, never a mismatch -- a bag-grouped "
        "build records no grouping block at all)",
    ]
    identity_rows = [
        ["path", *[str(s.build.path) for s in stats]],
        ["corpus pin", *[s.build.corpus_pin or NOT_RECORDED for s in stats]],
        ["answers pin", *[s.build.answers_pin or NOT_RECORDED for s in stats]],
        ["grouping mode", *[s.build.grouping_mode or NOT_RECORDED for s in stats]],
    ]
    for column in sorted({c for s in stats for c in s.build.scheme_versions}):
        identity_rows.append(
            [
                f"scheme version `{column}`",
                *[s.build.scheme_versions.get(column, NOT_RECORDED) for s in stats],
            ]
        )
    lines += _table(["field", *[s.label for s in stats]], identity_rows)
    lines.append("")

    # ---------------- D1 ----------------
    lines.append(
        "D1 BOOK-SPREAD RATIO, SIZE-MATCHED (mean distinct source_id per position, over the "
        "same figure under a seeded permutation of that build's own placed pool into positions "
        "of identical sizes)"
    )
    d1_rows = []
    for stat in stats:
        for band in stat.bands:
            d1_rows.append(
                [
                    stat.label,
                    band.label,
                    str(band.positions),
                    str(band.slots),
                    _num(band.sources_observed),
                    _num(band.sources_null),
                    _num(band.ratio),
                    _pct(band.cross_book_observed),
                    _pct(band.cross_book_null),
                ]
            )
    lines += _table(
        [
            "build",
            "band",
            "positions",
            "slots",
            "observed",
            "null",
            "ratio",
            "cross-book",
            "cross-book null",
        ],
        d1_rows,
    )
    lines.append(
        f"  plurality band on B (the band holding the most member slots): "
        f"{report.variant.plurality_band or 'n/a'}"
    )
    for stat in stats:
        if stat.missing_source:
            lines.append(
                f"  {stat.label}: {stat.missing_source} placed passage(s) with no source_id on "
                "the `claim` column -- missing, never counted as a book"
            )
    lines.append("")

    # ---------------- D2 ----------------
    lines.append(
        "D2 HELD-OUT `position`-AXIS PURITY, SIZE-MATCHED (the modal `position` category's share "
        "of a position's CATEGORISED members; the axis is built and never grouped on)"
    )
    lines += _table(
        [
            "build",
            "scored",
            "excluded (<2 categorised)",
            "of which 0 categorised",
            "member-weighted",
            "null",
            "lift",
            "per-position mean",
        ],
        [
            [
                stat.label,
                str(stat.purity.scored_positions),
                str(stat.purity.excluded_positions),
                str(stat.purity.excluded_uncategorised),
                _num(stat.purity.member_weighted, 4),
                _num(stat.purity.null, 4),
                _num(stat.purity.lift, 3),
                _num(stat.purity.per_position_mean, 4),
            ]
            for stat in stats
        ],
    )
    for stat in stats:
        purity = stat.purity
        if purity.universe is None:
            lines.append(
                f"  categorised base {stat.label}: of-selected n/a (this build persisted no "
                "group state to count over)"
            )
        else:
            share = (
                purity.categorised_of_selected / purity.selected if purity.selected else None
            )
            lines.append(
                f"  categorised base {stat.label}: {purity.categorised_of_selected} of "
                f"{purity.selected} selected ({_pct(share)}) -- counted over this build's own "
                f"group state of {purity.universe} chunk id(s), "
                f"{purity.selected_outside_universe} selected passage(s) outside it"
            )
        placed_share = purity.categorised_of_placed / purity.placed if purity.placed else None
        lines.append(
            f"  categorised base {stat.label}: {purity.categorised_of_placed} of "
            f"{purity.placed} placed ({_pct(placed_share)})"
        )
    lines.append(
        f"  assignment-instability floor: {report.instability_floor:.4f} purity points "
        "(measured 2026-08-29 over two model draws of the `position` column)"
    )
    lines.append(
        f"  `position` coverage per book for THIS DRAW ({report.vocabulary_dir}), over the "
        "passages either build placed -- worst first, and a property of this draw, never of "
        "the corpus: which books a draw refuses on does not reproduce across models (#838)"
    )
    for coverage in report.position_coverage:
        lines.append(
            f"    {coverage.source_id}: {coverage.categorised} of {coverage.placed} "
            f"({_pct(coverage.share)})"
        )
    lines.append("")

    # ---------------- D3 ----------------
    lines.append(
        f"D3 MEMBER COHERENCE (mean cosine of members' `claim` texts to their position's own "
        f"centroid, {ENCODER_MODEL}; the floor is the midpoint of A's own band value and A's "
        "own band null)"
    )
    d3_rows = []
    for stat in stats:
        for band in stat.bands:
            reference = report.baseline.band(band.label)
            floor = band_floor(reference) if reference is not None else None
            d3_rows.append(
                [
                    stat.label,
                    band.label,
                    str(band.coherence_positions),
                    _num(band.coherence_observed, 4),
                    _num(band.coherence_null, 4),
                    _num(floor, 4),
                ]
            )
    lines += _table(
        ["build", "band", "positions scored", "observed", "null", "floor"], d3_rows
    )
    lines.append(
        "  members with no `claim` text (missing, never scored 0): "
        + " | ".join(f"{stat.label} {stat.missing_claim}" for stat in stats)
    )
    lines.append("")

    # ---------------- D4 ----------------
    lines.append(
        "D4 PASSAGES REACHING NO POSITION (passages_selected minus the DISTINCT chunk ids in "
        "positions.jsonl -- never a sum of position sizes, which double-counts a passage sitting "
        "in two positions)"
    )
    for stat in stats:
        u = stat.unplaced
        lines.append(
            f"  {stat.label}: {u.selected} selected, {u.placed_distinct} distinct placed, "
            f"{u.unplaced} unplaced = {_pct(u.share)} of selected "
            f"(member slots {u.slots}, which is not a passage count)"
        )
        lines.append(
            f"     of which: declined by the extraction model {_int(u.unassigned)}, "
            f"shown in a failed read {_int(u.in_failed_reads)}, "
            f"reaching no group at all {_int(u.ungrouped)}"
        )
    lines.append("")

    # ---------------- D5 ----------------
    lines.append("D5 BLIND PAIRED HAND-SAMPLE")
    lines.append(
        "  not computed -- D5 is a human hand-sample: 12 positions from each build, stratified "
        "to the same size bands, shuffled, judged before the labels are revealed"
    )
    lines.append("")

    # ---------------- context ----------------
    lines.append(
        "CONTEXT (reported, never deciding -- fewer positions, larger positions and a lower "
        "single-passage share follow from the extraction call count, not from quality)"
    )
    for stat in stats:
        c = stat.context
        lines.append(
            f"  {stat.label}: {c.positions} position(s) | size p25/median/p75 "
            f"{_num(c.size_p25, 1)} / {_num(c.size_median, 1)} / {_num(c.size_p75, 1)} | "
            f"{c.slots} member slot(s) over {stat.purity.placed} distinct placed passage(s)"
        )
        lines.append(
            f"     single-passage: {c.single_passage_positions} = "
            f"{_pct(c.single_passage_position_share)} of {c.positions} position(s), "
            f"{_pct(c.single_passage_slot_share)} of {c.slots} member slot(s)"
        )
        lines.append(
            f"     cross-book: {_pct(c.cross_book_position_share)} of {c.banded_positions} "
            f"position(s) of size 2+, {_pct(c.cross_book_slot_share)} of {c.slots} member "
            f"slot(s), {_pct(c.cross_book_passage_share)} of {stat.purity.placed} distinct "
            "placed passage(s) -- band by band against its own null in D1's table above"
        )
        lines.append(
            f"     reads {_int(c.reads)} | units asked {_int(c.units_asked)} | units reused "
            f"{_int(c.units_reused)} | cost "
            f"{('$' + format(c.cost_usd, '.4f')) if c.cost_usd is not None else NOT_RECORDED} | "
            f"wall {_num(c.wall_time_sec, 1)}s"
        )
        lines.append(
            f"     embedding merge: {_int(c.embedding_folds)} fold(s), "
            f"{_num(c.embedding_folds_per_position, 3)} per final position"
        )
        if c.consolidation_folds is None:
            lines.append("     consolidation: no consolidation stage in this build")
        else:
            lines.append(
                f"     consolidation: {c.consolidation_folds} fold(s), "
                f"{_num(c.consolidation_folds_per_position, 3)} per final position "
                "(never added to the embedding merge's own -- two stages, two figures)"
            )
    lines.append("")

    lines.append("NOISE (reporting only, per the approach doc's §6 noise policy)")
    lines += [f"  {note}" for note in NOISE_NOTES]
    lines.append("")

    # ---------------- replicate ----------------
    lines.append("REPLICATE")
    if report.replicate is None:
        lines.append(
            "  not supplied -- the D1 and D2 replicate gaps were NOT measured, and no margin "
            "below is quoted against one"
        )
    else:
        reused = report.replicate.context.units_reused
        if report.replicate_gap_usable:
            lines.append(f"  C units_reused: {_int(reused)} -- the gap is usable as an error bar")
        else:
            lines.append(
                f"  C units_reused: {_int(reused)} -- NOT zero, so C reused prior reads and its "
                "gap is NOT usable as an error bar; every margin below reads as unmeasured"
            )
        lines.append(
            f"  D1 gap (plurality band {report.variant.plurality_band or 'n/a'}): "
            f"{_num(report.d1_gap, 4)}"
        )
        lines.append(f"  D2 gap (member-weighted purity): {_num(report.d2_gap, 4)}")
    lines.append("")

    lines.append("VERDICT (the bar is issue #831's own)")
    for verdict in report.verdicts:
        lines.append(f"  {verdict.metric}: {verdict.status} -- {verdict.reason}")
    lines.append(f"  overall: {report.overall}")

    return "\n".join(lines).rstrip("\n")
