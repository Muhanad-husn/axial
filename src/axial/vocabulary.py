"""The derived vocabulary (`plans/derived-vocabulary/`): two passes over
the twelve sentence-valued answer columns, one that reports and one that
persists.

`examine_vocabulary` (issue #805, slice 01) is the read-only report -- `about`, `claim`, `move`, `ranges_over`,
`stops_holding`, `position`, `arguing_against`, `mechanism`, `evidence`,
`comparison`, `concedes`, `assumes`. Every note answers seventeen questions;
three repeat often enough to join on and are out of scope here (`names`,
`uses`, `defines`); these twelve hold near-unique sentences instead, so
nothing joins on them today. This module asks whether they group by meaning
anyway -- not by embedding distance, which measures wording (rejected here
2026-08-27 after a run on the real corpus, see the plan's own status log),
but by having a model read a random sample and name the recurring kinds,
then testing that scheme against a disjoint sample it has never seen.

It is the go/no-go for the whole feature (`plans/derived-vocabulary/
README.md`), and it writes nothing -- no artifact, no category ids, no
reuse across runs, no corpus pin moved. It reports a scheme; a person reads
it and decides.

`build_vocabulary` (issue #806, slice 02) is the other half, and the two
face opposite directions. It takes a scheme as an INPUT -- committed to
`config/vocabulary.yaml` by a person, never derived at run time -- assigns
the WHOLE column against it, and persists that assignment under
`data/vocabulary/<column>/`. It proposes nothing. See `specs/PHASE-B.md`
§7.18 for the artifact's shape and the reuse rule, and the long comment
above `DEFAULT_VOCABULARY_SCHEME_PATH` below for why the scheme is frozen.

Reuses rather than rebuilds: `axial.query.reader.is_abstention` (the one
place an abstention is decided) and `axial.model_json.complete_json`/
`parse_model_json` (the one fenced-JSON parser every model-backed pass
already shares). The two prompts below are lifted, not rewritten, from the
probe that measured this approach against the real corpus 2026-08-27 (see
the plan's "Why this slice exists"): a model reading 400 `mechanism` values
named 14 categories, all cross-source, and 70.8% of a disjoint 400 it had
never seen fell into them, for $0.026.

**Propose, then assign held-out. Never score the proposal sample.** A scheme
always fits the values it was derived from -- the only number worth
reporting is the rate on values the model has not seen. `draw_vocabulary_
samples` draws both from one shuffle under a stated seed, so the assignment
sample never reaches the model that proposes the scheme and a re-run over
the same corpus draws the same two samples.

**Two models, never one grading itself.** The examine pass (`EXAMINE_PASS_
NAME`) proposes the scheme and assigns the held-out sample against it; the
check pass (`CHECK_PASS_NAME`) re-assigns a subsample of the same held-out
values against the same scheme, and the two models' agreement is the self-
consistency check -- without it, the assignment rate is one model grading
its own work. `config/pipeline.yaml`'s `model_by_pass` routes both passes to
their own tier, and the two tiers must resolve to different models
(`SelfConsistencyError`, checked once before any call is made) -- the same
pattern `axial.paper.shape`'s `SelfGradingError` established for the paper
shape check against the paper draft, not reused directly because it is
anchored to the drafting pass by name.
"""

from __future__ import annotations

import collections
import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from axial.interrogate import _default_answers_dir
from axial.llm import LLMClient, get_client
from axial.model_json import complete_json, parse_model_json
from axial.names import load_answer_records
from axial.paths import DEFAULT_PIPELINE_CONFIG_PATH
from axial.query.reader import is_abstention
from axial.yaml_loader import SAFE_LOADER

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

# The pass names `config/pipeline.yaml`'s `llm.model_by_pass` keys off of,
# mirroring `axial.argmap.build.PASS_NAME`'s own local (not `axial.llm`-
# centralised) convention: a pass name lives with the module that owns the
# pass, and only the TIER it routes to (`axial.llm.PRODUCTION_VOCABULARY_
# EXAMINE_TIER`/`..._CHECK_TIER`) needs registering centrally.
EXAMINE_PASS_NAME = "vocabulary_examine"
CHECK_PASS_NAME = "vocabulary_examine_check"

# The build's own pass name, routed to the SAME tier the examine pass uses
# (`config/pipeline.yaml`'s `model_by_pass`) -- pinned there, never left to
# default, so this buys a cost line and carries no routing change. It needs
# its own line because the two passes differ by an order of magnitude in
# what they spend: examine reads a 400-value sample, and a build over seven
# columns is ~648 calls and roughly $1. Charging that to the examine line
# would misprice both for whoever reads per-pass cost next.
BUILD_PASS_NAME = "vocabulary_build"

# Sample sizes measured at $0.026 for one column (the probe, 2026-08-27):
# 400 to propose a scheme, a disjoint 400 to test it. Arguments, not
# constants, because the go/no-go bar quantifies over them and an operator
# sweeping a different column shape may want to move them.
DEFAULT_PROPOSE_N = 400
DEFAULT_ASSIGN_N = 400

# Assignment runs in batches so one call's prompt never carries the whole
# held-out sample -- the probe's own batch size, and the size the plan
# states explicitly ("Batch of 100").
BATCH_SIZE = 100

# How much of the held-out sample the check pass re-assigns to measure
# self-consistency (bar condition 5). One batch's worth: enough to measure
# agreement without doubling the pass's own call count, and the same
# magnitude `BATCH_SIZE` already uses rather than a second invented number.
CHECK_SAMPLE_SIZE = 100

# The go/no-go bar's own floor (plan's "the bar for slice 02 to proceed",
# conditions 1 and 3): a category counts toward the bar only at 5 or more
# members.
MIN_CATEGORY_SIZE = 5

# A model that returns roughly as many categories as it was shown answers
# has restated the sample rather than categorised it (plan's design notes).
# "Roughly as many" is read here as more than half: the probe that measured
# this approach returned 14 categories for a 400-value sample (3.5%), and a
# scheme sized anywhere near half its own source sample cannot be naming
# recurring KINDS -- it is naming the values back.
#
# As calibrated, this guard is INERT (PR #815 review, F6): at
# `DEFAULT_PROPOSE_N` == 400, it fires only above 200 categories, and the
# largest scheme any of the twelve columns actually produced on the real
# corpus run was 36 (`mechanism`). It has never once seen the granularity
# problem that run actually hit -- a scheme that came out too coarse, not
# too fine. Kept as-is (the contract mandates the restatement flag, and the
# constant is not wrong, just far from the failure mode in play); pinning
# granularity is slice 02's problem, not this guard's.
RESTATEMENT_RATIO = 0.5

# Lifted verbatim from the probe that measured this approach against the
# real corpus (2026-08-27, `mechanism`: 14 categories, 70.8% held-out
# assignment, $0.026) -- not rewritten, per the slice's own design notes.
# The anti-restatement rule is the load-bearing part of both prompts.
PROPOSE_PROMPT = """Below are {n} answers drawn at random from one column of an
academic corpus's notes. Each is one note's answer to the same question, written
by a reader of a passage. The column is `{column}`.

Your task: say what recurring KINDS these answers fall into -- the categories a
scholar would use to file them, derived from what the answers actually say, not
from the words they happen to share.

Rules, and they are the whole task:
- A category is a KIND OF THING, not a topic. "War drives state formation" is a
  kind; "things about Syria" is a topic and is worthless here.
- A category must cover several answers that say the same thing in different
  words and about different subject matter. If two answers sit together only
  because they mention the same country, person or period, they are not one
  category.
- Do NOT restate the answers. Producing roughly as many categories as answers
  means the task was not done.
- If these answers genuinely do not recur -- if each is its own one-off -- say
  so by returning few categories or none. That is a real and acceptable answer.

Return JSON only, no prose:
{{"categories": [{{"name": "<short name>", "gloss": "<one sentence saying what
belongs here and what does not>"}}]}}

The answers:
{values}
"""

