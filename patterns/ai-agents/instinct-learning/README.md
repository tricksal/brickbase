# instinct-learning

## Was ist das?
Ein Agent beobachtet sein eigenes Verhalten via Hooks und destilliert daraus atomare "Instincts" — kleine gelernte Verhaltensweisen mit Confidence-Score. Über Zeit werden reife Instincts automatisch zu wiederverwendbaren Skills evolved.

## Wann benutzen?
- Agent soll aus eigenen Fehlern und Korrekturen lernen
- Session-Patterns sollen dauerhaft erhalten werden (nicht nur im Context Window)
- Skills sollen sich organisch aus echtem Verhalten entwickeln, nicht manuell geschrieben werden
- Multi-Session-Continuity ohne manuelles Memory-Management

## Kern-Konzept

```
Session-Aktivität (Hooks: PreToolUse / PostToolUse)
        ↓
Observation (tool, input, outcome: success/failure/correction)
        ↓
Pattern Detection (Heuristic oder Background-LLM)
        ↓
Instinct { trigger, action, confidence: 0.3-0.95, domain }
        ↓  (reinforcement über mehrere Sessions)
Mature Instinct (confidence ≥ 0.75, count ≥ 3)
        ↓
SKILL.md / command / agent (evolved)
```

**Instinct-Struktur:**
- `id`: kebab-case Name
- `trigger`: "when doing X..."
- `action`: "do Y"
- `confidence`: 0.3 (tentativ) → 0.95 (sicher)
- `scope`: project | global
- `evidence`: Liste von beobachteten Belegen

**Project Scoping:**
- Jedes Git-Repo bekommt eine stabile 12-char ID (hash des remote-URL)
- React-Patterns bleiben im React-Projekt, Python-Patterns im Python-Projekt
- Wenn ein Instinct in 2+ Projekten auftaucht → automatische Promotion zu global

## Dependencies
- Python 3.12+
- Kein externes LLM nötig (heuristische Extraktion), aber Haiku als Background-Agent erhöht Qualität stark

## Usage

```python
from core import InstinctStore, Instinct, detect_project_id, evolve_to_skill

store = InstinctStore()
project_id = detect_project_id()

# Instinct anlegen (z.B. nach Hook-Observation)
instinct = Instinct(
    id="grep-before-edit",
    trigger="when editing a file I haven't read yet",
    action="run grep/read first to understand context",
    domain="workflow",
    confidence=0.5,
    scope="project",
    project_id=project_id,
    evidence=["Agent edited wrong function"],
)

# Über Sessions hinweg verstärken
instinct = instinct.reinforce("Same pattern, prevented bug")
instinct = instinct.reinforce("Confirmed: saves 2-3 round trips")
store.save(instinct)

# Zu Skill evolved wenn reif
if instinct.is_mature:
    skill_md = evolve_to_skill(instinct)
    # → in ~/.agent/skills/ speichern
```

## Hook-Integration (Pseudo-JSON)

```json
{
  "PostToolUse": [{
    "matcher": "*",
    "hooks": [{ "type": "command", "command": "observe.sh" }]
  }]
}
```

`observe.sh` schreibt jede Tool-Nutzung als Observation in `observations.jsonl`.
Background-Agent (Haiku) liest diese und erstellt/aktualisiert Instincts.

## Quelle
- Original: [everything-claude-code](https://github.com/affaan-m/everything-claude-code/tree/main/skills/continuous-learning-v2)
- Extrahiert: 2026-03-08
