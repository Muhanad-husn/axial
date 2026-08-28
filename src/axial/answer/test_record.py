"""Inner unit tests for `axial.answer.record.build_record`'s `cost` field
(§7.14, issue #363), plus its `evidence` field (§7.3, issue #545) -- both
small enough to share this file rather than each earning its own, co-located
under src/axial/answer/, mirroring src/axial/answer/test_source_usage.py's
own layout for this module."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

import axial.answer.record as record_module
from axial.analyze.synthesis import Claim, CounterPositionGenerationFailedError
from axial.answer.record import (
    KNOWN_ARMS,
    MAP_ARM,
    MAP_VOCAB_ARM,
    NAME_ARM,
    UnknownArmError,
    build_record,
)
from axial.argmap.ask import AskResult, CorridorPosition, LandedPosition
from axial.argmap.vocabulary_join import CategoryReach, VocabularyJoinResult, VocabularyPosition
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult
from axial.llm import (
    INTERROGATE_PASS_NAME,
    PRICE_TABLE_USD_PER_1K,
    SYNTHESIZE_PASS_NAME,
    StubLLMClient,
    estimate_cost,
)


class _FakeUsageClient(StubLLMClient):
    """A minimal `LLMClient` double: `build_record` only ever calls
    `usage_for_pass`/`cost_for_pass` on the client it is given -- never a
    completion method -- so this double implements exactly that.
    `model_for_pass` is answered too (a fixed string, never asserted on by
    the existing `cost`-field tests below): `build_record` consults it only
    when `counter_position_result.model_called` is `True`, which every
    existing test here never reaches (each passes `claims=[]`, uncontested).

    `cost_by_pass` (issue #740) defaults to empty -- every pre-#740 test
    below constructs this double without it, so `cost_for_pass` answers
    `None` for every pass exactly like a client that never saw a
    provider-reported cost, and `usage_and_cost_by_pass` falls back to
    `estimate_cost` unchanged."""

    def __init__(
        self,
        usage_by_pass: dict[str, dict[str, int] | None],
        cost_by_pass: dict[str, float | None] | None = None,
    ) -> None:
        super().__init__()
        self._usage_by_pass = usage_by_pass
        self._cost_by_pass = cost_by_pass or {}

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return self._usage_by_pass.get(pass_name)

    def cost_for_pass(self, pass_name: str | None = None) -> float | None:
        return self._cost_by_pass.get(pass_name)

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "test-double-model"


def _brief(*, weights: dict[str, float] | None = None) -> Brief:
    return Brief(
        brief_id="deadbeefcafef00d",
        case="Syria",
        request="How did order change?",
        weights=weights or {},
    )


def _interrogation_result() -> InterrogationResult:
    # `claims`/`trajectory` passed to `build_record` below are empty either
    # way -- disposition value has no bearing on the `cost` field this
    # module tests, so a plain `proceed` keeps the fixture unconfusing.
    return InterrogationResult(
        premises_found=[], bounds_applied=[], refusal=None, disposition="proceed"
    )


def _build(
    model_by_pass: dict[str, str], client: _FakeUsageClient, *, brief: Brief | None = None
) -> dict:
    return build_record(
        brief if brief is not None else _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        lens="default",
        claims=[],
        trajectory=[],
        model_by_pass=model_by_pass,
        client=client,
    )


def test_cost_is_computed_per_pass_and_summed_to_a_total_for_priced_models():
    model_by_pass = {
        "interrogate": "deepseek/deepseek-v4-pro",
        "synthesize": "z-ai/glm-5.2",
    }
    client = _FakeUsageClient(
        {
            "interrogate": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            "synthesize": {"prompt_tokens": 2000, "completion_tokens": 800, "total_tokens": 2800},
        }
    )

    record = _build(model_by_pass, client)

    cost = record["cost"]
    expected_interrogate = estimate_cost("deepseek/deepseek-v4-pro", 1000, 500)
    expected_synthesize = estimate_cost("z-ai/glm-5.2", 2000, 800)
    assert cost["by_pass"]["interrogate"]["usd"] == expected_interrogate
    assert cost["by_pass"]["interrogate"]["prompt_tokens"] == 1000
    assert cost["by_pass"]["interrogate"]["completion_tokens"] == 500
    assert cost["by_pass"]["interrogate"]["total_tokens"] == 1500
    assert cost["by_pass"]["synthesize"]["usd"] == expected_synthesize
    assert cost["total_usd"] == expected_interrogate + expected_synthesize
    assert cost["total_usd"] > 0


def test_cost_is_null_not_zero_for_an_unpriced_model_and_the_run_still_succeeds():
    """Acceptance criterion 3 (issue #363): an unpriced model id never
    raises and never reports zero -- it reports null, distinct from a real
    zero-cost result."""
    model_by_pass = {"synthesize": "some-vendor/never-priced-model"}
    client = _FakeUsageClient(
        {"synthesize": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700}}
    )
    assert "some-vendor/never-priced-model" not in PRICE_TABLE_USD_PER_1K

    record = _build(model_by_pass, client)

    entry = record["cost"]["by_pass"]["synthesize"]
    assert entry["usd"] is None
    assert entry["prompt_tokens"] == 500  # tokens are still captured
    # total_usd is null too: this is the ONLY pass, and it's unpriced.
    assert record["cost"]["total_usd"] is None


def test_total_usd_sums_known_costs_even_when_one_pass_is_unpriced():
    """A mixed run (one priced pass, one unpriced pass) still reports a
    real total from what IS known, rather than nulling out the whole
    figure over one unpriced component."""
    model_by_pass = {
        "interrogate": "deepseek/deepseek-v4-pro",
        "synthesize": "some-vendor/never-priced-model",
    }
    client = _FakeUsageClient(
        {
            "interrogate": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            "synthesize": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
        }
    )

    record = _build(model_by_pass, client)

    assert record["cost"]["by_pass"]["synthesize"]["usd"] is None
    expected = estimate_cost("deepseek/deepseek-v4-pro", 1000, 500)
    assert record["cost"]["total_usd"] == expected


def test_cost_defaults_to_zero_tokens_and_null_usd_when_the_client_reports_no_usage():
    """A pass the client never captured usage for (e.g. a malformed real
    response, or a test double with nothing to report) contributes zero
    token counts and a null cost -- never a crash."""
    model_by_pass = {"interrogate": "deepseek/deepseek-v4-pro"}
    client = _FakeUsageClient({})

    record = _build(model_by_pass, client)

    entry = record["cost"]["by_pass"]["interrogate"]
    assert entry == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "usd": None,
    }
    assert record["cost"]["total_usd"] is None


def test_cost_prefers_the_providers_real_charge_over_the_price_table_estimate():
    """Issue #740: when the client's `cost_for_pass` reports a real number,
    that IS `usd` -- not `estimate_cost`'s price-table figure. The two are
    deliberately far apart here so this can only pass for the right reason
    (the estimate for this usage is on the order of $0.0013, nowhere near
    the provider's reported $9.99)."""
    model_by_pass = {"interrogate": "deepseek/deepseek-v4-pro"}
    client = _FakeUsageClient(
        {"interrogate": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}},
        cost_by_pass={"interrogate": 9.99},
    )
    estimate = estimate_cost("deepseek/deepseek-v4-pro", 1000, 500)
    assert estimate is not None
    assert abs(estimate - 9.99) > 1.0

    record = _build(model_by_pass, client)

    assert record["cost"]["by_pass"]["interrogate"]["usd"] == 9.99
    assert record["cost"]["total_usd"] == 9.99


def test_cost_falls_back_to_the_estimate_when_the_provider_reports_no_cost():
    """The provider-cost preference (#740) is a preference, not a
    requirement: a client whose `cost_for_pass` is `None` for a pass still
    gets `estimate_cost`'s price-table figure, unchanged from before #740."""
    model_by_pass = {"interrogate": "deepseek/deepseek-v4-pro"}
    client = _FakeUsageClient(
        {"interrogate": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500}},
        cost_by_pass={},
    )
    expected = estimate_cost("deepseek/deepseek-v4-pro", 1000, 500)

    record = _build(model_by_pass, client)

    assert record["cost"]["by_pass"]["interrogate"]["usd"] == expected


def test_cost_is_null_when_both_provider_and_price_table_are_silent():
    """Both sources absent (#740's third bar item) -- `usd` stays `null`,
    and a second, priced pass in the same run still contributes to
    `total_usd`."""
    model_by_pass = {
        "interrogate": "some-vendor/never-priced-model",
        "synthesize": "deepseek/deepseek-v4-pro",
    }
    client = _FakeUsageClient(
        {
            "interrogate": {"prompt_tokens": 500, "completion_tokens": 200, "total_tokens": 700},
            "synthesize": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
        },
        cost_by_pass={"synthesize": 3.5},
    )

    record = _build(model_by_pass, client)

    assert record["cost"]["by_pass"]["interrogate"]["usd"] is None
    assert record["cost"]["by_pass"]["synthesize"]["usd"] == 3.5
    assert record["cost"]["total_usd"] == 3.5


def test_evidence_field_defaults_to_zero_when_the_caller_passes_none():
    """A caller that omits `evidence_assembled_count`/`evidence_composed_
    count` -- `run_brief` on a `refuse` disposition, where stage 3/4 never
    ran -- still gets the field present and non-nullable, at 0/0, mirroring
    `claims`/`trajectory` defaulting empty on that same path."""
    record = _build({"interrogate": "deepseek/deepseek-v4-pro"}, _FakeUsageClient({}))

    assert record["evidence"] == {"assembled_count": 0, "composed_count": 0}


def test_evidence_field_carries_the_callers_counts_through_unchanged():
    """`build_record` neither recomputes nor validates the two counts against
    `claims`/`trajectory` -- it carries what the caller (`run_brief`, from
    `EvidenceSet.chunk_ids`/`ClaimGraph.evidence_composed_count`) already
    computed, the same pass-through `model_by_pass` gets."""
    record = build_record(
        _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        lens="default",
        claims=[],
        trajectory=[],
        model_by_pass={"interrogate": "deepseek/deepseek-v4-pro"},
        client=_FakeUsageClient({}),
        evidence_assembled_count=506,
        evidence_composed_count=146,
    )

    assert record["evidence"] == {"assembled_count": 506, "composed_count": 146}


# -- issue #534: `session_id` is an additive §7.3 field --


def test_session_id_defaults_to_none_for_a_plain_brief_run():
    record = _build({"interrogate": "deepseek/deepseek-v4-pro"}, _FakeUsageClient({}))

    assert record["session_id"] is None


def test_session_id_is_carried_through_verbatim_when_given():
    record = build_record(
        _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        lens="default",
        claims=[],
        trajectory=[],
        model_by_pass={"interrogate": "deepseek/deepseek-v4-pro"},
        client=_FakeUsageClient({}),
        session_id="a-session-id",
    )

    assert record["session_id"] == "a-session-id"


# -- issue #558: a counter-position GENERATION failure must not discard the run --


def test_a_counter_position_generation_failure_still_persists_the_record(monkeypatch):
    """Regression for the real loss: interrogation, retrieval and synthesis
    had all already succeeded when a live run's counter-position generation
    call raised, and because nothing caught it, NOTHING was persisted --
    every earlier stage's paid work was thrown away with it. `build_record`
    must catch the raise and still return a full record carrying the
    already-computed claims, with `counter_position` marked failed and its
    reason -- never silently laundered into a `corpus_one_sided` disclosure,
    which would misattribute a bug to a finding about the corpus."""
    monkeypatch.setattr(
        record_module,
        "generate_counter_position",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            CounterPositionGenerationFailedError("counter-position generation call failed: boom")
        ),
    )
    claims = [
        Claim(
            claim_id="c1",
            text="A claim that already made it through synthesis.",
            kind="c",
            grounds=[],
            confidence="low",
            names_touched=[],
        )
    ]

    record = build_record(
        _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        lens="default",
        claims=claims,
        trajectory=[],
        model_by_pass={"interrogate": "deepseek/deepseek-v4-pro"},
        client=_FakeUsageClient({}),
    )

    # The already-computed claim survived -- this is the whole point.
    assert record["claims"] == [
        {
            "claim_id": "c1",
            "text": "A claim that already made it through synthesis.",
            "kind": "c",
            "grounds": [],
            "confidence": "low",
            "names_touched": [],
        }
    ]
    counter_position = record["counter_position"]
    assert counter_position["failed"] is True
    assert "boom" in counter_position["failure_reason"]
    # Never laundered into either legitimate §7.8 outcome.
    assert counter_position["present"] is False
    assert counter_position["corpus_one_sided"] is False
    # A real call was attempted (contested is the only way this path is ever
    # reached), so its pass name still belongs in model_by_pass/cost.
    assert "counter_position_generate" in record["model_by_pass"]


