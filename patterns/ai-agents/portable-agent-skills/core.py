"""
Portable Agent Skills Pattern
==============================
A minimal Python implementation of the AgentSkills open format.
(https://agentskills.io)

Skills are directories with a SKILL.md file containing YAML frontmatter
and Markdown instructions. This module handles:
  - Parsing and validating skill directories
  - A registry for discovery (progressive disclosure: name+desc at startup)
  - Activation on demand (full instructions loaded when needed)
  - A SkillLoader that scans a directory tree for skills

Dependencies: PyYAML
  pip install pyyaml

Format spec: https://agentskills.io/specification.md
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:
    raise ImportError("PyYAML required: pip install pyyaml")


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")


def _validate_name(name: str) -> None:
    if not name:
        raise ValueError("Skill name must not be empty.")
    if len(name) > 64:
        raise ValueError(f"Skill name too long ({len(name)} chars, max 64): {name!r}")
    if "--" in name:
        raise ValueError(f"Skill name must not contain consecutive hyphens: {name!r}")
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Skill name must be lowercase alphanumeric + hyphens, "
            f"not start/end with hyphen: {name!r}"
        )


def _validate_description(desc: str) -> None:
    if not desc or not desc.strip():
        raise ValueError("Skill description must not be empty.")
    if len(desc) > 1024:
        raise ValueError(
            f"Skill description too long ({len(desc)} chars, max 1024)."
        )


# ---------------------------------------------------------------------------
# Skill data model
# ---------------------------------------------------------------------------

@dataclass
class SkillMeta:
    """
    Lightweight metadata loaded at agent startup (progressive disclosure step 1).
    Only name + description, keeping token cost minimal.
    """
    name: str
    description: str
    path: Path
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    allowed_tools: list[str] = field(default_factory=list)

    @property
    def skill_dir(self) -> Path:
        return self.path.parent


@dataclass
class Skill(SkillMeta):
    """
    Fully loaded skill including instructions (activated on demand).
    Inherits lightweight metadata from SkillMeta.
    """
    instructions: str = ""       # Markdown body after frontmatter

    def load_reference(self, ref_path: str) -> str:
        """
        Load a file from the skill's references/ or scripts/ directory.
        Skills can reference external files to keep SKILL.md lean.
        """
        target = self.skill_dir / ref_path
        if not target.exists():
            raise FileNotFoundError(f"Skill reference not found: {target}")
        return target.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def _parse_skill_md(skill_md_path: Path) -> Skill:
    """
    Parse a SKILL.md file and return a fully loaded Skill.

    SKILL.md format:
        ---
        name: my-skill
        description: What this skill does and when to use it.
        ---

        # Instructions
        ...
    """
    content = skill_md_path.read_text(encoding="utf-8")

    # Split frontmatter from body
    if not content.startswith("---"):
        raise ValueError(f"SKILL.md missing frontmatter: {skill_md_path}")

    parts = content.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"SKILL.md frontmatter not closed: {skill_md_path}")

    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"SKILL.md frontmatter YAML error: {exc}") from exc

    name = fm.get("name", "")
    description = fm.get("description", "")
    _validate_name(name)
    _validate_description(description)

    # name must match directory name
    expected_dir = skill_md_path.parent.name
    if name != expected_dir:
        raise ValueError(
            f"Skill name {name!r} does not match directory name {expected_dir!r}."
        )

    raw_tools = fm.get("allowed-tools", "")
    allowed_tools = raw_tools.split() if isinstance(raw_tools, str) else list(raw_tools)

    return Skill(
        name=name,
        description=description,
        path=skill_md_path,
        license=fm.get("license"),
        compatibility=fm.get("compatibility"),
        metadata=fm.get("metadata") or {},
        allowed_tools=allowed_tools,
        instructions=parts[2].strip(),
    )


# ---------------------------------------------------------------------------
# Registry (progressive disclosure)
# ---------------------------------------------------------------------------

class SkillRegistry:
    """
    Manages a collection of skills with two-phase loading:

    Phase 1 (startup): scan directories, load name+description only.
    Phase 2 (on demand): load full instructions when a skill is activated.

    Usage:
        registry = SkillRegistry()
        registry.scan("/path/to/skills")

        # Show agent what skills are available (startup context)
        for meta in registry.list_meta():
            print(meta.name, ":", meta.description)

        # Activate a specific skill (load full instructions)
        skill = registry.activate("pdf-processing")
        print(skill.instructions)
    """

    def __init__(self) -> None:
        self._meta: dict[str, SkillMeta] = {}
        self._loaded: dict[str, Skill] = {}

    def scan(self, skills_dir: str | Path) -> int:
        """
        Scan a directory for skill subdirectories.
        Loads only name+description (lightweight).
        Returns the number of skills found.
        """
        base = Path(skills_dir)
        if not base.is_dir():
            raise NotADirectoryError(f"Skills directory not found: {base}")

        count = 0
        for skill_dir in sorted(base.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                skill = _parse_skill_md(skill_md)
                # Store only lightweight meta at this stage
                self._meta[skill.name] = skill
                count += 1
            except (ValueError, FileNotFoundError) as exc:
                # Non-fatal: skip malformed skills with a warning
                print(f"[SkillRegistry] Skipping {skill_dir.name}: {exc}")

        return count

    def register(self, skill_md_path: str | Path) -> SkillMeta:
        """Register a single skill by path to its SKILL.md."""
        skill = _parse_skill_md(Path(skill_md_path))
        self._meta[skill.name] = skill
        return skill

    def list_meta(self) -> list[SkillMeta]:
        """Return lightweight metadata for all registered skills."""
        return list(self._meta.values())

    def startup_context(self) -> str:
        """
        Generate a compact startup context block listing all available skills.
        Inject this at the start of the agent's system prompt.
        """
        if not self._meta:
            return ""
        lines = ["<available_skills>"]
        for meta in self._meta.values():
            lines.append(f"  <skill>")
            lines.append(f"    <name>{meta.name}</name>")
            lines.append(f"    <description>{meta.description}</description>")
            if meta.compatibility:
                lines.append(f"    <compatibility>{meta.compatibility}</compatibility>")
            lines.append(f"  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def activate(self, name: str) -> Skill:
        """
        Activate a skill by name: load its full instructions.
        Returns cached result on repeated calls.
        """
        if name in self._loaded:
            return self._loaded[name]
        meta = self._meta.get(name)
        if meta is None:
            raise KeyError(f"Skill not found: {name!r}")
        # Re-parse to get full instructions
        skill = _parse_skill_md(meta.path)
        self._loaded[name] = skill
        return skill

    def find_by_task(self, task_description: str) -> list[SkillMeta]:
        """
        Simple keyword match to suggest relevant skills for a task.
        In production: replace with embedding similarity search.
        """
        task_lower = task_description.lower()
        return [
            meta for meta in self._meta.values()
            if any(word in meta.description.lower() for word in task_lower.split())
        ]

    def __len__(self) -> int:
        return len(self._meta)

    def __contains__(self, name: str) -> bool:
        return name in self._meta


# ---------------------------------------------------------------------------
# Example: create a skill programmatically
# ---------------------------------------------------------------------------

def create_skill(
    skills_dir: str | Path,
    name: str,
    description: str,
    instructions: str,
    license: str = "MIT",
) -> Path:
    """
    Create a new skill directory with a SKILL.md file.

    Returns the path to the created SKILL.md.
    """
    _validate_name(name)
    _validate_description(description)

    skill_dir = Path(skills_dir) / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = {"name": name, "description": description}
    if license:
        frontmatter["license"] = license

    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\n{yaml.dump(frontmatter, default_flow_style=False).strip()}\n---\n\n"
        + instructions,
        encoding="utf-8",
    )
    return skill_md


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        # Create two sample skills
        create_skill(
            tmp, "pdf-processing",
            description="Extract text and tables from PDF files, fill forms, merge documents. "
                        "Use when working with PDF documents.",
            instructions="# PDF Processing\n\n## Extract text\n1. Use pdfplumber...\n",
        )
        create_skill(
            tmp, "git-workflow",
            description="Commit, branch, merge, and rebase Git repositories. "
                        "Use when the user needs Git operations.",
            instructions="# Git Workflow\n\n## Commit changes\n1. Stage with git add...\n",
        )

        # Load registry
        registry = SkillRegistry()
        n = registry.scan(tmp)
        print(f"Loaded {n} skills\n")

        # Startup context (injected into system prompt)
        print("--- Startup context ---")
        print(registry.startup_context())
        print()

        # Task-based suggestion
        suggestions = registry.find_by_task("I need to extract text from a PDF report")
        print("Suggested skills:", [s.name for s in suggestions])

        # Activate on demand
        skill = registry.activate("pdf-processing")
        print(f"\nActivated: {skill.name}")
        print(f"Instructions preview: {skill.instructions[:80]}...")
