"""Inner unit tests for `axial.answer.record.build_record`'s `cost` field
(§7.14, issue #363), plus its `evidence` field (§7.3, issue #545) -- both
small enough to share this file rather than each earning its own, co-located
under src/axial/answer/, mirroring src/axial/answer/test_source_usage.py's
own layout for this module."""

from __future__ import annotations

import axial.answer.record as record_module
from axial.analyze.synthesis import Claim, CounterPositionGenerationFailedError
from axial.answer.record import build_record
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult
from axial.llm import PRICE_TABLE_USD_PER_1K, estimate_cost


class _FakeUsageClient:
    """A minimal `LLMClient` double: `build_record` only ever calls
    `usage_for_pass` on the client it is given -- never a completion
    method -- so this double implements exactly that. `model_for_pass`
    is answered too (a fixed string, never asserted on by the existing
    `cost`-field tests below): `build_record` consults it only when
    `counter_position_result.model_called` is `True`, which every existing
    test here never reaches (each passes `claims=[]`, uncontested)."""

    def __init__(self, usage_by_pass: dict[str, dict[str, int] | None]) -> None:
        self._usage_by_pass = usage_by_pass

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return self._usage_by_pass.get(pass_name)

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