# The one string the assign prompt below asks for when no category fits.
# Compared case-folded: "None" is the same word, and reading it as an
# unrecognised category name would raise a false alarm on the very signal
# that distinction exists to make trustworthy.
REFUSAL_TOKEN = "none"

ASSIGN_PROMPT = """Here is a category scheme derived from one column of an
academic corpus's notes, and {n} further answers from the same column that were
NOT used to build the scheme.

Assign each answer to exactly one category, or to "none" when no category fits.
"none" is the right answer whenever an answer is a one-off or fits only by
topic. Do not stretch a category to cover something it does not describe --
this is a test of whether the scheme holds, and a wrong assignment destroys the
measurement.

The categories:
{categories}

The answers, numbered:
{values}

Return JSON only, no prose:
{{"assignments": [{{"n": <number>, "category": "<category name or none>"}}]}}
"""


@dataclass(frozen=True)
class PopulationEntry:
    """One answered value: the sentence itself, and the note it came from.
    A list-valued column (`about`, `arguing_against`) contributes one entry
    per list element, so several entries can share a `chunk_id`.

    `element_index` (issue #806) is that element's position in the note's
    own list -- always `0` for a scalar column. It is the third part of the
    key a persisted assignment is filed under (`chunk_id`, column,
    `element_index`), and without it two elements of one note's list are
    indistinguishable on disk. It counts RAW list positions, so an element
    excluded as an abstention still consumes its own index rather than
    shifting its neighbours."""

    value: str
    chunk_id: str
    source_id: str
    element_index: int = 0


@dataclass(frozen=True)
class CategoryReport:
    """One category the examine pass named: its gloss, how many held-out
    values were assigned to it, and how many distinct sources those members
    come from. Every category the model proposed is reported here, even one
    with zero members -- a category nobody's held-out value fit is itself a
    finding, not a row to drop."""

    name: str
    gloss: str
    member_count: int
    source_count: int


@dataclass(frozen=True)
class ColumnVocabularyStats:
    """One column's full report. `propose_sample_size`/`assign_sample_size`
    are what was actually drawn -- equal to the requested `propose_n`/
    `assign_n` unless `reduced` is set, in which case the column's own
    population held fewer than the two combined and both were drawn from
    what there was. `proposal_failed` (restatement, `RESTATEMENT_RATIO`)
    means every field from `assignment_rate` on is `None`: assignment and
    the self-consistency check are never run against a scheme that failed
    to categorise, so no further spend is made on it.

    `unanswered_count`/`refused_count` split what an older cut of this
    module lumped together as "unassigned" (issue #815 review, F4):
    `unanswered_count` is an index the merged assign-batch responses never
    returned at all -- after `_assign_batch`'s own key validation (every
    batch response must return exactly the indexes it was asked about, or
    `VocabularyResponseError` re-asks it) this should always be `0` in a
    completed run, and it is printed anyway so that fact is visible rather
    than assumed. `refused_count` is an index the model DID return, with a
    label of `"none"` or one naming no proposed category -- a real,
    intentional non-placement, not a dropped response. Both are `None`
    exactly when `assignment_rate` is `None` (proposal failed or no
    held-out sample).

    Two agreement numbers, and neither substitutes for the other.
    `agreement_rate`/`agreement_sample_size` is the OVERALL rate over the
    whole check subsample: an entry where both models say "none" counts as
    agreement, because it is an honest denominator for "how often do the two
    models do the same thing" -- but it also means two models that both fail
    to place a value are scored as agreeing about it.
    `agreement_where_assigned_rate`/`agreement_where_assigned_sample_size` is
    restricted to the subsample entries the FIRST model placed in a real
    category; this is the number bar condition 5 (60% floor) is about, and
    it carries its own `n` because a restricted rate over a handful of
    values is not evidence. When the first model assigned nothing in the
    subsample, `agreement_where_assigned_rate` is `None`, not `0.0`."""

    column: str
    answered_count: int
    distinct_count: int
    excluded_count: int
    propose_sample_size: int
    assign_sample_size: int
    reduced: bool
    proposal_failed: bool
    categories: list[CategoryReport]
    assignment_rate: float | None
    unanswered_count: int | None
    refused_count: int | None
    categories_5plus: int | None
    categories_5plus_cross_source: int | None
    largest_category_share: float | None
    agreement_rate: float | None
    agreement_sample_size: int | None
    agreement_where_assigned_rate: float | None
    agreement_where_assigned_sample_size: int | None
    examine_model: str
    check_model: str | None
    examine_calls: int
    examine_cost: float | None
    check_calls: int
    check_cost: float | None


@dataclass(frozen=True)
class VocabularyExamineStats:
    columns: list[ColumnVocabularyStats]


class VocabularyResponseError(ValueError):
    """Raised when a propose/assign response from the model is not the
    expected shape -- re-askable within `complete_json`'s own bounded
    budget via its `validate` seam, exactly like `axial.gather.
    GatherResponseError`."""


class SelfConsistencyError(Exception):
    """Raised when the check pass (`CHECK_PASS_NAME`) resolves to the SAME
    model as the examine pass (`EXAMINE_PASS_NAME`) -- the model that
    proposed and assigned a scheme must never be the only model that grades
    whether it holds. Mirrors `axial.paper.shape.SelfGradingError`'s own
    rule, not reused directly because that class is anchored to the paper-
    drafting pass by name. Raised before any propose/assign/check call is
    made; zero calls are made when this fires."""

    def __init__(self, model: str) -> None:
        self.model = model
        super().__init__(
            f"the vocabulary check pass (pass_name={CHECK_PASS_NAME!r}) resolves to model "
            f"{model!r}, the SAME model as the examine pass (pass_name={EXAMINE_PASS_NAME!r}) "
            "-- self-consistency check: configure model_by_pass so the check pass runs under "
            "a different model than the pass that proposed and assigned the scheme"
        )


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
            for element_index, element in enumerate(value):
                text = _extract_scalar(element)
                if text is None:
                    excluded += 1
                else:
                    population.append(
                        PopulationEntry(text, chunk_id, source_id, element_index)
                    )
        else:
            text = _extract_scalar(value)
            if text is None:
                excluded += 1
            else:
                population.append(PopulationEntry(text, chunk_id, source_id))

    return population, excluded


def draw_vocabulary_samples(
    population: Sequence[PopulationEntry], propose_n: int, assign_n: int, seed: int
) -> tuple[list[PopulationEntry], list[PopulationEntry], bool]:
    """Two disjoint samples drawn from `population` under `seed`: up to
    `propose_n` for the model that names the category scheme, then up to
    `assign_n` more -- never overlapping the first -- for the model that
    assigns held-out values against it. `population` is shuffled once under
    `seed` and split by position, so a re-run over the same corpus draws the
    same two samples and the assignment sample never reaches the model that
    proposes the scheme (the whole measurement this slice exists to make).

    When `population` holds fewer than `propose_n + assign_n` entries, both
    samples are still drawn -- propose first, up to `propose_n`, then
    whatever remains, up to `assign_n` -- and the third element of the
    return value is `True`, so a caller reports the reduction rather than
    silently measuring a smaller sample as though it were the requested
    size."""
    pool = list(population)
    random.Random(seed).shuffle(pool)
    propose_take = min(propose_n, len(pool))
    propose_sample = pool[:propose_take]
    remaining = pool[propose_take:]
    assign_take = min(assign_n, len(remaining))
    assign_sample = remaining[:assign_take]
    reduced = len(pool) < propose_n + assign_n
    return propose_sample, assign_sample, reduced


