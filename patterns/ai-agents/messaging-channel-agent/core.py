#!/usr/bin/env python3
"""
messaging-channel-agent / core.py
===================================
Minimal, generic reference implementation of the Messaging Channel Agent pattern.

Architecture:
    WebhookServer → SessionRouter → GroupTriggerFilter → AgentBridge → reply

This demo runs a local HTTP webhook server that simulates inbound messages
from any messaging channel (WhatsApp, Signal, Telegram, etc.) and routes
them through isolated sessions to an AI agent callback.

Run with:
    python core.py

Then send a test DM:
    curl -s -X POST http://localhost:8765/webhook \
         -H "Content-Type: application/json" \
         -d '{"type":"dm","sender":"+49151123456","text":"Hello agent!"}'

Send a group message (no mention → ignored):
    curl -s -X POST http://localhost:8765/webhook \
         -H "Content-Type: application/json" \
         -d '{"type":"group","group_id":"group-42","sender":"+49151123456","text":"hi everyone"}'

Send a group message with mention → agent responds:
    curl -s -X POST http://localhost:8765/webhook \
         -H "Content-Type: application/json" \
         -d '{"type":"group","group_id":"group-42","sender":"+49151123456","text":"@bot what is 2+2?"}'
"""

import json
import re
import threading
import time
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Session Router
# ---------------------------------------------------------------------------

class Session:
    """Holds the conversation history for one isolated context."""

    def __init__(self, session_key: str):
        self.key = session_key
        self.history: List[Dict] = []
        self.created_at = time.time()
        self.updated_at = time.time()

    def add_message(self, role: str, text: str):
        self.history.append({"role": role, "text": text, "ts": time.time()})
        self.updated_at = time.time()

    def __repr__(self):
        return f"Session({self.key!r}, turns={len(self.history)})"


class SessionRouter:
    """
    Routes inbound messages to the correct isolated Session.

    Session key scheme (mirrors OpenClaw):
        DM  → "agent:main:dm:<sender_id>"          (per-sender isolation)
        Group → "agent:main:<channel>:group:<group_id>"

    In a real system you'd persist sessions to disk. Here we keep them
    in memory as a simple dict.
    """

    def __init__(self, dm_scope: str = "per-sender"):
        """
        dm_scope:
            "main"       — all DMs share one session (single-user setups)
            "per-sender" — isolated session per sender (multi-user setups, RECOMMENDED)
        """
        self._sessions: Dict[str, Session] = {}
        self.dm_scope = dm_scope
        self._lock = threading.Lock()

    def _dm_key(self, channel: str, sender: str) -> str:
        if self.dm_scope == "main":
            return "agent:main:main"
        # per-sender: isolate by channel + sender
        return f"agent:main:{channel}:dm:{sender}"

    def _group_key(self, channel: str, group_id: str) -> str:
        return f"agent:main:{channel}:group:{group_id}"

    def get_or_create(self, channel: str, msg_type: str,
                      sender: str, group_id: Optional[str] = None) -> Session:
        """Return the existing session or create a new one."""
        if msg_type == "dm":
            key = self._dm_key(channel, sender)
        elif msg_type == "group" and group_id:
            key = self._group_key(channel, group_id)
        else:
            raise ValueError(f"Unknown msg_type={msg_type!r} or missing group_id")

        with self._lock:
            if key not in self._sessions:
                self._sessions[key] = Session(key)
                print(f"[SessionRouter] Created new session: {key}")
            return self._sessions[key]

    def list_sessions(self) -> List[str]:
        with self._lock:
            return list(self._sessions.keys())


# ---------------------------------------------------------------------------
# Group Trigger Filter
# ---------------------------------------------------------------------------

