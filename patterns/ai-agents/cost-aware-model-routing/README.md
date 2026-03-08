# cost-aware-model-routing

## Was ist das?
Automatische Auswahl des günstigsten Modells das eine Aufgabe lösen kann. Kombiniert Model-Routing nach Task-Komplexität, unveränderliches Budget-Tracking, smarte Retry-Logik und Prompt-Caching zu einer wiederverwendbaren Pipeline.

## Wann benutzen?
- Jede Anwendung die LLM-APIs aufruft (Claude, GPT, etc.)
- Batch-Verarbeitung wo Kosten sich summieren
- Multi-Modell-Architekturen mit intelligentem Routing
- Produktionssysteme die Budget-Guardrails brauchen

## Kern-Konzept

### Pricing Reference (2025-2026)
| Modell | Input ($/1M) | Output ($/1M) | Faktor |
|--------|-------------|--------------|--------|
| Haiku  | $0.80       | $4.00        | 1x     |
| Sonnet | $3.00       | $15.00       | ~4x    |
| Opus   | $15.00      | $75.00       | ~19x   |

→ Für einfache Tasks Haiku statt Opus = **19x günstiger bei gleicher Qualität**

### 4 Bausteine

**1. Model-Routing** — billiges Modell für einfache Tasks, teures nur wenn nötig
```python
select_model(text_length=500)    # → Haiku
select_model(text_length=15_000) # → Sonnet
select_model(complexity="high")  # → Opus
```

**2. Immutable Cost Tracking** — nie mutieren, immer neue Instanz zurückgeben
```python
tracker = tracker.add(record)  # neuer Tracker, alter unverändert
```

**3. Narrow Retry** — nur transiente Fehler wiederholen (Rate Limit, Timeout)
```python
# AuthenticationError, BadRequestError → sofort fehlschlagen
# RateLimitError, ConnectionError → Exponential Backoff
```

**4. Prompt Caching** — lange System-Prompts cachen (spart Cost + Latenz)
```python
{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
```

## Dependencies
- `anthropic` Python SDK
- Python 3.12+ (dataclasses mit `slots=True`, `frozen=True`)

## Usage

```python
from core import select_model, CostTracker, process_with_budget, task_complexity
import anthropic

client = anthropic.Anthropic()
tracker = CostTracker(budget_limit=2.00)

system_prompt = "You are a helpful assistant. " * 500  # Long → wird gecacht

# Mehrere Tasks mit automatischem Routing
for task, task_type in [
    ("Summarize this text...", "summarize"),       # → Haiku
    ("Implement OAuth2...", "implement"),           # → Sonnet
    ("Design the architecture...", "architect"),   # → Opus
]:
    result, tracker = process_with_budget(
        task=task,
        task_type=task_type,
        system_prompt=system_prompt,
        client=client,
        tracker=tracker,
    )
    print(f"[{result.model_id}] {result.content[:80]}...")

print(tracker.summary())
# Total: $0.0124 / $2.00
#   claude-haiku:   $0.0008
#   claude-sonnet:  $0.0089
#   claude-opus:    $0.0027
```

## Gotchas & Learnings
- **Nie alle Requests an Opus** — für Commit Messages ist Haiku 19x günstiger und genauso gut
- **Nur transiente Fehler retrien** — Auth-Fehler sofort werfen, nie retrien
- **Prompt Caching erst ab ~1024 Tokens** wirksam — nicht für kurze Prompts
- **Frozen Dataclass** für CostRecord: macht Auditing einfach, verhindert unbeabsichtigte Mutation
- **Budget vor dem Call prüfen** — nicht danach (zu spät wenn Budget überschritten)
- **Thresholds loggen** — so kann man sie basierend auf echten Daten tunen

## Anti-Patterns
- ❌ Überall Opus hardcoden
- ❌ Alle Fehler retrien (Budgetverschwendung bei permanenten Fehlern)
- ❌ Cost-State mutieren (schwer zu debuggen, schwer zu auditen)
- ❌ Modell-Namen überall im Code verteilen (stattdessen Konstanten/Config)

## Quelle
- Original: [everything-claude-code](https://github.com/affaan-m/everything-claude-code/tree/main/skills/cost-aware-llm-pipeline)
- Extrahiert: 2026-03-08
