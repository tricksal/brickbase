"""
agent-api-docs — Dynamic API doc fetching for coding agents.

Prevents API hallucinations by giving agents access to current,
curated, annotatable documentation at runtime.

Brickbase Pattern: github.com/tricksal/brickbase
Source: https://github.com/andrewyng/context-hub
"""

import subprocess
from pathlib import Path
from typing import Optional


# --- Remote Docs via context-hub CLI ---

def fetch_docs(service: str, lang: str = "py") -> str:
    """
    Fetch current API docs for a service via context-hub.
    Requires: npm install -g @aisuite/chub

    Args:
        service: e.g. "openai/chat", "stripe/api", "anthropic/messages"
        lang: "py" or "js"

    Returns:
        Current documentation as markdown string, or error message.
    """
    try:
        result = subprocess.run(
            ["chub", "get", service, "--lang", lang],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        return f"No docs found for '{service}' (lang={lang}). Try: chub search {service.split('/')[0]}"
    except FileNotFoundError:
        return "context-hub not installed. Run: npm install -g @aisuite/chub"
    except subprocess.TimeoutExpired:
        return f"Timeout fetching docs for {service}"


def search_docs(query: str) -> str:
    """
    Search available docs in context-hub.

    Args:
        query: e.g. "stripe", "openai", "payments"

    Returns:
        Search results as string.
    """
    try:
        result = subprocess.run(
            ["chub", "search", query],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout if result.returncode == 0 else f"Search failed: {result.stderr}"
    except FileNotFoundError:
        return "context-hub not installed. Run: npm install -g @aisuite/chub"


def annotate_docs(service: str, note: str) -> str:
    """
    Annotate docs with a finding for future sessions.
    Annotations persist locally and appear on next chub get.

    Args:
        service: e.g. "stripe/api"
        note: what you discovered — gaps, gotchas, workarounds
    """
    try:
        subprocess.run(
            ["chub", "annotate", service, note],
            check=True, capture_output=True, text=True
        )
        return f"Annotated '{service}': {note}"
    except Exception as e:
        return f"Annotation failed: {e}"


def list_annotations() -> str:
    """List all local annotations across all services."""
    try:
        result = subprocess.run(
            ["chub", "annotate", "--list"],
            capture_output=True, text=True
        )
        return result.stdout or "No annotations yet."
    except Exception as e:
        return f"Error: {e}"


# --- Local Docs for internal/private APIs ---

LOCAL_DOCS_DIR = Path("~/.agent-docs").expanduser()


def fetch_local_docs(service: str) -> Optional[str]:
    """
    Fetch locally-maintained docs for internal/private APIs.
    Returns None if no local docs exist.
    """
    path = LOCAL_DOCS_DIR / f"{service.replace('/', '_')}.md"
    return path.read_text() if path.exists() else None


def write_local_docs(service: str, content: str) -> None:
    """
    Write/update local docs for an internal API.
    Use this to maintain docs for services not in context-hub.
    """
    path = LOCAL_DOCS_DIR / f"{service.replace('/', '_')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def get_docs(service: str, lang: str = "py") -> str:
    """
    Smart doc fetch: tries local first, then context-hub.
    One function for all doc needs in agent tool loop.
    """
    local = fetch_local_docs(service)
    if local:
        return f"[Local docs for {service}]\n\n{local}"
    return fetch_docs(service, lang)


# --- Agent Tool Definitions (Anthropic format) ---

TOOLS = [
    {
        "name": "get_api_docs",
        "description": (
            "Fetch current, curated API documentation for a service. "
            "ALWAYS call this before writing code that calls an external API "
            "to avoid hallucinating outdated parameters or methods."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service identifier, e.g. 'openai/chat', 'stripe/api', 'anthropic/messages'"
                },
                "lang": {
                    "type": "string",
                    "enum": ["py", "js"],
                    "description": "Language variant. Default: py",
                    "default": "py"
                }
            },
            "required": ["service"]
        }
    },
    {
        "name": "search_api_docs",
        "description": "Search available API documentation by keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "e.g. 'stripe', 'openai', 'payments'"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "annotate_api_docs",
        "description": (
            "Save a note about an API for future sessions. "
            "Use when you discover gaps, gotchas, or workarounds that aren't in the official docs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "e.g. 'stripe/api'"},
                "note": {"type": "string", "description": "What you discovered"}
            },
            "required": ["service", "note"]
        }
    }
]


def handle_tool(tool_name: str, inputs: dict) -> str:
    """Route tool calls to the right function."""
    if tool_name == "get_api_docs":
        return get_docs(inputs["service"], inputs.get("lang", "py"))
    elif tool_name == "search_api_docs":
        return search_docs(inputs["query"])
    elif tool_name == "annotate_api_docs":
        return annotate_docs(inputs["service"], inputs["note"])
    return f"Unknown tool: {tool_name}"


# --- System Prompt Snippet ---

SYSTEM_PROMPT_ADDON = """
Before writing code that calls any external API (OpenAI, Anthropic, Stripe, etc.):
1. Call get_api_docs to fetch current documentation
2. Write code based on the actual docs, not your training data
3. If you discover undocumented behavior or a gap, call annotate_api_docs

This prevents API hallucinations and makes your code reliable.
"""

if __name__ == "__main__":
    # Quick test
    print("Searching for openai docs...")
    print(search_docs("openai"))
    print("\nFetching openai/chat docs (py)...")
    print(fetch_docs("openai/chat", "py")[:500])