# --- issue #639: weights ride the record, verbatim and disclosed twice -----


def test_brief_dict_carries_weights_verbatim():
    client = _FakeUsageClient({})
    brief = _brief(weights={"beshara-2011": 0.1})

    record = _build({}, client, brief=brief)

    assert record["brief"]["weights"] == {"beshara-2011": 0.1}


def test_brief_dict_carries_an_empty_weights_dict_when_none_were_supplied():
    client = _FakeUsageClient({})

    record = _build({}, client)

    assert record["brief"]["weights"] == {}


def test_source_usage_discloses_the_same_weights_beside_its_own_effect():
    """The disclosure this issue is built around (§7.13): the instruction
    and its effect live in one place. `source_usage` reads `record["brief"]
    ["weights"]`, which `build_record` has already assembled by the time it
    calls `compute_source_usage` -- so the two never drift apart."""
    client = _FakeUsageClient({})
    brief = _brief(weights={"beshara-2011": 0.1})

    record = _build({}, client, brief=brief)

    assert record["source_usage"]["weights"] == record["brief"]["weights"]
    assert record["source_usage"]["weights"] == {"beshara-2011": 0.1}


# --- issue #649: the intake fork-check's own disclosure ---------------------


def test_intake_fork_defaults_to_the_honest_nothing_measured_shape():
    """Every caller before issue #649 (and every other test in this file)
    passes no `fork_result` at all -- `build_record` must still assemble a
    complete, honest `intake_fork` block, not a missing key."""
    client = _FakeUsageClient({})

    record = _build({}, client)

    assert record["intake_fork"] == {
        "measured": False,
        "is_fork": False,
        "failed": None,
        "concept": None,
        "kind": None,
        "question": None,
        "options": [],
        "answer": None,
        "effect": None,
    }


