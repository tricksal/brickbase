"""
Autonomous Loops Pattern
========================
Architectures for running AI agents autonomously — from simple sequential
pipelines (claude -p chains) to RFC-driven multi-agent DAG orchestration.

Source: everything-claude-code (affaan-m) — autonomous-loops
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Sequence


# ── 1. Sequential Pipeline ────────────────────────────────────────────────────

@dataclass
class PipelineStep:
    """One step in a sequential agent pipeline."""
    name: str
    prompt: str
    model: str = "claude-sonnet-4-6"
    allowed_tools: list[str] | None = None   # None = all tools

    def run(self, cwd: str | None = None) -> int:
        """Execute this step. Returns exit code."""
        cmd = ["claude", "-p", self.prompt, "--model", self.model]
        if self.allowed_tools:
            cmd += ["--allowedTools", ",".join(self.allowed_tools)]
        result = subprocess.run(cmd, cwd=cwd)
        return result.returncode


class SequentialPipeline:
    """
    Chain of agent steps. Stops on first failure (fail-fast).
    Each step gets a fresh context window — no bleed between steps.

    Example: implement → de-sloppify → verify → commit
    """

    def __init__(self, steps: list[PipelineStep]):
        self.steps = steps

    def run(self, cwd: str | None = None) -> bool:
        """Run all steps in order. Returns True if all succeeded."""
        for step in self.steps:
            print(f"[pipeline] → {step.name}")
            exit_code = step.run(cwd=cwd)
            if exit_code != 0:
                print(f"[pipeline] ✗ Step '{step.name}' failed (exit {exit_code})")
                return False
            print(f"[pipeline] ✓ {step.name}")
        return True


def make_feature_pipeline(spec_path: str) -> SequentialPipeline:
    """
    Standard feature development pipeline:
    1. Implement (Sonnet, fast)
    2. De-sloppify (clean up unnecessary code)
    3. Verify (build + test)
    4. Commit
    """
    return SequentialPipeline([
        PipelineStep(
            name="implement",
            prompt=f"Read the spec at {spec_path}. Implement it with TDD. No new documentation files.",
            model="claude-sonnet-4-6",
        ),
        PipelineStep(
            name="de-sloppify",
            prompt=(
                "Review all files changed in the last commit. "
                "Remove unnecessary type tests, overly defensive checks, and language-feature tests. "
                "Keep real business logic tests. Run the test suite after cleanup."
            ),
            model="claude-sonnet-4-6",
        ),
        PipelineStep(
            name="verify",
            prompt="Run the full build, lint, type check, and test suite. Fix any failures. Do NOT add new features.",
            model="claude-sonnet-4-6",
            allowed_tools=["Read", "Bash", "Grep"],  # No writes during verify
        ),
        PipelineStep(
            name="commit",
            prompt="Create a conventional commit for all staged changes.",
            model="claude-haiku-4-5-20251001",  # Cheap model for simple task
        ),
    ])


# ── 2. Quality Gate (De-Sloppify) ─────────────────────────────────────────────

class QualityGate:
    """
    A cleanup pass that runs after any Implementer step.
    Catches: unnecessary code, dead imports, testing language features,
    overly defensive checks, redundant comments.
    """

    PROMPT = """
    Review all recently changed files. Remove:
    - Unnecessary type tests (testing that TypeScript/Python generics work)
    - Overly defensive null checks on values that can't be null
    - Code that tests the language runtime, not business logic
    - Redundant comments that restate the code

    Keep:
    - Real business logic tests
    - Meaningful defensive programming
    - Documentation of non-obvious decisions

    Run the test suite after. Report what you removed and why.
    """

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    def run(self, cwd: str | None = None) -> bool:
        step = PipelineStep(name="quality-gate", prompt=self.PROMPT, model=self.model)
        return step.run(cwd=cwd) == 0


# ── 3. Infinite Agentic Loop ──────────────────────────────────────────────────

@dataclass
class AgentTask:
    """A task dispatched to a sub-agent."""
    task_id: int
    spec: str                    # Full specification text
    creative_direction: str      # Unique angle for this agent
    output_dir: Path
    existing_count: int          # How many iterations already exist

    def to_prompt(self) -> str:
        return f"""
Iteration #{self.task_id}

SPECIFICATION:
{self.spec}

YOUR CREATIVE DIRECTION:
{self.creative_direction}

OUTPUT:
Save your result to {self.output_dir}/{self.task_id:04d}/

