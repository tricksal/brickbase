"""
Instinct Learning Pattern
=========================
An agent observes its own behavior via hooks, extracts atomic "instincts"
(small learned behaviors with confidence scores), and evolves them into
reusable skills/commands over time.

Source: everything-claude-code (affaan-m) — continuous-learning-v2
"""

from __future__ import annotations

import json
import hashlib
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import datetime
from typing import Literal

# ── Types ────────────────────────────────────────────────────────────────────

Scope = Literal["project", "global"]
Domain = Literal["code-style", "testing", "git", "debugging", "workflow", "architecture"]

@dataclass
class Instinct:
    """
    An atomic learned behavior with confidence scoring.
    One trigger → one action. Backed by observed evidence.
    """
    id: str                        # kebab-case identifier
    trigger: str                   # "when doing X..."
    action: str                    # "do Y"
    domain: Domain
    confidence: float              # 0.3 (tentative) → 0.9 (near certain)
    scope: Scope = "project"
    project_id: str | None = None  # 12-char hash of git remote URL
    evidence: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_seen: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    observation_count: int = 1

    def reinforce(self, evidence_note: str, delta: float = 0.05) -> "Instinct":
        """Return a stronger version of this instinct (immutable update)."""
        new_confidence = min(0.95, self.confidence + delta)
        return Instinct(
            **{
                **asdict(self),
                "confidence": new_confidence,
                "evidence": self.evidence + [evidence_note],
                "last_seen": datetime.utcnow().isoformat(),
                "observation_count": self.observation_count + 1,
            }
        )

    def weaken(self, delta: float = 0.05) -> "Instinct":
        """Return a weaker version (counter-evidence observed)."""
        return Instinct(
            **{**asdict(self), "confidence": max(0.1, self.confidence - delta)}
        )

    @property
    def is_mature(self) -> bool:
        """Ready to be evolved into a skill/command/agent."""
        return self.confidence >= 0.75 and self.observation_count >= 3


# ── Project Detection ─────────────────────────────────────────────────────────

