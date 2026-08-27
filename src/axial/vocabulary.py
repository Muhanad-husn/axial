"""The derived-vocabulary census (issue #805, slice 01 of
`plans/derived-vocabulary/`): a read-only report over the twelve sentence-
valued answer columns -- `about`, `claim`, `move`, `ranges_over`,
`stops_holding`, `position`, `arguing_against`, `mechanism`, `evidence`,
`comparison`, `concedes`, `assumes`. Every note answers seventeen questions;
three repeat often enough to join on and are out of scope here (`names`,
`uses`, `defines`); these twelve hold near-unique sentences instead, so
nothing joins on them today. This module asks whether they group by meaning
anyway, at a sweep of cosine-distance thresholds, with zero model calls.

This is the go/no-go for the whole feature (`plans/derived-vocabulary/
README.md`). It reads `data/answers/` and writes nothing -- no artifact, no
group ids, no reuse across runs. Persisting a grouping is slice 02, gated on
this report's own numbers.

Reuses rather than rebuilds: `axial.argmap.build._default_encoder` (local
MiniLM, zero model calls) and `axial.query.reader.is_abstention` (the one
place an abstention is decided). The clustering itself is new -- a single
`scipy.cluster.hierarchy.linkage` per column, cut at every swept threshold
with `fcluster`, so the expensive step (encoding) still runs once per
column no matter how many thresholds are swept. `_agglomerative_cluster`
in `axial.argmap.build` cannot be reused directly: it re-fits per
threshold, and the sweep this module runs is the whole point.
"""

from __future__ import annotations

import collections
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from axial.argmap.build import BAG_DISTANCE_THRESHOLD, Encoder, _default_encoder
from axial.interrogate import _default_answers_dir
from axial.names import load_answer_records
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.reader import is_abstention

# The twelve sentence-valued columns this census covers (README's own
# table), named explicitly rather than inferred -- inferring "everything
# that isn't a list" would also catch `about`/`arguing_against`'s own list
# shape wrong, since those two ARE list-valued and still belong here.
VOCABULARY_COLUMNS: tuple[str, ...] = (
    "about",
    "claim",
    "move",
    "ranges_over",
    "stops_holding",
    "position",
    "arguing_against",
    "mechanism",
    "evidence",
    "comparison",
    "concedes",
    "assumes",
)

# Of the twelve, these two are asked for as JSON lists -- every other
# element is a bare sentence.
LIST_VALUED_COLUMNS = frozenset({"about", "arguing_against"})

# Issue #810: the literal string `"[]"` stored where an empty list belongs.
# Excluded from the population on the same terms as an abstention, and
# counted, never silently dropped.
_EXCLUDED_LITERALS = frozenset({"[]", ""})

# The live claim path runs `_agglomerative_cluster` at 0.55
# (`BAG_DISTANCE_THRESHOLD`). This sweeps a symmetric +-0.20 spread around
# it in steps of 0.10 -- five points, centred on the one number already
# proven in production rather than a fresh guess -- so the report shows how
# sensitive each column is instead of asserting a single cut.
DEFAULT_VOCABULARY_THRESHOLDS: tuple[float, ...] = tuple(
    round(BAG_DISTANCE_THRESHOLD + delta, 2) for delta in (-0.20, -0.10, 0.0, 0.10, 0.20)
)

# Pairwise distance is O(n^2); `about` (20,335 values) and `arguing_against`
# (11,990) sit above what has been proven at scale. `bag_passages` runs the
# claim path over the corpus's own note count -- 6,860 notes, README's own
# measured position -- so a column above that is measured on a random
# sample of that same proven size instead of computed whole.
SAMPLE_CEILING = 6_860

# How many of the largest groups, at the threshold nearest
# `BAG_DISTANCE_THRESHOLD`, the report prints as member sentences for the
# founder to read (bar condition 4).
TOP_GROUPS = 10

# The go/no-go bar's own floor (`plans/derived-vocabulary/
# 01-the-sentence-columns-are-counted.md`, "the bar for slice 02 to
# proceed", conditions 1 and 3): a group counts toward the bar only at 5
# or more members.
MIN_BAR_GROUP_SIZE = 5