def parse_propose_response(raw: str) -> list[dict[str, str]]:
    """Parse a propose-pass response into `[{"name", "gloss"}, ...]`. An
    empty list is a valid, real answer (the prompt says so explicitly) --
    only a malformed shape raises."""
    parsed = parse_model_json(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("categories"), list):
        raise VocabularyResponseError(
            f"expected an object with a 'categories' list, got {parsed!r}"
        )
    categories: list[dict[str, str]] = []
    for entry in parsed["categories"]:
        if not isinstance(entry, dict):
            raise VocabularyResponseError(f"a 'categories' entry is not an object: {entry!r}")
        name = entry.get("name")
        gloss = entry.get("gloss")
        if not isinstance(name, str) or not name.strip():
            raise VocabularyResponseError(f"a category has no usable 'name': {entry!r}")
        if not isinstance(gloss, str) or not gloss.strip():
            raise VocabularyResponseError(f"category {name!r} has no usable 'gloss'")
        categories.append({"name": name.strip(), "gloss": gloss.strip()})
    return categories


def parse_assign_response(raw: str) -> dict[int, str]:
    """Parse an assign-pass response into `{n: category_name}`. A malformed
    entry (no integer `n`, no string `category`) raises; a `category` that
    names no known category is left as-is here -- turning that into
    "unassigned" is the caller's job (it needs the category scheme, which
    this parser is never handed), matching `axial.gather.parse_gather_
    response`'s own division of labour between parsing and deciding."""
    parsed = parse_model_json(raw)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("assignments"), list):
        raise VocabularyResponseError(
            f"expected an object with an 'assignments' list, got {parsed!r}"
        )
    result: dict[int, str] = {}
    for entry in parsed["assignments"]:
        if not isinstance(entry, dict):
            raise VocabularyResponseError(f"an 'assignments' entry is not an object: {entry!r}")
        number = entry.get("n")
        category = entry.get("category")
        if not isinstance(number, int):
            raise VocabularyResponseError(f"an assignment has no integer 'n': {entry!r}")
        if not isinstance(category, str) or not category.strip():
            raise VocabularyResponseError(f"assignment {number} has no usable 'category'")
        result[number] = category.strip()
    return result


def _scheme_text(categories: Sequence[dict[str, str]]) -> str:
    return "\n".join(f"- {category['name']}: {category['gloss']}" for category in categories)


def _propose_categories(
    client: LLMClient, column: str, sample: Sequence[PopulationEntry]
) -> list[dict[str, str]]:
    values = "\n".join(f"- {entry.value}" for entry in sample)
    prompt = PROPOSE_PROMPT.format(n=len(sample), column=column, values=values)
    raw = complete_json(
        client, prompt, pass_name=EXAMINE_PASS_NAME, validate=parse_propose_response
    )
    return parse_propose_response(raw)


def _validate_assign_batch_keys(raw: str, expected_indexes: frozenset[int]) -> None:
    """Raise `VocabularyResponseError` unless a parsed assign-batch response
    returns keys that are exactly `expected_indexes` (issue #815 review,
    F4). Two failure modes look identical downstream if this is skipped,
    and both silently score as unassigned: a truncated completion that
    loses its tail of assignments (these calls run 170-250s producing
    ~10k completion tokens, squarely the truncation regime), and a model
    that renumbers a later batch 1..N instead of continuing the global
    numbering, which would overwrite the earlier batch's real assignments
    through `dict.update` in `_assign_all`. Raising here, inside
    `complete_json`'s own `validate` seam, gets the batch re-asked within
    its bounded attempt budget instead of trusted as-is."""
    got = set(parse_assign_response(raw))
    if got != expected_indexes:
        missing = sorted(expected_indexes - got)
        extra = sorted(got - expected_indexes)
        raise VocabularyResponseError(
            f"assign batch returned {len(got)} key(s), expected exactly the "
            f"{len(expected_indexes)} indexes {sorted(expected_indexes)} -- "
            f"missing={missing}, extra={extra} (a truncated completion or a "
            "renumbered batch)"
        )


def _assign_batch(
    client: LLMClient,
    pass_name: str,
    scheme_text: str,
    batch: Sequence[PopulationEntry],
    start: int,
) -> dict[int, str]:
    numbered = "\n".join(f"{start + i + 1}. {entry.value}" for i, entry in enumerate(batch))
    prompt = ASSIGN_PROMPT.format(n=len(batch), categories=scheme_text, values=numbered)
    expected_indexes = frozenset(range(start + 1, start + len(batch) + 1))
    raw = complete_json(
        client,
        prompt,
        pass_name=pass_name,
        validate=lambda response: _validate_assign_batch_keys(response, expected_indexes),
    )
    return parse_assign_response(raw)


def _assign_all(
    client: LLMClient,
    pass_name: str,
    scheme_text: str,
    sample: Sequence[PopulationEntry],
    workers: int = 1,
) -> dict[int, str]:
    """Assign the whole of `sample` against `scheme_text`, in `BATCH_SIZE`
    batches, numbered globally (1-based, continuing across batches) so a
    caller can compare this pass's assignment for index `i` against another
    pass's assignment for the same index -- what the self-consistency check
    does.

    `workers` runs those batches concurrently (issue #806). Each batch is
    an independent call over a disjoint slice of the global index space, so
    merging their results is order-free -- and `_validate_assign_batch_keys`
    is what makes that safe, since a batch that renumbered itself 1..N is
    re-asked rather than allowed to overwrite a concurrent batch's real
    assignments. The examine pass (slice 01) keeps the serial default: it
    assigns 400 values, four batches, where a pool buys nothing. A build
    over the whole `mechanism` column is ~60 batches, which serially is
    hours rather than the twenty minutes at twelve workers issue #806
    budgets for.
    """
    starts = list(range(0, len(sample), BATCH_SIZE))
    assignments: dict[int, str] = {}
    if workers <= 1 or len(starts) <= 1:
        for start in starts:
            batch = sample[start : start + BATCH_SIZE]
            assignments.update(_assign_batch(client, pass_name, scheme_text, batch, start))
        return assignments

    with ThreadPoolExecutor(max_workers=min(workers, len(starts))) as pool:
        futures = [
            pool.submit(
                _assign_batch,
                client,
                pass_name,
                scheme_text,
                sample[start : start + BATCH_SIZE],
                start,
            )
            for start in starts
        ]
        for future in futures:
            assignments.update(future.result())
    return assignments


def _empty_column_stats(
    column: str,
    answered_count: int,
    distinct_count: int,
    excluded: int,
    reduced: bool,
    examine_model: str,
    check_model: str,
) -> ColumnVocabularyStats:
    return ColumnVocabularyStats(
        column=column,
        answered_count=answered_count,
        distinct_count=distinct_count,
        excluded_count=excluded,
        propose_sample_size=0,
        assign_sample_size=0,
        reduced=reduced,
        proposal_failed=False,
        categories=[],
        assignment_rate=None,
        unanswered_count=None,
        refused_count=None,
        categories_5plus=None,
        categories_5plus_cross_source=None,
        largest_category_share=None,
        agreement_rate=None,
        agreement_sample_size=None,
        agreement_where_assigned_rate=None,
        agreement_where_assigned_sample_size=None,
        examine_model=examine_model,
        check_model=check_model,
        examine_calls=0,
        examine_cost=None,
        check_calls=0,
        check_cost=None,
    )


def _cost_delta(before: float | None, after: float | None) -> float | None:
    if after is None:
        return None
    if before is None:
        # `before is None` means nothing had been spent on that pass yet, which is 0.0,
        # not unknown. Treat it as zero.
        return after
    return after - before


