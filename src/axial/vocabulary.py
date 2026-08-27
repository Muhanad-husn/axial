"""The derived-vocabulary categorisation pass (issue #805, slice 01 of
`plans/derived-vocabulary/`): a read-only report over the twelve sentence-
valued answer columns -- `about`, `claim`, `move`, `ranges_over`,
`stops_holding`, `position`, `arguing_against`, `mechanism`, `evidence`,
`comparison`, `concedes`, `assumes`. Every note answers seventeen questions;
three repeat often enough to join on and are out of scope here (`names`,
`uses`, `defines`); these twelve hold near-unique sentences instead, so
nothing joins on them today. This module asks whether they group by meaning
anyway -- not by embedding distance, which measures wording (rejected here
2026-08-27 after a run on the real corpus, see the plan's own status log),
but by having a model read a random sample and name the recurring kinds,
then testing that scheme against a disjoint sample it has never seen.

This is the go/no-go for the whole feature (`plans/derived-vocabulary/
README.md`). It reads `data/answers/` and writes nothing -- no artifact, no
category ids, no reuse across runs, no corpus pin moved. Persisting a
category scheme is slice 02, gated on this report's own numbers.

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
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from axial.interrogate import _default_answers_dir
from axial.llm import LLMClient, get_client
from axial.model_json import complete_json, parse_model_json
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

# The pass names `config/pipeline.yaml`'s `llm.model_by_pass` keys off of,
# mirroring `axial.argmap.build.PASS_NAME`'s own local (not `axial.llm`-
# centralised) convention: a pass name lives with the module that owns the
# pass, and only the TIER it routes to (`axial.llm.PRODUCTION_VOCABULARY_
# EXAMINE_TIER`/`..._CHECK_TIER`) needs registering centrally.
EXAMINE_PASS_NAME = "vocabulary_examine"
CHECK_PASS_NAME = "vocabulary_examine_check"

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
    per list element, so several entries can share a `chunk_id`."""

    value: str
    chunk_id: str
    source_id: str


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


def _assign_batch(
    client: LLMClient,
    pass_name: str,
    scheme_text: str,
    batch: Sequence[PopulationEntry],
    start: int,
) -> dict[int, str]:
    numbered = "\n".join(f"{start + i + 1}. {entry.value}" for i, entry in enumerate(batch))
    prompt = ASSIGN_PROMPT.format(n=len(batch), categories=scheme_text, values=numbered)
    raw = complete_json(client, prompt, pass_name=pass_name, validate=parse_assign_response)
    return parse_assign_response(raw)


def _assign_all(
    client: LLMClient,
    pass_name: str,
    scheme_text: str,
    sample: Sequence[PopulationEntry],
) -> dict[int, str]:
    """Assign the whole of `sample` against `scheme_text`, in `BATCH_SIZE`
    batches, numbered globally (1-based, continuing across batches) so a
    caller can compare this pass's assignment for index `i` against another
    pass's assignment for the same index -- what the self-consistency check
    does."""
    assignments: dict[int, str] = {}
    for start in range(0, len(sample), BATCH_SIZE):
        batch = sample[start : start + BATCH_SIZE]
        assignments.update(_assign_batch(client, pass_name, scheme_text, batch, start))
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
    if before is None or after is None:
        return None
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
        unassigned = 0
        for index, entry in enumerate(assign_sample, start=1):
            label = assignments.get(index, "")
            if label not in category_names:
                unassigned += 1
            else:
                members[label].append(entry)

        hit = len(assign_sample) - unassigned
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
                    f"  categories with {MIN_CATEGORY_SIZE}+ members: {column.categories_5plus} "
                    f"(of those, spanning 2+ sources: {column.categories_5plus_cross_source})"
                )
                lines.append(f"  largest category share: {column.largest_category_share:.1%}")
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
