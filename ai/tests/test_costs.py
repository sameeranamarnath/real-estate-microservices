"""Unit tests for token accounting and spend metering."""

from __future__ import annotations

import pytest

from costs import (
    UsageMeter,
    estimate_cost_usd,
    estimate_tokens,
    price_for,
)


class TestPriceFor:
    def test_exact_match(self) -> None:
        assert price_for("gpt-4o") == (2.50, 10.00)

    def test_longest_prefix_wins(self) -> None:
        """gpt-4.1-mini must not be priced as gpt-4.1."""
        assert price_for("gpt-4.1-mini") == (0.40, 1.60)

    def test_dated_variant_falls_back_to_prefix(self) -> None:
        assert price_for("gpt-4o-mini-2024-07-18") == (0.15, 0.60)

    def test_case_insensitive(self) -> None:
        assert price_for("GPT-4O") == (2.50, 10.00)

    def test_self_hosted_model_is_free_per_token(self) -> None:
        assert price_for("Qwen/Qwen3-32B") == (0.0, 0.0)

    def test_unknown_model_is_zero_not_an_error(self) -> None:
        assert price_for("some-internal-model") == (0.0, 0.0)

    def test_none_is_zero(self) -> None:
        assert price_for("") == (0.0, 0.0)


class TestEstimateTokens:
    def test_empty_is_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_single_character_is_at_least_one(self) -> None:
        assert estimate_tokens("x") == 1

    def test_scales_with_length(self) -> None:
        assert estimate_tokens("a" * 400) == 100


class TestEstimateCost:
    def test_known_arithmetic(self) -> None:
        # 1M input tokens of gpt-4o at 2.50 -> 2.50
        assert estimate_cost_usd("gpt-4o", 1_000_000, 0) == pytest.approx(2.50)

    def test_output_priced_separately(self) -> None:
        assert estimate_cost_usd("gpt-4o", 0, 1_000_000) == pytest.approx(10.00)

    def test_zero_usage_is_zero(self) -> None:
        assert estimate_cost_usd("gpt-4o", 0, 0) == 0.0

    def test_self_hosted_has_no_token_cost(self) -> None:
        assert estimate_cost_usd("Qwen/Qwen3-32B", 100_000, 100_000) == 0.0


class TestUsageMeter:
    def test_accumulates_calls(self) -> None:
        meter = UsageMeter()
        meter.record("gpt-4o", 1000, 500)
        meter.record("gpt-4o", 1000, 500)
        assert len(meter.calls) == 2
        assert meter.total_tokens == 3000

    def test_total_is_the_sum_of_calls(self) -> None:
        meter = UsageMeter()
        meter.record("gpt-4o", 1_000_000, 0)
        assert meter.total_usd == pytest.approx(2.50)

    def test_no_budget_never_reports_over(self) -> None:
        meter = UsageMeter()
        meter.record("gpt-4o", 5_000_000, 0)
        assert not meter.over_budget

    def test_budget_is_enforced(self) -> None:
        meter = UsageMeter(budget_usd=1.00)
        meter.record("gpt-4o", 1_000_000, 0)
        assert meter.over_budget

    def test_budget_read_from_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_BUDGET_USD", "0.05")
        meter = UsageMeter()
        assert meter.budget_usd == pytest.approx(0.05)

    def test_malformed_budget_is_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_BUDGET_USD", "not-a-number")
        assert UsageMeter().budget_usd is None

    def test_summary_shape(self) -> None:
        meter = UsageMeter(budget_usd=10.0)
        meter.record("gpt-4o-mini", 100, 50)
        summary = meter.summary()
        assert set(summary) == {"calls", "total_tokens", "total_usd", "budget_usd", "over_budget"}
        assert summary["calls"] == 1