def test_intake_fork_discloses_a_found_and_answered_fork():
    from axial.brief.fork import ForkAnswer, ForkCheckResult, ForkOption

    client = _FakeUsageClient({})
    fork_result = ForkCheckResult(
        is_fork=True,
        concept="Syria",
        kind="source_imbalance",
        question="78% of this is one 2021 monograph -- background only, or full voices?",
        options=(
            ForkOption(
                label="background only",
                drop_source_ids=("vignal-2021",),
                per_source_cap=2,
                guidance="treat vignal-2021 as background",
            ),
        ),
    )
    fork_answer = ForkAnswer(option="background only")
    fork_effect = {"notes_before": 10, "notes_after": 4, "sources_before": 3, "sources_after": 2}

    record = build_record(
        _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        lens="default",
        claims=[],
        trajectory=[],
        model_by_pass={},
        client=client,
        fork_result=fork_result,
        fork_answer=fork_answer,
        fork_effect=fork_effect,
    )

    assert record["intake_fork"]["measured"] is True
    assert record["intake_fork"]["is_fork"] is True
    assert record["intake_fork"]["concept"] == "Syria"
    assert record["intake_fork"]["question"].startswith("78% of this")
    assert record["intake_fork"]["options"] == [
        {
            "label": "background only",
            "drop_source_ids": ["vignal-2021"],
            "per_source_cap": 2,
            "guidance": "treat vignal-2021 as background",
        }
    ]
    assert record["intake_fork"]["answer"] == {"option": "background only", "free_text": None}
    assert record["intake_fork"]["effect"] == fork_effect


