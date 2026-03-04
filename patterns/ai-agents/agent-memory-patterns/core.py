"""
Agent Memory Patterns — Core Implementations
==============================================
Brickbase Pattern: agent-memory-patterns
https://github.com/tricksal/brickbase/tree/main/patterns/ai-agents/agent-memory-patterns

Two self-contained implementations:
1. SimpleFileMemory  — Read/Write/Search in a Markdown file (zero deps, practical)
2. LayeredMemory     — Working + Episodic + Long-Term memory (Mem0-style, no external deps)

Run directly:
    python core.py
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, date
from pathlib import Path
from typing import Optional


# ===========================================================================
# 1. SimpleFileMemory
#    Inspired by: OpenClaw MEMORY.md pattern, opencode-agent-memory plugin
#    Idea: Agent reads/writes plain Markdown — dead simple, portable, auditable
# ===========================================================================

class SimpleFileMemory:
    """
    File-based persistent memory backed by a single Markdown file.

    Layout:
        # Memory
        ## [timestamp] <key>
        <value>

    The agent can add, update, delete, and search entries. Everything is human-
    readable and survives process restarts. Works with any LLM system that can
    call tools (read_file, write_file) or via direct API.

    Usage:
        mem = SimpleFileMemory("memory/MEMORY.md")
        mem.write("user_name", "Alice")
        mem.write("project", "Builds a recipe app in Python")
        results = mem.search("recipe")    # keyword search
        val = mem.read("user_name")       # exact key lookup
        mem.delete("user_name")
    """

    def __init__(self, path: str | Path = "MEMORY.md"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("# Memory\n\n")

    # -----------------------------------------------------------------------
    # Core CRUD
    # -----------------------------------------------------------------------

    def write(self, key: str, value: str) -> None:
        """Add or update a memory entry."""
        content = self.path.read_text(encoding="utf-8")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        new_section = f"\n## [{timestamp}] {key}\n{value.strip()}\n"

        # Remove existing entry with same key if present
        pattern = rf"\n## \[.*?\] {re.escape(key)}\n.*?(?=\n## |\Z)"
        content = re.sub(pattern, "", content, flags=re.DOTALL)

        self.path.write_text(content.rstrip() + new_section, encoding="utf-8")

    def read(self, key: str) -> Optional[str]:
        """Read a specific memory entry by key. Returns None if not found."""
        content = self.path.read_text(encoding="utf-8")
        pattern = rf"## \[.*?\] {re.escape(key)}\n(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, flags=re.DOTALL)
        return match.group(1).strip() if match else None

    def delete(self, key: str) -> bool:
        """Delete a memory entry. Returns True if deleted."""
        content = self.path.read_text(encoding="utf-8")
        pattern = rf"\n## \[.*?\] {re.escape(key)}\n.*?(?=\n## |\Z)"
        new_content, count = re.subn(pattern, "", content, flags=re.DOTALL)
        if count:
            self.path.write_text(new_content, encoding="utf-8")
        return count > 0

    def list_keys(self) -> list[str]:
        """List all memory keys."""
        content = self.path.read_text(encoding="utf-8")
        return re.findall(r"## \[.*?\] (.+)", content)

    # -----------------------------------------------------------------------
    # Search (keyword-based, sufficient for most agent use-cases)
    # -----------------------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> list[dict]:
        """
        Simple keyword search across all memory entries.
        Returns list of {key, value, score} sorted by relevance.

        For semantic search, swap this for a vector store (see LayeredMemory).
        """
        content = self.path.read_text(encoding="utf-8")
        entries = re.findall(
            r"## \[(.*?)\] (.+?)\n(.*?)(?=\n## |\Z)", content, flags=re.DOTALL
        )
        query_terms = query.lower().split()
        results = []
        for timestamp, key, value in entries:
            text = f"{key} {value}".lower()
            score = sum(term in text for term in query_terms)
            if score > 0:
                results.append({
                    "key": key,
                    "value": value.strip(),
                    "timestamp": timestamp,
                    "score": score,
                })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def dump(self) -> str:
        """Return the full raw Markdown content (for injection into system prompt)."""
        return self.path.read_text(encoding="utf-8")

    def __repr__(self) -> str:
        keys = self.list_keys()
        return f"SimpleFileMemory(path={self.path}, entries={len(keys)})"


# ===========================================================================
# 2. LayeredMemory
#    Inspired by: Mem0 (multi-level), Letta/MemGPT (hierarchical blocks)
#    Idea: Three tiers — Working (current session) → Episodic → Long-Term
#
#    Memory Hierarchy:
#
#    ┌──────────────────────────────────┐
#    │  Working Memory (in-context RAM) │  ← Current session facts, fast access
#    │  max_working_size items          │
#    └──────────────┬───────────────────┘
#                   │ overflow / end-of-session flush
#    ┌──────────────▼───────────────────┐
#    │  Episodic Memory (recent events) │  ← Timestamped experiences, last N days
#    │  JSON log, per-day files         │
#    └──────────────┬───────────────────┘
#                   │ consolidation / promotion
#    ┌──────────────▼───────────────────┐
#    │  Long-Term Memory (semantic)     │  ← Distilled facts, preferences, skills
#    │  Markdown + keyword index        │
#    └──────────────────────────────────┘
#
#    The agent uses remember() to store facts (automatically tiered).
#    recall() searches across all layers, weighted by recency.
#    consolidate() promotes important episodic memories to long-term.
# ===========================================================================

class LayeredMemory:
    """
    Three-tier memory system (no external dependencies):

    - Working Memory: in-process dict (current session, fast, not persisted)
    - Episodic Memory: JSON log files (daily, persisted, timestamped)
    - Long-Term Memory: consolidated Markdown (slow to write, durable, searchable)

    For production use, replace the keyword-search recall() with vector
    embeddings (e.g. mem0ai, sentence-transformers, or an LLM embedding API).

    Usage:
        mem = LayeredMemory(base_dir="./agent_memory")
        mem.remember("user likes Python", tier="working")
        mem.remember("user completed onboarding", tier="episodic")
        mem.remember("user prefers concise answers", tier="long_term")

        results = mem.recall("Python preferences")
        mem.end_session()    # flushes working → episodic
        mem.consolidate()    # promotes episodic → long_term (call periodically)
    """

    TIERS = ("working", "episodic", "long_term")

    def __init__(
        self,
        base_dir: str | Path = "./agent_memory",
        max_working_size: int = 50,
        episodic_retention_days: int = 30,
    ):
        self.base_dir = Path(base_dir)
        self.max_working_size = max_working_size
        self.episodic_retention_days = episodic_retention_days
        self._session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Dirs
        self._episodic_dir = self.base_dir / "episodic"
        self._long_term_file = self.base_dir / "long_term.md"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._episodic_dir.mkdir(exist_ok=True)
        if not self._long_term_file.exists():
            self._long_term_file.write_text("# Long-Term Memory\n\n")

        # Working memory: simple list of {content, importance, ts}
        self._working: list[dict] = []

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def remember(
        self,
        content: str,
        tier: str = "working",
        importance: float = 0.5,
        tags: list[str] | None = None,
    ) -> None:
        """
        Store a memory in the specified tier.

        Args:
            content:    The fact/experience to remember.
            tier:       'working' | 'episodic' | 'long_term'
            importance: 0.0–1.0, used during consolidation to decide promotion.
            tags:       Optional labels for filtering (e.g. ['user_pref', 'skill']).
        """
        if tier not in self.TIERS:
            raise ValueError(f"tier must be one of {self.TIERS}")

        entry = {
            "content": content,
            "importance": importance,
            "tags": tags or [],
            "ts": time.time(),
            "session": self._session_id,
        }

        if tier == "working":
            self._working.append(entry)
            # Overflow: spill oldest low-importance items to episodic
            if len(self._working) > self.max_working_size:
                spilled = self._working.pop(0)
                self._append_episodic(spilled)

        elif tier == "episodic":
            self._append_episodic(entry)

        elif tier == "long_term":
            self._append_long_term(entry)

    def _append_episodic(self, entry: dict) -> None:
        """Append an entry to today's episodic log file."""
        today = date.today().isoformat()
        log_file = self._episodic_dir / f"{today}.jsonl"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _append_long_term(self, entry: dict) -> None:
        """Append a consolidated fact to the long-term Markdown store."""
        ts_str = datetime.fromtimestamp(entry["ts"]).strftime("%Y-%m-%d %H:%M")
        tags_str = " ".join(f"#{t}" for t in entry["tags"]) if entry["tags"] else ""
        line = f"\n- [{ts_str}] {entry['content']}  {tags_str}\n"
        with self._long_term_file.open("a", encoding="utf-8") as f:
            f.write(line)

    # -----------------------------------------------------------------------
    # Read / Recall
    # -----------------------------------------------------------------------

    def recall(self, query: str, limit: int = 10) -> list[dict]:
        """
        Search across all three tiers. Returns ranked results.

        Scoring: keyword overlap + recency bonus + importance weight.
        For production: replace keyword scoring with cosine similarity on embeddings.
        """
        query_terms = set(query.lower().split())
        results: list[dict] = []

        def score_entry(entry: dict, tier: str) -> dict | None:
            text = entry["content"].lower()
            # Add tags to searchable text
            text += " " + " ".join(entry.get("tags", []))
            keyword_score = sum(1 for t in query_terms if t in text) / max(len(query_terms), 1)
            if keyword_score == 0:
                return None
            # Recency: normalize age to [0, 1] where 1 = now
            age_days = (time.time() - entry["ts"]) / 86400
            recency = max(0.0, 1.0 - age_days / max(self.episodic_retention_days, 1))
            # Combined score
            combined = (keyword_score * 0.5) + (recency * 0.3) + (entry.get("importance", 0.5) * 0.2)
            return {
                "tier": tier,
                "content": entry["content"],
                "tags": entry.get("tags", []),
                "ts": entry["ts"],
                "score": round(combined, 3),
                "session": entry.get("session"),
            }

        # Working memory
        for entry in self._working:
            r = score_entry(entry, "working")
            if r:
                results.append(r)

        # Episodic memory (recent files)
        for log_file in sorted(self._episodic_dir.glob("*.jsonl"), reverse=True):
            try:
                for line in log_file.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        entry = json.loads(line)
                        r = score_entry(entry, "episodic")
                        if r:
                            results.append(r)
            except Exception:
                pass

        # Long-term memory
        lt_content = self._long_term_file.read_text(encoding="utf-8")
        for line in lt_content.splitlines():
            match = re.match(r"- \[(.+?)\] (.+?)(?:\s+(#\S+(?:\s+#\S+)*))?$", line.strip())
            if match:
                ts_str, content, tags_str = match.groups()
                tags = re.findall(r"#(\S+)", tags_str or "")
                try:
                    ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M").timestamp()
                except ValueError:
                    ts = time.time()
                entry = {"content": content, "tags": tags, "ts": ts, "importance": 0.7}
                r = score_entry(entry, "long_term")
                if r:
                    results.append(r)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_working_context(self) -> str:
        """
        Return working memory formatted for injection into an LLM system prompt.
        Letta-style: this is the agent's 'core memory block'.
        """
        if not self._working:
            return "[Working memory is empty]"
        lines = [f"- {e['content']}" for e in self._working]
        return "## Working Memory\n" + "\n".join(lines)

    # -----------------------------------------------------------------------
    # Session management
    # -----------------------------------------------------------------------

    def end_session(self) -> int:
        """
        Flush all working memory to episodic store.
        Call this at the end of each agent session (before context compaction).
        Returns number of flushed entries.
        """
        count = len(self._working)
        for entry in self._working:
            self._append_episodic(entry)
        self._working.clear()
        return count

    def consolidate(self, min_importance: float = 0.7) -> int:
        """
        Promote high-importance episodic memories to long-term storage.
        Prunes episodic entries older than `episodic_retention_days`.

        Call periodically (e.g. once per day, or via a cron-style agent turn).
        Returns number of entries promoted.
        """
        promoted = 0
        cutoff_ts = time.time() - (self.episodic_retention_days * 86400)

        for log_file in sorted(self._episodic_dir.glob("*.jsonl")):
            surviving_lines = []
            try:
                for line in log_file.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    if entry.get("importance", 0) >= min_importance:
                        # Promote to long-term
                        self._append_long_term(entry)
                        promoted += 1
                        # Don't keep in episodic (dedup)
                    elif entry.get("ts", 0) < cutoff_ts:
                        # Old + low-importance: discard
                        pass
                    else:
                        surviving_lines.append(line)
            except Exception:
                continue

            log_file.write_text("\n".join(surviving_lines) + ("\n" if surviving_lines else ""), encoding="utf-8")

        return promoted

    def stats(self) -> dict:
        """Return memory statistics across all tiers."""
        episodic_count = sum(
            sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
            for f in self._episodic_dir.glob("*.jsonl")
        )
        lt_count = len([
            l for l in self._long_term_file.read_text(encoding="utf-8").splitlines()
            if l.startswith("- [")
        ])
        return {
            "working": len(self._working),
            "episodic": episodic_count,
            "long_term": lt_count,
            "session_id": self._session_id,
        }

    def __repr__(self) -> str:
        s = self.stats()
        return f"LayeredMemory(working={s['working']}, episodic={s['episodic']}, long_term={s['long_term']})"


