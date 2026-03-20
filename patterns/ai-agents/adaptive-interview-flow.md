# adaptive-interview-flow

**Kategorie:** `human-ai-interaction`  
**Quelle:** tricksal-contact, Meet Me Beyond (beyond.place), Orakel Schaffhausen  
**Status:** ✅ fertig  
**Datum:** 2026-03-20

---

## Problem

Ein AI-System muss einen Menschen durch ein Gespräch führen, dessen Ziel der Mensch selbst noch nicht kennt. Standardformulare und vordefinierte Skripte funktionieren nicht — sie fühlen sich kalt an und liefern oberflächliche Antworten. Freies Chat-Interface überfordert oder führt ins Leere.

---

## Pattern

Ein **adaptiver Gesprächsbaum**, der in Echtzeit aus den Antworten des Menschen die nächste Frage generiert. Das System hat ein Ziel (Qualifikation, existenzielle Frage, Selbsterkenntnis), aber keinen fixen Pfad dorthin.

```
Einstieg (Seed-Frage)
    ↓
Antwort des Menschen
    ↓
LLM analysiert Antwort → generiert nächste Frage + Reasoning
    ↓ (wiederhole N-mal)
Konvergenz: System erkennt Ziel erreicht
    ↓
Output: Zusammenfassung / Antwort / Termin / Orakel-Aussage
```

**Kernprinzip:** Die Frage ist das Artefakt. Nicht die Antwort des Systems, sondern der Prozess des Fragens bringt den Menschen zu etwas, das er vorher nicht kannte.

---

## Varianten

### 1. Qualifikations-Interview (tricksal-contact)
- **Ziel:** Verstehen wer der Visitor ist und was er braucht
- **Input:** E-Mail-verifizierte Session, offene + MC-Fragen
- **Output:** Personalisierte Zusammenfassung + optionaler Termin
- **Besonderheit:** Split-Screen — links zeigt die AI ihr Reasoning ("Thinking")
- **Signal:** LLM gibt `suggest_booking: true` wenn Termin sinnvoll

### 2. Philosophischer Gesprächsbaum (Meet Me Beyond)
- **Ziel:** Den Menschen zu einer tiefen, persönlichen Erkenntnis führen
- **Input:** Zwei Antwortoptionen pro Frage (binär, aber nicht simpel)
- **Output:** Unerwartete Gesprächstiefe, die ohne den Prozess nicht entstanden wäre
- **Besonderheit:** Kein sichtbares Ziel — der Weg ist das Ziel

### 3. Existenzielle Frage herausarbeiten (Orakel Schaffhausen)
- **Ziel:** Die eine echte Frage des Besuchers destillieren
- **Input:** Ja/Nein-Fragen, informiert durch Handanalyse (Vision AI)
- **Output:** Formulierte Kernfrage → Orakel-Antwort (Audio)
- **Besonderheit:** Zwei-Akt-Struktur — erst Hand lesen, dann Fragen. Hand-Profil informiert Fragen-Richtung.

---

## Core Implementation