def _examine_column(
    client: LLMClient,
    column: str,
    records: Sequence[Mapping[str, Any]],
    propose_n: int,
    assign_n: int,
    seed: int,
    examine_model: str,
    check_model: str,
) -> ColumnVocabularyStats:
    population, excluded = read_column(records, column)
    answered_count = len(population)
    distinct_count = len({entry.value for entry in population})

    propose_sample, assign_sample, reduced = draw_vocabulary_samples(
        population, propose_n, assign_n, seed
    )

    if not propose_sample:
        return _empty_column_stats(
            column, answered_count, distinct_count, excluded, reduced, examine_model, check_model
        )

    examine_calls_before = client.calls_for_pass(EXAMINE_PASS_NAME)
    examine_cost_before = client.cost_for_pass(EXAMINE_PASS_NAME)

    categories = _propose_categories(client, column, propose_sample)
    proposal_failed = len(categories) > len(propose_sample) * RESTATEMENT_RATIO

    category_reports: list[CategoryReport] = []
    assignment_rate: float | None = None
    unanswered_count: int | None = None
    refused_count: int | None = None
    categories_5plus: int | None = None
    categories_5plus_cross: int | None = None
    largest_share: float | None = None
    agreement_rate: float | None = None
    agreement_sample_size: int | None = None
    agreement_where_assigned_rate: float | None = None
    agreement_where_assigned_sample_size: int | None = None
    check_calls = 0
    check_cost: float | None = None

    if proposal_failed or not categories or not assign_sample:
        category_reports = [
            CategoryReport(category["name"], category["gloss"], 0, 0) for category in categories
        ]
    else:
        scheme_text = _scheme_text(categories)
        assignments = _assign_all(client, EXAMINE_PASS_NAME, scheme_text, assign_sample)
        category_names = {category["name"] for category in categories}

        members: dict[str, list[PopulationEntry]] = collections.defaultdict(list)
        unanswered = 0
        refused = 0
        for index, entry in enumerate(assign_sample, start=1):
            if index not in assignments:
                # After `_assign_batch`'s own key validation this should
                # never happen in a completed run -- see the docstring.
                unanswered += 1
                continue
            label = assignments[index]
            if label not in category_names:
                refused += 1
            else:
                members[label].append(entry)

        unanswered_count = unanswered
        refused_count = refused
        hit = len(assign_sample) - unanswered - refused
        assignment_rate = hit / len(assign_sample)
        category_reports = [
            CategoryReport(
                name=category["name"],
                gloss=category["gloss"],
                member_count=len(members.get(category["name"], [])),
                source_count=len({e.source_id for e in members.get(category["name"], [])}),
            )
            for category in categories
        ]
        five_plus = [report for report in category_reports if report.member_count >= MIN_CATEGORY_SIZE]
        categories_5plus = len(five_plus)
        categories_5plus_cross = sum(1 for report in five_plus if report.source_count >= 2)
        largest_share = (
            max((report.member_count for report in category_reports), default=0)
            / len(assign_sample)
        )

        check_take = min(CHECK_SAMPLE_SIZE, len(assign_sample))
        subsample = assign_sample[:check_take]
        check_calls_before = client.calls_for_pass(CHECK_PASS_NAME)
        check_cost_before = client.cost_for_pass(CHECK_PASS_NAME)
        check_assignments = _assign_batch(client, CHECK_PASS_NAME, scheme_text, subsample, 0)
        check_calls = client.calls_for_pass(CHECK_PASS_NAME) - check_calls_before
        check_cost = _cost_delta(check_cost_before, client.cost_for_pass(CHECK_PASS_NAME))

        agree = 0
        assigned_total = 0
        assigned_agree = 0
        for index in range(1, check_take + 1):
            first_label = assignments.get(index, "")
            first_label = first_label if first_label in category_names else "none"
            second_label = check_assignments.get(index, "")
            second_label = second_label if second_label in category_names else "none"
            matches = first_label == second_label
            if matches:
                agree += 1
            if first_label != "none":
                assigned_total += 1
                if matches:
                    assigned_agree += 1
        agreement_rate = agree / check_take if check_take else None
        agreement_sample_size = check_take
        agreement_where_assigned_rate = assigned_agree / assigned_total if assigned_total else None
        agreement_where_assigned_sample_size = assigned_total

    examine_calls = client.calls_for_pass(EXAMINE_PASS_NAME) - examine_calls_before
    examine_cost = _cost_delta(examine_cost_before, client.cost_for_pass(EXAMINE_PASS_NAME))

    return ColumnVocabularyStats(
        column=column,
        answered_count=answered_count,
        distinct_count=distinct_count,
        excluded_count=excluded,
        propose_sample_size=len(propose_sample),
        assign_sample_size=len(assign_sample),
        reduced=reduced,
        proposal_failed=proposal_failed,
        categories=category_reports,
        assignment_rate=assignment_rate,
        unanswered_count=unanswered_count,
        refused_count=refused_count,
        categories_5plus=categories_5plus,
        categories_5plus_cross_source=categories_5plus_cross,
        largest_category_share=largest_share,
        agreement_rate=agreement_rate,
        agreement_sample_size=agreement_sample_size,
        agreement_where_assigned_rate=agreement_where_assigned_rate,
        agreement_where_assigned_sample_size=agreement_where_assigned_sample_size,
        examine_model=examine_model,
        check_model=check_model,
        examine_calls=examine_calls,
        examine_cost=examine_cost,
        check_calls=check_calls,
        check_cost=check_cost,
    )


def examine_vocabulary(
    answers_dir: Path | None = None,
    columns: Sequence[str] = VOCABULARY_COLUMNS,
    propose_n: int = DEFAULT_PROPOSE_N,
    assign_n: int = DEFAULT_ASSIGN_N,
    seed: int = 0,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
) -> VocabularyExamineStats:
    """The categorisation pass: for each of `columns`, its whole-column
    answered/distinct/excluded counts, then propose-then-assign-held-out
    against two disjoint samples (`draw_vocabulary_samples`), then a
    self-consistency check by a second model against a subsample of the
    same held-out values.

    Writes no pipeline artifact -- read-only over `answers_dir` (default
    resolved via `axial.interrogate._default_answers_dir`) and whatever the
    injected/default `client` reads from `config/pipeline.yaml` and
    `secrets/secrets.toml`.

    `client` defaults to `axial.llm.get_client()` -- the injection seam
    `axial.argmap.build.run_map_build` and `axial.gather.run_gather`
    already expose, so a unit test never makes a network call. Raises
    `SelfConsistencyError` before any call is made, for any column, when
    `CHECK_PASS_NAME` resolves to the same model as `EXAMINE_PASS_NAME`."""
    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    records = load_answer_records(Path(answers_dir))

    if client is None:
        client = get_client(config_path)

    examine_model = client.model_for_pass(EXAMINE_PASS_NAME)
    check_model = client.model_for_pass(CHECK_PASS_NAME)
    if check_model == examine_model:
        raise SelfConsistencyError(examine_model)

    columns_out = [
        _examine_column(client, column, records, propose_n, assign_n, seed, examine_model, check_model)
        for column in columns
    ]
    return VocabularyExamineStats(columns=columns_out)


def _format_cost(cost: float | None) -> str:
    return f"${cost:.4f}" if cost is not None else "n/a"


