# agent-api-docs

## Was ist das?

Coding Agents halluzinieren APIs — weil ihr Training veraltet ist und sie keine aktuellen Docs haben. Dieses Pattern gibt Agents die Fähigkeit, kuratierte, versionierte API-Dokumentation on-demand abzurufen, statt aus dem Gedächtnis zu raten. Lokal annotierbar für Session-übergreifendes Lernen.

Inspiriert von [context-hub (Andrew Ng / AI Suite)](https://github.com/andrewyng/context-hub).

## Problem

```
Agent: "Nutze stripe.PaymentIntent.create(amount=100, currency='usd', payment_method_types=['card'])"
Reality: Parameter heißt seit v12 anders → Runtime-Error, wasted tokens, debugging-Loop
```

Agents verlassen sich auf Training-Daten, die Monate oder Jahre alt sein können. API-Docs ändern sich. Das Ergebnis: halluzinierte Parameter, falsche Methodennamen, veraltete Patterns.

## Lösung

Zwei Schichten:

1. **Remote Docs** — kuratierte, versionierte Markdown-Docs per CLI abrufbar (`chub get`)
2. **Lokale Annotationen** — Agent schreibt eigene Notizen dazu wenn er Gaps findet (`chub annotate`)

Der Agent lernt in einer Session etwas Neues → annotiert lokal → beim nächsten Abruf erscheint die Annotation automatisch.

## Pattern-Struktur

```
AGENT TASK
  │
  ▼
fetch_docs("stripe/api", lang="py")     ← remote kuratierte Docs
  │
  ▼
[Docs + ggf. lokale Annotationen]
  │
  ▼
CODE SCHREIBEN (keine Halluzinationen)
  │
  ▼
Gap entdeckt? → annotate("stripe/api", "webhook braucht raw body")
  │
  ▼
NÄCHSTE SESSION: Annotation erscheint automatisch
```

## Installation

```bash
npm install -g @aisuite/chub
```

## Core Commands

```bash
chub search openai                     # verfügbare Docs finden
chub get openai/chat --lang py         # Python-Docs holen
chub get stripe/api --lang js          # JS-Variante
chub annotate stripe/api "raw body für webhooks nötig"  # Gap dokumentieren
chub annotate stripe/api --clear       # Annotation entfernen
chub annotate --list                   # alle eigenen Annotationen
chub feedback stripe/api up            # Community-Feedback
```

## Einbindung in Agent-Workflows

### Als Tool

```python
import subprocess

def fetch_api_docs(service: str, lang: str = "py") -> str:
    """Fetch current API docs for a service. Use before writing API code."""
    result = subprocess.run(
        ["chub", "get", service, "--lang", lang],
        capture_output=True, text=True
    )
    return result.stdout if result.returncode == 0 else f"Docs not found for {service}"

def annotate_docs(service: str, note: str) -> str:
    """Annotate docs with a finding for future sessions."""
    subprocess.run(["chub", "annotate", service, note], check=True)
    return f"Annotated: {note}"

# Als Anthropic Tools:
tools = [
    {
        "name": "fetch_api_docs",
        "description": "Fetch current, curated API documentation for a service. Always call this before writing API code to avoid hallucinating outdated parameters.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "e.g. 'openai/chat', 'stripe/api', 'anthropic/messages'"},
                "lang": {"type": "string", "enum": ["py", "js"], "default": "py"}
            },
            "required": ["service"]
        }
    },
    {
        "name": "annotate_api_docs",
        "description": "When you discover a gap or important note about an API, annotate it so future sessions benefit.",
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "note": {"type": "string"}
            },
            "required": ["service", "note"]
        }
    }
]
```

### System Prompt Snippet

```
Before writing code that calls any external API, use fetch_api_docs to get the current documentation.
If you discover undocumented behavior or gaps, use annotate_api_docs so future sessions benefit.
```

### Als Claude Code Skill

Lege `~/.claude/skills/get-api-docs/SKILL.md` an (direkt aus context-hub beziehbar):
```bash
chub get get-api-docs/skill
```

## Eigene Docs hinzufügen

context-hub ist open - alle Docs sind Markdown im Repo. Eigene APIs (intern, nicht öffentlich) als lokale Markdown-Dateien verwalten:

```python
DOCS_DIR = Path("~/.agent-docs").expanduser()

def fetch_local_docs(service: str) -> str:
    """Fetch locally-maintained docs (for internal APIs)."""
    path = DOCS_DIR / f"{service.replace('/', '_')}.md"
    return path.read_text() if path.exists() else "No local docs found."

def write_local_docs(service: str, content: str) -> None:
    """Maintain docs for internal APIs."""
    path = DOCS_DIR / f"{service.replace('/', '_')}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
```

## Wann benutzen?

- Agent schreibt Code der externe APIs aufruft (OpenAI, Stripe, Anthropic, etc.)
- Codebase nutzt schnell evolvierende Libraries
- Agents haben wiederholt Halluzinationsprobleme mit bestimmten APIs

## Verwandte Patterns

- `compiled-context` - Context vor Agent-Run aufbereiten
- `knowledge-graph-from-codebase` - interne Docs aus Codebase extrahieren
- `instinct-learning` - Agent lernt aus Erfahrungen

## Quelle

- context-hub: https://github.com/andrewyng/context-hub
- Extrahiert: 2026-03-16
