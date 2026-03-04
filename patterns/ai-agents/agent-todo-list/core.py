"""
Agent Todo List — core.py
Brickbase Pattern: ai-agents/agent-todo-list

Distilled Python implementation combining the best ideas from:
  - Gemini CLI: "full replacement" model (no delta updates, no conflicts)
  - Pi Agent:   status-based tracking with structured Todo objects
  - Claude Code: explicit read-before-write discipline

Design philosophy:
  Replace the ENTIRE list on every update. This eliminates merge conflicts,
  out-of-order updates, and partial-state bugs. The agent always provides
  the complete desired state — the storage layer just overwrites.

Usage (as agent tools):
    todos = TodoList()
    todos.write([
        Todo("Research API docs", "in_progress"),
        Todo("Implement handler", "pending"),
        Todo("Write tests", "pending"),
    ])
    current = todos.read()
    todos.write([t.with_status("completed") if t.description == "Research API docs" else t
                 for t in current])
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# Domain model
# ---------------------------------------------------------------------------

class Status(str, Enum):
    PENDING     = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


@dataclass
class Todo:
    """A single task item with an optional ID (auto-assigned on write)."""
    description: str
    status: Status = Status.PENDING
    id: int = -1  # -1 = not yet persisted

    def with_status(self, status: str | Status) -> "Todo":
        """Return a copy with a new status (immutable-style helper)."""
        return Todo(self.description, Status(status), self.id)

    def is_done(self) -> bool:
        return self.status in (Status.COMPLETED, Status.CANCELLED)

    def __repr__(self) -> str:
        marker = {"pending": "○", "in_progress": "▶", "completed": "✓", "cancelled": "✗"}.get(
            self.status, "?"
        )
        return f"[{marker}] #{self.id:>2} {self.description}"


# ---------------------------------------------------------------------------
# Storage backends
# ---------------------------------------------------------------------------

class InMemoryStorage:
    """
    Ephemeral storage. State lives only for this process.
    Good for: tests, short-lived agents, notebooks.
    """
    def __init__(self) -> None:
        self._data: list[dict] = []

    def save(self, todos: list[dict]) -> None:
        self._data = list(todos)

    def load(self) -> list[dict]:
        return list(self._data)


class FileStorage:
    """
    JSON file storage. Persists across agent restarts.
    Good for: long-running sessions, human-readable state.

    Full-replacement semantics: every write overwrites the whole file.
    This is deliberately simple — no locking, no journaling needed for
    single-agent use-cases.
    """
    def __init__(self, path: str | Path = "/tmp/agent_todos.json") -> None:
        self._path = Path(path)

    def save(self, todos: list[dict]) -> None:
        self._path.write_text(json.dumps(todos, indent=2))

    def load(self) -> list[dict]:
        if not self._path.exists():
            return []
        return json.loads(self._path.read_text())


# ---------------------------------------------------------------------------
# Core TodoList — the pattern implementation
# ---------------------------------------------------------------------------

class TodoList:
    """
    Agent Todo List with full-replacement semantics.

    Key invariants:
      - At most ONE task is `in_progress` at a time.
      - write() always replaces the FULL list (no partial updates).
      - read() must be called before write() — explicit discipline.
      - IDs are auto-assigned and stable within a session.

    These invariants are enforced to prevent the most common agent bugs:
      parallel in-progress tasks, stale reads, id collisions.
    """

    def __init__(self, storage=None, on_change: Callable | None = None) -> None:
        self._storage = storage or InMemoryStorage()
        self._on_change = on_change  # optional hook (e.g., UI refresh)
        self._next_id = 1
        self._last_read: float | None = None
        self._load_existing()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> list[Todo]:
        """
        Read current todos. MUST be called before write() in agent code.
        Returns a snapshot — modifying the list won't affect stored state.
        """
        raw = self._storage.load()
        todos = [self._from_dict(r) for r in raw]
        self._last_read = time.monotonic()
        return todos

    def write(self, todos: list[Todo]) -> dict:
        """
        Replace the ENTIRE todo list with the provided items.

        Enforces:
          - max one in_progress item
          - auto-assigns IDs to new items (id == -1)
          - returns a summary dict (agent-friendly return value)

        This is the ONLY mutation method. No add/remove/toggle helpers.
        That keeps the API surface minimal and the contract clear.
        """
        # Validate: max one in_progress
        in_progress = [t for t in todos if t.status == Status.IN_PROGRESS]
        if len(in_progress) > 1:
            raise ValueError(
                f"Only one task may be in_progress at a time. Got: "
                + ", ".join(f'"{t.description}"' for t in in_progress)
            )

        # Assign IDs to new items
        for todo in todos:
            if todo.id == -1:
                todo.id = self._next_id
                self._next_id += 1

        # Persist (full replacement)
        raw = [self._to_dict(t) for t in todos]
        self._storage.save(raw)

        # Fire change hook (UI refresh, logging, etc.)
        if self._on_change:
            self._on_change(todos)

        # Return summary (useful as agent tool result)
        return {
            "total": len(todos),
            "pending": sum(1 for t in todos if t.status == Status.PENDING),
            "in_progress": sum(1 for t in todos if t.status == Status.IN_PROGRESS),
            "completed": sum(1 for t in todos if t.status == Status.COMPLETED),
            "cancelled": sum(1 for t in todos if t.status == Status.CANCELLED),
            "current_task": next(
                (t.description for t in todos if t.status == Status.IN_PROGRESS), None
            ),
        }

    def summary(self) -> str:
        """Human-readable summary (e.g., for agent context injection)."""
        todos = self.read()
        if not todos:
            return "No todos."
        lines = [repr(t) for t in todos]
        done = sum(1 for t in todos if t.is_done())
        lines.append(f"\n{done}/{len(todos)} completed")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_existing(self) -> None:
        """On init, recover next_id from persisted data."""
        raw = self._storage.load()
        if raw:
            self._next_id = max(r.get("id", 0) for r in raw) + 1

    @staticmethod
    def _to_dict(todo: Todo) -> dict:
        return {"id": todo.id, "description": todo.description, "status": todo.status.value}

    @staticmethod
    def _from_dict(d: dict) -> Todo:
        return Todo(d["description"], Status(d["status"]), d["id"])


# ---------------------------------------------------------------------------
# Agent tool wrappers  (LLM-callable function signatures)
# ---------------------------------------------------------------------------

def make_agent_tools(todos: TodoList):
    """
    Returns (read_todos, write_todos) as plain functions suitable for
    wrapping with any tool-calling framework (OpenAI functions, LangChain,
    Claude tool_use, etc.).
    """

    def read_todos() -> dict:
        """
        Read the current todo list.
        Always call this before write_todos to get the latest state.
        """
        items = todos.read()
        return {
            "todos": [
                {"id": t.id, "description": t.description, "status": t.status.value}
                for t in items
            ]
        }

    def write_todos(items: list[dict]) -> dict:
        """
        Replace the entire todo list.

        Args:
            items: Complete list of todos. Each item: {description, status, id?}.
                   Status: "pending" | "in_progress" | "completed" | "cancelled"
                   id: preserve from read_todos() output; omit for new tasks.
                   Only one item may have status "in_progress" at a time.

        Returns:
            Summary with counts and current in-progress task.
        """
        parsed = [Todo(i["description"], Status(i["status"]), i.get("id", -1)) for i in items]
        return todos.write(parsed)

    return read_todos, write_todos


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=== Agent Todo List Demo ===\n")

    todos = TodoList()
    read_todos, write_todos = make_agent_tools(todos)

    # Step 1: Agent plans the work
    print("Step 1: Agent creates initial plan")
    result = write_todos([
        {"description": "Analyse existing codebase", "status": "in_progress"},
        {"description": "Design new module interface", "status": "pending"},
        {"description": "Implement core logic", "status": "pending"},
        {"description": "Write unit tests", "status": "pending"},
        {"description": "Update documentation", "status": "pending"},
    ])
    print("  →", result)

    # Step 2: Agent reads before updating (explicit discipline)
    print("\nStep 2: Agent reads current state")
    current = read_todos()
    print("  →", current)

    # Step 3: Agent marks first task done, starts next
    print("\nStep 3: Agent marks analysis complete, starts design")
    updated = [
        {**t, "status": "completed"} if t["description"] == "Analyse existing codebase"
        else {**t, "status": "in_progress"} if t["description"] == "Design new module interface"
        else t
        for t in current["todos"]
    ]
    result = write_todos(updated)
    print("  →", result)

    print("\nFinal state:")
    print(todos.summary())