def format_vocabulary_report(stats: VocabularyExamineStats) -> str:
    """Render `VocabularyExamineStats` as a human-readable report. Format is
    left to the implementer, only that every listed number is present
    (mirrors `axial.names.format_names_report`'s own docstring)."""
    lines: list[str] = []

    for column in stats.columns:
        lines.append(
            f"{column.column}: {column.answered_count} answered value(s), "
            f"{column.distinct_count} distinct string(s), "
            f"{column.excluded_count} excluded (abstention/[]/empty)"
        )
        reduced_note = " (samples reduced: population smaller than propose+assign)" if column.reduced else ""
        lines.append(
            f"  propose sample {column.propose_sample_size}, "
            f"assign (held-out) sample {column.assign_sample_size}{reduced_note}"
        )

        if column.proposal_failed:
            lines.append(
                f"  PROPOSAL FAILED: {len(column.categories)} category(ies) proposed for "
                f"{column.propose_sample_size} answer(s) -- restated rather than categorised; "
                "assignment and the self-consistency check were skipped"
            )
        elif column.categories:
            lines.append(f"  {len(column.categories)} category(ies) proposed:")
            for category in column.categories:
                lines.append(
                    f"    - {category.name}: {category.gloss} "
                    f"({category.member_count} member(s), {category.source_count} source(s))"
                )
            if column.assignment_rate is not None:
                lines.append(
                    f"  assignment rate on held-out sample: {column.assignment_rate:.1%}"
                )
                lines.append(
                    f"  unanswered (no returned entry): {column.unanswered_count}, "
                    f'refused ("none"/out-of-scheme): {column.refused_count}'
                )
                lines.append(
                    f"  categories with {MIN_CATEGORY_SIZE}+ members: {column.categories_5plus} "
                    f"(of those, spanning 2+ sources: {column.categories_5plus_cross_source})"
                )
                lines.append(
                    "  largest category share (of the held-out sample): "
                    f"{column.largest_category_share:.1%}"
                )
            if column.agreement_rate is not None:
                lines.append(
                    f"  two-model agreement overall (subsample of "
                    f"{column.agreement_sample_size}): {column.agreement_rate:.1%}"
                )
                if column.agreement_where_assigned_rate is not None:
                    lines.append(
                        "  two-model agreement where the first model assigned a category "
                        f"(n={column.agreement_where_assigned_sample_size}): "
                        f"{column.agreement_where_assigned_rate:.1%}"
                    )
                else:
                    lines.append(
                        "  two-model agreement where the first model assigned a category: "
                        "not applicable (the first model assigned nothing in the subsample)"
                    )
        else:
            lines.append("  0 categories proposed -- these answers did not recur")

        lines.append(
            f"  model: {column.examine_model} ({column.examine_calls} call(s), "
            f"cost {_format_cost(column.examine_cost)}); "
            f"check model: {column.check_model} ({column.check_calls} call(s), "
            f"cost {_format_cost(column.check_cost)})"
        )
        lines.append("")

    return "\n".join(lines).rstrip("\n")


# ---------------------------------------------------------------------------
# Issue #806 (slice 02): the frozen scheme, and the assignment persisted
# against it.
#
# Slice 01 above PROPOSES a scheme from a sample and scores it on a disjoint
# sample, writing nothing. Everything below takes a scheme as an INPUT --
# committed to `config/vocabulary.yaml` by a person -- assigns the WHOLE
# column against it, and persists that assignment under `data/vocabulary/`.
# There is no proposal call here at all.
#
# Frozen is the point. Slice 01 measured the same prompt under the same
# model producing different granularity between runs (`mechanism` 36
# categories then 20), and a vocabulary that reshuffles on every build is
# not an index -- reconciling one build's categories against the next one's
# is name merging wearing a new coat, which is the cost this whole feature
# exists to escape.
#
# The persistence shape mirrors `axial.names`'s own fit-persistence pattern
# (`_write_fit_artifact`/`_read_fit_artifact`/`_manifest_reusable`), which
# `axial.argmap.build` already mirrored once for bag state (#677): a
# manifest recording exactly what a later run must match, written LAST so a
# directory without one was never a completed build, and a reusability
# check that reads the manifest before it opens the artifact at all.
#
# The pin is content-keyed over the rendered input, the convention merge and
# Gather use for their decision logs: it covers the answered values and
# nothing else, so an edited answer re-assigns and a model swap does not.
# The scheme version is carried BESIDE it rather than inside it, because the
# two failure modes differ -- a moved pin assigns the values that moved, a
# moved scheme version means the artifact and the config describe different
# vocabularies and must not be merged into one file.
#
# The vocabulary is a TREE (founder ruling, 2026-08-28). This slice builds
# depth 1 only, but nothing here assumes depth 1: a category carries a
# parent id, the scheme file nests, the version covers every level, and an
# assignment records the level it was made at, so adding depth 2 never
# re-asks depth 1 and needs no migration.
# ---------------------------------------------------------------------------

# The committed scheme file. Configuration a person writes, never an
# artifact a command derives.
DEFAULT_VOCABULARY_SCHEME_PATH = Path("config/vocabulary.yaml")

# Where the assignment lands: one directory per column, holding the
# manifest and the assignment records.
VOCABULARY_DIR = Path("data/vocabulary")
MANIFEST_FILENAME = "manifest.json"
ASSIGNMENTS_FILENAME = "assignments.jsonl"

# The top of the tree. A depth-1 category's parent id is null and its level
# is this; a depth-2 category would carry its parent's id and level 2.
ROOT_LEVEL = 1

# Twelve, the concurrency issue #806 budgets the `mechanism` build at
# (5,905 values, ~60 batches, ~20 minutes). The examine pass keeps
# `_assign_all`'s serial default -- four batches gain nothing from a pool.
DEFAULT_ASSIGN_WORKERS = 12


class VocabularySchemeError(Exception):
    """Raised when `config/vocabulary.yaml` cannot be read as a scheme for
    the column asked for: the file is absent, the column has no scheme, a
    category is missing an id/name/gloss, two categories share an id or a
    name, or the committed scheme is deeper than this slice assigns. Always
    names the column and the file, because the fix is always an edit to
    that file."""


class SchemeVersionMismatchError(Exception):
    """Raised when an existing artifact for a column was built against a
    different scheme version than `config/vocabulary.yaml` now holds.

    The build refuses rather than merging, and refuses rather than silently
    overwriting: two schemes in one file would leave a category id meaning
    one thing under some notes and another thing under others, which is
    exactly the property freezing the scheme exists to guarantee. Nothing
    is written and no model call is made. Re-assigning under the new
    version is a deliberate act -- pass `--force`, which moves the column's
    directory aside to a timestamped sibling (it is the only record of what
    each note was filed under, and it was paid for) and re-assigns the
    whole column under the new version."""

    def __init__(self, column: str, artifact_version: str | None, scheme_version: str, artifact_dir: Path) -> None:
        self.column = column
        self.artifact_version = artifact_version
        self.scheme_version = scheme_version
        self.artifact_dir = artifact_dir
        super().__init__(
            f"column {column!r} already has an assignment built against scheme version "
            f"{artifact_version!r}, but config now holds version {scheme_version!r} -- "
            f"refusing to mix two schemes in one artifact. Re-run with --force to set "
            f"{artifact_dir} aside to a timestamped sibling and re-assign the whole "
            "column under the new version."
        )


@dataclass(frozen=True)
class SchemeCategory:
    """One committed category. `id` is what the artifact and every
    downstream join record, and it never changes meaning under a note
    already filed against it. `name` and `gloss` are what the model reads
    when it assigns -- and the model answers with the NAME, which is why
    two categories may not share one. `parent_id` is `None` at depth 1 and
    the field exists anyway."""

    id: str
    name: str
    gloss: str
    parent_id: str | None
    level: int


@dataclass(frozen=True)
class ColumnScheme:
    """One column's whole category tree, flattened -- every node at every
    level, each carrying its own parent and level. `version` covers the
    WHOLE tree rather than a level of it, so adding depth 2 is a version
    bump and not a second versioning scheme."""

    column: str
    version: str
    categories: tuple[SchemeCategory, ...]

    @property
    def max_level(self) -> int:
        return max((category.level for category in self.categories), default=ROOT_LEVEL)

    def at_level(self, level: int) -> tuple[SchemeCategory, ...]:
        return tuple(category for category in self.categories if category.level == level)


