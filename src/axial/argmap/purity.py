"""`axial map purity` (issue #827): the cross-tab that confirms or kills the
positions-not-names diagnosis (`docs/approach-positions-not-names.md` §2).

Zero model calls, zero network: a pure join over two artifacts already on
disk for a built map's pin -- `bag_state.json` (issue #677, `axial.argmap.
build`), the local-embedding clustering that puts every interrogated claim
into one of ~660 wording bags, and `<vocabulary_dir>/<column>/assignments.
jsonl` (issue #806, `axial.vocabulary`), the model's own filing of the same
claims into a committed category scheme. If a bag is pure on a constitutive
axis -- every categorised member files under the same category -- wording
similarity already respects that axis and grouping by it buys nothing new.
If a category is scattered across many bags, passages making the same
argument are systematically kept apart by the current grouping.

Run first on `claim` (issue #826): the approach doc's own kill condition --
high median purity, low scatter there -- would mean the diagnosis is wrong
and the feature stops. The mechanism-axis baseline it is judged against is
measured and recorded in `docs/approach-positions-not-names.md` §2 and
this slice's own run log (`data/logs/2026-08-28-claim-bag-purity/`), not
repeated here where a docstring number goes stale with nothing to catch it.

Resolves the pin by the cheap route on purpose: `axial.argmap.build.
_prior_pin_dir`'s own newest-by-`map.json`-mtime helper, reused as-is,
rather than `axial.argmap.ask.resolve_pinned_map_dir`, which computes the
corpus pin by hashing every raw source when no pin is given -- seconds over
a real corpus, and impossible in a worktree where `data/` (gitignored) does
not exist at all. `--pin`/`--map-dir` bypass that resolution entirely."""

from __future__ import annotations

import collections
import itertools
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from axial.argmap.build import BAG_STATE_FILENAME, _bag_state_path, _prior_pin_dir
from axial.argmap.vocabulary_join import NoVocabularyError
from axial.paths import default_map_dir
from axial.vocabulary import ASSIGNMENTS_FILENAME, MANIFEST_FILENAME, ROOT_LEVEL, VOCABULARY_DIR

# The two pairs #826's verification could not choose between (issue #827
# comment, founder ruling 2026-08-28): the DEFAULT for `compute_purity`'s
# `named_pairs` parameter and the CLI's `--named-pair`, so a bare run keeps
# checking them without a flag -- not a hardwired gate. These ids are
# `claim`-scheme data (`config/vocabulary.yaml`), not a rule this module
# enforces; `--named-pair` repeated on the CLI replaces this default
# wholesale for a run against a different column or scheme (issue #827 fix
# round, reviewer F6).
NAMED_PAIRS: tuple[tuple[str, str], ...] = (
    (
        "causal-argument-state-formation-or-power",
        "causal-argument-violence-war-or-conflict",
    ),
    (
        "characterization-of-regime-movement-or-system",
        "empirical-finding-without-causal-claim",
    ),
)

# `category_for_note`'s own three reasons a categorised join can fail
# (`axial.argmap.vocabulary_join`), mirrored here rather than imported --
# that module's version is keyed to a landed *position*, this one to a bare
# chunk id, so the logic differs even though the vocabulary is the same.
REASON_ASSIGNED = "assigned"
REASON_REFUSED = "refused"
REASON_OUT_OF_SCHEME = "out-of-scheme"


class PurityError(Exception):
    """Base class for every error `axial.argmap.purity` raises."""


class NoMapDirError(PurityError):
    """Raised when `map_dir` does not exist, or (with no `--pin`) it holds
    no completed build -- no child directory carrying its own `map.json` --
    to pick as the newest one. Named, with the path, rather than a
    traceback: the fix is `axial map build` first, or a `--map-dir` pointed
    at a real map root."""

    def __init__(self, map_dir: Path, pin: str | None) -> None:
        self.map_dir = map_dir
        self.pin = pin
        if pin is not None:
            message = f"no map directory at {map_dir / pin} -- run `axial map build` first"
        else:
            message = (
                f"no completed map build under {map_dir} -- no child directory carries its "
                "own map.json. Run `axial map build` first, or point --map-dir at a real map root"
            )
        super().__init__(message)