def test_intake_fork_discloses_a_found_but_unanswered_fork_in_batch_mode():
    """A batch run (`axial brief run`/`smoke`/`sweep`) with no `on_fork`
    callback and no pre-supplied `brief.fork_answer` (issue #649's own
    acceptance bar: never guess, never block)."""
    from axial.brief.fork import ForkCheckResult

    client = _FakeUsageClient({})
    fork_result = ForkCheckResult(
        is_fork=True, concept="Syria", kind="source_imbalance", question="q", options=()
    )

    record = build_record(
        _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        lens="default",
        claims=[],
        trajectory=[],
        model_by_pass={},
        client=client,
        fork_result=fork_result,
        fork_answer=None,
        fork_effect=None,
    )

    assert record["intake_fork"]["is_fork"] is True
    assert record["intake_fork"]["answer"] is None
    assert record["intake_fork"]["effect"] is None


def test_brief_dict_carries_fork_answer_verbatim():
    client = _FakeUsageClient({})
    brief = Brief(
        brief_id="deadbeefcafef00d",
        case="Syria",
        request="How did order change?",
        fork_answer={"option": "background only", "free_text": None},
    )

    record = _build({}, client, brief=brief)

    assert record["brief"]["fork_answer"] == {"option": "background only", "free_text": None}


