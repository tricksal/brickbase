"""
Multi-Agent Trust Layer

A trust scoring and secure delegation system for multi-agent architectures.
Agents get verifiable identities, trust scores (0-1000), and delegations
with narrowed permissions. Full audit trail included.

Pattern: multi-agent-trust-layer
Category: ai-agents
Source: https://github.com/Shubhamsaboo/awesome-llm-apps
Extracted: 2026-03-08
"""

import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


# ============================================================================
# TRUST LEVELS
# ============================================================================

class TrustLevel(Enum):
    """Trust levels based on score ranges (0-1000)."""
    SUSPENDED = "suspended"   # 0-299: blocked from action
    RESTRICTED = "restricted" # 300-499: limited actions
    PROBATION = "probation"   # 500-699: monitored
    STANDARD = "standard"     # 700-899: normal operation
    TRUSTED = "trusted"       # 900-1000: elevated privileges

    @classmethod
    def from_score(cls, score: int) -> "TrustLevel":
        if score >= 900: return cls.TRUSTED
        elif score >= 700: return cls.STANDARD
        elif score >= 500: return cls.PROBATION
        elif score >= 300: return cls.RESTRICTED
        else: return cls.SUSPENDED


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class AgentIdentity:
    """Verified identity for an agent in the system."""
    agent_id: str
    public_key: str
    human_sponsor: str     # accountable human (email)
    organization: str
    roles: List[str]
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TrustScore:
    """Dynamic trust score with full history."""
    agent_id: str
    score: int = 700           # start at STANDARD
    level: TrustLevel = TrustLevel.STANDARD
    history: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def update(self, delta: int, reason: str):
        """Adjust score (clamped 0-1000) and log the change."""
        old = self.score
        self.score = max(0, min(1000, self.score + delta))
        self.level = TrustLevel.from_score(self.score)
        self.last_updated = datetime.utcnow()
        self.history.append({
            "timestamp": self.last_updated.isoformat(),
            "old_score": old, "new_score": self.score,
            "delta": delta, "reason": reason,
        })


@dataclass
class DelegationScope:
    """Permissions granted when one agent delegates to another."""
    allowed_actions: Set[str]
    denied_actions: Set[str] = field(default_factory=set)
    max_tokens: int = 10_000
    time_limit_minutes: int = 60
    max_sub_delegations: int = 0   # 0 = cannot re-delegate

    def allows(self, action: str) -> bool:
        if action in self.denied_actions:
            return False
        return not self.allowed_actions or action in self.allowed_actions

    def narrow(self, child: "DelegationScope") -> "DelegationScope":
        """Create a strictly-narrower scope for sub-delegation."""
        return DelegationScope(
            allowed_actions=self.allowed_actions & child.allowed_actions,
            denied_actions=self.denied_actions | child.denied_actions,
            max_tokens=min(self.max_tokens, child.max_tokens),
            time_limit_minutes=min(self.time_limit_minutes, child.time_limit_minutes),
            max_sub_delegations=max(0, self.max_sub_delegations - 1),
        )


@dataclass
class DelegationToken:
    """Cryptographically signed delegation from parent to child agent."""
    token_id: str
    parent_agent_id: str
    child_agent_id: str
    scope: DelegationScope
    issued_at: datetime
    expires_at: datetime
    signature: str    # HMAC over token contents

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


@dataclass
class AuditEntry:
    """Single record in the immutable audit trail."""
    entry_id: str
    timestamp: datetime
    agent_id: str
    action: str
    details: Dict[str, Any]
    trust_delta: Optional[int] = None
    delegation_token_id: Optional[str] = None


# ============================================================================
# TRUST REGISTRY
# ============================================================================