# ===========================================================================
# Demo / Quick test
# ===========================================================================

def demo_simple_file_memory():
    print("=== SimpleFileMemory Demo ===")
    mem = SimpleFileMemory("/tmp/demo_memory.md")
    mem.write("user_name", "Alice")
    mem.write("project", "Builds a recipe recommendation app in Python")
    mem.write("preferences", "Concise answers, code examples preferred")
    mem.write("last_topic", "Vector databases and embeddings")

    print(f"Keys: {mem.list_keys()}")
    print(f"Read 'user_name': {mem.read('user_name')}")
    print(f"Search 'Python': {mem.search('Python')}")
    print(f"Search 'recipe': {mem.search('recipe')}")
    print()


def demo_layered_memory():
    print("=== LayeredMemory Demo ===")
    mem = LayeredMemory("/tmp/demo_layered_memory")

    # Working memory: current session facts
    mem.remember("User's name is Bob", tier="working", importance=0.8)
    mem.remember("User is working on a web scraper in Python", tier="working", importance=0.6)
    mem.remember("User is frustrated with rate limiting", tier="working", importance=0.4)

    # Episodic: log this interaction
    mem.remember("Helped Bob debug a requests.Session timeout issue", tier="episodic", importance=0.75, tags=["debug", "python"])
    mem.remember("Bob prefers asyncio over threading", tier="episodic", importance=0.85, tags=["preference"])

    # Long-term: distilled facts that should always be available
    mem.remember("Bob is an experienced Python dev, skip basics", tier="long_term", tags=["user_profile"])

    print(f"Stats: {mem.stats()}")
    print(f"\nWorking context:\n{mem.get_working_context()}")
    print(f"\nRecall 'Python': {mem.recall('Python', limit=3)}")
    print(f"\nRecall 'asyncio': {mem.recall('asyncio', limit=3)}")

    # End session: flush working → episodic
    flushed = mem.end_session()
    print(f"\nEnd session: flushed {flushed} working entries to episodic")

    # Consolidate: promote high-importance episodic → long-term
    promoted = mem.consolidate(min_importance=0.8)
    print(f"Consolidation: promoted {promoted} entries to long-term")
    print(f"Stats after: {mem.stats()}")


if __name__ == "__main__":
    demo_simple_file_memory()
    demo_layered_memory()
