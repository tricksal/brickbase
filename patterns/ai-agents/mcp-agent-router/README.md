# Pattern: mcp-agent-router

## What it does
Routes user queries to **specialized agents**, each with only the MCP tools it needs — instead of one bloated agent with every tool.

A lightweight keyword classifier picks the right agent. Each agent runs its own isolated MCP server connections and an autonomous tool-call loop until the task is done.

## When to use
- You have 2+ distinct domains (code, research, security, data, …)
- Different domains need different external tools (GitHub, browser, DB, APIs)
- You want cheaper/faster calls by limiting each agent's tool surface
- You want cleaner prompts (focused system prompts > one mega-prompt)

## Core concepts

| Concept | Description |
|---|---|
| `Agent` | Dataclass: name, system_prompt, keyword list, MCP server configs |
| `AgentRouter` | Classifies queries → selects agent → runs it |
| `classify()` | Keyword match over agent.keywords; falls back to default_agent |
| `run_agent()` | Connects MCP servers, enters agentic loop, returns final text |
| Per-agent history | Each agent gets its own conversation history (multi-turn) |

## File
```
core.py   ← drop in, subclass or compose
```

## Quick usage
```python
from core import Agent, AgentRouter

researcher = Agent(
    name="Researcher",
    description="Fetches and synthesizes web content",
    system_prompt="You are a research assistant. Cite your sources.",
    keywords=["research", "find", "what is", "explain", "summarize"],
    mcp_servers=[
        {"name": "fetch", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"]},
    ],
)

coder = Agent(
    name="Code Reviewer",
    description="Reviews code for bugs and quality",
    system_prompt="You are an expert code reviewer. Be specific, cite line numbers.",
    keywords=["review", "bug", "refactor", "code", "pr", "pull request"],
    mcp_servers=[
        {"name": "github", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
        {"name": "filesystem", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]},
    ],
)

router = AgentRouter(
    agents={"researcher": researcher, "coder": coder},
    default_agent="researcher",
)

agent_id, response = router.route_and_run("Review this PR for security issues")
print(f"[{agent_id}] {response}")
```

## MCP server config format
```python
{
    "name": "my-server",        # display name only
    "command": "npx",           # executable
    "args": ["-y", "@mcp/server-fetch"],  # args list
    "env": {"API_KEY": "..."},  # optional extra env vars
}
```

## Extension points
- **Custom classifier:** Override `AgentRouter.classify()` for LLM-based routing
- **Parallel agents:** Run `_run_agent_async()` concurrently for fan-out patterns
- **Agent chaining:** Pass one agent's response as query to another
- **Persistent history:** Serialize `router.histories` between sessions

## Dependencies
```
anthropic>=0.25
mcp>=1.0
```

## Source
Extracted from: https://github.com/Shubhamsaboo/awesome-llm-apps  
Path: `mcp_ai_agents/multi_mcp_agent_router/agent_forge.py`
