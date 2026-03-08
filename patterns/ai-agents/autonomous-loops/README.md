# autonomous-loops

## Was ist das?
Architekturen für autonome Agenten-Loops — vom simplen sequentiellen Pipeline (Schritt für Schritt) bis zum parallelen Multi-Agenten-System mit RFC-getriebenem DAG. Jede Stufe löst eine andere Klasse von Problemen.

## Wann benutzen?
- Wiederkehrende Entwicklungsschritte automatisieren (täglich, wöchentlich)
- Parallele Content-Generierung mit vielen Varianten
- Multi-Tage-Projekte mit automatischen CI-Gates
- Batch-Verarbeitung wo ein Agent zu langsam wäre

## Loop-Spektrum

| Pattern | Komplexität | Wann |
|---------|-------------|------|
| Sequential Pipeline | Niedrig | Skriptbare Workflows, klare Schritte |
| PR Loop | Mittel | Iterative Projekte mit CI |
| Infinite Agentic Loop | Mittel | Parallele Generierung N Varianten |
| DAG Orchestration | Hoch | Große Features, Multi-Unit parallel |

## Kern-Konzept

### 1. Sequential Pipeline
```
Step 1 (implement) → Step 2 (cleanup) → Step 3 (verify) → Step 4 (commit)
   ↓ frischer Context        ↓                ↓                ↓
   jeder Step ist isoliert — kein Context-Bleed zwischen Schritten
```

**Key Insight:** Jeder `claude -p`-Aufruf hat ein frisches Context Window.
Das ist kein Bug — es ist ein Feature. Schritte bauen auf dem Filesystem-State auf, nicht auf dem Context.

**Negative Instructions vermeiden:** Statt "Schreib keine unnötigen Tests" lieber einen separaten Cleanup-Schritt hinzufügen (De-Sloppify Pattern).

### 2. De-Sloppify Pattern (Add-on)
Nach jedem Implement-Step:
- Entfernt unnötige Typ-Tests
- Entfernt übermäßig defensive Checks
- Entfernt Tests die Sprach-Features testen statt Business Logic
- Läuft Test-Suite danach

### 3. Infinite Agentic Loop
```
Orchestrator liest Spec
    → plant N einzigartige Creative Directions
    → deployt N Sub-Agenten parallel
    → jeder schreibt in eigenes Output-Dir (keine Konflikte)
    → Wellen à 3-5 Agenten bis Context voll
```

**Two-Prompt System:** Orchestrator-Prompt + Sub-Agent-Prompt strikt getrennt.

### 4. Model Routing
```python
"research"  → Opus  (tiefes Denken)
"implement" → Sonnet (solides Coding)
"commit"    → Haiku  (einfache Aufgabe, 19x billiger als Opus)
```

## Dependencies
- `claude` CLI (claude -p für non-interactive runs)
- Python 3.12+ (für die Wrapper-Klassen)
- `subprocess` (stdlib)

## Usage

```python
from core import make_feature_pipeline, PRLoop, InfiniteAgenticLoop
from pathlib import Path

# Feature-Pipeline (implement → cleanup → verify → commit)
pipeline = make_feature_pipeline("docs/feature-spec.md")
pipeline.run(cwd="/path/to/repo")

# PR-Loop mit CI-Gate
loop = PRLoop(
    goal="Add payment integration with Stripe",
    max_iterations=8,
    ci_command="pytest && npm run test",
)
loop.run()

# Parallele Generierung (5 Varianten)
gen_loop = InfiniteAgenticLoop(
    spec_path=Path("specs/component.md"),
    output_dir=Path("generated/"),
    count=5,
    wave_size=3,
)
gen_loop.run()
```

## Gotchas & Learnings
- **set -e** in Shell-Skripten: Pipeline bricht bei erstem Fehler ab — gewollt!
- Context wächst nicht über Steps hinweg → bewusst keine Session-Continuity
- Infinite Mode braucht Interrupt-Handling (Ctrl+C) oder Context-Monitoring
- Sub-Agenten dürfen NIE in dieselbe Output-Datei schreiben (Iteration-ID vergeben!)
- Negative Instructions ("schreib nicht X") sind fragil → Cleanup als eigener Step

## Quelle
- Original: [everything-claude-code](https://github.com/affaan-m/everything-claude-code/tree/main/skills/autonomous-loops)
- Extrahiert: 2026-03-08
