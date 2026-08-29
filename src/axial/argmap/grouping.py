"""`axial map grouping-report` (issue #828): the inner split, computed both
ways, so the founder chooses one on numbers instead of taste (`docs/
approach-positions-not-names.md` §6 "The change").

Today the map bags passages by wording similarity. §6's diagnosis (measured
and confirmed by `axial map purity`, issue #827) is that grouping by a
committed category instead -- `claim`'s own scheme -- surfaces the same
argument even when its wording differs, but a corpus-wide `claim` category
is far too large for one extraction call (a bag averages nine passages
today; a `claim` category averages hundreds). §6 proposes two candidate
INNER splits to bring a category back down to a readable size, and asks that
both be measured before either is built:

- **`group_by_intersection`** -- a second constitutive axis, `mechanism`.
  `claim` x `mechanism` cells are small by construction, at the cost of two
  refusal rates compounding: a passage refused or unassigned on EITHER axis
  is reported ungrouped, never silently dropped, because that compounding is
  exactly the cost §6 wants measured.
- **`group_by_subcluster`** -- wording similarity, demoted from the whole
  corpus to sizing duty INSIDE one already-shared category, through the same
  injectable `encode`/`cluster_fn` seam `axial.argmap.build.bag_passages`
  already gives a unit test (no local encoder needed to test this module).

Both are zero-model-call, zero-network, pure functions over already-loaded
`chunk_id -> category_id` (and, for the sub-cluster candidate, `chunk_id ->
value` text) maps -- the join and the report-level I/O around them
(`compute_grouping_report`) are a separate, thin layer, the same split
`axial.argmap.purity` keeps between `compute_purity` and its own pure
cross-tab.

These functions are not report-internal: slice 04 wires whichever candidate
the founder chooses straight into `axial map build`, so both are public,
reusable API from the day this ships, not a throwaway measurement script."""

from __future__ import annotations

import collections
import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from axial.argmap.build import (
    BAG_DISTANCE_THRESHOLD,
    EXTRACT_SLICE,
    ClusterFn,
    Encoder,
    _agglomerative_cluster,
    _default_encoder,
)
from axial.argmap.purity import _load_bag_assignments, resolve_map_pin_dir
from axial.argmap.vocabulary_join import NoVocabularyError
from axial.paths import default_map_dir
from axial.vocabulary import ASSIGNMENTS_FILENAME, MANIFEST_FILENAME, ROOT_LEVEL, VOCABULARY_DIR

# HDBSCAN's own noise-label convention (`axial.names.NOISE_LABEL`), not
# imported from there -- that module pulls in HDBSCAN at call time for a
# reason this module has no use for, and the value itself is the whole of
# what's shared. Any injected `cluster_fn` that follows the same convention
# (a residue re-fit, the kind of clustering slice 04 might inject here) has
# its noise reported as ungrouped encoder residue, never as a group of its
# own -- the approach doc's own phrase for what the sub-cluster candidate's
# ungrouped count measures, distinct from "no claim category at all".
NOISE_LABEL = -1

# Candidate names, printed and used as the `GroupingResult.candidate`/
# `GroupingStats.candidate` value on both sides of the report -- plain
# strings rather than an enum, since nothing here dispatches on them beyond
# display and slice 04's own choice of which one to call.
CANDIDATE_INTERSECTION = "claim x mechanism"
CANDIDATE_SUBCLUSTER = "claim + subcluster"


@dataclass(frozen=True)
class Group:
    """One group a candidate formed: a deterministic label and the passages
    it holds, always non-empty (an empty group is never emitted -- there is
    nothing to report about a cell or a sub-cluster nobody landed in)."""

    label: str
    chunk_ids: tuple[str, ...]

    @property
    def size(self) -> int:
        return len(self.chunk_ids)


@dataclass(frozen=True)
class GroupingResult:
    """One candidate's own grouping over a passage universe: every non-empty
    group, in a deterministic order, and every passage the candidate could
    not place -- reported by id, never dropped (the acceptance criterion's
    own "never silently dropped" clause). What "could not place" means
    differs by candidate: refused or unassigned on either axis for
    `group_by_intersection`, no claim category or cluster_fn-reported noise
    for `group_by_subcluster`."""

    candidate: str
    groups: tuple[Group, ...]
    ungrouped_chunk_ids: tuple[str, ...]


