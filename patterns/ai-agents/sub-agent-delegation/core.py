"""
Sub-Agent Delegation Pattern
==============================
An orchestrator agent spawns isolated sub-agents for focused sub-tasks.

Each sub-agent gets:
  - Its own isolated context window (fresh, no history bleed)
  - A precise task description (all needed context in the spawn prompt)
  - Optional tool restrictions (principle of least privilege)

The orchestrator collects results and synthesises a final answer.

Key design decisions:
  - Full context isolation (no shared history)
  - Push-based completion (sub-agent announces done, no polling)
  - Configurable concurrency (parallel vs sequential)
  - Timeout per sub-agent

Dependencies: stdlib only (concurrent.futures, threading, dataclasses)
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# A sub-agent callable: receives a task prompt, returns a string result.
SubAgentFn = Callable[[str], str]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SubTask:
    """
    A unit of work to be delegated to a sub-agent.

    task_id:     Unique identifier (used for tracking and result mapping).
    prompt:      Full self-contained task description. Sub-agent has NO prior context,
                 so everything needed must be in this prompt.
    timeout:     Max seconds to wait for this sub-agent to complete.
    metadata:    Arbitrary key-value pairs for caller use (not sent to sub-agent).
    """
    task_id: str
    prompt: str
    timeout: int = 120
    metadata: dict = field(default_factory=dict)


@dataclass
class SubTaskResult:
    """Result of a completed (or failed/timed-out) sub-agent run."""
    task_id: str
    output: Optional[str]       # None if failed or timed out
    success: bool
    duration_seconds: float
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class SubAgentOrchestrator:
    """
    Spawns sub-agents for a list of sub-tasks and collects their results.

    The orchestrator does NOT share session history with sub-agents.
    Each sub-agent receives only what's in SubTask.prompt.

    Usage:
        def my_sub_agent(prompt: str) -> str:
            return call_llm(prompt)  # your LLM call here

        orchestrator = SubAgentOrchestrator(sub_agent_fn=my_sub_agent)
        results = orchestrator.run_parallel([
            SubTask("task-1", "Summarise this document: ..."),
            SubTask("task-2", "Find all dates in: ..."),
        ])
        for r in results:
            print(r.task_id, r.output)
    """

    def __init__(
        self,
        sub_agent_fn: SubAgentFn,
        max_workers: int = 4,
        default_timeout: int = 120,
    ):
        self.sub_agent_fn = sub_agent_fn
        self.max_workers = max_workers
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_parallel(self, tasks: list[SubTask]) -> list[SubTaskResult]:
        """
        Spawn all tasks concurrently and wait for all to complete (or timeout).

        Returns results in the same order as input tasks.
        """
        results: dict[str, SubTaskResult] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_task: dict[Future, SubTask] = {
                pool.submit(self._run_one, task): task
                for task in tasks
            }

            for future in as_completed(future_to_task):
                task = future_to_task[future]
                try:
                    result = future.result(timeout=task.timeout or self.default_timeout)
                except TimeoutError:
                    log.warning("Sub-agent '%s' timed out.", task.task_id)
                    result = SubTaskResult(
                        task_id=task.task_id,
                        output=None,
                        success=False,
                        duration_seconds=task.timeout,
                        error="Timeout",
                    )
                except Exception as exc:
                    log.exception("Sub-agent '%s' raised an exception.", task.task_id)
                    result = SubTaskResult(
                        task_id=task.task_id,
                        output=None,
                        success=False,
                        duration_seconds=0.0,
                        error=str(exc),
                    )
                results[task.task_id] = result

        # Return in original task order
        return [results[t.task_id] for t in tasks]

    def run_sequential(self, tasks: list[SubTask]) -> list[SubTaskResult]:
        """
        Run tasks one at a time. Use when order matters or resources are tight.
        """
        return [self._run_one(task) for task in tasks]

    def synthesise(
        self,
        results: list[SubTaskResult],
        synthesis_fn: Callable[[list[SubTaskResult]], str],
    ) -> str:
        """
        Pass sub-agent results to a synthesis function (e.g. another LLM call)
        and return the combined output.
        """
        return synthesis_fn(results)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_one(self, task: SubTask) -> SubTaskResult:
        """Execute a single sub-agent task."""
        log.info("Spawning sub-agent for task '%s'", task.task_id)
        start = time.monotonic()

        try:
            output = self.sub_agent_fn(task.prompt)
            duration = time.monotonic() - start
            log.info("Sub-agent '%s' completed in %.1fs.", task.task_id, duration)
            return SubTaskResult(
                task_id=task.task_id,
                output=output,
                success=True,
                duration_seconds=duration,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            log.exception("Sub-agent '%s' failed.", task.task_id)
            return SubTaskResult(
                task_id=task.task_id,
                output=None,
                success=False,
                duration_seconds=duration,
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def build_sub_task_prompt(
    task_description: str,
    context: dict[str, Any],
    output_format: str = "Return your result as plain text.",
) -> str:
    """
    Build a self-contained sub-agent prompt.

    ⚠️  Critical: Sub-agents have NO prior context. Everything they need
    must be embedded in this prompt string.

    Args:
        task_description: What the sub-agent should do.
        context:          Key-value pairs of relevant data (will be formatted inline).
        output_format:    Instructions on how to format the output.
    """
    context_block = "\n".join(f"- {k}: {v}" for k, v in context.items())
    return f"""# Task
{task_description}

# Context
{context_block}

# Output format
{output_format}
"""


# ---------------------------------------------------------------------------
# Example usage (runnable demo)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Stub sub-agent (replace with actual LLM call)
    def stub_sub_agent(prompt: str) -> str:
        time.sleep(0.5)  # simulate LLM latency
        # Extract task number from prompt for demo output
        lines = prompt.strip().splitlines()
        task_line = next((l for l in lines if "Task" in l or "task" in l), "unknown")
        return f"[Stub result for: {task_line[:60]}]"

    orchestrator = SubAgentOrchestrator(
        sub_agent_fn=stub_sub_agent,
        max_workers=3,
    )

    tasks = [
        SubTask(
            task_id="summarise",
            prompt=build_sub_task_prompt(
                task_description="Summarise the following text in 2 sentences.",
                context={"text": "OpenClaw is a multi-agent AI gateway..."},
                output_format="Return exactly 2 sentences.",
            ),
        ),
        SubTask(
            task_id="extract-dates",
            prompt=build_sub_task_prompt(
                task_description="Extract all dates mentioned in the text.",
                context={"text": "The project started 2026-01-01 and ends 2026-12-31."},
                output_format="Return a JSON array of ISO date strings.",
            ),
        ),
        SubTask(
            task_id="sentiment",
            prompt=build_sub_task_prompt(
                task_description="Determine the sentiment of this review.",
                context={"review": "Absolutely amazing product, would buy again!"},
                output_format="Return: positive / neutral / negative",
            ),
        ),
    ]

    print("Running sub-agents in parallel…")
    results = orchestrator.run_parallel(tasks)

    print("\n--- Results ---")
    for r in results:
        status = "✓" if r.success else "✗"
        print(f"{status} [{r.task_id}] ({r.duration_seconds:.2f}s): {r.output or r.error}")

    # Synthesis step: combine all results into a final answer
    def my_synthesis(results: list[SubTaskResult]) -> str:
        parts = [f"- {r.task_id}: {r.output}" for r in results if r.success]
        return "Combined analysis:\n" + "\n".join(parts)

    final = orchestrator.synthesise(results, my_synthesis)
    print("\n--- Final synthesis ---")
    print(final)
