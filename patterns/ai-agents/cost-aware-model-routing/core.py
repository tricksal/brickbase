"""
Cost-Aware Model Routing Pattern
=================================
Select the cheapest model that can handle the task. Track spend immutably.
Retry only on transient errors. Cache long system prompts.

Source: everything-claude-code (affaan-m) — cost-aware-llm-pipeline
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


# ── Model Registry ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Model:
    id: str
    input_cost_per_1m: float   # USD per 1M input tokens
    output_cost_per_1m: float  # USD per 1M output tokens

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self.input_cost_per_1m
            + output_tokens / 1_000_000 * self.output_cost_per_1m
        )


MODELS = {
    "haiku":  Model("claude-haiku-4-5-20251001", input_cost_per_1m=0.80,  output_cost_per_1m=4.00),
    "sonnet": Model("claude-sonnet-4-6",          input_cost_per_1m=3.00,  output_cost_per_1m=15.00),
    "opus":   Model("claude-opus-4-6",             input_cost_per_1m=15.00, output_cost_per_1m=75.00),
}

# Routing thresholds
_SONNET_TEXT_THRESHOLD  = 10_000   # chars — route to Sonnet above this
_SONNET_ITEM_THRESHOLD  = 30       # items — route to Sonnet above this
_OPUS_TEXT_THRESHOLD    = 50_000   # chars — route to Opus above this


# ── Routing Logic ─────────────────────────────────────────────────────────────

def select_model(
    *,
    text_length: int = 0,
    item_count: int = 0,
    complexity: str = "auto",   # "low" | "medium" | "high" | "auto"
    force: str | None = None,
) -> Model:
    """
    Select the cheapest model that can handle the task.

    auto mode:  route by text length + item count
    explicit:   "low" → Haiku, "medium" → Sonnet, "high" → Opus

    Always use `force` to override for testing or special cases.
    """
    if force:
        return MODELS[force]

    if complexity != "auto":
        mapping = {"low": "haiku", "medium": "sonnet", "high": "opus"}
        return MODELS[mapping[complexity]]

    # Auto routing
    if text_length >= _OPUS_TEXT_THRESHOLD:
        return MODELS["opus"]
    if text_length >= _SONNET_TEXT_THRESHOLD or item_count >= _SONNET_ITEM_THRESHOLD:
        return MODELS["sonnet"]
    return MODELS["haiku"]


def task_complexity(task_type: str) -> str:
    """Map named task types to complexity tiers."""
    tiers = {
        "low":    {"summarize", "classify", "extract", "format", "commit-message", "tag"},
        "medium": {"implement", "refactor", "debug", "review", "test", "document"},
        "high":   {"architect", "research", "security-audit", "complex-debug", "design"},
    }
    for tier, tasks in tiers.items():
        if task_type in tasks:
            return tier
    return "medium"  # Safe default


# ── Immutable Cost Tracking ────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CostRecord:
    model_id: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    task: str = ""

    @classmethod
    def from_response(cls, model: Model, input_tokens: int, output_tokens: int, task: str = "") -> "CostRecord":
        return cls(
            model_id=model.id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=model.cost(input_tokens, output_tokens),
            task=task,
        )


@dataclass(frozen=True, slots=True)
class CostTracker:
    """
    Immutable cost tracker. Never mutates — always returns a new instance.
    This makes it safe to pass between functions and easy to audit.
    """
    budget_limit: float = 1.00
    records: tuple[CostRecord, ...] = ()

    def add(self, record: CostRecord) -> "CostTracker":
        """Return new tracker with this record appended."""
        return CostTracker(budget_limit=self.budget_limit, records=(*self.records, record))

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def remaining_budget(self) -> float:
        return self.budget_limit - self.total_cost

    @property
    def over_budget(self) -> bool:
        return self.total_cost > self.budget_limit

    def summary(self) -> str:
        by_model: dict[str, float] = {}
        for r in self.records:
            by_model[r.model_id] = by_model.get(r.model_id, 0) + r.cost_usd
        lines = [f"Total: ${self.total_cost:.4f} / ${self.budget_limit:.2f}"]
        for model_id, cost in sorted(by_model.items(), key=lambda x: -x[1]):
            lines.append(f"  {model_id}: ${cost:.4f}")
        return "\n".join(lines)


class BudgetExceededError(Exception):
    def __init__(self, spent: float, limit: float):
        super().__init__(f"Budget exceeded: ${spent:.4f} > ${limit:.2f}")
        self.spent = spent
        self.limit = limit


# ── Retry Logic ───────────────────────────────────────────────────────────────

class TransientError(Exception):
    """Network, rate-limit, or server errors — safe to retry."""

class PermanentError(Exception):
    """Auth, bad request, etc. — fail immediately."""


def with_retry(
    fn: Callable[[], Any],
    max_retries: int = 3,
    base_delay: float = 1.0,
    retryable: tuple[type[Exception], ...] = (TransientError,),
) -> Any:
    """
    Retry fn() on transient errors with exponential backoff.
    Fails immediately on permanent errors.
    Only retries exceptions listed in `retryable`.
    """
    for attempt in range(max_retries):
        try:
            return fn()
        except retryable as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[retry] Attempt {attempt + 1} failed ({e}), retrying in {delay:.1f}s...")
            time.sleep(delay)
        # Any other exception (PermanentError, etc.) raises immediately
    raise RuntimeError("Unreachable")  # pragma: no cover


# ── Prompt Caching ────────────────────────────────────────────────────────────

def build_cached_messages(system_prompt: str, user_input: str) -> list[dict]:
    """
    Structure messages with cache_control for long system prompts.
    Anthropic caches prompts > 1024 tokens, reducing both cost and latency.
    """
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # ← Cache this part
                },
                {
                    "type": "text",
                    "text": user_input,  # Variable — not cached
                },
            ],
        }
    ]


# ── Full Pipeline ─────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    content: str
    input_tokens: int
    output_tokens: int
    model_id: str


def process_with_budget(
    *,
    task: str,
    task_type: str,
    system_prompt: str,
    client: Any,                          # anthropic.Anthropic instance
    tracker: CostTracker,
    force_model: str | None = None,
) -> tuple[LLMResult, CostTracker]:
    """
    Full pipeline: route model → check budget → call with retry + cache → track cost.

    Returns (result, updated_tracker). Never mutates tracker.
    """
    # 1. Route
    complexity = task_complexity(task_type)
    model = select_model(
        text_length=len(task),
        complexity=complexity,
        force=force_model,
    )

    # 2. Budget check
    if tracker.over_budget:
        raise BudgetExceededError(tracker.total_cost, tracker.budget_limit)

    # 3. Call with retry + caching
    def _call():
        try:
            response = client.messages.create(
                model=model.id,
                max_tokens=2048,
                messages=build_cached_messages(system_prompt, task),
            )
            return response
        except Exception as e:
            err_str = str(e).lower()
            if any(kw in err_str for kw in ["rate_limit", "overloaded", "connection", "timeout"]):
                raise TransientError(str(e)) from e
            raise PermanentError(str(e)) from e

    response = with_retry(_call)

    # 4. Track cost (immutable)
    record = CostRecord.from_response(
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        task=task_type,
    )
    tracker = tracker.add(record)

    result = LLMResult(
        content=response.content[0].text,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        model_id=model.id,
    )
    return result, tracker


# ── Usage Example ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Model routing examples
    print(select_model(text_length=500).id)          # → haiku (simple)
    print(select_model(text_length=15_000).id)       # → sonnet (medium)
    print(select_model(text_length=60_000).id)       # → opus (complex)
    print(select_model(complexity="low").id)         # → haiku
    print(select_model(force="opus").id)             # → opus (forced)

    # Budget tracking
    tracker = CostTracker(budget_limit=0.50)
    record = CostRecord.from_response(MODELS["sonnet"], 1000, 500, task="implement")
    tracker = tracker.add(record)
    print(tracker.summary())

    # Task routing
    for task in ["summarize", "implement", "architect"]:
        model = select_model(complexity=task_complexity(task))
        print(f"{task:15} → {model.id}")