@dataclass(frozen=True)
class GroupingStats:
    """The numbers the acceptance criterion asks for, per candidate: group
    count, group-size min/median/max (`None` when there are no groups),
    passages left ungrouped, and the extraction slices this grouping would
    project at `extract_slice`."""

    candidate: str
    group_count: int
    min_size: int | None
    median_size: float | None
    max_size: int | None
    ungrouped_count: int
    projected_slices: int


def group_by_intersection(
    chunk_ids: Iterable[str],
    claim_category_by_chunk: Mapping[str, str],
    mechanism_category_by_chunk: Mapping[str, str],
) -> GroupingResult:
    """§6's first candidate: passages sharing a (claim category, mechanism
    category) cell land in one group. A passage present in `chunk_ids` but
    missing from EITHER map -- refused, out-of-scheme, or never answered for
    that column -- is reported in `ungrouped_chunk_ids`, never silently
    dropped: the two refusal rates compound, and that compounding is exactly
    the cost §6 asks this candidate be measured against.

    Labels are `f"{claim_category}::{mechanism_category}"`, and both the
    groups and each group's own `chunk_ids` are sorted -- deterministic
    across runs regardless of `chunk_ids`' own input order, which iterating
    a `bag_state.json` dict (unordered by chunk id) would not otherwise
    guarantee."""
    members: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    ungrouped: list[str] = []
    for chunk_id in chunk_ids:
        claim_category = claim_category_by_chunk.get(chunk_id)
        mechanism_category = mechanism_category_by_chunk.get(chunk_id)
        if claim_category is None or mechanism_category is None:
            ungrouped.append(chunk_id)
            continue
        members[(claim_category, mechanism_category)].append(chunk_id)

    groups = tuple(
        Group(
            label=f"{claim_category}::{mechanism_category}",
            chunk_ids=tuple(sorted(members[(claim_category, mechanism_category)])),
        )
        for claim_category, mechanism_category in sorted(members)
    )
    return GroupingResult(
        candidate=CANDIDATE_INTERSECTION,
        groups=groups,
        ungrouped_chunk_ids=tuple(sorted(ungrouped)),
    )


def group_by_subcluster(
    chunk_ids: Iterable[str],
    claim_category_by_chunk: Mapping[str, str],
    claim_value_by_chunk: Mapping[str, str],
    encode: Encoder,
    cluster_fn: ClusterFn | None = None,
) -> GroupingResult:
    """§6's second candidate: `claim` category is the outer level; inside
    each category, `encode`/`cluster_fn` (the same injection seam
    `axial.argmap.build.bag_passages` already gives a unit test) split it
    further. Every passage that HAS a claim category lands in exactly one
    group -- unless `cluster_fn` reports it as noise (`NOISE_LABEL`, this
    module's own convention for a residue-reporting `cluster_fn`), which
    joins `ungrouped_chunk_ids` alongside passages with no claim category at
    all. A category with a single member skips clustering entirely (mirrors
    `axial.argmap.build._agglomerative_cluster`'s own single-vector case):
    it is trivially its own group, and calling `encode` on one text would
    only spend the encoder for a decision that was never in doubt.

    Categories are visited in sorted order, and each category's own members
    are sorted before encoding, so `cluster_fn` always sees the same input
    order for the same input data -- deterministic labels regardless of
    `chunk_ids`' own input order."""
    by_category: dict[str, list[str]] = collections.defaultdict(list)
    ungrouped: list[str] = []
    for chunk_id in chunk_ids:
        claim_category = claim_category_by_chunk.get(chunk_id)
        if claim_category is None:
            ungrouped.append(chunk_id)
            continue
        by_category[claim_category].append(chunk_id)

    groups: list[Group] = []
    for claim_category in sorted(by_category):
        members = sorted(by_category[claim_category])
        if len(members) <= 1:
            labels = [0] * len(members)
        else:
            texts = [claim_value_by_chunk.get(chunk_id, "") for chunk_id in members]
            vectors = encode(texts)
            labels = (
                cluster_fn(vectors)
                if cluster_fn is not None
                else _agglomerative_cluster(vectors, BAG_DISTANCE_THRESHOLD)
            )

        sub_members: dict[int, list[str]] = collections.defaultdict(list)
        for chunk_id, label in zip(members, labels):
            if label == NOISE_LABEL:
                ungrouped.append(chunk_id)
                continue
            sub_members[label].append(chunk_id)

        for label in sorted(sub_members):
            groups.append(
                Group(label=f"{claim_category}::{label}", chunk_ids=tuple(sub_members[label]))
            )

    return GroupingResult(
        candidate=CANDIDATE_SUBCLUSTER,
        groups=tuple(groups),
        ungrouped_chunk_ids=tuple(sorted(ungrouped)),
    )