EXISTING ITERATIONS: {self.existing_count} (be different from them)
"""


class InfiniteAgenticLoop:
    """
    Two-prompt orchestration for parallel spec-driven generation.

    Orchestrator:
    1. Reads spec file
    2. Scans output dir for highest iteration number
    3. Plans N unique creative directions
    4. Deploys N sub-agents in parallel (each writes to its own dir)

    For "infinite" mode: deploys in waves of 3-5 until context is low.
    """

    def __init__(
        self,
        spec_path: Path,
        output_dir: Path,
        count: int | None = None,  # None = infinite
        wave_size: int = 4,
    ):
        self.spec = spec_path.read_text()
        self.output_dir = output_dir
        self.count = count
        self.wave_size = wave_size
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _next_iteration_id(self) -> int:
        existing = sorted(self.output_dir.iterdir()) if self.output_dir.exists() else []
        return len(existing) + 1

    def _creative_directions(self, n: int) -> list[str]:
        """
        In production, ask an LLM to generate N distinct creative directions.
        Here: simple placeholders.
        """
        base = [
            "minimalist, focus on clarity",
            "comprehensive, cover all edge cases",
            "performance-optimized, benchmark everything",
            "developer-experience focused, great error messages",
            "security-hardened, threat-model driven",
        ]
        return [base[i % len(base)] for i in range(n)]

    def run_wave(self, wave_size: int) -> list[int]:
        """
        Deploy one wave of parallel sub-agents.
        Returns list of completed iteration IDs.
        """
        start = self._next_iteration_id()
        directions = self._creative_directions(wave_size)
        tasks = [
            AgentTask(
                task_id=start + i,
                spec=self.spec,
                creative_direction=directions[i],
                output_dir=self.output_dir,
                existing_count=start - 1,
            )
            for i in range(wave_size)
        ]

        # In a real implementation, spawn these as parallel claude -p calls
        # using subprocess or Task tool (inside Claude Code context)
        procs = []
        for task in tasks:
            cmd = ["claude", "-p", task.to_prompt()]
            procs.append(subprocess.Popen(cmd))

        # Wait for all to complete
        for proc in procs:
            proc.wait()

        return [t.task_id for t in tasks]

    def run(self) -> None:
        if self.count is not None:
            waves = (self.count + self.wave_size - 1) // self.wave_size
            for _ in range(waves):
                completed = self.run_wave(min(self.wave_size, self.count))
                print(f"[infinite-loop] Wave done: {completed}")
        else:
            # Infinite mode — run until interrupted
            wave = 0
            while True:
                wave += 1
                completed = self.run_wave(self.wave_size)
                print(f"[infinite-loop] Wave {wave} done: {completed}")
                time.sleep(1)


# ── 4. PR Loop ────────────────────────────────────────────────────────────────

class PRLoop:
    """
    Multi-day iterative project loop with CI gates.
    Runs: implement → CI check → fix failures → PR → review → next iteration.

    Stops when: max iterations reached, CI green, or human intervention.
    """

    def __init__(
        self,
        goal: str,
        max_iterations: int = 10,
        ci_command: str = "npm test",
    ):
        self.goal = goal
        self.max_iterations = max_iterations
        self.ci_command = ci_command

    def _ci_passes(self) -> bool:
        result = subprocess.run(self.ci_command, shell=True)
        return result.returncode == 0

    def run(self) -> bool:
        for i in range(1, self.max_iterations + 1):
            print(f"\n[pr-loop] Iteration {i}/{self.max_iterations}")

            # Implement
            impl_step = PipelineStep(
                name=f"implement-{i}",
                prompt=f"Continue working on: {self.goal}. Focus on the most impactful next step.",
            )
            impl_step.run()

            # CI check
            if self._ci_passes():
                print(f"[pr-loop] ✅ CI green at iteration {i}")
                return True

            # Fix failures
            fix_step = PipelineStep(
                name=f"fix-{i}",
                prompt=f"CI failed. Run '{self.ci_command}' and fix all failures.",
                allowed_tools=["Read", "Edit", "Bash"],
            )
            fix_step.run()

            if self._ci_passes():
                print(f"[pr-loop] ✅ Fixed at iteration {i}")
                return True

        print(f"[pr-loop] ✗ Max iterations ({self.max_iterations}) reached")
        return False


# ── Model Routing for Pipelines ───────────────────────────────────────────────

def route_model(step_type: str) -> str:
    """
    Route pipeline steps to the right model by complexity.
    Cheap steps → Haiku. Complex reasoning → Opus.
    """
    routing = {
        "research": "claude-opus-4-6",       # Deep reasoning
        "architect": "claude-opus-4-6",       # System design
        "implement": "claude-sonnet-4-6",     # Solid coding
        "fix": "claude-sonnet-4-6",           # Debugging
        "review": "claude-opus-4-6",          # Thorough review
        "commit": "claude-haiku-4-5-20251001", # Simple task
        "format": "claude-haiku-4-5-20251001", # Trivial
        "cleanup": "claude-sonnet-4-6",
    }
    return routing.get(step_type, "claude-sonnet-4-6")


# ── Usage Example ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Example 1: Feature pipeline
    pipeline = make_feature_pipeline("docs/auth-spec.md")
    success = pipeline.run(cwd=".")
    print(f"Pipeline: {'✅' if success else '✗'}")

    # Example 2: PR loop
    loop = PRLoop(
        goal="Add OAuth2 login with Google and GitHub",
        max_iterations=5,
        ci_command="pytest && npm test",
    )
    loop.run()
