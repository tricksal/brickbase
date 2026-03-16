# tiered-context-loading

## Was ist das?

Agent-Context in drei Schichten organisieren: L0 (immer geladen), L1 (session-spezifisch), L2 (on-demand per Retrieval). Reduziert Token-Verbrauch radikal, verbessert Retrieval-Qualität und macht den Context-Zugriff vollständig observierbar.

Inspiriert von [OpenViking (volcengine/ByteDance)](https://github.com/volcengine/OpenViking) — einer Context-Datenbank die das Filesystem-Paradigma statt klassischem RAG nutzt.

## Das Problem mit flachem RAG

```
Klassisches RAG:
User Query → Embeddings → k-nearest-neighbor → [Chunk1, Chunk2, Chunk3] → LLM

Probleme:
- Globale Sicht fehlt: Chunk weiss nicht wo er "herkommt"
- Black Box: warum wurde genau dieser Chunk gefunden?
- Alles gleich wichtig: Core-Facts und Details konkurrieren
- Keine Hierarchie: Agent-Identity vs. Projekt-Docs vs. Schritt-Logs
```

## Die Lösung: L0/L1/L2

```
L0 — IMMER GELADEN (Core Identity + Permanent Rules)
     Wer ist der Agent? Welche Grundregeln gelten?
     Klein, unveränderlich, immer im Context.
     z.B.: SOUL.md, AGENTS.md, USER.md

L1 — SESSION-SPEZIFISCH (Task-Kontext)
     Was ist der aktuelle Task? Welche Projekte sind aktiv?
     Wird bei Session-Start geladen, am Ende komprimiert.
     z.B.: memory/2026-03-16.md, aktive Skills, HEARTBEAT.md

L2 — ON-DEMAND (Detail + History)
     Spezifische Docs, alte Memory-Files, Projekt-Details.
     Nur laden wenn explizit gebraucht — per Retrieval oder direktem Abruf.
     z.B.: /opt/superrig-app/llm.py, ältere Obsidian-Docs, Recherche-Files
```

## Warum das funktioniert

1. **Hierarchische Relevanz**: L0-Fakten überschreiben immer L2-Details
2. **Token-Effizienz**: 80% des Context-Bedarfs durch L2 on-demand → nur laden was gebraucht wird
3. **Observierbar**: Jede Information hat eine klare Herkunft (L0/L1/L2 + Pfad)
4. **Self-Evolving**: Session-Ende → L1 komprimieren → wichtiges nach L0 promoten

## Filesystem-Paradigma

OpenViking's Kernidee: Context-Management wie Dateiverwaltung.

```
context/
├── L0/                      ← immer im System Prompt
│   ├── identity.md          # Wer ist der Agent
│   ├── user.md              # Wer ist der User
│   └── core_rules.md        # Unveränderliche Regeln
│
├── L1/                      ← session-init geladen
│   ├── today.md             # Tages-Memory
│   ├── active_projects.md   # Aktive Projekte
│   └── heartbeat.md         # Laufende Checks
│
└── L2/                      ← on-demand retrieval
    ├── memory/              # Historische Memory-Files
    ├── projects/            # Projekt-Docs
    └── knowledge/           # Wissensbasis
```

Das ist kein neues Konzept — es ist wie ein Betriebssystem:
- CPU-Register = L0 (immer verfügbar, ultra-schnell)
- RAM = L1 (session-spezifisch, schnell)
- Disk = L2 (persistent, on-demand)

## Implementation

Komplett in `core.py`:
- `TieredContextManager`: verwaltet alle drei Schichten
- `load_session_context()`: baut den vollständigen System-Prompt zusammen
- `retrieve_l2()`: keyword + semantic search über L2
- `compact_l1()`: extrahiert wichtige Fakten am Session-Ende
- `promote_to_l0()`: Fact in permanenten Context aufnehmen

## Wann benutzen?

- Agent hat viele Dokumente aber nicht alle sind immer relevant
- Token-Kosten sind ein Problem (L2 on-demand spart 50-80%)
- Du willst wissen WARUM ein bestimmter Context-Teil geladen wurde
- Long-running Agents die über Sessions hinweg smarter werden sollen

## Verwandte Patterns

- `agent-memory-patterns` - Memory-Management generell
- `compiled-context` - Context-Aufbereitung vor Agent-Run
- `self-evolving-agent` - Agent der aus Erfahrungen lernt

## Quelle

- OpenViking: https://github.com/volcengine/OpenViking
- Extrahiert: 2026-03-16