class GroupTriggerFilter:
    """
    Decides whether the agent should respond to a group message.

    Trigger modes (per group config):
        "mention"  — respond only when @mentioned or reply-to-bot (default)
        "always"   — respond to every message in the group
        "never"    — never respond (monitor-only)

    Mention detection:
        1. Explicit @mention regex patterns
        2. Keyword patterns (fallback, channel-agnostic)
        3. Reply-to-bot detection (msg contains reply_to_bot=True)
    """

    def __init__(
        self,
        bot_name: str = "bot",
        mention_patterns: Optional[List[str]] = None,
        keywords: Optional[List[str]] = None,
    ):
        self.bot_name = bot_name
        # Build a combined mention regex
        base_patterns = [rf"@{re.escape(bot_name)}"]
        if mention_patterns:
            base_patterns.extend(mention_patterns)
        self._mention_re = re.compile(
            "|".join(base_patterns), re.IGNORECASE
        )
        self._keyword_re: Optional[re.Pattern] = None
        if keywords:
            self._keyword_re = re.compile(
                "|".join(re.escape(k) for k in keywords), re.IGNORECASE
            )

        # Per-group activation: "mention" | "always" | "never"
        self._group_mode: Dict[str, str] = {}
        self._default_mode = "mention"

    def set_group_mode(self, group_id: str, mode: str):
        """Override trigger mode for a specific group."""
        assert mode in ("mention", "always", "never"), f"Invalid mode: {mode!r}"
        self._group_mode[group_id] = mode
        print(f"[GroupTriggerFilter] Group {group_id!r} mode → {mode}")

    def should_respond(
        self,
        group_id: str,
        text: str,
        reply_to_bot: bool = False,
    ) -> bool:
        """
        Return True if the agent should generate a reply.
        Return False if the message should only be stored for context (history).
        """
        mode = self._group_mode.get(group_id, self._default_mode)

        if mode == "always":
            return True
        if mode == "never":
            return False
        # mode == "mention" (default)
        if reply_to_bot:
            return True
        if self._mention_re.search(text):
            return True
        if self._keyword_re and self._keyword_re.search(text):
            return True
        return False


# ---------------------------------------------------------------------------
# Agent Bridge
# ---------------------------------------------------------------------------

class AgentBridge:
    """
    Calls the AI agent and returns a reply string.

    In this demo, the "agent" is a simple echo function.
    In a real system, replace `_call_agent` with your LLM API call,
    tool loop, or sub-agent dispatch.

    The bridge also handles:
        - Injecting session history as context
        - Sending the reply back via the channel's send callback
    """

    def __init__(self, send_fn: Callable[[str, str, str, Optional[str]], None]):
        """
        send_fn(channel, recipient, text, group_id):
            Sends `text` back to the originating chat.
            group_id is None for DMs.
        """
        self._send = send_fn

    def _call_agent(self, session: Session, user_text: str) -> str:
        """
        REPLACE THIS with your real LLM call.
        Receives the session (with history) and the latest user message.
        Returns the agent's reply as a string.
        """
        # Build a simple context summary for the demo
        history_summary = ""
        if session.history:
            last_msgs = session.history[-3:]
            history_summary = " | ".join(
                f"{m['role']}: {m['text'][:40]}" for m in last_msgs
            )

        # Stub response — replace with actual LLM call
        reply = (
            f"[Agent reply to: '{user_text[:60]}'] "
            f"Session: {session.key} | "
            f"Turns so far: {len(session.history)} | "
            f"Recent ctx: [{history_summary}]"
        )
        return reply

    def handle(
        self,
        channel: str,
        session: Session,
        sender: str,
        text: str,
        group_id: Optional[str] = None,
    ):
        """Full agent turn: add user msg → call agent → store reply → send."""
        # 1. Add user message to session history
        session.add_message("user", text)

        # 2. Call agent (blocking; use threading for concurrency in production)
        reply = self._call_agent(session, text)

        # 3. Store agent reply in session
        session.add_message("agent", reply)

        # 4. Send reply back via channel
        recipient = group_id if group_id else sender
        self._send(channel, recipient, reply, group_id)
        print(f"[AgentBridge] Replied to {recipient!r} on {channel!r}")


# ---------------------------------------------------------------------------
# Webhook Server
# ---------------------------------------------------------------------------