def slice_projection(group_sizes: Iterable[int], *, extract_slice: int = EXTRACT_SLICE) -> int:
    """How many `axial.argmap.build.ExtractJob`s a set of groups would
    project at `extract_slice`: `ceil(n / extract_slice)` per group, summed
    -- the same arithmetic `build_jobs` applies per bag today, read here
    against a group instead."""
    return sum(math.ceil(size / extract_slice) for size in group_sizes)


def summarize(result: GroupingResult, *, extract_slice: int = EXTRACT_SLICE) -> GroupingStats:
    """`GroupingResult` reduced to the numbers the acceptance criterion asks
    for. `min`/`median`/`max` are `None` when `result` holds no groups at
    all (every passage ungrouped), rather than a division error or a false
    zero."""
    sizes = sorted(group.size for group in result.groups)
    return GroupingStats(
        candidate=result.candidate,
        group_count=len(result.groups),
        min_size=sizes[0] if sizes else None,
        median_size=statistics.median(sizes) if sizes else None,
        max_size=sizes[-1] if sizes else None,
        ungrouped_count=len(result.ungrouped_chunk_ids),
        projected_slices=slice_projection(sizes, extract_slice=extract_slice),
    )


# ---------------------------------------------------------------------------
# The report-level join: read the pinned map's own selected passages and
# both vocabulary columns off disk, run both candidates, print them side by
# side. Mirrors the split `axial.argmap.purity` already keeps between its
# own pure cross-tab and `compute_purity`'s file I/O.
# ---------------------------------------------------------------------------


