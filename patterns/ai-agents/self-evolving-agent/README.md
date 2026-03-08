# Pattern: Self-Evolving Agent

> An AI agent that adaptively improves its own strategy through a closed feedback loop:
> **Execute → Evaluate → Reflect → Update → Repeat**

---

## What It Does

After each task execution the agent runs two meta-steps:

1. **Evaluate** – a critic LLM scores the output and writes a critique.
2. **Reflect** – a reflector LLM reads the critique and produces an improved system prompt / strategy.

The improved strategy is used in the next iteration. The loop continues until the score threshold is reached or the iteration budget is exhausted.

```
┌─────────────┐
│  TASK       │
└──────┬──────┘
       │
       ▼
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  Execute    │───▶│  Evaluate   │───▶│   Reflect   │
│ (strategy)  │    │  (score +   │    │ (new strat) │
└─────────────┘    │  critique)  │    └──────┬──────┘
       ▲           └─────────────┘           │
       │                                     │
       └─────────────────────────────────────┘
                  iterate
```

---

## Files

| File | Purpose |
|------|---------|
| `core.py` | The complete pattern – `SelfEvolvingAgent` and `SelfEvolvingWorkflow` |

---

## Key Concepts

### `SelfEvolvingAgent`
Single-step agent with an evolution loop.

```python
from core import SelfEvolvingAgent

agent = SelfEvolvingAgent(
    llm_call=my_llm,                    # callable(system, user) -> str
    initial_strategy="You are a helpful, concise assistant.",
    max_iterations=5,
    score_threshold=0.9,                # stop early on good enough score
)

output = agent.run("Summarise the concept of backpropagation.")
agent.print_history()   # prints score/critique per iteration
```

### `SelfEvolvingWorkflow`
Multi-step variant that also *plans* before executing.

```python
from core import SelfEvolvingWorkflow

wf = SelfEvolvingWorkflow(llm_call=my_llm, max_iterations=3)
result = wf.run("Build a REST API design for a todo application.")
```

The planner decomposes the goal into sub-tasks, executes them sequentially, synthesises a final answer, then evolves the strategy for the next round.

---

## Plugging In an LLM

The pattern is library-agnostic. Any callable `(system: str, user: str) -> str` works:

```python
# OpenAI
from openai import OpenAI
client = OpenAI()
def llm(system, user):
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return r.choices[0].message.content
```

```python
# Anthropic
import anthropic
c = anthropic.Anthropic()
def llm(system, user):
    msg = c.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text
```

```python
# LiteLLM (any provider)
import litellm
def llm(system, user):
    r = litellm.completion(
        model="ollama/llama3",
        messages=[{"role":"system","content":system},{"role":"user","content":user}],
    )
    return r.choices[0].message.content
```

---

## Advanced Usage

### Different models per role
Use a cheap model for execution, a strong model for reflection:

```python
agent = SelfEvolvingAgent(
    llm_call=cheap_llm,           # executor
    initial_strategy="...",
    evaluator_llm=strong_llm,     # critic
    reflector_llm=strong_llm,     # strategy updater
)
```

### Export history (logging / analytics)
```python
import json
history = agent.export_history()
print(json.dumps(history, indent=2))
```

### Custom evaluator
Replace the built-in LLM-based evaluator with a deterministic metric:

```python
class MyAgent(SelfEvolvingAgent):
    def _evaluate(self, task, output):
        # e.g. run unit tests, count correct answers, BLEU score, etc.
        score = run_tests(output)
        critique = f"Tests passed: {int(score * 10)}/10"
        return score, critique
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Strategy = system prompt | Most LLMs are sensitive to system prompt wording; it's the highest-leverage lever |
| Separate evaluator/reflector LLMs | Allows using a stronger (slower/costlier) model only for meta-steps |
| Score threshold + max iterations | Prevents infinite loops; exits early when quality is sufficient |
| JSON eval format | Structured output is easier to parse reliably than free text |
| Fallback on parse errors | Loop never crashes; degraded eval (score=0.5) is better than a hard fail |

---

## When to Use This Pattern

✅ **Good fit when:**
- The quality of an output is measurable (by LLM or metric)
- You have iteration budget (cost / latency)
- Initial strategy is uncertain — you want the system to discover good prompts
- Task domain is consistent (same type of task across runs)

❌ **Not ideal when:**
- Single-shot latency is critical
- Every task is completely different (strategy can't transfer)
- You have a very strong initial prompt already

---

## Related Patterns

- **iterative-refinement** – simpler: no strategy update, just re-prompting
- **agent-memory-patterns** – persistence across sessions vs. within a run
- **autonomous-loops** – general loop scaffolding without self-improvement

---

## Source

Inspired by the [EvoAgentX](https://github.com/EvoAgentX/EvoAgentX) framework —
an automated framework for evaluating and evolving agentic workflows,
integrating algorithms like **TextGrad**, **AFlow**, and **MIPRO**.

Original example from:
[awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps) →
`advanced_ai_agents/multi_agent_apps/ai_self_evolving_agent/`