def test_brief_dict_carries_none_fork_answer_when_none_supplied():
    client = _FakeUsageClient({})

    record = _build({}, client)

    assert record["brief"]["fork_answer"] is None


# --- issue #750: the declared decline policy's own walk disclosure ----------


def _hinnebusch_fork():
    from axial.brief.fork import ForkCheckResult, ForkOption

    return ForkCheckResult(
        is_fork=True,
        concept="Ba'th Party",
        kind="temporal_role",
        question=(
            "Should retrieval treat Hinnebusch (1990) as a witness to pre-coup roots "
            "and later sources as witnesses to consequences, reading both eras as "
            "complementary evidence of change, or would you prefer to cap "
            "Hinnebusch's notes to prevent its dominant voice from overshadowing the "
            "later witnesses?"
        ),
        options=(
            ForkOption(label="keep all, assign temporal roles"),
            ForkOption(label="cap the dominant 1990 source", per_source_cap=80),
            ForkOption(
                label="exclude the dominant 1990 source", drop_source_ids=("hinnebusch-1990-x",)
            ),
        ),
    )


def test_fork_declined_message_never_ends_in_a_question():
    from axial.answer.record import _fork_declined_message

    message = _fork_declined_message(_hinnebusch_fork())

    assert not message.rstrip().endswith("?")


def test_fork_declined_message_discloses_concept_options_and_policy():
    from axial.answer.record import _fork_declined_message

    message = _fork_declined_message(_hinnebusch_fork())

    # The imbalance measured: which concept, and its shape.
    assert "Ba'th Party" in message
    assert "period" in message
    # The options that were available, by label.
    assert "keep all, assign temporal roles" in message
    assert "cap the dominant 1990 source" in message
    assert "exclude the dominant 1990 source" in message
    # That the service declined under its declared policy, and the run
    # proceeded unconstrained.
    assert "declines" in message
    assert "unconstrained" in message


