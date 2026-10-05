"""Token accounting and spend estimation.

Prices are per million tokens in USD and are configuration, not truth: they are
overridable from the environment because contracts differ. A self-hosted vLLM
deployment has no per-token price, so the default table carries 0.0 for it and
the meter still records tokens.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    # model prefix -> (input usd / 1M, output usd / 1M)
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "claude-3-5-sonnet": (3.00, 15.00),
    "qwen/qwen3-32b": (0.0, 0.0),
}

_CHARS_PER_TOKEN = 4  # conservative English/code average, used only for pre-flight estimates


def price_for(model: str) -> tuple[float, float]:
    """Longest-prefix match, so gpt-4.1-mini does not match gpt-4.1."""
    key = (model or "").lower()
    if key in DEFAULT_PRICES_PER_MILLION:
        return DEFAULT_PRICES_PER_MILLION[key]
    for prefix in sorted(DEFAULT_PRICES_PER_MILLION, key=len, reverse=True):
        if key.startswith(prefix):
            return DEFAULT_PRICES_PER_MILLION[prefix]
    return (0.0, 0.0)


def estimate_tokens(text: str) -> int:
    """Rough token count for pre-flight budgeting. Not a substitute for the API's usage."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price_in, price_out = price_for(model)
    return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000


@dataclass(frozen=True)
class Usage:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass
class UsageMeter:
    """Accumulates per-request usage and enforces an optional spend ceiling.

    The ceiling is what turns "we have cost visibility" into "we cannot ship a
    loop that quietly burns the budget".
    """

    budget_usd: float | None = None
    calls: list[Usage] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.budget_usd is None:
            env = os.getenv("LLM_BUDGET_USD")
            if env:
                try:
                    self.budget_usd = float(env)
                except ValueError:
                    self.budget_usd = None

    def record(self, model: str, prompt_tokens: int, completion_tokens: int) -> Usage:
        usage = Usage(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=estimate_cost_usd(model, prompt_tokens, completion_tokens),
        )
        self.calls.append(usage)
        return usage

    @property
    def total_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 6)

    @property
    def total_tokens(self) -> int:
        return sum(c.total_tokens for c in self.calls)

    @property
    def over_budget(self) -> bool:
        return self.budget_usd is not None and self.total_usd > self.budget_usd

    def summary(self) -> dict[str, float | int | bool | None]:
        return {
            "calls": len(self.calls),
            "total_tokens": self.total_tokens,
            "total_usd": self.total_usd,
            "budget_usd": self.budget_usd,
            "over_budget": self.over_budget,
        }