def _load_json_or_none(path: Path) -> dict[str, Any] | None:
    """Local, tolerant JSON read -- the same shape every sibling module's
    own manifest reader keeps privately (`axial.vocabulary`, `axial.argmap.
    build`, `axial.argmap.purity`, `axial.argmap.vocabulary_join`) rather
    than importing another module's private helper, the precedent all four
    already set."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_assignment_records(path: Path) -> list[dict[str, Any]]:
    """Every persisted assignment record under `path`, or `[]` when the file
    does not exist. A torn final line is dropped, not raised -- the same
    tolerance every other reader of this file already gives it."""
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _load_column(
    vocabulary_dir: Path, column: str, level: int | None
) -> tuple[dict[str, str], dict[str, str], int]:
    """`column`'s own `chunk_id -> category_id` (assigned only) and
    `chunk_id -> value` (the answered sentence, present whether or not it
    was assigned) at `level` (or the column's own persisted `max_level`).
    Raises `NoVocabularyError` when `column` has never been built -- the
    same failure `axial.argmap.vocabulary_join.vocabulary_neighbours` and
    `axial.argmap.purity.compute_purity` both name rather than a stack
    trace when a column has no manifest at all."""
    column_dir = Path(vocabulary_dir) / column
    manifest = _load_json_or_none(column_dir / MANIFEST_FILENAME)
    if manifest is None:
        raise NoVocabularyError(column, column_dir)
    resolved_level = level if level is not None else int(manifest.get("max_level", ROOT_LEVEL))

    category_by_chunk: dict[str, str] = {}
    value_by_chunk: dict[str, str] = {}
    for record in _read_assignment_records(column_dir / ASSIGNMENTS_FILENAME):
        if int(record.get("level", ROOT_LEVEL)) != resolved_level:
            continue
        chunk_id = str(record.get("chunk_id", ""))
        value = record.get("value")
        if isinstance(value, str):
            value_by_chunk[chunk_id] = value
        category_id = record.get("category_id")
        if isinstance(category_id, str):
            category_by_chunk[chunk_id] = category_id
    return category_by_chunk, value_by_chunk, resolved_level


@dataclass(frozen=True)
class GroupingReport:
    """`compute_grouping_report`'s own return: both candidates, resolved and
    summarized, plus enough about where they came from (pin, both columns'
    resolved levels, the passage universe size) to render standalone."""

    pin: str
    map_dir: Path
    vocabulary_dir: Path
    claim_level: int
    mechanism_level: int
    universe_count: int
    extract_slice: int
    intersection: GroupingResult
    intersection_stats: GroupingStats
    subcluster: GroupingResult
    subcluster_stats: GroupingStats


def compute_grouping_report(
    *,
    map_dir: Path | None = None,
    pin: str | None = None,
    vocabulary_dir: Path | None = None,
    level: int | None = None,
    encode: Encoder | None = None,
    cluster_fn: ClusterFn | None = None,
    extract_slice: int = EXTRACT_SLICE,
) -> GroupingReport:
    """The full report (issue #828): resolves the map pin the cheap way
    (`axial.argmap.purity.resolve_map_pin_dir` -- newest-by-`map.json`-mtime,
    never `axial.argmap.ask.resolve_pinned_map_dir`'s raw-source hashing),
    reads its `bag_state.json` for the passage universe (the current build's
    own selected passages, exactly as `axial.argmap.purity._load_bag_
    assignments` reads it), reads `claim` and `mechanism`'s built
    vocabularies, and runs both candidates over the same universe. Raises
    `NoMapDirError`/`NoBagStateError` (`axial.argmap.purity`) for anything
    wrong on the map side, `NoVocabularyError` (`axial.argmap.
    vocabulary_join`) when either column has never been built.

    `encode` defaults to the local sentence-transformer encoder
    (`axial.argmap.build._default_encoder`) only when actually constructed
    here -- unconditionally, the same way `axial.argmap.build.run_map_build`
    itself builds one before bagging, rather than a lazy-only-if-a-category-
    needs-it branch this report has no call to invent. A caller (a unit
    test, slice 04) that already has one injects it and this never runs."""
    root = Path(map_dir) if map_dir is not None else default_map_dir()
    outdir, resolved_pin = resolve_map_pin_dir(root, pin)
    bag_assignments = _load_bag_assignments(outdir)
    chunk_ids = sorted(bag_assignments)

    vocab_root = Path(vocabulary_dir) if vocabulary_dir is not None else VOCABULARY_DIR
    claim_category_by_chunk, claim_value_by_chunk, claim_level = _load_column(
        vocab_root, "claim", level
    )
    mechanism_category_by_chunk, _mechanism_value_by_chunk, mechanism_level = _load_column(
        vocab_root, "mechanism", level
    )

    intersection = group_by_intersection(
        chunk_ids, claim_category_by_chunk, mechanism_category_by_chunk
    )
    resolved_encode = encode if encode is not None else _default_encoder()
    subcluster = group_by_subcluster(
        chunk_ids, claim_category_by_chunk, claim_value_by_chunk, resolved_encode, cluster_fn
    )

    return GroupingReport(
        pin=resolved_pin,
        map_dir=outdir,
        vocabulary_dir=vocab_root,
        claim_level=claim_level,
        mechanism_level=mechanism_level,
        universe_count=len(chunk_ids),
        extract_slice=extract_slice,
        intersection=intersection,
        intersection_stats=summarize(intersection, extract_slice=extract_slice),
        subcluster=subcluster,
        subcluster_stats=summarize(subcluster, extract_slice=extract_slice),
    )


def _cell(value: str, width: int) -> str:
    return value.ljust(width)


def _size_text(stats: GroupingStats) -> str:
    min_text = stats.min_size if stats.min_size is not None else "n/a"
    max_text = stats.max_size if stats.max_size is not None else "n/a"
    median_text = f"{stats.median_size:.2f}" if stats.median_size is not None else "n/a"
    return f"{min_text} / {median_text} / {max_text}"


def format_grouping_report(report: GroupingReport) -> str:
    """Render `GroupingReport` with both candidates side by side (the
    acceptance criterion's own "print side by side in one table" clause).
    Format is left to the implementer, only that every number the
    acceptance criterion asks for is present, the same latitude `axial.
    argmap.purity.format_purity_report`'s own docstring keeps."""
    stats = (report.intersection_stats, report.subcluster_stats)
    name_width = max(len(s.candidate) for s in stats)
    label_width = len("projected extraction slices (000)")

    def row(label: str, values: tuple[str, str]) -> str:
        cells = "  ".join(_cell(value, name_width) for value in values)
        return f"{label.ljust(label_width)}  {cells}"

    lines = [
        f"pin: {report.pin} ({report.map_dir})",
        f"vocabulary: {report.vocabulary_dir}",
        f"claim level: {report.claim_level}  mechanism level: {report.mechanism_level}",
        f"passages (selected, this pin): {report.universe_count}",
        "",
        row("", tuple(s.candidate for s in stats)),
        row("groups", tuple(str(s.group_count) for s in stats)),
        row("group size min/median/max", tuple(_size_text(s) for s in stats)),
        row("ungrouped", tuple(str(s.ungrouped_count) for s in stats)),
        row(
            f"projected extraction slices ({report.extract_slice})",
            tuple(str(s.projected_slices) for s in stats),
        ),
    ]
    return "\n".join(lines).rstrip("\n")
