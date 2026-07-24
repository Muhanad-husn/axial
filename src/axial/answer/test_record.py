"""Inner unit tests for `axial.answer.record.build_record`'s `cost` field
(§7.14, issue #363) -- co-located under src/axial/answer/, mirroring
src/axial/answer/test_source_usage.py's own layout for this module."""

from __future__ import annotations

from axial.answer.record import build_record
from axial.brief.intake import Brief
from axial.brief.interrogate import InterrogationResult
from axial.llm import PRICE_TABLE_USD_PER_1K, estimate_cost


class _FakeUsageClient:
    """A minimal `LLMClient` double: `build_record` only ever calls
    `usage_for_pass` on the client it is given -- never a completion
    method -- so this double implements exactly that."""

    def __init__(self, usage_by_pass: dict[str, dict[str, int] | None]) -> None:
        self._usage_by_pass = usage_by_pass

    def usage_for_pass(self, pass_name: str | None = None) -> dict[str, int] | None:
        return self._usage_by_pass.get(pass_name)


def _brief() -> Brief:
    return Brief(brief_id="deadbeefcafef00d", case="Syria", request="How did order change?")


def _interrogation_result() -> InterrogationResult:
    # `claims`/`trajectory` passed to `build_record` below are empty either
    # way -- disposition value has no bearing on the `cost` field this
    # module tests, so a plain `proceed` keeps the fixture unconfusing.
    return InterrogationResult(
        premises_found=[], bounds_applied=[], refusal=None, disposition="proceed"
    )


def _build(model_by_pass: dict[str, str], client: _FakeUsageClient) -> dict:
    return build_record(
        _brief(),
        _interrogation_result(),
        corpus_pin="baseline",
        schema_version="0.1",
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
