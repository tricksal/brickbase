"""
MCP Agent Router — Brickbase Pattern
=====================================
Route user queries to specialized agents, each with only the MCP tools they need.

Pattern: Instead of one omnipotent agent with all tools, create domain-specific
agents with focused toolsets. A lightweight classifier picks the right agent.

Source: https://github.com/Shubhamsaboo/awesome-llm-apps
        (mcp_ai_agents/multi_mcp_agent_router/agent_forge.py)

Usage:
    from core import AgentRouter, Agent

    router = AgentRouter(agents={
        "researcher": Agent(
            name="Researcher",
            description="Fetches and summarizes web content",
            system_prompt="You are a research assistant...",
            keywords=["research", "find", "search", "summarize"],
            mcp_servers=[
                {"name": "fetch", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"]},
            ],
        ),
    }, default_agent="researcher")

    response = router.route_and_run("What is the latest on LLMs?")
    print(response)
"""

import asyncio
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Optional

from anthropic import Anthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Agent:
    """A specialized agent bound to a set of MCP servers.

    Attributes:
        name:          Human-readable display name.
        description:   One-line summary of the agent's expertise.
        system_prompt: Full system prompt sent to the LLM.
        keywords:      Words used by the router to classify queries (lower-case).
        mcp_servers:   List of MCP server configs (dict with keys: name, command, args, env).
    """
    name: str
    description: str
    system_prompt: str
    keywords: list[str] = field(default_factory=list)
    mcp_servers: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------

