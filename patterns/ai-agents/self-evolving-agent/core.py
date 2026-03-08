"""
Self-Evolving Agent Pattern
===========================
An agent that adaptively improves itself through a closed feedback loop:

    Execute → Evaluate → Reflect → Update Strategy → Repeat

Core idea (from EvoAgentX / TextGrad / AFlow paradigm):
- The agent runs a task using its current system prompt / workflow strategy.
- A critic (another LLM call or metric) scores the output.
- A reflector generates a *diff* – concrete improvements to the strategy.
- The updated strategy is persisted and used in the next iteration.

Usage
-----
    agent = SelfEvolvingAgent(
        llm_call=my_openai_wrapper,       # callable(system, user) -> str
        initial_strategy="You are a helpful assistant.",
        max_iterations=5,
    )
    final_output = agent.run(task="Write a poem about recursion.")
    agent.print_history()

The `llm_call` abstraction keeps this pattern LLM-library agnostic.
Plug in openai, anthropic, litellm, ollama — whatever you like.

Source inspiration: https://github.com/Shubhamsaboo/awesome-llm-apps
                    (ai_self_evolving_agent / EvoAgentX framework)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type alias: any function that takes (system_prompt, user_message) -> str
# ---------------------------------------------------------------------------
LLMCallable = Callable[[str, str], str]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class IterationRecord:
    """Snapshot of one evolution cycle."""
    iteration: int
    strategy: str          # system prompt / plan used this round
    task: str
    output: str            # raw agent response
    score: float           # 0.0 – 1.0, higher is better
    critique: str          # human-readable feedback from the evaluator
    improvement_suggestion: str  # what the reflector recommends changing


@dataclass
class EvolutionState:
    """Mutable state carried across iterations."""
    strategy: str
    history: List[IterationRecord] = field(default_factory=list)
    best_score: float = 0.0
    best_strategy: str = ""

    def record(self, record: IterationRecord) -> None:
        self.history.append(record)
        if record.score > self.best_score:
            self.best_score = record.score
            self.best_strategy = record.strategy


# ---------------------------------------------------------------------------
# Built-in prompts (all overridable)
# ---------------------------------------------------------------------------

_DEFAULT_EVALUATOR_SYSTEM = """\
You are an expert evaluator. Given a task and the agent's response, score the
response on a scale from 0.0 to 1.0 and provide concise critique.

Respond in JSON:
{
  "score": <float 0.0-1.0>,
  "critique": "<what is good/bad about the response>"
}
"""

_DEFAULT_REFLECTOR_SYSTEM = """\
You are a meta-learning coach. You receive:
- The current agent system prompt (strategy)
- The task
- The agent's response
- Evaluation critique and score