class InvalidNamedPairError(PurityError):
    """Raised by `parse_named_pair` when a `--named-pair` value is not
    exactly two non-empty, comma-separated category ids. Named, with the
    raw text, rather than an unpacking traceback."""

    def __init__(self, raw: str) -> None:
        self.raw = raw
        super().__init__(
            f"--named-pair {raw!r} is not two comma-separated category ids "
            "(expected the shape 'id-a,id-b')"
        )


class NoBagStateError(PurityError):
    """Raised when the resolved pin directory has no `bag_state.json`
    (issue #677): a build that finished before bag state was persisted, or a
    pin directory that happens to be newest by `map.json` mtime but was
    never bagged. On the corpus this shipped against, the newest build IS
    the bagged one and the bare, no-`--pin` command resolves it and prints a
    full report -- this class exists for the directory layout where that is
    not true, not because it was observed to be. No newest-BAGGED fallback
    is added to cover it: for an instrument, naming the missing bag state is
    safer than silently measuring an older build. Reported by name, never a
    traceback -- the fix is `--pin` naming a build that does carry one."""

    def __init__(self, pin: str, outdir: Path) -> None:
        self.pin = pin
        self.outdir = outdir
        super().__init__(
            f"pin {pin!r} at {outdir} has no {BAG_STATE_FILENAME} -- purity needs a build "
            "that persisted bag state; pass --pin naming one that does"
        )


@dataclass(frozen=True)
class CoverageReport:
    """Every chunk on either side of the join, and where it fell -- never
    silently dropped (the acceptance criterion's own third clause).
    `overlap_*` splits the chunks present on BOTH sides by what the
    vocabulary column made of them: assigned a category, genuinely refused,
    or answered with a string naming no committed category.

    `overlap_multi_category_count` is the chunks among `overlap_assigned_
    count` that carry MORE than one category at the resolved level -- only
    possible for a list-valued column (`about`/`arguing_against`; neither
    `claim` nor `mechanism` is list-valued, so this reads 0 on both today).
    Inert now on purpose: purity's own denominator counts CHUNKS, and a
    chunk contributing to two categories would inflate a bag's modal share
    and enter the pair table under both categories at once without this
    count on record to catch the day that stops being true."""

    bag_chunk_count: int
    vocabulary_chunk_count: int
    overlap_count: int
    bag_only_count: int
    vocabulary_only_count: int
    overlap_assigned_count: int
    overlap_refused_count: int
    overlap_out_of_scheme_count: int
    overlap_multi_category_count: int


@dataclass(frozen=True)
class PurityStats:
    """Purity over bags holding 2+ categorised members: a bag's own share in
    its modal (most common) category, among the categorised members it
    holds. A bag with fewer than 2 categorised members is excluded from
    every average here (a single member is trivially 100% pure and would
    only inflate the picture) but is counted in `excluded_bag_count`, never
    dropped."""

    eligible_bag_count: int
    excluded_bag_count: int
    median_purity: float | None
    mean_purity: float | None
    pure_bag_count: int
    pure_bag_share: float | None
    median_distinct_categories: float | None
    mean_distinct_categories: float | None


@dataclass(frozen=True)
class CategoryScatter:
    """One committed category's own standing in the join: how many bagged,
    categorised chunks it holds (`member_count`), and how many DISTINCT bags
    those chunks are spread across (`bag_count`) -- the scatter number the
    approach doc's kill condition (`docs/approach-positions-not-names.md`
    §2) is stated in."""

    category_id: str
    category_name: str
    member_count: int
    bag_count: int


@dataclass(frozen=True)
class ScatterStats:
    """The reverse table: every committed category, including one with zero
    bagged members (reported, not dropped), and the min/median/max of
    `bag_count` over the categories that DO have at least one bagged member
    -- an empty category would only read as "scattered across zero bags"
    and drag the average toward a number that is not about scatter at
    all.

    `population_bag_count` is the number of bags a `bag_count` entry can
    possibly land in: every bag holding at least one categorised member,
    counted BEFORE `PurityStats`'s own `eligible_bag_count` filter (2+
    categorised members) is applied. The two counts differ -- a bag with
    exactly one categorised member is scattered but not purity-eligible --
    and reporting only `eligible_bag_count` next to a `bag_count` invites
    dividing by the wrong base."""

    categories: tuple[CategoryScatter, ...]
    population_bag_count: int
    min_bag_count: int | None
    median_bag_count: float | None
    max_bag_count: int | None