def test_fork_declined_message_never_quotes_the_models_own_question_text():
    from axial.answer.record import _fork_declined_message

    message = _fork_declined_message(_hinnebusch_fork())

    assert "or would you prefer" not in message


def test_fork_disclosure_message_declines_with_no_answering_mechanism():
    """The service worker, and every batch caller with no pre-supplied
    `brief.fork_answer` (`axial brief run`/`smoke`/`sweep`), have neither
    an `on_fork` callback nor an answer on file -- the declared policy's
    disclosure applies."""
    from axial.answer.record import _fork_declined_message, _fork_disclosure_message

    fork = _hinnebusch_fork()

    message = _fork_disclosure_message(fork, fork_answer_supplied=False, has_on_fork=False)

    assert message == _fork_declined_message(fork)


def test_fork_disclosure_message_unchanged_when_axial_ask_can_prompt():
    """`axial ask` passes `on_fork` -- its interactive path is unchanged by
    this issue: the walk still shows the model's own question, which
    `_fork_prompt` (src/axial/cli.py) then asks live."""
    from axial.answer.record import _fork_disclosure_message

    fork = _hinnebusch_fork()

    message = _fork_disclosure_message(fork, fork_answer_supplied=False, has_on_fork=True)

    assert message == f"a clarifying question was found: {fork.question}"


def test_fork_disclosure_message_unchanged_when_a_batch_answer_is_on_file():
    """A batch run with `brief.fork_answer` already supplied (§7.1) is a
    real, pre-known answer, not a decline -- unchanged by this issue."""
    from axial.answer.record import _fork_disclosure_message

    fork = _hinnebusch_fork()

    message = _fork_disclosure_message(fork, fork_answer_supplied=True, has_on_fork=False)

    assert message == f"a clarifying question was found: {fork.question}"


# ---------------------------------------------------------------------------
# `_map_retrieval_to_dict`'s own `vocabulary` block, and `run_brief`'s named
# `arm` (issue #807, plans/derived-vocabulary/03-two-notes-meet-at-a-shared-
# group.md). `run_map_ask_for_brief` is monkeypatched throughout -- the same
# convention `tests/analysis/test_argmap_corridor.py` already uses for
# `run_brief(use_map=True)` -- so these tests prove the WIRING (the record
# shape, the arm precedence, the empty trajectory, `UnknownArmError` failing
# fast). The join itself, computed for real against an encoder-free fixture
# map and vocabulary artifact, is proven in `src/axial/argmap/test_ask.py`.
# ---------------------------------------------------------------------------


def _vocab_brief() -> Brief:
    return Brief(brief_id="vocab_wiring_001", case="A case.", request="A question?")


def _chunk_frontmatter(chunk_id: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "section": "Synthetic Section",
        "chunk_text": f"SENTINEL_{chunk_id}: synthetic prose.",
        "source_meta": {
            "author": "A. Synthetic Author",
            "title": "A Synthetic Fixture Source",
            "date": 2021,
            "thesis": "Synthetic thesis.",
            "scope": "Synthetic scope.",
        },
        "frame_version": "0.1",
        "answers": {"claim": f"Claim of {chunk_id}.", "move": "stating a mechanism"},
    }


def _write_vault(root: Path, chunk_ids: list[str]) -> Path:
    prose_dir = root / "vault" / "prose"
    prose_dir.mkdir(parents=True, exist_ok=True)
    for chunk_id in chunk_ids:
        frontmatter = _chunk_frontmatter(chunk_id)
        text = "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\nBody.\n"
        (prose_dir / f"{chunk_id}.md").write_text(text, encoding="utf-8")
    return root / "vault"