ClusterSweepFn = Callable[[np.ndarray, Sequence[float]], dict[float, list[int]]]


@dataclass(frozen=True)
class PopulationEntry:
    """One answered value: the sentence itself, and the note it came from.
    A list-valued column (`about`, `arguing_against`) contributes one entry
    per list element, so several entries can share a `chunk_id`."""

    value: str
    chunk_id: str
    source_id: str


@dataclass(frozen=True)
class ThresholdStats:
    """One swept threshold's own slice of a column's report. `sampled`/
    `sample_size` are carried on every threshold row, not just the column's
    own summary line, so a sampled row is marked wherever it appears and no
    reader can mistake it for a whole-column measurement.

    `bar_group_count`/`bar_cross_source_group_count` are the go/no-go bar's
    own figures (conditions 1 and 3): groups with `MIN_BAR_GROUP_SIZE`+
    members, and how many of THOSE span 2+ sources. `cross_source_group_
    count` above counts every cross-source group regardless of size -- the
    broader reading the acceptance criterion names -- and stays as it is;
    the two bar figures are additional, not a replacement."""

    threshold: float
    group_count: int
    grouped_share: float  # share of the measured population in a group of 2+
    largest_group_size: int
    cross_source_group_count: int
    bar_group_count: int
    bar_cross_source_group_count: int
    sampled: bool
    sample_size: int | None


@dataclass(frozen=True)
class TopGroup:
    """One of the ten largest groups at the report's sampling threshold, as
    its member sentences -- what bar condition 4 is read against."""

    size: int
    source_count: int
    members: list[str]


@dataclass(frozen=True)
class ColumnStats:
    """One column's full report: its whole-column answered/distinct/
    excluded counts, plus the threshold sweep and the printed top groups --
    both computed over a random sample when `sampled` is true."""

    column: str
    answered_count: int
    distinct_count: int
    excluded_count: int
    sampled: bool
    sample_size: int | None
    thresholds: list[ThresholdStats]
    sample_threshold: float | None
    top_groups: list[TopGroup]


@dataclass(frozen=True)
class VocabularyExamineStats:
    columns: list[ColumnStats]


def _extract_scalar(value: Any) -> str | None:
    """The usable sentence in `value`, or `None` when it is an abstention
    (`is_abstention`), the literal `"[]"`/empty string (issue #810), or not
    a string at all. Shared by scalar columns and by each element of a
    list-valued column's own list."""
    if is_abstention(value):
        return None
    if not isinstance(value, str):
        return None
    if value in _EXCLUDED_LITERALS or not value.strip():
        return None
    return value


def read_column(
    records: Sequence[Mapping[str, Any]], column: str
) -> tuple[list[PopulationEntry], int]:
    """Every value `column` answered across `records`: one `PopulationEntry`
    per note for a scalar column, one per list element for `about`/
    `arguing_against`. Returns `(population, excluded_count)` -- an
    abstention, the literal `"[]"`/empty string, or (for a list column) a
    non-list value all count as excluded and are reported, never dropped
    silently. A record that never answered `column` (the key is absent)
    contributes to neither count: that is `is_abstention`'s own third
    state, a missing key rather than a refusal."""
    population: list[PopulationEntry] = []
    excluded = 0
    is_list_column = column in LIST_VALUED_COLUMNS

    for record in records:
        answers = record.get("answers")
        if not isinstance(answers, dict) or column not in answers:
            continue
        value = answers[column]
        chunk_id = record.get("chunk_id", "")
        source_id = record.get("source_id", "")

        if is_list_column:
            if not isinstance(value, list):
                excluded += 1
                continue
            for element in value:
                text = _extract_scalar(element)
                if text is None:
                    excluded += 1
                else:
                    population.append(PopulationEntry(text, chunk_id, source_id))
        else:
            text = _extract_scalar(value)
            if text is None:
                excluded += 1
            else:
                population.append(PopulationEntry(text, chunk_id, source_id))

    return population, excluded