@dataclass(frozen=True)
class CategoryPair:
    """One pair of categories and how many bags hold a categorised member of
    each. `share` is of `PairCooccurrence.multi_category_bag_count`, `None`
    when that is zero. `applicable` is `False` only for a named pair (see
    `NAMED_PAIRS`) whose id or ids are not part of THIS column's committed
    scheme -- reported anyway, marked, rather than silently dropping a
    claim-axis pair from a mechanism-axis run."""

    category_a: str
    category_b: str
    name_a: str
    name_b: str
    bag_count: int
    share: float | None
    applicable: bool = True


@dataclass(frozen=True)
class PairCooccurrence:
    """The category-pair confusion table (issue #827 comment, added after
    #826's verification): every pair of categories that co-occurs in at
    least one bag holding 2+ categories among its own categorised members,
    ranked by how many bags they share, plus the two pairs #826's
    verification could not choose between -- always reported by name,
    whether or not they rank."""

    multi_category_bag_count: int
    pairs: tuple[CategoryPair, ...]
    named_pairs: tuple[CategoryPair, ...]


@dataclass(frozen=True)
class PurityReport:
    pin: str
    map_dir: Path
    vocabulary_dir: Path
    column: str
    level: int
    coverage: CoverageReport
    purity: PurityStats
    scatter: ScatterStats
    pairs: PairCooccurrence


