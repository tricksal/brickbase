# vector-graph-memory

## Was ist das?
Hybrides Memory-System für AI-Agenten: Vector Search (semantisch) + Knowledge Graph (Beziehungen + Temporal Reasoning). Löst das klassische "MEMORY.md wird riesig und veraltet"-Problem durch automatisches Vergessen, Update-Tracking und implizites Speichern via Hooks.

## Wann benutzen?
- Agent braucht Long-Term Memory über mehrere Sessions
- Fakten über User/Kontext verändern sich über Zeit (z.B. "Arne baut jetzt Kognio v2")
- Kontext-Injection in LLM-Calls soll automatisch passieren (Memory Router)
- Man will "vergessen" können — ohne manuell MEMORY.md zu curatieren

## Kern-Konzept

```
WRITE:  content → embedding → graph node
                              + edge: "supersedes" alten Node

SEARCH: query → embedding → similar nodes
                          + graph traversal: linked nodes
                          → inject as context into LLM

DECAY:  cron → nodes mit altem last_accessed → confidence--
              confidence <= 0 → is_active = False
```

Jede Memory hat:
- `is_latest` — ob sie die aktuelle Version ist (oder schon überschrieben)
- `is_active` — ob sie noch relevant ist (oder schon decayed)
- `confidence` — nimmt ab wenn lange nicht accessed

## Dependencies
```
# Minimal (core.py nutzt nur stdlib)
# Für Produktion:
openai          # Embeddings (text-embedding-3-small)
pgvector        # Vector store (PostgreSQL Extension)
# oder:
chromadb        # Alternative lokale Vector DB
```

## Usage

```python
from core import VectorGraphMemory, MemoryRouter

# --- Basis Usage ---
store = VectorGraphMemory(decay_after_days=30)

# Speichern
m = store.add("User prefers Python", {"category": "preference"})

# Update (erstellt neue Version, markiert alte als superseded)
store.update(m.id, "User prefers Python, specifically FastAPI for APIs")

# Suchen (nur latest + active)
results = store.search("Python preferences", top_k=3)

# Graph-Link manuell
store.link(id_a, id_b, relation="related_to")

# Decay laufen lassen (z.B. täglich per Cron)
decayed = store.run_decay()

# --- Memory Router (Drop-in vor LLM) ---
router = MemoryRouter(store, llm_client=openai_client)

# Hook: automatisch Fakten aus Gespräch speichern
def fact_hook(user_msg, response):
    if "prefer" in response.lower():
        return f"User preference noted: {user_msg[:80]}"
    return None

router.add_hook(fact_hook)
reply = router.chat("Should I use FastAPI or Django?")
# → Relevant memories werden automatisch injiziert
# → Hook speichert Fakten automatisch nach dem Call
```

## Quelle
- Inspiration: Supermemory (supermemory.ai) — Dhravya Shah
- Talk: https://youtu.be/Io0mAsHkiRY
- GitHub: https://github.com/supermemory/supermemory
- Extrahiert: 2026-03-09

## Verwandte Patterns
- `agent-memory-patterns` — einfachere MEMORY.md-basierte Ansätze
- `agent-hooks` — Hook-System für implizite Side-Effects
- `document-knowledge-graph` — Graph-Patterns für Dokumente
