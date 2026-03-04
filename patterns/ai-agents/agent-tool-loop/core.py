"""
Agent Tool Loop Pattern
=======================
A minimal implementation of the agentic tool-call loop.

The model runs in a loop:
  1. Receives conversation history (with optional tool results)
  2. Decides: call a tool OR produce a final reply
  3. If tool call → execute → append result to history → repeat
  4. If final reply → return result, loop ends

This is the foundation of every LLM-based agent.

Dependencies: openai (or any OpenAI-compatible SDK)
  pip install openai
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

# A tool function receives keyword args and returns a serializable result.
ToolFn = Callable[..., Any]

@dataclass
class Tool:
    """Wraps a Python function as an LLM-callable tool."""
    name: str
    description: str
    parameters: dict          # JSON Schema for the arguments
    fn: ToolFn

    def to_schema(self) -> dict:
        """Return the OpenAI function-call schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def call(self, **kwargs) -> Any:
        """Execute the underlying function."""
        return self.fn(**kwargs)


# ---------------------------------------------------------------------------
# Agent loop
# ---------------------------------------------------------------------------

@dataclass
class AgentLoopConfig:
    """Configuration for a single agent loop run."""
    model: str = "gpt-4o-mini"
    max_iterations: int = 20           # hard cap to prevent infinite loops
    system_prompt: str = "You are a helpful assistant."
    timeout_seconds: int = 300         # wall-clock budget per run


class AgentToolLoop:
    """
    Runs the agent ↔ tool loop until the model stops calling tools.

    Usage:
        agent = AgentToolLoop(client, tools=[...], config=AgentLoopConfig())
        result = agent.run("What's the weather in Berlin?")
        print(result)
    """

    def __init__(
        self,
        client,                      # OpenAI-compatible client
        tools: list[Tool],
        config: AgentLoopConfig | None = None,
    ):
        self.client = client
        self.tools = {t.name: t for t in tools}
        self.config = config or AgentLoopConfig()
        self.log = logging.getLogger(self.__class__.__name__)

    def run(self, user_message: str, history: list[dict] | None = None) -> str:
        """
        Run the agent loop for a single user message.

        Args:
            user_message: The user's input.
            history: Optional prior conversation (for multi-turn sessions).

        Returns:
            The final assistant reply as a string.
        """
        # Build initial message list
        messages: list[dict] = [
            {"role": "system", "content": self.config.system_prompt},
            *(history or []),
            {"role": "user", "content": user_message},
        ]

        tool_schemas = [t.to_schema() for t in self.tools.values()]
        iteration = 0

        while iteration < self.config.max_iterations:
            iteration += 1
            self.log.debug("Loop iteration %d — sending %d messages", iteration, len(messages))

            # --- Model inference ---
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                tools=tool_schemas or None,
                tool_choice="auto" if tool_schemas else None,
            )

            choice = response.choices[0]
            assistant_message = choice.message

            # Append the assistant turn (may contain tool_calls)
            messages.append(assistant_message.model_dump(exclude_none=True))

            # --- Termination: no more tool calls → return final reply ---
            if not assistant_message.tool_calls:
                self.log.info("Loop complete after %d iteration(s).", iteration)
                return assistant_message.content or ""

            # --- Tool execution phase ---
            for tool_call in assistant_message.tool_calls:
                result = self._execute_tool(tool_call)
                # Append tool result to history so the model can consume it
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result),
                })

        # Max iterations reached — return what we have
        self.log.warning("Max iterations (%d) reached.", self.config.max_iterations)
        return "[Agent loop terminated: max iterations reached]"

    def _execute_tool(self, tool_call) -> Any:
        """Look up and execute a tool call from the model."""
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments or "{}")

        tool = self.tools.get(name)
        if tool is None:
            self.log.error("Unknown tool: %s", name)
            return {"error": f"Tool '{name}' not found"}

        self.log.info("Calling tool: %s(%s)", name, args)
        try:
            return tool.call(**args)
        except Exception as exc:
            self.log.exception("Tool '%s' raised an error.", name)
            return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Example usage (runnable demo)
# ---------------------------------------------------------------------------

def _make_demo_tools() -> list[Tool]:
    """Create a small set of demo tools for illustration."""

    def add(a: float, b: float) -> float:
        return a + b

    def get_weather(city: str) -> dict:
        # Stub — replace with a real API call
        return {"city": city, "temp_c": 18, "condition": "partly cloudy"}

    return [
        Tool(
            name="add",
            description="Add two numbers together.",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            fn=add,
        ),
        Tool(
            name="get_weather",
            description="Get current weather for a city.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
            fn=get_weather,
        ),
    ]


if __name__ == "__main__":
    import os
    from openai import OpenAI

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    tools = _make_demo_tools()
    config = AgentLoopConfig(model="gpt-4o-mini", max_iterations=10)

    agent = AgentToolLoop(client=client, tools=tools, config=config)
    answer = agent.run("What is 42 plus 58, and what's the weather in Berlin?")
    print("\nFinal answer:", answer)
