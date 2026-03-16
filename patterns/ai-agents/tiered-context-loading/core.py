"""
tiered-context-loading — L0/L1/L2 hierarchical context for AI agents.

Organizes agent context in three tiers:
- L0: Always loaded (identity, core rules) — small, permanent
- L1: Session-specific (today's context, active projects) — loaded at start
- L2: On-demand (history, docs, details) — retrieved when needed

Inspired by OpenViking: https://github.com/volcengine/OpenViking

Brickbase Pattern: github.com/tricksal/brickbase
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ContextTier:
    name: str           # "L0", "L1", "L2"
    path: Path          # directory on disk
    files: list[str]    # which filenames to load (L0/L1); empty = all
    always_load: bool   # L0=True, L1=True, L2=False


@dataclass
class LoadedContext:
    tier: str
    source: str        # filename/path — for observability
    content: str
    char_count: int = field(init=False)

    def __post_init__(self):
        self.char_count = len(self.content)


class TieredContextManager:
    """
    Manages L0/L1/L2 context for an AI agent.

    Usage:
        ctx = TieredContextManager(base_dir=Path("~/.agent").expanduser())
        system_prompt = ctx.load_session_context()
        # Agent runs with system_prompt
        ctx.compact_l1(agent_summary)  # at session end
    """

    def __init__(self, base_dir: Path):
        self.base = base_dir
        self.base.mkdir(parents=True, exist_ok=True)

        self.l0_dir = base_dir / "L0"
        self.l1_dir = base_dir / "L1"
        self.l2_dir = base_dir / "L2"

        for d in [self.l0_dir, self.l1_dir, self.l2_dir]:
            d.mkdir(exist_ok=True)

        self._loaded: list[LoadedContext] = []

    # ------------------------------------------------------------------ #
    # Session Init

    def load_session_context(self) -> str:
        """
        Build the full system prompt for a new session.
        Loads L0 (always) + L1 (session-specific).
        Returns formatted context string ready to use as system prompt.
        """
        self._loaded = []
        parts: list[str] = []

        # L0: always loaded, every file
        l0_parts = self._load_dir(self.l0_dir, tier="L0")
        if l0_parts:
            parts.append("## CORE CONTEXT (L0)\n\n" + "\n\n---\n\n".join(
                c.content for c in l0_parts
            ))

        # L1: session-specific
        l1_parts = self._load_dir(self.l1_dir, tier="L1")
        if l1_parts:
            parts.append("## SESSION CONTEXT (L1)\n\n" + "\n\n---\n\n".join(
                c.content for c in l1_parts
            ))

        self._loaded = l0_parts + l1_parts
        return "\n\n".join(parts)

    def _load_dir(self, directory: Path, tier: str) -> list[LoadedContext]:
        """Load all .md and .txt files from a directory."""
        results = []
        for f in sorted(directory.glob("*.md")) + sorted(directory.glob("*.txt")):
            try:
                content = f.read_text(encoding="utf-8").strip()
                if content:
                    results.append(LoadedContext(
                        tier=tier,
                        source=str(f.relative_to(self.base)),
                        content=content,
                    ))
            except Exception as e:
                print(f"[TieredContext] Error reading {f}: {e}")
        return results

    # ------------------------------------------------------------------ #
    # L2: On-Demand Retrieval

    def retrieve_l2(self, query: str, top_k: int = 3) -> list[LoadedContext]:
        """
        Retrieve relevant L2 documents for a query.
        Simple keyword search — replace with semantic search for production.

        Args:
            query: what to search for
            top_k: how many results to return

        Returns:
            List of LoadedContext sorted by relevance.
        """
        query_terms = set(query.lower().split())
        results: list[tuple[int, LoadedContext]] = []

        for f in self.l2_dir.rglob("*.md"):
            try:
                content = f.read_text(encoding="utf-8")
                score = sum(
                    1 for term in query_terms
                    if term in content.lower()
                )
                if score > 0:
                    results.append((score, LoadedContext(
                        tier="L2",
                        source=str(f.relative_to(self.base)),
                        content=content.strip()
                    )))
            except Exception:
                pass

        results.sort(key=lambda x: x[0], reverse=True)
        return [ctx for _, ctx in results[:top_k]]

    def get_l2_file(self, relative_path: str) -> Optional[str]:
        """
        Directly fetch a specific L2 file by path.
        Use when you know exactly what you need (no retrieval needed).
        """
        path = self.l2_dir / relative_path
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def write_l2(self, relative_path: str, content: str) -> None:
        """Write or update a file in L2 storage."""
        path = self.l2_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Context Evolution

    def compact_l1(self, session_summary: str) -> None:
        """
        Called at session end. Compresses session context:
        1. Saves summary to L2 (history)
        2. Clears volatile L1 files
        3. Updates L1/today.md with distilled facts

        Args:
            session_summary: what happened this session (from LLM)
        """
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Archive to L2
        archive_path = f"memory/{today}.md"
        existing = self.get_l2_file(archive_path) or ""
        self.write_l2(archive_path, existing + f"\n\n## Session {timestamp}\n\n{session_summary}")

        # Update L1 today.md
        today_path = self.l1_dir / "today.md"
        self._update_today(today_path, session_summary)

    def _update_today(self, path: Path, summary: str) -> None:
        """Keep only the most recent summary in today.md."""
        timestamp = datetime.now().strftime("%H:%M")
        content = path.read_text() if path.exists() else f"# Today — {datetime.now().strftime('%Y-%m-%d')}\n"

        # Append latest
        content += f"\n## {timestamp}\n{summary}\n"

        # Trim if too long (keep L1 small)
        lines = content.splitlines()
        if len(lines) > 100:
            content = "\n".join(lines[-80:])  # keep last 80 lines

        path.write_text(content, encoding="utf-8")

    def promote_to_l0(self, fact: str, filename: str = "promoted_facts.md") -> None:
        """
        Promote a fact from session learning into permanent L0 context.
        Use sparingly — L0 is always loaded and should stay small.

        Args:
            fact: the fact/rule to permanently remember
            filename: which L0 file to append to
        """
        path = self.l0_dir / filename
        existing = path.read_text() if path.exists() else "# Promoted Facts\n\n"
        timestamp = datetime.now().strftime("%Y-%m-%d")
        path.write_text(existing + f"- [{timestamp}] {fact}\n", encoding="utf-8")

    # ------------------------------------------------------------------ #
    # Observability

    def get_load_report(self) -> dict:
        """
        Returns a report of what was loaded and why.
        Use for debugging — no more RAG black box.
        """
        return {
            "loaded": [
                {
                    "tier": c.tier,
                    "source": c.source,
                    "chars": c.char_count
                }
                for c in self._loaded
            ],
            "total_chars": sum(c.char_count for c in self._loaded),
            "by_tier": {
                tier: sum(c.char_count for c in self._loaded if c.tier == tier)
                for tier in ["L0", "L1", "L2"]
            }
        }


# ------------------------------------------------------------------ #
# Minimal Setup Helper

def create_agent_context(
    base_dir: Path,
    identity: str,
    user_info: str = "",
    core_rules: str = ""
) -> TieredContextManager:
    """
    Bootstrap a new TieredContextManager with L0 content.

    Args:
        base_dir: where to store context files
        identity: who is the agent (name, role, vibe)
        user_info: who is the user
        core_rules: permanent rules and constraints
    """
    ctx = TieredContextManager(base_dir)

    if identity:
        (ctx.l0_dir / "identity.md").write_text(f"# Agent Identity\n\n{identity}")
    if user_info:
        (ctx.l0_dir / "user.md").write_text(f"# User Context\n\n{user_info}")
    if core_rules:
        (ctx.l0_dir / "rules.md").write_text(f"# Core Rules\n\n{core_rules}")

    return ctx


# ------------------------------------------------------------------ #
# Agent Tool: L2 Retrieval

RETRIEVE_TOOL = {
    "name": "retrieve_context",
    "description": (
        "Search long-term context (L2) for relevant information. "
        "Use when you need details not already in your current context "
        "(history, old docs, project files)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for in long-term memory"
            },
            "top_k": {
                "type": "integer",
                "description": "How many results to return (default: 3)",
                "default": 3
            }
        },
        "required": ["query"]
    }
}


if __name__ == "__main__":
    # Quick demo
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        ctx = create_agent_context(
            base_dir=Path(tmp),
            identity="Botto — Familienbot der Familie Magold. Locker, hilfreich, direkt.",
            user_info="Arne Magold — Creative Coder, Tricksal GmbH, München.",
            core_rules="Kein em-dash. Kein Sycophanting. Files > mental notes.",
        )

        # Write some L1 and L2 content
        (ctx.l1_dir / "today.md").write_text("# Heute\n\n- SuperRig Assessment deployed")
        ctx.write_l2("projects/superrig.md", "# SuperRig\n\nFastAPI app, Port 7780, /opt/superrig-app/")

        # Load session
        system_prompt = ctx.load_session_context()
        print("=== System Prompt ===")
        print(system_prompt[:500])

        # Retrieve L2
        results = ctx.retrieve_l2("superrig deployment")
        print(f"\n=== L2 Retrieval ({len(results)} results) ===")
        for r in results:
            print(f"  [{r.tier}] {r.source}: {r.content[:100]}")

        # Load report
        print("\n=== Load Report ===")
        print(json.dumps(ctx.get_load_report(), indent=2))