class WebhookServer:
    """
    Minimal HTTP server that receives inbound messages via POST /webhook.

    Expected JSON payload:
    {
        "channel":  "whatsapp",          // optional, defaults to "demo"
        "type":     "dm" | "group",
        "sender":   "+49151123456",
        "text":     "Hello!",
        "group_id": "group-42",          // required for type=group
        "reply_to_bot": false            // optional, true if replying to bot msg
    }

    This is a simplified, channel-agnostic webhook. In a real deployment,
    each channel (WhatsApp/Signal/Telegram) has its own inbound format that
    gets normalized before reaching this routing layer.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        bot_name: str = "bot",
        dm_scope: str = "per-sender",
    ):
        self.host = host
        self.port = port

        # Core components
        self.router = SessionRouter(dm_scope=dm_scope)
        self.trigger_filter = GroupTriggerFilter(
            bot_name=bot_name,
            mention_patterns=[rf"@{bot_name}", bot_name],
            keywords=[],  # add domain-specific keywords here
        )
        self.bridge = AgentBridge(send_fn=self._send_reply)

        # Pending group history: messages not yet triggering a reply
        # stored for context injection (mirrors OpenClaw historyLimit=50)
        self._pending_history: Dict[str, List[Dict]] = defaultdict(list)
        self._history_limit = 50

    def _send_reply(
        self,
        channel: str,
        recipient: str,
        text: str,
        group_id: Optional[str],
    ):
        """
        REPLACE with real channel-specific send (WhatsApp/Signal/Telegram API).
        Here we just print to stdout.
        """
        if group_id:
            print(f"\n📤 [{channel}] → GROUP {recipient}: {text}\n")
        else:
            print(f"\n📤 [{channel}] → DM {recipient}: {text}\n")

    def _handle_message(self, payload: Dict):
        """Core routing logic for one inbound message."""
        channel = payload.get("channel", "demo")
        msg_type = payload.get("type", "dm")
        sender = payload.get("sender", "unknown")
        text = payload.get("text", "")
        group_id = payload.get("group_id")
        reply_to_bot = payload.get("reply_to_bot", False)

        print(f"[Webhook] Inbound [{msg_type}] from {sender!r}: {text!r}")

        if msg_type == "dm":
            # DMs always get a reply
            session = self.router.get_or_create(channel, "dm", sender)
            self.bridge.handle(channel, session, sender, text, group_id=None)

        elif msg_type == "group":
            if not group_id:
                print("[Webhook] ⚠️  Group message without group_id — dropping")
                return

            # Check trigger filter
            should_reply = self.trigger_filter.should_respond(
                group_id, text, reply_to_bot=reply_to_bot
            )

            session = self.router.get_or_create(channel, "group", sender, group_id)

            if not should_reply:
                # Store for context (pending history injection)
                pending = self._pending_history[session.key]
                pending.append({"sender": sender, "text": text, "ts": time.time()})
                if len(pending) > self._history_limit:
                    pending.pop(0)  # drop oldest
                print(
                    f"[Webhook] Group msg stored as context "
                    f"(pending={len(pending)}, no trigger)"
                )
                return

            # Inject pending history as context before the triggering message
            pending = self._pending_history.pop(session.key, [])
            if pending:
                context_block = "\n".join(
                    f"  [{m['sender']}]: {m['text']}" for m in pending
                )
                injected = (
                    f"[Chat messages since last reply — for context]\n"
                    f"{context_block}\n"
                    f"[Current message — respond to this]"
                )
                session.add_message("system", injected)
                print(f"[Webhook] Injected {len(pending)} pending msgs as context")

            self.bridge.handle(channel, session, sender, text, group_id=group_id)

        else:
            print(f"[Webhook] Unknown message type: {msg_type!r}")

    def _make_handler(self):
        """Build a request handler class with access to this WebhookServer."""
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path != "/webhook":
                    self.send_response(404)
                    self.end_headers()
                    return

                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as e:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(f"Bad JSON: {e}".encode())
                    return

                # Handle in a thread so HTTP response is immediate
                t = threading.Thread(
                    target=server_ref._handle_message, args=(payload,), daemon=True
                )
                t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"queued"}')

            def do_GET(self):
                if self.path == "/sessions":
                    sessions = server_ref.router.list_sessions()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"sessions": sessions}).encode())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *args):
                pass  # suppress default access log

        return Handler

    def run(self):
        handler_cls = self._make_handler()
        httpd = HTTPServer((self.host, self.port), handler_cls)
        print(f"🚀 WebhookServer listening on http://{self.host}:{self.port}/webhook")
        print(f"   Sessions: http://{self.host}:{self.port}/sessions")
        print()
        print("Test commands:")
        print(
            f'  DM:           curl -s -X POST http://{self.host}:{self.port}/webhook '
            '-H "Content-Type: application/json" '
            '-d \'{"type":"dm","sender":"+49151123","text":"Hello!"}\''
        )
        print(
            f'  Group (miss):  curl -s -X POST http://{self.host}:{self.port}/webhook '
            '-H "Content-Type: application/json" '
            '-d \'{"type":"group","group_id":"grp1","sender":"+49151123","text":"just chatting"}\''
        )
        print(
            f'  Group (hit):   curl -s -X POST http://{self.host}:{self.port}/webhook '
            '-H "Content-Type: application/json" '
            '-d \'{"type":"group","group_id":"grp1","sender":"+49151123","text":"@bot what is 2+2?"}\''
        )
        print()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 Shutting down.")
            httpd.shutdown()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    server = WebhookServer(
        host="localhost",
        port=8765,
        bot_name="bot",
        dm_scope="per-sender",  # isolate DM sessions per sender (multi-user safe)
    )

    # Example: configure group-42 to always reply (no mention needed)
    server.trigger_filter.set_group_mode("group-42-vip", "always")

    server.run()
