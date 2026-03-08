# mcp-agent-router

## What is this?
Route user queries to specialized agents, each with access to only the MCP tools they need. Instead of one all-knowing agent, you get clean separation of concerns and minimal tool surface per agent.

## When to use?
- You have multiple domains (code review, research, security, etc.)
- Each domain needs different external tools (GitHub MCP, Fetch MCP, Filesystem MCP...)
- You want automatic routing by intent, or explicit agent selection
- You need per-agent conversation memory within a session

## Core Concept

```
User Query
    │
    ▼
[Router] classifies intent
    │
    ├── Code Review  ──► Agent A: [GitHub MCP, Filesystem MCP]
    ├── Security     ──► Agent B: [GitHub MCP, Fetch MCP]
    ├── Research     ──► Agent C: [Fetch MCP, Filesystem MCP]
    └── Custom       ──► Agent D: [Your MCP]
```

Each specialist agent only sees the tools it needs — safer, cheaper, more focused.

## Dependencies
```
anthropic
mcp
```

## Usage
```python
from core import Agent, MCPAgentRouter

# Define specialist agents
agents = {
    "code_reviewer": Agent(
        name="Code Reviewer",
        system_prompt="You are an expert code reviewer...",
        mcp_servers=[
            {"name": "github", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
        ],
    ),
    "researcher": Agent(
        name="Researcher",
        system_prompt="You are a research specialist...",
        mcp_servers=[
            {"name": "fetch", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-fetch"]},
        ],
    ),
}

router = MCPAgentRouter(agents=agents, api_key="your-anthropic-key")

# Auto-route by intent
response = await router.route_and_run("Review this PR for security issues")

# Or explicitly select agent
response = await router.run_agent("researcher", "What is the latest on MCP?")
```

## Key Properties
- **Minimal tool surface**: each agent only gets what it needs
- **Per-agent memory**: conversation history kept separate
- **Auto-routing**: LLM classifies intent → picks specialist
- **Streaming-ready**: async generator for streamed responses

## Source
- Original Repo: https://github.com/Shubhamsaboo/awesome-llm-apps
- Extracted: 2026-03-08
