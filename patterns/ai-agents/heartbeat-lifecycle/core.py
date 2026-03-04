"""
Heartbeat Lifecycle Pattern
============================
A background scheduler that wakes an AI agent periodically.

The agent checks for anything worth reporting and responds either:
  - HEARTBEAT_OK  → nothing relevant, drop the message silently
  - <actual text> → something worth surfacing to the user

Key ideas:
  - Configurable interval (e.g. every 30 min)
  - Active hours window (skip beats at night)
  - HEARTBEAT.md checklist injected into prompt
  - ACK token stripped before delivery

Dependencies: stdlib only (threading, datetime, pathlib)
  No external packages required.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

# Signature: agent_fn(prompt: str) -> str
AgentCallable = Callable[[str], str]

# Signature: delivery_fn(message: str) -> None
DeliveryCallable = Callable[[str], None]

ACK_TOKEN = "HEARTBEAT_OK"
DEFAULT_PROMPT = (
    "Read HEARTBEAT.md if it exists (workspace context). "
    "Follow it strictly. Do not infer or repeat old tasks from prior chats. "
    "If nothing needs attention, reply HEARTBEAT_OK."
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ActiveHours:
    """Restrict heartbeat runs to a time window (local time)."""
    start: dtime = dtime(8, 0)    # 08:00
    end: dtime = dtime(23, 0)     # 23:00

    def is_active(self, now: Optional[datetime] = None) -> bool:
        t = (now or datetime.now()).time()
        return self.start <= t < self.end


@dataclass
class HeartbeatConfig:
    """
    Configuration for the heartbeat scheduler.

    interval_seconds: How often to run (default: 30 minutes).
    prompt:           The prompt injected into the agent run.
    ack_max_chars:    Max non-ACK content allowed before we treat it as "silent".
    checklist_path:   Path to HEARTBEAT.md (or similar checklist file).
    active_hours:     Restrict beats to this time window. None = always run.
    """
    interval_seconds: int = 1800           # 30 minutes
    prompt: str = DEFAULT_PROMPT
    ack_max_chars: int = 300
    checklist_path: Optional[Path] = None  # e.g. Path("HEARTBEAT.md")
    active_hours: Optional[ActiveHours] = field(default_factory=ActiveHours)


# ---------------------------------------------------------------------------
# ACK detection
# ---------------------------------------------------------------------------

def is_ack_reply(reply: str, ack_max_chars: int = 300) -> bool:
    """
    Return True when the reply is a silent acknowledgment.

    Rules (matching OpenClaw semantics):
      - HEARTBEAT_OK at the START or END of the reply
      - After stripping the token, remaining content ≤ ack_max_chars
      - HEARTBEAT_OK in the *middle* is NOT treated as an ACK
    """
    stripped = reply.strip()

    if stripped == ACK_TOKEN:
        return True

    if stripped.startswith(ACK_TOKEN):
        remainder = stripped[len(ACK_TOKEN):].strip()
        return len(remainder) <= ack_max_chars

    if stripped.endswith(ACK_TOKEN):
        remainder = stripped[: -len(ACK_TOKEN)].strip()
        return len(remainder) <= ack_max_chars

    return False


def strip_ack_token(reply: str) -> str:
    """Remove the HEARTBEAT_OK token from start/end of reply."""
    stripped = reply.strip()
    if stripped.startswith(ACK_TOKEN):
        return stripped[len(ACK_TOKEN):].strip()
    if stripped.endswith(ACK_TOKEN):
        return stripped[: -len(ACK_TOKEN)].strip()
    return stripped


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class HeartbeatScheduler:
    """
    Runs periodic heartbeat agent turns in a background thread.

    Usage:
        def my_agent(prompt: str) -> str:
            # call your LLM here
            return llm_response

        def my_delivery(message: str) -> None:
            send_to_user(message)

        scheduler = HeartbeatScheduler(
            agent_fn=my_agent,
            delivery_fn=my_delivery,
            config=HeartbeatConfig(interval_seconds=1800),
        )
        scheduler.start()
        # ... your app runs ...
        scheduler.stop()
    """

    def __init__(
        self,
        agent_fn: AgentCallable,
        delivery_fn: DeliveryCallable,
        config: Optional[HeartbeatConfig] = None,
    ):
        self.agent_fn = agent_fn
        self.delivery_fn = delivery_fn
        self.config = config or HeartbeatConfig()

        self._stop_event = threading.Event()
        self._busy = threading.Lock()           # prevents overlapping runs
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background heartbeat thread."""
        if self._thread and self._thread.is_alive():
            log.warning("Heartbeat scheduler already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="heartbeat")
        self._thread.start()
        log.info("Heartbeat scheduler started (interval=%ds).", self.config.interval_seconds)

    def stop(self) -> None:
        """Stop the scheduler gracefully."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        log.info("Heartbeat scheduler stopped.")

    def trigger_now(self) -> None:
        """Manually trigger a heartbeat immediately (in the calling thread)."""
        self._run_beat()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        """Main scheduler loop — ticks every interval."""
        while not self._stop_event.wait(timeout=self.config.interval_seconds):
            self._run_beat()

    def _run_beat(self) -> None:
        """Execute one heartbeat turn."""
        # Respect active hours
        if self.config.active_hours and not self.config.active_hours.is_active():
            log.debug("Outside active hours — skipping heartbeat.")
            return

        # Prevent overlapping runs (e.g. if agent is slow)
        if not self._busy.acquire(blocking=False):
            log.info("Agent busy — skipping heartbeat tick.")
            return

        try:
            prompt = self._build_prompt()
            log.info("Running heartbeat…")
            reply = self.agent_fn(prompt)
            self._handle_reply(reply)
        except Exception:
            log.exception("Heartbeat agent run failed.")
        finally:
            self._busy.release()

    def _build_prompt(self) -> str:
        """Build the heartbeat prompt, optionally injecting checklist content."""
        checklist = ""
        if self.config.checklist_path and self.config.checklist_path.exists():
            raw = self.config.checklist_path.read_text(encoding="utf-8").strip()
            # Skip if checklist is empty (only whitespace/headings)
            non_empty = [
                line for line in raw.splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if non_empty:
                checklist = f"\n\nChecklist:\n{raw}"

        return self.config.prompt + checklist

    def _handle_reply(self, reply: str) -> None:
        """Decide whether to deliver or silently drop the reply."""
        if is_ack_reply(reply, self.config.ack_max_chars):
            log.debug("Heartbeat ACK received — dropping silently.")
            return

        # Strip stray ACK token if present alongside real content
        clean = strip_ack_token(reply)
        if clean:
            log.info("Heartbeat alert — delivering to user.")
            self.delivery_fn(clean)


# ---------------------------------------------------------------------------
# Example usage (runnable demo)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    # Stub agent: sometimes silent, sometimes has something to say
    def stub_agent(prompt: str) -> str:
        if random.random() < 0.7:
            return "HEARTBEAT_OK"
        return "📬 Reminder: You have 2 unread emails that need a reply."

    # Stub delivery: just print
    def stub_delivery(message: str) -> None:
        print(f"\n[DELIVERED TO USER]: {message}\n")

    config = HeartbeatConfig(
        interval_seconds=5,            # short for demo; use 1800 (30min) in production
        active_hours=ActiveHours(start=dtime(0, 0), end=dtime(23, 59)),  # always active
    )

    scheduler = HeartbeatScheduler(
        agent_fn=stub_agent,
        delivery_fn=stub_delivery,
        config=config,
    )

    scheduler.start()
    print("Heartbeat running for 30 seconds… (Ctrl+C to stop)")
    try:
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    scheduler.stop()