```python
# core.py — Adaptive Interview Flow

from anthropic import Anthropic
import json

client = Anthropic()

def generate_next_question(
    context: dict,           # Seed-Kontext: Ziel, Persona, Tonalität
    conversation: list[dict], # Bisherige Turns: [{question, answer}]
    max_turns: int = 5
) -> dict:
    """
    Generiert die nächste adaptive Frage basierend auf dem Gesprächsverlauf.
    
    Returns:
        {
            "question": str,
            "type": "open" | "binary" | "mc",
            "options": list[str] | None,
            "thinking": str,    # Reasoning: warum diese Frage jetzt?
            "is_final": bool,   # True wenn Konvergenz erreicht
            "signal": str | None  # optionales Signal (z.B. "suggest_booking")
        }
    """
    turn_count = len(conversation)
    
    system_prompt = f"""
{context['system']}

GESPRÄCHSREGELN:
- Maximal {max_turns} Turns gesamt. Aktuell Turn {turn_count + 1}.
- Jede Frage basiert auf der vorherigen Antwort — kein Skript, kein fixes Schema.
- is_final = true wenn das Ziel erreicht ist oder max_turns überschritten.
- thinking: 1-2 ehrliche Sätze — was hast du in der letzten Antwort wahrgenommen und warum fragst du das jetzt?

Antworte ausschließlich als JSON:
{{
  "question": "...",
  "type": "open|binary|mc",
  "options": ["...", "..."] oder null,
  "thinking": "...",
  "is_final": false,
  "signal": null
}}
"""
    
    messages = []
    for turn in conversation:
        messages.append({"role": "assistant", "content": turn["question"]})
        messages.append({"role": "user", "content": turn["answer"]})
    
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=system_prompt,
        messages=messages if messages else [{"role": "user", "content": "Start"}]
    )
    
    return json.loads(response.content[0].text)


def run_interview(context: dict, get_answer_fn, max_turns: int = 5) -> list[dict]:
    """
    Führt ein komplettes Interview durch.
    get_answer_fn(question, options) → str  (z.B. CLI-Input oder API-Call)
    """
    conversation = []
    
    for _ in range(max_turns):
        result = generate_next_question(context, conversation, max_turns)
        answer = get_answer_fn(result["question"], result.get("options"))
        
        conversation.append({
            "question": result["question"],
            "thinking": result["thinking"],
            "answer": answer,
            "signal": result.get("signal")
        })
        
        if result.get("is_final"):
            break
    
    return conversation
```

---

## Kontext-Konfiguration (Beispiele)

```python
# tricksal-contact: Qualifikations-Interview
CONTACT_CONTEXT = {
    "system": """Du führst ein Qualifikations-Gespräch für eine Kreativagentur.
Ziel: Verstehen wer dieser Mensch ist, was ihn zu uns geführt hat, und ob ein Telefontermin sinnvoll wäre.
Tonalität: Warm, direkt, professionell. Kein Marketing-Speak.
Setze signal='suggest_booking' wenn Interesse konkret und Termin sinnvoll ist."""
}

# Meet Me Beyond: Philosophisches Gespräch
MMB_CONTEXT = {
    "system": """Du führst ein philosophisches Gespräch ohne vorgegebenes Ziel.
Jede Frage soll den Menschen tiefer in ein Thema führen, das ihn wirklich bewegt.
Immer genau zwei Antwortoptionen — keine Mitte, keine Ausweichmöglichkeit.
type='binary' für alle Fragen."""
}

# Orakel: Existenzielle Frage destillieren
ORACLE_CONTEXT = {
    "system": """Du bist ein Orakel. Deine Aufgabe: die eine echte Frage dieses Menschen herausarbeiten.
Nicht was er fragt — was er wirklich wissen will.
Nutze das Handprofil: {hand_profile}
Stelle Ja/Nein-Fragen die von außen nach innen führen.
is_final=true wenn die Kernfrage klar ist."""
}
```

---

## Schlüsseleigenschaften

| Eigenschaft | Beschreibung |
|---|---|
| **Adaptivität** | Keine fixen Pfade — jede Frage entsteht aus dem Kontext |
| **Transparenz** | Thinking-Feld macht das Reasoning sichtbar (links-Panel) |
| **Konvergenz** | System erkennt wenn Ziel erreicht (`is_final`) |
| **Signal** | Optionales Output-Signal für externe Aktionen (`suggest_booking` etc.) |
| **Konfigurierbar** | Alles über Context-Dict steuerbar: Ziel, Ton, Typ, Turns |

---

## Wo verwendet

- `tricksal/tricksal-contact` — `/opt/tricksal-contact/llm.py`
- `beyond.place / Meet Me Beyond` — MR-Installation
- `tricksal/orakel` — Exponat Museum zu Allerheiligen, Schaffhausen (2026)

---

## Verwandte Patterns

- [[iterative-refinement]] — ähnliche Feedback-Loop-Struktur, aber ohne menschlichen Input
- [[progressive-disclosure]] — schrittweise Informationspreisgabe
- [[agent-tool-loop]] — wenn der Agent selbst Tools aufruft statt den Menschen zu befragen