def detect_project_id(cwd: str | None = None) -> str | None:
    """
    Derive a stable 12-char project ID from the git remote URL.
    Same repo on different machines → same ID.
    Falls back to repo path hash if no remote.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=cwd
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            return hashlib.sha256(url.encode()).hexdigest()[:12]
        # Fallback: repo root path
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, cwd=cwd
        )
        if result.returncode == 0:
            path = result.stdout.strip()
            return hashlib.sha256(path.encode()).hexdigest()[:12]
    except FileNotFoundError:
        pass
    return None  # Not in a git repo → global scope


# ── Storage ───────────────────────────────────────────────────────────────────

class InstinctStore:
    """
    File-backed store for instincts.
    Layout:
      ~/.agent/homunculus/
        instincts/personal/          ← global instincts
        projects/<hash>/instincts/   ← project-scoped instincts
        projects.json                ← registry (hash → name)
    """

    def __init__(self, base_dir: Path = Path.home() / ".agent" / "homunculus"):
        self.base_dir = base_dir
        self.global_dir = base_dir / "instincts" / "personal"
        self.projects_file = base_dir / "projects.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.global_dir.mkdir(parents=True, exist_ok=True)

    def _instinct_path(self, instinct: Instinct) -> Path:
        if instinct.scope == "global" or instinct.project_id is None:
            return self.global_dir / f"{instinct.id}.json"
        project_dir = self.base_dir / "projects" / instinct.project_id / "instincts"
        project_dir.mkdir(parents=True, exist_ok=True)
        return project_dir / f"{instinct.id}.json"

    def save(self, instinct: Instinct) -> None:
        path = self._instinct_path(instinct)
        path.write_text(json.dumps(asdict(instinct), indent=2))

    def load(self, instinct_id: str, project_id: str | None = None) -> Instinct | None:
        for candidate in [
            self.global_dir / f"{instinct_id}.json",
            *(
                [self.base_dir / "projects" / project_id / "instincts" / f"{instinct_id}.json"]
                if project_id else []
            ),
        ]:
            if candidate.exists():
                return Instinct(**json.loads(candidate.read_text()))
        return None

    def all(self, project_id: str | None = None) -> list[Instinct]:
        """Return all instincts (global + optionally project-scoped)."""
        results: list[Instinct] = []
        for f in self.global_dir.glob("*.json"):
            results.append(Instinct(**json.loads(f.read_text())))
        if project_id:
            project_dir = self.base_dir / "projects" / project_id / "instincts"
            for f in project_dir.glob("*.json"):
                results.append(Instinct(**json.loads(f.read_text())))
        return results

    def mature_instincts(self, project_id: str | None = None) -> list[Instinct]:
        """Return instincts ready to be evolved into skills."""
        return [i for i in self.all(project_id) if i.is_mature]


# ── Observation Pipeline ──────────────────────────────────────────────────────

@dataclass
class Observation:
    """A raw event captured by a hook (PreToolUse / PostToolUse)."""
    tool: str
    input_snippet: str
    outcome: Literal["success", "failure", "correction"]
    project_id: str | None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


def extract_instinct_from_observation(obs: Observation) -> Instinct | None:
    """
    Heuristic pattern detection.
    In production, run this via a background Haiku agent for better accuracy.
    Returns None if no clear pattern is detected.
    """
    # Corrections are high-signal: user corrected the agent
    if obs.outcome == "correction":
        return Instinct(
            id=f"correction-{obs.tool.lower()}-{hashlib.md5(obs.input_snippet.encode()).hexdigest()[:6]}",
            trigger=f"when using {obs.tool}",
            action=f"learned from correction: {obs.input_snippet[:80]}",
            domain="workflow",
            confidence=0.5,  # Start medium — needs reinforcement
            scope="project" if obs.project_id else "global",
            project_id=obs.project_id,
            evidence=[f"User correction at {obs.timestamp}"],
        )
    # Repeated failures → learn to avoid pattern
    if obs.outcome == "failure":
        return Instinct(
            id=f"avoid-{obs.tool.lower()}-{hashlib.md5(obs.input_snippet.encode()).hexdigest()[:6]}",
            trigger=f"when using {obs.tool} with similar input",
            action=f"avoid pattern: {obs.input_snippet[:80]}",
            domain="debugging",
            confidence=0.35,
            scope="project" if obs.project_id else "global",
            project_id=obs.project_id,
            evidence=[f"Failure at {obs.timestamp}"],
        )
    return None


# ── Evolution: Instinct → Skill ───────────────────────────────────────────────

def evolve_to_skill(instinct: Instinct) -> str:
    """
    Convert a mature instinct into a SKILL.md-compatible Markdown string.
    Cluster related instincts first for richer skills.
    """
    assert instinct.is_mature, "Only evolve mature instincts (confidence ≥ 0.75, count ≥ 3)"

    return f"""---
name: {instinct.id}
description: Auto-evolved from instinct. {instinct.trigger} → {instinct.action}
origin: instinct-learning
confidence: {instinct.confidence}
---

# {instinct.id.replace("-", " ").title()}

## Trigger
{instinct.trigger}

## Action
{instinct.action}

## Evidence
{chr(10).join(f"- {e}" for e in instinct.evidence)}

## Domain
{instinct.domain}

---
*Auto-generated from {instinct.observation_count} observations. Confidence: {instinct.confidence:.2f}*
"""


# ── Promotion: Project → Global ───────────────────────────────────────────────

def should_promote(instinct: Instinct, seen_in_projects: int) -> bool:
    """
    Promote a project-scoped instinct to global if observed in 2+ projects.
    Universal patterns (validate input, grep before edit) become global.
    """
    return instinct.scope == "project" and seen_in_projects >= 2 and instinct.confidence >= 0.7


# ── Usage Example ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    store = InstinctStore()
    project_id = detect_project_id()

    # Simulate reinforcing an instinct over multiple sessions
    instinct = Instinct(
        id="grep-before-edit",
        trigger="when editing a file I haven't read yet",
        action="run grep/read first to understand context",
        domain="workflow",
        confidence=0.5,
        scope="project",
        project_id=project_id,
        evidence=["Initial observation: agent edited wrong function"],
    )

    # Reinforce from repeated observations
    instinct = instinct.reinforce("Session 2: same pattern observed")
    instinct = instinct.reinforce("Session 3: confirmed best practice")
    instinct = instinct.reinforce("Session 4: prevents 2 bugs")

    store.save(instinct)
    print(f"Instinct '{instinct.id}' — confidence: {instinct.confidence:.2f}, mature: {instinct.is_mature}")

    if instinct.is_mature:
        skill_md = evolve_to_skill(instinct)
        Path(f"/tmp/{instinct.id}.skill.md").write_text(skill_md)
        print(f"Evolved to skill → /tmp/{instinct.id}.skill.md")