Your job: suggest a concrete, specific improvement to the strategy that will
raise the score in the next iteration. Be precise — output only the improved
strategy text (the new system prompt), nothing else.
"""


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class SelfEvolvingAgent:
    """
    A generic self-evolving agent that improves its strategy over iterations.

    Parameters
    ----------
    llm_call : LLMCallable
        Function signature: (system: str, user: str) -> str
        Called for execution, evaluation, and reflection steps.
        You can use different models per step via the optional overrides.
    initial_strategy : str
        The starting system prompt / behavioural strategy.
    max_iterations : int
        How many improve-cycles to run.
    score_threshold : float
        Stop early if a score >= this value is achieved.
    evaluator_system : str, optional
        Override the default evaluator system prompt.
    reflector_system : str, optional
        Override the default reflector system prompt.
    evaluator_llm : LLMCallable, optional
        Use a separate (possibly stronger) model for evaluation.
    reflector_llm : LLMCallable, optional
        Use a separate model for reflection / strategy update.
    """

    def __init__(
        self,
        llm_call: LLMCallable,
        initial_strategy: str,
        max_iterations: int = 5,
        score_threshold: float = 0.9,
        evaluator_system: Optional[str] = None,
        reflector_system: Optional[str] = None,
        evaluator_llm: Optional[LLMCallable] = None,
        reflector_llm: Optional[LLMCallable] = None,
    ) -> None:
        self.executor_llm = llm_call
        self.evaluator_llm = evaluator_llm or llm_call
        self.reflector_llm = reflector_llm or llm_call

        self.max_iterations = max_iterations
        self.score_threshold = score_threshold

        self.evaluator_system = evaluator_system or _DEFAULT_EVALUATOR_SYSTEM
        self.reflector_system = reflector_system or _DEFAULT_REFLECTOR_SYSTEM

        self.state = EvolutionState(
            strategy=initial_strategy,
            best_strategy=initial_strategy,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, task: str) -> str:
        """
        Execute the self-improvement loop for the given task.

        Returns the best output found across all iterations.
        """
        best_output = ""

        for i in range(1, self.max_iterations + 1):
            logger.info("=== Iteration %d / %d ===", i, self.max_iterations)

            # 1. Execute
            output = self._execute(task)
            logger.debug("Output: %s", output[:200])

            # 2. Evaluate
            score, critique = self._evaluate(task, output)
            logger.info("Score: %.2f | Critique: %s", score, critique[:120])

            # 3. Reflect – generate improvement for next round
            suggestion = self._reflect(task, output, score, critique)

            # 4. Record
            record = IterationRecord(
                iteration=i,
                strategy=self.state.strategy,
                task=task,
                output=output,
                score=score,
                critique=critique,
                improvement_suggestion=suggestion,
            )
            self.state.record(record)

            if score > self.state.best_score or best_output == "":
                best_output = output

            # 5. Early exit?
            if score >= self.score_threshold:
                logger.info("Score threshold reached. Stopping.")
                break

            # 6. Update strategy for next iteration
            self.state.strategy = suggestion
            logger.info("Strategy updated.")

        logger.info(
            "Evolution complete. Best score: %.2f", self.state.best_score
        )
        return best_output

    def print_history(self) -> None:
        """Pretty-print the evolution history to stdout."""
        print("\n" + "=" * 60)
        print("Self-Evolving Agent – History")
        print("=" * 60)
        for rec in self.state.history:
            print(f"\n[Iteration {rec.iteration}]")
            print(f"  Score    : {rec.score:.2f}")
            print(f"  Critique : {rec.critique}")
            print(f"  Strategy : {rec.strategy[:100]}...")
            print(f"  Output   : {rec.output[:150]}...")
        print(f"\nBest score: {self.state.best_score:.2f}")
        print("=" * 60)

    def export_history(self) -> List[dict]:
        """Return the evolution history as a list of dicts (JSON-serialisable)."""
        return [
            {
                "iteration": r.iteration,
                "score": r.score,
                "critique": r.critique,
                "strategy": r.strategy,
                "output": r.output,
                "improvement_suggestion": r.improvement_suggestion,
            }
            for r in self.state.history
        ]

    # ------------------------------------------------------------------
    # Internal steps
    # ------------------------------------------------------------------

    def _execute(self, task: str) -> str:
        """Run the task with the current strategy."""
        return self.executor_llm(self.state.strategy, task)

    def _evaluate(self, task: str, output: str) -> tuple[float, str]:
        """
        Ask the evaluator LLM to score the output.

        Returns (score, critique).  Falls back to (0.5, "parse error") on
        malformed JSON so the loop can continue.
        """
        user_message = (
            f"Task:\n{task}\n\n"
            f"Agent Response:\n{output}"
        )
        raw = self.evaluator_llm(self.evaluator_system, user_message)

        try:
            # Strip markdown code fences if present
            cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
            data = json.loads(cleaned)
            score = float(data.get("score", 0.5))
            critique = str(data.get("critique", ""))
            return max(0.0, min(1.0, score)), critique
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("Evaluator returned non-JSON output: %s | err: %s", raw[:200], exc)
            return 0.5, raw[:300]

    def _reflect(
        self,
        task: str,
        output: str,
        score: float,
        critique: str,
    ) -> str:
        """
        Generate an improved strategy for the next iteration.

        Returns the new system prompt / strategy string.
        """
        user_message = (
            f"Current Strategy:\n{self.state.strategy}\n\n"
            f"Task:\n{task}\n\n"
            f"Agent Output:\n{output}\n\n"
            f"Score: {score:.2f}\n"
            f"Critique:\n{critique}\n\n"
            "Provide the improved strategy (system prompt) only:"
        )
        new_strategy = self.reflector_llm(self.reflector_system, user_message)
        return new_strategy.strip()


# ---------------------------------------------------------------------------
# Workflow-level variant (mirrors EvoAgentX's WorkFlowGenerator approach)
# ---------------------------------------------------------------------------

class SelfEvolvingWorkflow:
    """
    Extends the pattern to multi-step workflows that also self-evolve.

    The LLM first *generates a plan* (list of sub-tasks) from the goal,
    then executes each step, evaluates the final result, and refines the
    plan for the next iteration.

    This mirrors the EvoAgentX architecture where:
      WorkFlowGenerator → WorkFlowGraph → WorkFlow.execute()
    but implemented without framework dependencies.
    """

    _PLANNER_SYSTEM = """\