class TrustRegistry:
    """
    Central registry for agent identities, trust scores, delegations, and audit log.

    Usage:
        registry = TrustRegistry(secret_key="your-secret")
        registry.register("agent-1", sponsor="alice@example.com", org="Acme", roles=["reader"])
        token = registry.delegate("agent-1", "agent-2", DelegationScope({"search", "summarize"}))
        registry.record("agent-2", "search", details={"query": "..."}, token_id=token.token_id)
        registry.reward("agent-1", +50, "task completed")
        registry.penalize("agent-2", -100, "policy violation")
    """

    def __init__(self, secret_key: str = ""):
        self._secret = secret_key or secrets.token_hex(32)
        self._identities: Dict[str, AgentIdentity] = {}
        self._scores: Dict[str, TrustScore] = {}
        self._delegations: Dict[str, DelegationToken] = {}
        self._audit: List[AuditEntry] = []

    # --- Registration ---

    def register(self, agent_id: str, sponsor: str, org: str,
                  roles: List[str], initial_score: int = 700) -> AgentIdentity:
        """Register a new agent. Returns its identity."""
        pub_key = hashlib.sha256(f"{agent_id}:{self._secret}".encode()).hexdigest()
        identity = AgentIdentity(agent_id=agent_id, public_key=pub_key,
                                 human_sponsor=sponsor, organization=org, roles=roles)
        self._identities[agent_id] = identity
        self._scores[agent_id] = TrustScore(agent_id=agent_id, score=initial_score,
                                             level=TrustLevel.from_score(initial_score))
        self._log(agent_id, "register", {"sponsor": sponsor, "org": org, "roles": roles})
        logger.info(f"Registered agent {agent_id!r} (sponsor: {sponsor})")
        return identity

    # --- Trust management ---

    def get_score(self, agent_id: str) -> TrustScore:
        return self._scores[agent_id]

    def reward(self, agent_id: str, delta: int, reason: str):
        """Increase trust score (use for successful behaviour)."""
        self._scores[agent_id].update(abs(delta), reason)
        self._log(agent_id, "reward", {"delta": delta, "reason": reason}, trust_delta=delta)

    def penalize(self, agent_id: str, delta: int, reason: str):
        """Decrease trust score (use for violations)."""
        self._scores[agent_id].update(-abs(delta), reason)
        self._log(agent_id, "penalize", {"delta": -delta, "reason": reason}, trust_delta=-delta)

    def is_allowed(self, agent_id: str, action: str,
                   token_id: Optional[str] = None) -> bool:
        """Check whether an agent may perform an action (optionally within a delegation)."""
        score = self._scores.get(agent_id)
        if not score or score.level == TrustLevel.SUSPENDED:
            return False
        if token_id:
            token = self._delegations.get(token_id)
            if not token or token.is_expired or token.child_agent_id != agent_id:
                return False
            return token.scope.allows(action)
        return True

    # --- Delegation ---

    def delegate(self, parent_id: str, child_id: str,
                 scope: DelegationScope, duration_minutes: int = 60) -> DelegationToken:
        """Issue a delegation token from parent to child."""
        if not self.is_allowed(parent_id, "delegate"):
            raise PermissionError(f"Agent {parent_id!r} cannot delegate (score too low?)")
        now = datetime.utcnow()
        token_id = secrets.token_urlsafe(16)
        sig_input = f"{token_id}:{parent_id}:{child_id}:{now.isoformat()}"
        signature = hashlib.sha256(f"{sig_input}:{self._secret}".encode()).hexdigest()
        token = DelegationToken(
            token_id=token_id, parent_agent_id=parent_id, child_agent_id=child_id,
            scope=scope, issued_at=now, expires_at=now + timedelta(minutes=duration_minutes),
            signature=signature,
        )
        self._delegations[token_id] = token
        self._log(parent_id, "delegate", {"child": child_id, "token": token_id,
                                           "actions": list(scope.allowed_actions)})
        return token

    # --- Audit ---

    def record(self, agent_id: str, action: str, details: Dict[str, Any],
               token_id: Optional[str] = None):
        """Record an agent action in the audit trail."""
        self._log(agent_id, action, details, delegation_token_id=token_id)

    def get_audit(self, agent_id: Optional[str] = None) -> List[AuditEntry]:
        if agent_id:
            return [e for e in self._audit if e.agent_id == agent_id]
        return list(self._audit)

    def _log(self, agent_id: str, action: str, details: Dict[str, Any],
             trust_delta: Optional[int] = None, delegation_token_id: Optional[str] = None):
        entry = AuditEntry(
            entry_id=secrets.token_hex(8),
            timestamp=datetime.utcnow(),
            agent_id=agent_id, action=action, details=details,
            trust_delta=trust_delta, delegation_token_id=delegation_token_id,
        )
        self._audit.append(entry)


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    registry = TrustRegistry(secret_key="demo-secret")

    # Register two agents
    registry.register("orchestrator", sponsor="alice@example.com",
                      org="Acme", roles=["orchestrate", "delegate"])
    registry.register("worker", sponsor="alice@example.com",
                      org="Acme", roles=["execute"])

    # Orchestrator delegates a narrowed scope to worker
    scope = DelegationScope(allowed_actions={"search", "summarize"}, max_tokens=5000)
    token = registry.delegate("orchestrator", "worker", scope, duration_minutes=30)
    print(f"Token issued: {token.token_id}")

    # Worker tries to act within delegation
    ok = registry.is_allowed("worker", "search", token_id=token.token_id)
    print(f"Worker can search: {ok}")  # True

    blocked = registry.is_allowed("worker", "delete", token_id=token.token_id)
    print(f"Worker can delete: {blocked}")  # False

    # Reward / penalize
    registry.reward("worker", 50, "completed task correctly")
    registry.penalize("orchestrator", 30, "late response")

    # Audit trail
    for entry in registry.get_audit("worker"):
        print(f"  [{entry.timestamp:%H:%M:%S}] {entry.action} — {entry.details}")