def _load_json_or_none(path: Path) -> dict[str, Any] | None:
    """Local, tolerant JSON read -- the same shape every other module's own
    manifest reader keeps privately (`axial.vocabulary._load_json_or_none`,
    `axial.argmap.build._load_json_or_none`, `axial.argmap.vocabulary_join.
    _load_json_or_none`) rather than importing another module's private
    helper, the precedent all three already set."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _read_assignment_records(path: Path) -> list[dict[str, Any]]:
    """Every persisted assignment record under `path`, or `[]` when the
    file does not exist. A torn final line is dropped, not raised -- the
    same tolerance every other reader of this file already gives it."""
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


def resolve_map_pin_dir(map_dir: Path, pin: str | None) -> tuple[Path, str]:
    """The pin directory to read bag state from: `map_dir / pin` when `pin`
    is given, otherwise the newest sibling under `map_dir` by its own
    `map.json` mtime (`axial.argmap.build._prior_pin_dir`, called with an
    empty `current_pin` so no real build is excluded and every completed one
    competes). Raises `NoMapDirError` when there is nothing to resolve,
    `NoBagStateError` when what resolves has no persisted bag state."""
    root = Path(map_dir)
    if pin is not None:
        outdir = root / pin
        if not outdir.is_dir():
            raise NoMapDirError(root, pin)
        resolved_pin = pin
    else:
        newest = _prior_pin_dir(root, current_pin="")
        if newest is None:
            raise NoMapDirError(root, None)
        outdir = newest
        resolved_pin = outdir.name

    if not _bag_state_path(outdir).is_file():
        raise NoBagStateError(resolved_pin, outdir)
    return outdir, resolved_pin


def _load_bag_assignments(outdir: Path) -> dict[str, int]:
    raw = _load_json_or_none(_bag_state_path(outdir)) or {}
    assignments = raw.get("assignments")
    if not isinstance(assignments, dict):
        return {}
    return {str(chunk_id): int(label) for chunk_id, label in assignments.items()}


def parse_named_pair(raw: str) -> tuple[str, str]:
    """One `--named-pair id-a,id-b` value into the `(category_a, category_b)`
    shape `compute_purity`'s own `named_pairs` parameter takes. Raises
    `InvalidNamedPairError` naming the bad value -- never lets a malformed
    flag reach `compute_purity` as a one-element or three-element tuple."""
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 2 or not all(parts):
        raise InvalidNamedPairError(raw)
    return (parts[0], parts[1])


def _named_pair(
    id_a: str,
    id_b: str,
    category_names: Mapping[str, str],
    pair_counts: Mapping[tuple[str, str], int],
    multi_category_bag_count: int,
    known_category_ids: set[str],
) -> CategoryPair:
    applicable = id_a in known_category_ids and id_b in known_category_ids
    key = tuple(sorted((id_a, id_b)))
    count = pair_counts.get(key, 0) if applicable else 0
    share = (count / multi_category_bag_count) if applicable and multi_category_bag_count else None
    return CategoryPair(
        category_a=key[0],
        category_b=key[1],
        name_a=category_names.get(key[0], ""),
        name_b=category_names.get(key[1], ""),
        bag_count=count,
        share=share,
        applicable=applicable,
    )


def compute_purity(
    *,
    column: str,
    map_dir: Path | None = None,
    pin: str | None = None,
    vocabulary_dir: Path | None = None,
    level: int | None = None,
    named_pairs: Sequence[tuple[str, str]] = NAMED_PAIRS,
) -> PurityReport:
    """The full cross-tab (issue #827): resolves the map pin, reads its bag
    state, reads `column`'s built vocabulary, and joins the two. Raises
    `NoMapDirError`/`NoBagStateError` (this module) for anything wrong on
    the map side, `NoVocabularyError` (`axial.argmap.vocabulary_join`) when
    `column` has never been built. Zero model calls, zero network -- every
    number here comes from two files already on disk.

    `named_pairs` defaults to `NAMED_PAIRS` -- the two pairs #826's
    verification flagged, always checked on a bare run so that guarantee
    survives without a flag -- but is a plain parameter, not a constant
    baked into the join itself: `config/vocabulary.yaml` is corpus-specific
    data, and a scheme this command runs against later needs its own pair
    or pairs of interest without a code change (`--named-pair` on the CLI,
    `axial.cli._map_purity`)."""
    root = Path(map_dir) if map_dir is not None else default_map_dir()
    outdir, resolved_pin = resolve_map_pin_dir(root, pin)
    bag_assignments = _load_bag_assignments(outdir)

    vocab_root = Path(vocabulary_dir) if vocabulary_dir is not None else VOCABULARY_DIR
    column_dir = vocab_root / column
    manifest = _load_json_or_none(column_dir / MANIFEST_FILENAME)
    if manifest is None:
        raise NoVocabularyError(column, column_dir)
    resolved_level = level if level is not None else int(manifest.get("max_level", ROOT_LEVEL))
    category_names = {
        str(entry.get("category_id")): str(entry.get("name", ""))
        for entry in manifest.get("categories", [])
        if isinstance(entry, dict) and isinstance(entry.get("category_id"), str)
    }

    records = _read_assignment_records(column_dir / ASSIGNMENTS_FILENAME)
    records_by_chunk: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for record in records:
        if int(record.get("level", ROOT_LEVEL)) != resolved_level:
            continue
        records_by_chunk[str(record.get("chunk_id", ""))].append(record)

    category_ids_by_chunk: dict[str, frozenset[str]] = {}
    reason_by_chunk: dict[str, str] = {}
    for chunk_id, recs in records_by_chunk.items():
        assigned = {
            record["category_id"] for record in recs if isinstance(record.get("category_id"), str)
        }
        if assigned:
            category_ids_by_chunk[chunk_id] = frozenset(assigned)
            reason_by_chunk[chunk_id] = REASON_ASSIGNED
        elif any(record.get("out_of_scheme") for record in recs):
            reason_by_chunk[chunk_id] = REASON_OUT_OF_SCHEME
        else:
            reason_by_chunk[chunk_id] = REASON_REFUSED

    bag_chunk_ids = set(bag_assignments)
    vocabulary_chunk_ids = set(records_by_chunk)
    overlap = bag_chunk_ids & vocabulary_chunk_ids

    overlap_assigned = {c for c in overlap if reason_by_chunk.get(c) == REASON_ASSIGNED}
    overlap_refused = {c for c in overlap if reason_by_chunk.get(c) == REASON_REFUSED}
    overlap_out_of_scheme = {c for c in overlap if reason_by_chunk.get(c) == REASON_OUT_OF_SCHEME}
    # Issue #827 fix round, reviewer F4: a chunk carrying 2+ categories at
    # this level (only possible on a list-valued column -- neither `claim`
    # nor `mechanism` is one) would otherwise inflate purity's modal share
    # and double-enter the pair table silently. Counted and printed even
    # though it is 0 on both live columns today.
    overlap_multi_category_count = sum(
        1 for c in overlap_assigned if len(category_ids_by_chunk[c]) > 1
    )

    coverage = CoverageReport(
        bag_chunk_count=len(bag_chunk_ids),
        vocabulary_chunk_count=len(vocabulary_chunk_ids),
        overlap_count=len(overlap),
        bag_only_count=len(bag_chunk_ids - vocabulary_chunk_ids),
        vocabulary_only_count=len(vocabulary_chunk_ids - bag_chunk_ids),
        overlap_assigned_count=len(overlap_assigned),
        overlap_refused_count=len(overlap_refused),
        overlap_out_of_scheme_count=len(overlap_out_of_scheme),
        overlap_multi_category_count=overlap_multi_category_count,
    )

    bag_members: dict[int, list[str]] = collections.defaultdict(list)
    for chunk_id in bag_chunk_ids:
        bag_members[bag_assignments[chunk_id]].append(chunk_id)

    purities: list[float] = []
    distinct_counts: list[int] = []
    eligible_bag_count = 0
    # Issue #827 fix round, reviewer F2: the population `bag_count` (below)
    # is drawn from -- every bag holding at least one categorised member,
    # BEFORE the 2+ eligibility filter purity applies. Tracked separately so
    # the report never states a scatter count next to `eligible_bag_count`
    # and lets a reader divide by the wrong base.
    population_bag_count = 0
    category_reach: dict[str, dict[str, set]] = collections.defaultdict(
        lambda: {"chunk_ids": set(), "bag_labels": set()}
    )
    pair_counts: collections.Counter[tuple[str, str]] = collections.Counter()
    multi_category_bag_count = 0

    for bag_label, members in bag_members.items():
        categorised = [chunk_id for chunk_id in members if chunk_id in overlap_assigned]
        if categorised:
            population_bag_count += 1
        category_counts: collections.Counter[str] = collections.Counter()
        for chunk_id in categorised:
            for category_id in category_ids_by_chunk[chunk_id]:
                category_counts[category_id] += 1
                category_reach[category_id]["chunk_ids"].add(chunk_id)
                category_reach[category_id]["bag_labels"].add(bag_label)

        if len(categorised) < 2:
            continue
        eligible_bag_count += 1
        modal_count = max(category_counts.values())
        purities.append(modal_count / len(categorised))
        distinct_counts.append(len(category_counts))

        if len(category_counts) >= 2:
            multi_category_bag_count += 1
            for category_a, category_b in itertools.combinations(sorted(category_counts), 2):
                pair_counts[(category_a, category_b)] += 1

    pure_bag_count = sum(1 for value in purities if value == 1.0)
    purity = PurityStats(
        eligible_bag_count=eligible_bag_count,
        excluded_bag_count=len(bag_members) - eligible_bag_count,
        median_purity=statistics.median(purities) if purities else None,
        mean_purity=statistics.fmean(purities) if purities else None,
        pure_bag_count=pure_bag_count,
        pure_bag_share=(pure_bag_count / len(purities)) if purities else None,
        median_distinct_categories=statistics.median(distinct_counts) if distinct_counts else None,
        mean_distinct_categories=statistics.fmean(distinct_counts) if distinct_counts else None,
    )

    all_category_ids = set(category_names) | set(category_reach)
    scatter_categories = tuple(
        sorted(
            (
                CategoryScatter(
                    category_id=category_id,
                    category_name=category_names.get(category_id, ""),
                    member_count=len(category_reach[category_id]["chunk_ids"]),
                    bag_count=len(category_reach[category_id]["bag_labels"]),
                )
                for category_id in all_category_ids
            ),
            key=lambda scatter: (-scatter.bag_count, scatter.category_id),
        )
    )
    populated_bag_counts = [
        scatter.bag_count for scatter in scatter_categories if scatter.member_count > 0
    ]
    scatter = ScatterStats(
        categories=scatter_categories,
        population_bag_count=population_bag_count,
        min_bag_count=min(populated_bag_counts) if populated_bag_counts else None,
        median_bag_count=statistics.median(populated_bag_counts) if populated_bag_counts else None,
        max_bag_count=max(populated_bag_counts) if populated_bag_counts else None,
    )

    ranked_pairs = tuple(
        CategoryPair(
            category_a=category_a,
            category_b=category_b,
            name_a=category_names.get(category_a, ""),
            name_b=category_names.get(category_b, ""),
            bag_count=count,
            share=(count / multi_category_bag_count) if multi_category_bag_count else None,
        )
        for (category_a, category_b), count in sorted(
            pair_counts.items(), key=lambda item: (-item[1], item[0])
        )
    )

    known_category_ids = set(category_names)
    named_pair_results = tuple(
        _named_pair(
            id_a, id_b, category_names, pair_counts, multi_category_bag_count, known_category_ids
        )
        for id_a, id_b in named_pairs
    )

    return PurityReport(
        pin=resolved_pin,
        map_dir=outdir,
        vocabulary_dir=column_dir,
        column=column,
        level=resolved_level,
        coverage=coverage,
        purity=purity,
        scatter=scatter,
        pairs=PairCooccurrence(
            multi_category_bag_count=multi_category_bag_count,
            pairs=ranked_pairs,
            named_pairs=named_pair_results,
        ),
    )


def _pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _num(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def format_purity_report(report: PurityReport) -> str:
    """Render `PurityReport` as a human-readable report. Format is left to
    the implementer, only that every number the acceptance criterion asks
    for is present (mirrors `axial.vocabulary.format_vocabulary_report`'s
    own docstring)."""
    lines: list[str] = [
        f"pin: {report.pin} ({report.map_dir})",
        f"column: {report.column} (level {report.level})",
        f"vocabulary: {report.vocabulary_dir}",
        "",
    ]

    coverage = report.coverage
    lines += [
        "COVERAGE",
        f"  bag-side chunks: {coverage.bag_chunk_count}",
        f"  vocabulary-side chunks: {coverage.vocabulary_chunk_count}",
        f"  overlap (joinable both sides): {coverage.overlap_count}",
        f"  bag-only (no vocabulary record for this column): {coverage.bag_only_count}",
        f"  vocabulary-only (no bag): {coverage.vocabulary_only_count}",
        f"  overlap assigned a category: {coverage.overlap_assigned_count}",
        f"  overlap assigned 2+ categories: {coverage.overlap_multi_category_count}",
        f"  overlap refused: {coverage.overlap_refused_count}",
        f"  overlap out-of-scheme: {coverage.overlap_out_of_scheme_count}",
        "",
    ]

    purity = report.purity
    lines += [
        "PURITY (bags with 2+ categorised members)",
        f"  eligible bags: {purity.eligible_bag_count}",
        f"  excluded (fewer than 2 categorised members): {purity.excluded_bag_count}",
        f"  median purity: {_num(purity.median_purity)}",
        f"  mean purity: {_num(purity.mean_purity)}",
        f"  pure bags (purity == 1.0): {purity.pure_bag_count} ({_pct(purity.pure_bag_share)})",
        f"  median distinct categories per bag: {_num(purity.median_distinct_categories)}",
        f"  mean distinct categories per bag: {_num(purity.mean_distinct_categories)}",
        "",
    ]

    scatter = report.scatter
    lines.append(
        "CATEGORY SCATTER (over "
        f"{scatter.population_bag_count} bag(s) holding at least one categorised member)"
    )
    min_text = scatter.min_bag_count if scatter.min_bag_count is not None else "n/a"
    max_text = scatter.max_bag_count if scatter.max_bag_count is not None else "n/a"
    lines.append(
        f"  min/median/max bags per populated category: {min_text} / "
        f"{_num(scatter.median_bag_count)} / {max_text}"
    )
    for category in scatter.categories:
        lines.append(
            f"    {category.category_id} ({category.category_name}): "
            f"{category.bag_count} bag(s), {category.member_count} member(s)"
        )
    lines.append("")

    pairs = report.pairs
    lines.append(
        f"CATEGORY PAIR CO-OCCURRENCE ({pairs.multi_category_bag_count} multi-category bag(s))"
    )
    if pairs.pairs:
        for rank, pair in enumerate(pairs.pairs, start=1):
            lines.append(
                f"  {rank}. {pair.category_a} x {pair.category_b}: {pair.bag_count} bag(s) "
                f"({_pct(pair.share)})"
            )
    else:
        lines.append("  no pair co-occurs in any bag")
    lines.append("")

    lines.append("NAMED PAIRS (#826's verification -- reported whether or not they rank)")
    ranks_by_key = {(p.category_a, p.category_b): i for i, p in enumerate(pairs.pairs, start=1)}
    for pair in pairs.named_pairs:
        if not pair.applicable:
            lines.append(
                f"  {pair.category_a} x {pair.category_b}: not applicable "
                "(not both in this column's scheme)"
            )
            continue
        rank = ranks_by_key.get((pair.category_a, pair.category_b))
        rank_note = f"rank {rank}" if rank is not None else "absent from the ranking (0 bags)"
        lines.append(
            f"  {pair.category_a} x {pair.category_b}: {pair.bag_count} bag(s) "
            f"({_pct(pair.share)}), {rank_note}"
        )

    return "\n".join(lines).rstrip("\n")