You are a workflow planner. Given a goal, output a JSON list of sub-tasks
that together accomplish the goal. Each item is a short action string.
Example: ["Research topic X", "Draft outline", "Write introduction", "Review"]
Output only valid JSON, no prose.
"""

    _SYNTHESISER_SYSTEM = """\
You are a synthesis agent. Given a goal and a list of completed sub-task
outputs, combine them into a single coherent final answer.
"""

    def __init__(
        self,
        llm_call: LLMCallable,
        initial_strategy: str = "You are a helpful, precise assistant.",
        max_iterations: int = 3,
        score_threshold: float = 0.85,
    ) -> None:
        self.llm_call = llm_call
        self.max_iterations = max_iterations
        self.score_threshold = score_threshold

        # Wrap a SelfEvolvingAgent for the planning/execution loop
        self._agent = SelfEvolvingAgent(
            llm_call=llm_call,
            initial_strategy=initial_strategy,
            max_iterations=max_iterations,
            score_threshold=score_threshold,
        )

    def run(self, goal: str) -> str:
        """
        Generate a plan from the goal, execute each step, synthesise,
        then evolve the overall approach across iterations.
        """
        best_output = ""

        for i in range(1, self.max_iterations + 1):
            logger.info("=== Workflow Iteration %d ===", i)

            # 1. Generate plan
            plan = self._generate_plan(goal)
            logger.info("Plan: %s", plan)

            # 2. Execute each step sequentially
            step_outputs: List[str] = []
            context = ""
            for step in plan:
                prompt = f"Context so far:\n{context}\n\nTask: {step}" if context else f"Task: {step}"
                result = self.llm_call(self._agent.state.strategy, prompt)
                step_outputs.append(f"[{step}]\n{result}")
                context += f"\n{result}"

            # 3. Synthesise into final answer
            synthesis_input = f"Goal: {goal}\n\n" + "\n\n".join(step_outputs)
            final_output = self.llm_call(self._SYNTHESISER_SYSTEM, synthesis_input)

            # 4. Evaluate
            score, critique = self._agent._evaluate(goal, final_output)
            logger.info("Workflow score: %.2f", score)

            # 5. Reflect and update strategy
            suggestion = self._agent._reflect(goal, final_output, score, critique)

            record = IterationRecord(
                iteration=i,
                strategy=self._agent.state.strategy,
                task=goal,
                output=final_output,
                score=score,
                critique=critique,
                improvement_suggestion=suggestion,
            )
            self._agent.state.record(record)
            if score > self._agent.state.best_score or best_output == "":
                best_output = final_output

            if score >= self.score_threshold:
                break

            self._agent.state.strategy = suggestion

        return best_output

    def _generate_plan(self, goal: str) -> List[str]:
        """Ask the LLM to decompose the goal into a list of sub-tasks."""
        raw = self.llm_call(self._PLANNER_SYSTEM, f"Goal: {goal}")
        try:
            cleaned = raw.strip().removeprefix("```json").removesuffix("```").strip()
            plan = json.loads(cleaned)
            if isinstance(plan, list) and all(isinstance(s, str) for s in plan):
                return plan
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: treat the whole thing as a single step
        return [goal]


# ---------------------------------------------------------------------------
# Example wiring (not run by import)
# ---------------------------------------------------------------------------

def _example_llm_call(system: str, user: str) -> str:
    """
    Replace this with your actual LLM client.

    Example using openai:
        from openai import OpenAI
        client = OpenAI()

        def my_llm(system, user):
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content
    """
    raise NotImplementedError("Plug in your LLM client here.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # -- Plug in your LLM here --
    # from openai import OpenAI
    # client = OpenAI()
    # def llm(system, user):
    #     r = client.chat.completions.create(
    #         model="gpt-4o-mini",
    #         messages=[{"role":"system","content":system},{"role":"user","content":user}]
    #     )
    #     return r.choices[0].message.content

    # agent = SelfEvolvingAgent(
    #     llm_call=llm,
    #     initial_strategy="You are a helpful assistant.",
    #     max_iterations=4,
    # )
    # output = agent.run("Explain the concept of gradient descent in one paragraph.")
    # agent.print_history()
    # print("\nFinal output:\n", output)
    pass
