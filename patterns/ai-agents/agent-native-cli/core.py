"""
agent-native-cli — Brick Pattern
=================================
A reusable blueprint for building CLI tools that are optimized for AI agents.

Key features:
  - Dual output mode: JSON (for agents) or human-readable (for humans)
  - Stateful session with undo/redo (persists to disk)
  - REPL mode for interactive agent loops
  - Self-documenting via --help flags
  - Structured command groups (verb + noun)

Usage:
    python core.py --help
    python core.py --json status
    python core.py repl

Inspired by: https://github.com/HKUDS/CLI-Anything
"""

import json
import os
import time
import click
from pathlib import Path
from typing import Any, Optional


# ─────────────────────────────────────────────
# SESSION — Stateful context with undo/redo
# ─────────────────────────────────────────────

SESSION_DIR = Path.home() / ".agent-cli" / "sessions"
MAX_UNDO_DEPTH = 50


class Session:
    """
    A persistent, stateful session for a CLI tool.
    Survives process restarts. Supports undo/redo.

    Usage:
        session = Session.load_or_create("my-tool")
        session.checkpoint()      # before any mutation
        session.state["key"] = "value"
        session.save()
        session.undo()
    """

    def __init__(self, tool_name: str, session_id: Optional[str] = None):
        self.tool_name = tool_name
        self.session_id = session_id or f"session_{int(time.time())}"
        self.state: dict = {}
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._session_path = SESSION_DIR / tool_name / f"{self.session_id}.json"

    @classmethod
    def load_or_create(cls, tool_name: str) -> "Session":
        """Load last session or create a new one."""
        session_dir = SESSION_DIR / tool_name
        session_dir.mkdir(parents=True, exist_ok=True)

        # Find most recent session
        sessions = sorted(session_dir.glob("*.json"), key=lambda p: p.stat().st_mtime)
        if sessions:
            s = cls(tool_name)
            s._session_path = sessions[-1]
            s._load()
            return s

        # New session
        s = cls(tool_name)
        s._session_path.parent.mkdir(parents=True, exist_ok=True)
        return s

    def checkpoint(self) -> None:
        """
        Save current state to undo stack BEFORE a mutation.
        Always call this before modifying state.
        """
        import copy
        snap = copy.deepcopy(self.state)
        self._undo_stack.append(snap)
        if len(self._undo_stack) > MAX_UNDO_DEPTH:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        """Restore previous state. Returns True if successful."""
        import copy
        if not self._undo_stack:
            return False
        self._redo_stack.append(copy.deepcopy(self.state))
        self.state = self._undo_stack.pop()
        self.save()
        return True

    def redo(self) -> bool:
        """Redo last undone action. Returns True if successful."""
        import copy
        if not self._redo_stack:
            return False
        self._undo_stack.append(copy.deepcopy(self.state))
        self.state = self._redo_stack.pop()
        self.save()
        return True

    def save(self) -> None:
        """Persist session to disk."""
        data = {
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "state": self.state,
            "undo_depth": len(self._undo_stack),
        }
        with open(self._session_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _load(self) -> None:
        """Load session from disk."""
        if self._session_path.exists():
            with open(self._session_path) as f:
                data = json.load(f)
            self.session_id = data.get("session_id", self.session_id)
            self.state = data.get("state", {})


# ─────────────────────────────────────────────
# OUTPUT — Dual mode: JSON for agents, Human for users
# ─────────────────────────────────────────────

_json_mode = False


def set_json_mode(enabled: bool) -> None:
    global _json_mode
    _json_mode = enabled


def emit(data: Any, message: str = "", error: bool = False) -> None:
    """
    Output data in JSON mode (for agents) or human-readable (for humans).

    JSON mode:  {"status": "ok", "data": {...}}
    Human mode: Pretty-printed text

    Args:
        data:    The structured data payload
        message: Human-readable summary (only shown in human mode)
        error:   If True, marks as error in JSON output
    """
    if _json_mode:
        envelope = {
            "status": "error" if error else "ok",
            "data": data,
        }
        click.echo(json.dumps(envelope, indent=2, default=str))
    else:
        if error:
            click.secho(f"Error: {message or data}", fg="red", err=True)
        else:
            if message:
                click.echo(message)
            _pretty_print(data)


def _pretty_print(data: Any, indent: int = 0) -> None:
    """Human-readable recursive print."""
    prefix = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                click.echo(f"{prefix}{k}:")
                _pretty_print(v, indent + 1)
            else:
                click.echo(f"{prefix}{k}: {v}")
    elif isinstance(data, list):
        for item in data:
            _pretty_print(item, indent)
            click.echo()
    else:
        click.echo(f"{prefix}{data}")


# ─────────────────────────────────────────────
# CLI — Click-based command structure
# ─────────────────────────────────────────────

# Global session instance
_session: Optional[Session] = None


def get_session() -> Session:
    global _session
    if _session is None:
        _session = Session.load_or_create("my-tool")
    return _session


@click.group()
@click.option("--json", "use_json", is_flag=True, help="Output as JSON (for agents)")
def cli(use_json: bool) -> None:
    """
    My Tool — Agent-Native CLI

    Optimized for use by AI agents. Use --json for machine-readable output.
    """
    set_json_mode(use_json)


# ─── Status ───────────────────────────────────

@cli.command()
def status() -> None:
    """Show current session status."""
    session = get_session()
    emit(
        data={
            "session_id": session.session_id,
            "state_keys": list(session.state.keys()),
            "undo_available": len(session._undo_stack) > 0,
            "redo_available": len(session._redo_stack) > 0,
        },
        message=f"Session: {session.session_id}"
    )


# ─── Set / Get ────────────────────────────────

@cli.command()
@click.argument("key")
@click.argument("value")
def set(key: str, value: str) -> None:
    """Set a value in the current session state."""
    session = get_session()
    session.checkpoint()
    session.state[key] = value
    session.save()
    emit(data={"key": key, "value": value}, message=f"Set {key} = {value}")


@cli.command()
@click.argument("key")
def get(key: str) -> None:
    """Get a value from the current session state."""
    session = get_session()
    value = session.state.get(key)
    if value is None:
        emit(data={"key": key, "value": None}, message=f"Key '{key}' not found", error=True)
    else:
        emit(data={"key": key, "value": value}, message=f"{key}: {value}")


# ─── Undo / Redo ──────────────────────────────

@cli.command()
def undo() -> None:
    """Undo the last change."""
    session = get_session()
    if session.undo():
        emit(data={"status": "undone", "state": session.state}, message="Undone.")
    else:
        emit(data={"status": "nothing_to_undo"}, message="Nothing to undo.", error=True)


@cli.command()
def redo() -> None:
    """Redo the last undone change."""
    session = get_session()
    if session.redo():
        emit(data={"status": "redone", "state": session.state}, message="Redone.")
    else:
        emit(data={"status": "nothing_to_redo"}, message="Nothing to redo.", error=True)


# ─── REPL ─────────────────────────────────────

@cli.command()
def repl() -> None:
    """
    Interactive REPL mode for agents and power users.
    Keeps session warm between commands.
    Type 'exit' or Ctrl-C to quit.
    """
    click.echo("Entering REPL mode. Type 'exit' to quit.\n")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not line or line.lower() in ("exit", "quit"):
            break

        args = line.split()
        try:
            cli.main(args=args, standalone_mode=False)
        except SystemExit:
            pass
        except Exception as e:
            click.secho(f"Error: {e}", fg="red")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == "__main__":
    cli()