@dataclass(frozen=True)
class CategoryCount:
    """One category's standing in the built column: how many of the
    column's answered values were filed under it, and how many distinct
    sources those values came from. Every committed category is reported,
    including one nothing was filed under -- an empty category is a
    finding, not a row to drop."""

    category_id: str
    name: str
    parent_id: str | None
    level: int
    member_count: int
    source_count: int


@dataclass(frozen=True)
class ColumnBuildResult:
    """What one column's build did. `reused` is `True` only when the whole
    artifact was left untouched -- the scheme version and the answers pin
    both matched a complete artifact already on disk, and zero model calls
    were made."""

    column: str
    scheme_version: str
    answers_pin: str
    artifact_dir: Path
    reused: bool
    forced_aside: Path | None
    answered_count: int
    excluded_count: int
    assigned_count: int
    refused_count: int
    out_of_scheme_count: int
    out_of_scheme_names: list[str]
    unanswered_count: int
    reused_assignment_count: int
    newly_assigned_count: int
    categories: list[CategoryCount]
    model: str
    calls: int
    cost: float | None

    @property
    def complete(self) -> bool:
        """A completed build has zero unanswered values."""
        return self.unanswered_count == 0


@dataclass(frozen=True)
class VocabularyBuildStats:
    columns: list[ColumnBuildResult]

    @property
    def complete(self) -> bool:
        return all(column.complete for column in self.columns)


# ---------------------------------------------------------------------------
# The scheme file
# ---------------------------------------------------------------------------


def _scheme_document(scheme_path: Path) -> dict[str, Any]:
    if not Path(scheme_path).is_file():
        raise VocabularySchemeError(
            f"no category scheme file at {scheme_path} -- the scheme is configuration a "
            "person commits, so create it before building a vocabulary"
        )
    with Path(scheme_path).open("r", encoding="utf-8") as handle:
        parsed = yaml.load(handle, Loader=SAFE_LOADER)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("columns"), dict):
        raise VocabularySchemeError(
            f"{scheme_path} does not hold a 'columns' mapping of column name to scheme"
        )
    return parsed


def scheme_columns(scheme_path: Path = DEFAULT_VOCABULARY_SCHEME_PATH) -> list[str]:
    """Every column `scheme_path` commits a scheme for, in file order. What
    `axial vocabulary build` builds when no `--columns` is given: adding a
    column to the frozen scheme file is what widens the build, so the
    column set is read from configuration rather than named in code."""
    return [str(column) for column in _scheme_document(scheme_path)["columns"]]