class _ArmScriptedClient(StubLLMClient):
    """`interrogate` always proceeds and `synthesize` cites whatever the
    test wires in; `decompose_brief` is never called here because
    `run_map_ask_for_brief` itself is monkeypatched below (module comment)
    -- a call to it would be a fixture bug, so it raises rather than
    returning a plausible-looking response that would mask one."""

    def __init__(self, synthesize_response: str) -> None:
        super().__init__()
        self._synthesize_response = synthesize_response

    def complete(self, prompt: str, pass_name: str | None = None) -> str:
        if pass_name == INTERROGATE_PASS_NAME:
            return json.dumps({"premises_found": [], "bounds_applied": [], "refusal": None})
        if pass_name == SYNTHESIZE_PASS_NAME:
            return self._synthesize_response
        raise AssertionError(f"unexpected pass_name in this fixture: {pass_name!r}")

    def model_for_pass(self, pass_name: str | None = None) -> str:
        return "test-double-model"


def _fake_ask_result(*, with_vocabulary: bool) -> AskResult:
    chunk_ids = ["fixmap-2021-a_1_s_001", "fixmap-2021-a_1_s_002"]
    landed = (
        LandedPosition(
            position_id="pos-0001",
            score=0.87,
            argument="States extract resources through coercion.",
            size=1,
            sources=("fixmap-2021-a",),
            authors=("fixmap",),
            chunk_ids=(chunk_ids[0],),
        ),
    )
    corridor = (
        CorridorPosition(
            position_id="pos-0002",
            relation_count=1,
            labels=("qualifies ->",),
            argument="A counterpart argument.",
            size=1,
            sources=("fixmap-2021-a",),
            authors=("fixmap",),
            chunk_ids=(),
        ),
    )
    vocabulary = None
    assembled = list(chunk_ids[:1])
    if with_vocabulary:
        vocabulary = VocabularyJoinResult(
            column="mechanism",
            level=1,
            cap=20,
            categories=(
                CategoryReach(
                    category_id="war-and-state",
                    category_name="War and state formation",
                    chunk_ids=(chunk_ids[1],),
                    source_count=1,
                    cap_applied=False,
                ),
            ),
            positions=(
                VocabularyPosition(
                    position_id="pos-0003",
                    categories=("war-and-state",),
                    chunk_ids=(chunk_ids[1],),
                    argument="A neighbour reached through a shared mechanism.",
                    size=1,
                    sources=("other-2020-b",),
                    authors=("other",),
                ),
            ),
        )
        # The note only the vocabulary step reaches -- proof the assembled
        # evidence rests partly on a category edge, never on landing or the
        # corridor.
        assembled.append(chunk_ids[1])
    return AskResult(
        brief=_vocab_brief(),
        asks=("States extract resources through coercion.",),
        landed=landed,
        corridor=corridor,
        assembled_chunk_ids=tuple(assembled),
        pin="fixmap-pin-001",
        vocabulary=vocabulary,
    )


def _run_scripted_arm(tmp_path: Path, monkeypatch, *, arm: str, with_vocabulary: bool):
    ask_result = _fake_ask_result(with_vocabulary=with_vocabulary)
    vault_dir = _write_vault(tmp_path, list(ask_result.assembled_chunk_ids))

    def _fake_run_map_ask_for_brief(brief, **_kwargs):
        return ask_result

    monkeypatch.setattr(record_module, "run_map_ask_for_brief", _fake_run_map_ask_for_brief)

    synthesize_response = json.dumps(
        {
            "claims": [
                {
                    "text": "The corpus states that states extract resources through coercion.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                    "confidence": "medium",
                }
            ]
        }
    )
    client = _ArmScriptedClient(synthesize_response)
    return record_module.run_brief(_vocab_brief(), client=client, vault_dir=vault_dir, arm=arm)