def _default_cluster_sweep(vectors: np.ndarray, thresholds: Sequence[float]) -> dict[float, list[int]]:
    """One average-linkage tree over `vectors` (`scipy.cluster.hierarchy.
    linkage`, cosine distance), cut at every threshold in `thresholds`
    (`fcluster`) -- the sweep's own load-bearing property: encoding runs
    once per column, and this runs the fit once too, no matter how many
    thresholds are swept. Same criterion as `axial.argmap.build.
    _agglomerative_cluster` (cosine, average linkage). `scipy` is imported
    lazily, exactly as that function imports `sklearn`, so a test that
    injects its own `cluster_fn` never needs it installed."""
    from scipy.cluster.hierarchy import fcluster, linkage

    tree = linkage(vectors, method="average", metric="cosine")
    return {
        threshold: [int(label) for label in fcluster(tree, t=threshold, criterion="distance")]
        for threshold in thresholds
    }


def _threshold_stats(
    threshold: float,
    population: Sequence[PopulationEntry],
    labels: Sequence[int],
    sampled: bool,
    sample_size: int | None,
) -> ThresholdStats:
    groups: dict[int, list[PopulationEntry]] = collections.defaultdict(list)
    for entry, label in zip(population, labels):
        groups[label].append(entry)

    sizes = sorted((len(members) for members in groups.values()), reverse=True)
    grouped = sum(size for size in sizes if size >= 2)
    cross_source = sum(
        1 for members in groups.values() if len({member.source_id for member in members}) >= 2
    )
    bar_groups = [members for members in groups.values() if len(members) >= MIN_BAR_GROUP_SIZE]
    bar_cross_source = sum(
        1 for members in bar_groups if len({member.source_id for member in members}) >= 2
    )
    return ThresholdStats(
        threshold=threshold,
        group_count=len(groups),
        grouped_share=grouped / len(population) if population else 0.0,
        largest_group_size=sizes[0] if sizes else 0,
        cross_source_group_count=cross_source,
        bar_group_count=len(bar_groups),
        bar_cross_source_group_count=bar_cross_source,
        sampled=sampled,
        sample_size=sample_size,
    )


def _top_groups(
    population: Sequence[PopulationEntry], labels: Sequence[int], top_n: int
) -> list[TopGroup]:
    groups: dict[int, list[PopulationEntry]] = collections.defaultdict(list)
    for entry, label in zip(population, labels):
        groups[label].append(entry)

    ranked = sorted(groups.values(), key=len, reverse=True)[:top_n]
    return [
        TopGroup(
            size=len(members),
            source_count=len({member.source_id for member in members}),
            members=[member.value for member in members],
        )
        for members in ranked
    ]


def _closest_threshold(thresholds: Sequence[float], target: float) -> float:
    """The swept threshold nearest `target` -- always a member of
    `thresholds`, so the report samples a threshold it actually swept."""
    return min(thresholds, key=lambda candidate: (abs(candidate - target), candidate))