def _walk_categories(
    raw: Any, column: str, scheme_path: Path, parent_id: str | None, level: int
) -> list[SchemeCategory]:
    if not isinstance(raw, list):
        raise VocabularySchemeError(
            f"the scheme for column {column!r} in {scheme_path} has no 'categories' list"
        )
    categories: list[SchemeCategory] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise VocabularySchemeError(
                f"a category in column {column!r} ({scheme_path}) is not a mapping: {entry!r}"
            )
        fields = {}
        for field in ("id", "name", "gloss"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise VocabularySchemeError(
                    f"a category in column {column!r} ({scheme_path}) has no usable "
                    f"{field!r}: {entry!r}"
                )
            fields[field] = value.strip()
        categories.append(
            SchemeCategory(
                id=fields["id"],
                name=fields["name"],
                gloss=fields["gloss"],
                parent_id=parent_id,
                level=level,
            )
        )
        children = entry.get("children")
        if children:
            categories.extend(
                _walk_categories(children, column, scheme_path, fields["id"], level + 1)
            )
    return categories


def load_vocabulary_scheme(
    column: str, scheme_path: Path = DEFAULT_VOCABULARY_SCHEME_PATH
) -> ColumnScheme:
    """`column`'s committed category tree, flattened, from `scheme_path`.

    Raises `VocabularySchemeError` naming the column and the file when the
    column has no scheme, the version is missing, a category lacks an
    id/name/gloss, or two categories share an id or a name. The name check
    is not pedantry: the assign prompt renders names, the model answers
    with a name, and slice 01's own corrected run persisted all twenty
    `mechanism` categories under the identical name "Causal mechanism" --
    committed as-is, every assignment would have been ambiguous."""
    document = _scheme_document(scheme_path)
    columns = document["columns"]
    if column not in columns:
        raise VocabularySchemeError(
            f"{scheme_path} commits no category scheme for column {column!r} "
            f"(it has: {', '.join(sorted(str(key) for key in columns)) or 'none'}) -- "
            "which columns are worth committing is a person's read of "
            "`axial vocabulary examine`, never a rule in code"
        )
    raw = columns[column]
    if not isinstance(raw, dict):
        raise VocabularySchemeError(
            f"the scheme for column {column!r} in {scheme_path} is not a mapping"
        )
    version = raw.get("version")
    if not isinstance(version, str) or not version.strip():
        raise VocabularySchemeError(
            f"the scheme for column {column!r} in {scheme_path} has no 'version' string -- "
            "the version covers the whole tree and every artifact records the one it was "
            "built against"
        )

    categories = _walk_categories(raw.get("categories"), column, scheme_path, None, ROOT_LEVEL)

    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for category in categories:
        if category.id in seen_ids:
            raise VocabularySchemeError(
                f"column {column!r} in {scheme_path} has two categories with id "
                f"{category.id!r} -- an id is what every assignment is filed under and "
                "must identify exactly one category"
            )
        if category.name in seen_names:
            raise VocabularySchemeError(
                f"column {column!r} in {scheme_path} has two categories named "
                f"{category.name!r} -- the model assigns by name, so two categories "
                "sharing one cannot be told apart in a response"
            )
        seen_ids.add(category.id)
        seen_names.add(category.name)

    return ColumnScheme(column=column, version=version.strip(), categories=tuple(categories))


# ---------------------------------------------------------------------------
# The pin, the artifact, and reuse
# ---------------------------------------------------------------------------


def compute_answers_pin(population: Sequence[PopulationEntry]) -> str:
    """A sha256 digest (first 16 hex chars) over the rendered input this
    build assigns: every answered value with the note and list position it
    came from, sorted, and NOTHING else.

    Content-keyed like merge's and Gather's decision logs: an edited or
    added answer moves the pin and gets assigned; a model swap, a prompt
    tweak, a code change anywhere in the repo does not move it and re-asks
    nothing. Sorted rather than taken in read order so a renamed answer
    file, which changes nothing about the content, does not move it
    either."""
    rendered = sorted(
        [entry.chunk_id, entry.element_index, entry.value] for entry in population
    )
    canonical = json.dumps(rendered, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _load_json_or_none(path: Path) -> dict[str, Any] | None:
    """A tolerant JSON read: `None` when `path` does not exist or fails to
    parse -- either way this run cannot tell whether what is on disk is
    reusable, so it falls back to building. Same tolerance
    `axial.names._load_manifest` and `axial.argmap.build._load_json_or_none`
    already apply to their own manifests."""
    if not Path(path).is_file():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _manifest_reusable(
    manifest: dict[str, Any] | None, scheme_version: str, answers_pin: str
) -> bool:
    """Whether a persisted assignment's own manifest says it was built
    against exactly this scheme version and these answers, and that it
    finished. A `False` means the build reads the assignment records and
    works out what still has to be asked; a `True` means it opens nothing
    and makes no call.

    `complete` is part of the check, not decoration: an artifact with an
    unanswered value is a failed run, and reusing it would freeze the hole
    in place forever, since a hole is never written and so never matches an
    entry on a later run."""
    if not manifest:
        return False
    return (
        manifest.get("scheme_version") == scheme_version
        and manifest.get("answers_pin") == answers_pin
        and manifest.get("complete") is True
    )


def _assignment_key(record: Mapping[str, Any]) -> tuple[str, int, int]:
    return (
        str(record.get("chunk_id", "")),
        int(record.get("element_index", 0)),
        int(record.get("level", ROOT_LEVEL)),
    )


def _read_assignment_records(path: Path) -> list[dict[str, Any]]:
    """Every persisted assignment record under `path`, or `[]` when the
    file is absent. A torn final line is dropped rather than crashing the
    read: the value it named is simply asked about again."""
    if not Path(path).is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
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


def _write_assignment_records(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    """Persist the column's assignments, one JSON object per line, keys
    sorted. A record read back and written again round-trips to the same
    bytes, which is what lets an incremental build leave every assignment
    already on disk byte-identical."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Written LAST, after the assignments -- so a column directory without
    a readable manifest was never a completed build, the same ordering
    `axial.argmap.build` gives `map.json`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _record_for(
    entry: PopulationEntry,
    column: str,
    level: int,
    category_id: str | None,
    out_of_scheme: str | None = None,
) -> dict[str, Any]:
    """One assignment record. `out_of_scheme` carries the string the model
    answered with when that string named no committed category and was not
    `REFUSAL_TOKEN` -- and the key is written ONLY then, so every record
    that was assigned or genuinely refused keeps the bytes it had before
    this key existed and an artifact built earlier still round-trips
    unchanged."""
    record: dict[str, Any] = {
        "chunk_id": entry.chunk_id,
        "source_id": entry.source_id,
        "column": column,
        "element_index": entry.element_index,
        "level": level,
        "value": entry.value,
        "category_id": category_id,
        "refused": category_id is None and out_of_scheme is None,
    }
    if out_of_scheme is not None:
        record["out_of_scheme"] = out_of_scheme
    return record


def _category_counts(
    scheme: ColumnScheme, records: Sequence[Mapping[str, Any]]
) -> list[CategoryCount]:
    members: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for record in records:
        category_id = record.get("category_id")
        if isinstance(category_id, str):
            members[category_id].append(record)
    return [
        CategoryCount(
            category_id=category.id,
            name=category.name,
            parent_id=category.parent_id,
            level=category.level,
            member_count=len(members.get(category.id, [])),
            source_count=len({m.get("source_id", "") for m in members.get(category.id, [])}),
        )
        for category in scheme.categories
    ]


def _counts_from_manifest(manifest: Mapping[str, Any]) -> list[CategoryCount]:
    return [
        CategoryCount(
            category_id=str(entry.get("category_id", "")),
            name=str(entry.get("name", "")),
            parent_id=entry.get("parent_id"),
            level=int(entry.get("level", ROOT_LEVEL)),
            member_count=int(entry.get("member_count", 0)),
            source_count=int(entry.get("source_count", 0)),
        )
        for entry in manifest.get("categories", [])
        if isinstance(entry, dict)
    ]


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


def _build_column(
    client: LLMClient,
    column: str,
    scheme: ColumnScheme,
    records: Sequence[Mapping[str, Any]],
    vocabulary_dir: Path,
    workers: int,
    force: bool = False,
) -> ColumnBuildResult:
    population, excluded = read_column(records, column)
    answers_pin = compute_answers_pin(population)
    column_dir = Path(vocabulary_dir) / column
    manifest_path = column_dir / MANIFEST_FILENAME
    assignments_path = column_dir / ASSIGNMENTS_FILENAME

    # `--force`: the whole column re-assigns, whatever is on disk. The
    # previous artifact moves to a timestamped sibling rather than being
    # deleted -- it is the only record of what each note was filed under
    # and it was paid for, the same promise `axial map build --force` makes
    # about a paid ledger. Timestamped to the microsecond so two forced
    # runs, or two in one process, never overwrite each other.
    forced_aside: Path | None = None
    if force and column_dir.is_dir():
        forced_aside = column_dir.with_name(
            f"{column}.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
        )
        column_dir.replace(forced_aside)

    manifest = _load_json_or_none(manifest_path)
    model = client.model_for_pass(BUILD_PASS_NAME)

    if manifest is not None and manifest.get("scheme_version") != scheme.version:
        raise SchemeVersionMismatchError(
            column, manifest.get("scheme_version"), scheme.version, column_dir
        )

    if _manifest_reusable(manifest, scheme.version, answers_pin):
        assert manifest is not None
        return ColumnBuildResult(
            column=column,
            scheme_version=scheme.version,
            answers_pin=answers_pin,
            artifact_dir=column_dir,
            reused=True,
            forced_aside=forced_aside,
            answered_count=int(manifest.get("answered_count", 0)),
            excluded_count=int(manifest.get("excluded_count", 0)),
            assigned_count=int(manifest.get("assigned_count", 0)),
            refused_count=int(manifest.get("refused_count", 0)),
            out_of_scheme_count=int(manifest.get("out_of_scheme_count", 0)),
            out_of_scheme_names=[str(name) for name in manifest.get("out_of_scheme_names", [])],
            unanswered_count=int(manifest.get("unanswered_count", 0)),
            reused_assignment_count=int(manifest.get("answered_count", 0)),
            newly_assigned_count=0,
            categories=_counts_from_manifest(manifest),
            model=model,
            calls=0,
            cost=None,
        )

    existing = {
        _assignment_key(record): record
        for record in _read_assignment_records(assignments_path)
    }

    reused_records: list[dict[str, Any]] = []
    pending: list[PopulationEntry] = []
    for entry in population:
        prior = existing.get((entry.chunk_id, entry.element_index, ROOT_LEVEL))
        if prior is not None and prior.get("value") == entry.value:
            reused_records.append(prior)
        else:
            pending.append(entry)

    calls_before = client.calls_for_pass(BUILD_PASS_NAME)
    cost_before = client.cost_for_pass(BUILD_PASS_NAME)

    new_records: list[dict[str, Any]] = []
    unanswered = 0
    if pending:
        level_categories = scheme.at_level(ROOT_LEVEL)
        scheme_text = _scheme_text(
            [{"name": category.name, "gloss": category.gloss} for category in level_categories]
        )
        id_by_name = {category.name: category.id for category in level_categories}
        assignments = _assign_all(client, BUILD_PASS_NAME, scheme_text, pending, workers)
        for index, entry in enumerate(pending, start=1):
            if index not in assignments:
                # After `_validate_assign_batch_keys` this is unreachable in
                # a completed run -- a batch that did not answer about every
                # index it was asked about is re-asked, not accepted. The
                # count is kept and reported anyway, because slice 01's first
                # corpus run lost assignments exactly here and read 50.7%
                # where the truth was 88.5%. The value is left OUT of the
                # artifact rather than written as a null: a hole is not a
                # result, and an absent key is what makes the next run ask
                # about it again.
                unanswered += 1
                continue
            answer = assignments[index]
            category_id = id_by_name.get(answer)
            # A model that answered with a string naming no committed
            # category has not refused -- it has answered wrongly, and the
            # two must not read the same. A refusal says how well the
            # scheme fits the corpus, which is a thing a person decides
            # about; an unrecognised name (a wrong case, a truncation, a
            # hallucination) is a defect, and a persisted record satisfies
            # the next run's reuse check whatever it holds, so one that
            # passes as a refusal is paid for once and frozen forever.
            out_of_scheme = (
                answer
                if category_id is None and answer.casefold() != REFUSAL_TOKEN
                else None
            )
            new_records.append(
                _record_for(entry, column, ROOT_LEVEL, category_id, out_of_scheme)
            )

    calls = client.calls_for_pass(BUILD_PASS_NAME) - calls_before
    cost = _cost_delta(cost_before, client.cost_for_pass(BUILD_PASS_NAME))

    out_records = sorted(reused_records + new_records, key=_assignment_key)
    assigned_count = sum(1 for record in out_records if record.get("category_id") is not None)
    out_of_scheme_names = sorted(
        {str(record["out_of_scheme"]) for record in out_records if record.get("out_of_scheme")}
    )
    out_of_scheme_count = sum(1 for record in out_records if record.get("out_of_scheme"))
    refused_count = len(out_records) - assigned_count - out_of_scheme_count
    categories = _category_counts(scheme, out_records)

    _write_assignment_records(assignments_path, out_records)
    _write_manifest(
        manifest_path,
        {
            "column": column,
            "scheme_version": scheme.version,
            "answers_pin": answers_pin,
            "max_level": scheme.max_level,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "answered_count": len(population),
            "excluded_count": excluded,
            "assigned_count": assigned_count,
            "refused_count": refused_count,
            "out_of_scheme_count": out_of_scheme_count,
            "out_of_scheme_names": out_of_scheme_names,
            "unanswered_count": unanswered,
            "complete": unanswered == 0,
            "categories": [
                {
                    "category_id": count.category_id,
                    "name": count.name,
                    "parent_id": count.parent_id,
                    "level": count.level,
                    "member_count": count.member_count,
                    "source_count": count.source_count,
                }
                for count in categories
            ],
        },
    )

    return ColumnBuildResult(
        column=column,
        scheme_version=scheme.version,
        answers_pin=answers_pin,
        artifact_dir=column_dir,
        reused=False,
        forced_aside=forced_aside,
        answered_count=len(population),
        excluded_count=excluded,
        assigned_count=assigned_count,
        refused_count=refused_count,
        out_of_scheme_count=out_of_scheme_count,
        out_of_scheme_names=out_of_scheme_names,
        unanswered_count=unanswered,
        reused_assignment_count=len(reused_records),
        newly_assigned_count=len(new_records),
        categories=categories,
        model=model,
        calls=calls,
        cost=cost,
    )


def build_vocabulary(
    answers_dir: Path | None = None,
    columns: Sequence[str] | None = None,
    scheme_path: Path = DEFAULT_VOCABULARY_SCHEME_PATH,
    vocabulary_dir: Path | None = None,
    workers: int = DEFAULT_ASSIGN_WORKERS,
    force: bool = False,
    config_path: Path = DEFAULT_PIPELINE_CONFIG_PATH,
    client: LLMClient | None = None,
) -> VocabularyBuildStats:
    """Assign every answered value in each of `columns` against that
    column's frozen scheme in `scheme_path`, and persist the assignment
    under `vocabulary_dir/<column>/`.

    `columns` defaults to every column the scheme file commits a scheme for
    -- widening the build is an edit to that file, not to this code.

    A run over an unchanged corpus and an unchanged scheme re-assigns
    nothing and makes zero model calls. A run after new answers land
    assigns only the values that are new or changed, and leaves every
    assignment already on disk byte-identical. A run against a different
    scheme version refuses (`SchemeVersionMismatchError`) rather than
    mixing two vocabularies in one artifact.

    `force` re-assigns each column whatever is on disk, moving the previous
    artifact aside to a timestamped sibling first. It is the deliberate act
    a scheme edit needs, and the only way past the version refusal -- the
    safe default is kept.

    Every scheme is loaded and checked BEFORE any answer is read or any
    call is made, so a scheme error costs nothing -- the same rule
    `examine_vocabulary` applies to `SelfConsistencyError`.

    `client` defaults to `axial.llm.get_client()`, the injection seam
    `examine_vocabulary`, `axial.argmap.build.run_map_build` and
    `axial.gather.run_gather` already expose, so a unit test never makes a
    network call. Assignment runs under `BUILD_PASS_NAME`, pinned in
    `config/pipeline.yaml` to the same tier the examine pass uses: the same
    call against the same kind of scheme, so the tier is right, but its own
    cost line, because a build spends an order of magnitude more than the
    sample pass it borrows its path from."""
    if columns is None:
        columns = scheme_columns(scheme_path)

    schemes = {column: load_vocabulary_scheme(column, scheme_path) for column in columns}
    for column, scheme in schemes.items():
        if scheme.max_level > ROOT_LEVEL:
            raise VocabularySchemeError(
                f"the scheme for column {column!r} in {scheme_path} is {scheme.max_level} "
                f"levels deep, and this build assigns level {ROOT_LEVEL} only (issue #806 "
                "ships depth 1) -- assigning its roots and reporting success would "
                "silently drop the rest of the committed scheme"
            )

    if answers_dir is None:
        answers_dir = _default_answers_dir(config_path)
    if vocabulary_dir is None:
        vocabulary_dir = VOCABULARY_DIR
    records = load_answer_records(Path(answers_dir))

    if client is None:
        client = get_client(config_path)

    return VocabularyBuildStats(
        columns=[
            _build_column(
                client, column, schemes[column], records, Path(vocabulary_dir), workers, force
            )
            for column in columns
        ]
    )


def format_vocabulary_build_report(stats: VocabularyBuildStats) -> str:
    """Render `VocabularyBuildStats` as a human-readable report: per column,
    what was assigned, what was refused, what was reused rather than
    rebuilt, and each category's member and distinct-source counts."""
    lines: list[str] = []

    for column in stats.columns:
        lines.append(
            f"{column.column}: {column.answered_count} answered value(s), "
            f"{column.excluded_count} excluded (abstention/[]/empty)"
        )
        lines.append(
            f"  scheme {column.scheme_version} ({len(column.categories)} category(ies), "
            f"depth {max((c.level for c in column.categories), default=ROOT_LEVEL)}), "
            f"answers pin {column.answers_pin}"
        )
        lines.append(f"  artifact: {column.artifact_dir}")
        if column.forced_aside is not None:
            lines.append(
                f"  --force: the previous artifact was set aside to {column.forced_aside} "
                "(never deleted -- it was paid for) and the whole column re-assigned"
            )
        if column.reused:
            lines.append(
                "  REUSED: the scheme version and the answers pin are both unchanged -- "
                "0 model call(s), nothing re-assigned"
            )
        else:
            lines.append(
                f"  built: {column.newly_assigned_count} newly assigned, "
                f"{column.reused_assignment_count} reused from the previous build"
            )
        lines.append(
            f"  {column.assigned_count} assigned to a category, "
            f'{column.refused_count} refused ("none"), '
            f"{column.out_of_scheme_count} out-of-scheme, "
            f"{column.unanswered_count} unanswered (never returned)"
        )
        if column.out_of_scheme_count:
            lines.append(
                f"  OUT OF SCHEME: {column.out_of_scheme_count} value(s) came back under a "
                "name no committed category carries -- a defect (a wrong case, a truncation, "
                "a hallucination), not a fact about how well the scheme fits: "
                + ", ".join(repr(name) for name in column.out_of_scheme_names)
            )
        if not column.complete:
            lines.append(
                f"  INCOMPLETE: {column.unanswered_count} value(s) the model never answered "
                "about are absent from the artifact rather than written as holes -- an "
                "unanswered value is a failed run, not a result; run the build again"
            )
        if column.categories:
            lines.append("  categories, by member count:")
            for category in sorted(
                column.categories, key=lambda c: (-c.member_count, c.category_id)
            ):
                lines.append(
                    f"    - {category.category_id} ({category.name}): "
                    f"{category.member_count} member(s), {category.source_count} source(s)"
                )
        lines.append(
            f"  model: {column.model} ({column.calls} call(s), cost {_format_cost(column.cost)})"
        )
        lines.append("")

    return "\n".join(lines).rstrip("\n")