def test_run_brief_arm_map_vocab_records_the_vocabulary_block(tmp_path: Path, monkeypatch):
    result = _run_scripted_arm(tmp_path, monkeypatch, arm=MAP_VOCAB_ARM, with_vocabulary=True)

    record = result.record
    assert record["trajectory"] == []
    assert "vocabulary" in record["map_retrieval"]
    vocabulary = record["map_retrieval"]["vocabulary"]
    assert vocabulary["column"] == "mechanism"
    assert vocabulary["categories"] == [
        {
            "category_id": "war-and-state",
            "name": "War and state formation",
            "note_count": 1,
            "source_count": 1,
            "cap_applied": False,
        }
    ]
    # The assembled evidence rests partly on a note reached ONLY through the
    # category edge -- neither `landed` nor `corridor` carries it.
    assert "fixmap-2021-a_1_s_002" in record["map_retrieval"]["assembled_chunk_ids"]


def test_run_brief_arm_map_records_no_vocabulary_block(tmp_path: Path, monkeypatch):
    result = _run_scripted_arm(tmp_path, monkeypatch, arm=MAP_ARM, with_vocabulary=False)

    record = result.record
    assert record["trajectory"] == []
    assert "vocabulary" not in record["map_retrieval"]


def test_run_brief_unknown_arm_is_refused_before_any_call(tmp_path: Path, monkeypatch):
    calls: list[str] = []

    def _fail_if_called(*_args, **_kwargs):
        calls.append("called")
        raise AssertionError("no call should be made before an unknown arm is refused")

    monkeypatch.setattr(record_module, "run_map_ask_for_brief", _fail_if_called)

    class _ExplodingClient(StubLLMClient):
        def complete(self, prompt: str, pass_name: str | None = None) -> str:
            calls.append("called")
            raise AssertionError("interrogation must never run for an unknown arm")

    with pytest.raises(UnknownArmError) as exc_info:
        record_module.run_brief(_vocab_brief(), client=_ExplodingClient(), arm="bogus-arm")

    assert calls == []
    assert "bogus-arm" in str(exc_info.value)
    for arm_name in KNOWN_ARMS:
        assert arm_name in str(exc_info.value)


def test_run_brief_arm_name_wins_over_use_map_true(tmp_path: Path, monkeypatch):
    """`arm=NAME_ARM` with `use_map=True` also given must still run the
    name layer -- `arm`, when given, decides, the same precedence
    `axial.brief.sweep._run_one_draw` already gives its own pair (module
    comment above)."""
    from axial.retrieve.loop import RetrievalResult

    chunk_ids = ["fixprec-2021-a_1_s_001"]
    vault_dir = _write_vault(tmp_path, chunk_ids)

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("the map path must not run when arm=name wins precedence")

    monkeypatch.setattr(record_module, "run_map_ask_for_brief", _fail_if_called)

    trajectory = [
        {
            "step": 1,
            "tool": "get_name",
            "args": {"canonical": "Fixture Name"},
            "result_ids": chunk_ids,
            "result_count": 1,
        }
    ]

    def _fake_run_planned_retrieval(*_args, **_kwargs):
        return RetrievalResult(trajectory=trajectory, evidence_ids=list(chunk_ids))

    monkeypatch.setattr(record_module, "run_planned_retrieval", _fake_run_planned_retrieval)

    synthesize_response = json.dumps(
        {
            "claims": [
                {
                    "text": "The corpus states a fixture claim.",
                    "kind": "a",
                    "grounds": [{"ref_type": "chunk", "ref_id": "[c1]"}],
                    "confidence": "medium",
                }
            ]
        }
    )
    client = _ArmScriptedClient(synthesize_response)

    result = record_module.run_brief(
        _vocab_brief(), client=client, vault_dir=vault_dir, use_map=True, arm=NAME_ARM
    )

    record = result.record
    assert record["map_retrieval"] is None
    assert record["trajectory"] == trajectory