def _mcp_tool_to_anthropic(tool) -> dict:
    """Convert an MCP ToolInfo object to Anthropic's tool format."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


async def _connect_mcp_servers(agent: Agent) -> tuple[AsyncExitStack, list[dict], dict[str, ClientSession]]:
    """Spawn all MCP servers for an agent and collect their tools.

    Returns:
        stack:       AsyncExitStack owning all server processes (call .aclose() when done).
        tools:       Anthropic-format tool list (passed to messages.create).
        session_map: Maps tool_name -> ClientSession for dispatching tool calls.
    """
    stack = AsyncExitStack()
    await stack.__aenter__()

    tools: list[dict] = []
    session_map: dict[str, ClientSession] = {}

    for srv in agent.mcp_servers:
        # Merge extra env vars without polluting the current process
        env = {**os.environ, **srv.get("env", {})}

        params = StdioServerParameters(
            command=srv["command"],
            args=srv.get("args", []),
            env=env,
        )

        # stdio_client returns (read_stream, write_stream)
        transport = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(*transport))
        await session.initialize()

        for tool in (await session.list_tools()).tools:
            tools.append(_mcp_tool_to_anthropic(tool))
            session_map[tool.name] = session

    return stack, tools, session_map


# ---------------------------------------------------------------------------
# Core agentic loop
# ---------------------------------------------------------------------------

async def _run_agent_async(
    client: Anthropic,
    agent: Agent,
    query: str,
    history: list[dict],
    model: str = "claude-opus-4-5",
    max_tokens: int = 4096,
) -> str:
    """Run a single query through an agent's full agentic loop (async).

    Handles tool calls iteratively until the model stops with end_turn.

    Args:
        client:     Anthropic client instance.
        agent:      The agent to invoke.
        query:      The user's query string.
        history:    Prior conversation messages for this agent (mutated in-place).
        model:      Anthropic model name.
        max_tokens: Max tokens for each LLM call.

    Returns:
        The agent's final text response.
    """
    messages = history + [{"role": "user", "content": query}]

    # Fast path: no MCP servers → plain chat
    if not agent.mcp_servers:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=agent.system_prompt,
            messages=messages,
        )
        return resp.content[0].text

    stack, tools, session_map = await _connect_mcp_servers(agent)

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=agent.system_prompt,
            messages=messages,
            tools=tools,
        )

        # Agentic loop — keep going while the model wants to use tools
        while resp.stop_reason == "tool_use":
            tool_results = []

            for block in resp.content:
                if block.type != "tool_use":
                    continue

                session = session_map.get(block.name)
                if session is None:
                    # Tool not found — return an error result so the LLM can recover
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error: unknown tool '{block.name}'",
                        "is_error": True,
                    })
                    continue

                try:
                    result = await session.call_tool(block.name, block.input)
                    # Flatten mixed content (text + embedded objects) to a single string
                    text = "".join(
                        c.text if hasattr(c, "text") else str(c)
                        for c in result.content
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": text,
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Tool error: {exc}",
                        "is_error": True,
                    })

            # Feed tool results back and continue
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})

            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=agent.system_prompt,
                messages=messages,
                tools=tools,
            )

        # Collect all text blocks from the final response
        text_parts = [b.text for b in resp.content if hasattr(b, "text")]
        return "\n".join(text_parts) if text_parts else "(no response)"

    finally:
        await stack.aclose()


def run_agent(
    client: Anthropic,
    agent: Agent,
    query: str,
    history: Optional[list[dict]] = None,
    model: str = "claude-opus-4-5",
    max_tokens: int = 4096,
) -> str:
    """Synchronous wrapper — runs the async agent loop in a fresh event loop.

    Args:
        client:     Anthropic client instance.
        agent:      The agent to invoke.
        query:      The user's query string.
        history:    Prior conversation messages (optional; a new list is used if omitted).
        model:      Anthropic model name.
        max_tokens: Max tokens per LLM call.

    Returns:
        The agent's final text response.
    """
    history = history if history is not None else []
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            _run_agent_async(client, agent, query, history, model, max_tokens)
        )
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

class AgentRouter:
    """Routes user queries to the most appropriate specialized agent.

    Routing is keyword-based by default and falls back to a configurable
    default agent when no keywords match.

    Example:
        router = AgentRouter(
            agents={"researcher": researcher_agent, "coder": coder_agent},
            default_agent="researcher",
        )
        response = router.route_and_run("What is the latest on transformers?")
    """

    def __init__(
        self,
        agents: dict[str, Agent],
        default_agent: str,
        api_key: Optional[str] = None,
        model: str = "claude-opus-4-5",
    ):
        """
        Args:
            agents:        Mapping of agent_id -> Agent.
            default_agent: agent_id used when no keywords match.
            api_key:       Anthropic API key (falls back to ANTHROPIC_API_KEY env var).
            model:         Default Anthropic model for all agents.
        """
        assert default_agent in agents, f"default_agent '{default_agent}' not in agents"
        self.agents = agents
        self.default_agent = default_agent
        self.model = model
        self.client = Anthropic(api_key=api_key or os.environ["ANTHROPIC_API_KEY"])
        # Per-agent conversation history (enables multi-turn within a session)
        self.histories: dict[str, list[dict]] = {k: [] for k in agents}

    def classify(self, query: str) -> str:
        """Return the agent_id best matching the query via keyword search.

        The first agent whose keyword list has any match wins (dict order matters).
        Falls back to self.default_agent if nothing matches.
        """
        q = query.lower()
        for agent_id, agent in self.agents.items():
            if any(kw in q for kw in agent.keywords):
                return agent_id
        return self.default_agent

    def route_and_run(
        self,
        query: str,
        agent_id: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> tuple[str, str]:
        """Route a query and run it through the selected agent.

        Args:
            query:      User query.
            agent_id:   Force a specific agent (skips classify if provided).
            model:      Override the router-level model for this call.
            max_tokens: Max tokens.

        Returns:
            (agent_id, response_text) tuple so callers know which agent handled it.
        """
        chosen = agent_id or self.classify(query)
        agent = self.agents[chosen]
        response = run_agent(
            self.client,
            agent,
            query,
            history=self.histories[chosen],
            model=model or self.model,
            max_tokens=max_tokens,
        )
        # Update per-agent history for multi-turn support
        self.histories[chosen].append({"role": "user", "content": query})
        self.histories[chosen].append({"role": "assistant", "content": response})
        return chosen, response

    def reset_history(self, agent_id: Optional[str] = None) -> None:
        """Clear conversation history for one agent or all agents."""
        if agent_id:
            self.histories[agent_id] = []
        else:
            self.histories = {k: [] for k in self.agents}