def examine_vocabulary(
    answers_dir: Path | None = None,
    columns: Sequence[str] = VOCABULARY_COLUMNS,
    thresholds: Sequence[float] = DEFAULT_VOCABULARY_THRESHOLDS,
    sample_ceiling: int = SAMPLE_CEILING,
    top_n: int = TOP_GROUPS,
    seed: int = 0,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    encode: Encoder | None = None,
    cluster_fn: ClusterSweepFn | None = None,
) -> VocabularyExamineStats:
    """The census: for each of `columns`, its whole-column answered/
    distinct/excluded counts, then a group-count/coverage/cross-source
    report at every threshold in `thresholds`, then the `top_n` largest
    groups at the threshold nearest `BAG_DISTANCE_THRESHOLD` as their
    member sentences.

    Zero model calls, zero pipeline writes -- read-only over
    `answers_dir` (default resolved via `axial.interrogate.
    _default_answers_dir`).

    A column whose population exceeds `sample_ceiling` is measured (encoded
    and clustered) on a random sample of that size, seeded by `seed` for a
    reproducible report; `answered_count`/`distinct_count` still reflect the
    whole column. `encode`/`cluster_fn`, when given, replace the local
    MiniLM encoder and the default linkage sweep -- the injection seam
    `axial.argmap.build.bag_passages` already uses, so a unit test never
    pays MiniLM's load cost and never needs `scipy`/`sklearn` installed."""
    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    records = load_answer_records(Path(answers_dir))

    swept = sorted(set(thresholds)) or [BAG_DISTANCE_THRESHOLD]
    sample_target = _closest_threshold(swept, BAG_DISTANCE_THRESHOLD)

    active_encode = encode
    columns_out: list[ColumnStats] = []

    for column in columns:
        population, excluded = read_column(records, column)
        answered_count = len(population)
        distinct_count = len({entry.value for entry in population})

        sampled = False
        sample_size: int | None = None
        measured = population
        if len(population) > sample_ceiling:
            sampled = True
            sample_size = sample_ceiling
            measured = random.Random(seed).sample(population, sample_ceiling)

        if not measured:
            columns_out.append(
                ColumnStats(
                    column=column,
                    answered_count=answered_count,
                    distinct_count=distinct_count,
                    excluded_count=excluded,
                    sampled=sampled,
                    sample_size=sample_size,
                    thresholds=[
                        ThresholdStats(
                            threshold=t,
                            group_count=0,
                            grouped_share=0.0,
                            largest_group_size=0,
                            cross_source_group_count=0,
                            bar_group_count=0,
                            bar_cross_source_group_count=0,
                            sampled=sampled,
                            sample_size=sample_size,
                        )
                        for t in swept
                    ],
                    sample_threshold=None,
                    top_groups=[],
                )
            )
            continue

        if active_encode is None:
            active_encode = _default_encoder()
        vectors = active_encode([entry.value for entry in measured])

        if len(measured) < 2:
            labels_by_threshold = {t: [0] * len(measured) for t in swept}
        else:
            sweep = cluster_fn if cluster_fn is not None else _default_cluster_sweep
            labels_by_threshold = sweep(vectors, swept)

        threshold_stats = [
            _threshold_stats(t, measured, labels_by_threshold[t], sampled, sample_size)
            for t in swept
        ]
        top_groups = _top_groups(measured, labels_by_threshold[sample_target], top_n)

        columns_out.append(
            ColumnStats(
                column=column,
                answered_count=answered_count,
                distinct_count=distinct_count,
                excluded_count=excluded,
                sampled=sampled,
                sample_size=sample_size,
                thresholds=threshold_stats,
                sample_threshold=sample_target,
                top_groups=top_groups,
            )
        )

    return VocabularyExamineStats(columns=columns_out)


def format_vocabulary_report(stats: VocabularyExamineStats) -> str:
    """Render `VocabularyExamineStats` as a human-readable report. Format is
    left to the implementer, only that every listed number is present
    (mirrors `axial.names.format_names_report`'s own docstring)."""
    lines: list[str] = []

    for column in stats.columns:
        sample_note = f" (SAMPLED n={column.sample_size} for clustering)" if column.sampled else ""
        lines.append(
            f"{column.column}: {column.answered_count} answered value(s){sample_note}, "
            f"{column.distinct_count} distinct string(s), "
            f"{column.excluded_count} excluded (abstention/[]/empty)"
        )

        for threshold_stats in column.thresholds:
            row_sample_note = (
                f" (sampled n={threshold_stats.sample_size})" if threshold_stats.sampled else ""
            )
            lines.append(
                f"  threshold={threshold_stats.threshold}: "
                f"{threshold_stats.group_count} group(s), "
                f"{threshold_stats.grouped_share:.1%} in a group of 2+, "
                f"largest group {threshold_stats.largest_group_size}, "
                f"{threshold_stats.cross_source_group_count} cross-source group(s), "
                f"{threshold_stats.bar_group_count} group(s) with "
                f"{MIN_BAR_GROUP_SIZE}+ member(s), "
                f"{threshold_stats.bar_cross_source_group_count} of those cross-source"
                f"{row_sample_note}"
            )

        if column.sample_threshold is not None:
            lines.append(
                f"  sampling threshold for the {len(column.top_groups)} largest "
                f"group(s): {column.sample_threshold}{sample_note}"
            )
            for index, group in enumerate(column.top_groups, start=1):
                lines.append(
                    f"    group {index} (size={group.size}, {group.source_count} source(s)):"
                )
                for member in group.members:
                    lines.append(f"      - {member}")

        lines.append("")

    return "\n".join(lines).rstrip("\n")
