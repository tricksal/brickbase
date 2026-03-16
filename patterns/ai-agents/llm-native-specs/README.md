# llm-native-specs

## Was ist das?

Schreibe menschenlesbare **Spezifikationen** statt Code. Ein LLM "kompiliert" die Specs zur Laufzeit oder on-demand in ausführbaren Code. Ergebnis: Codebasen die 5-10x kleiner sind, leichter zu warten, und von jedem Teammitglied verstanden werden können.

Inspiriert von [CodeSpeak](https://codespeak.dev/) — einer LLM-nativen Programmiersprache.

## Wann benutzen?

- Wenn Logik sich regelmäßig ändert und Code-Wartung teuer ist
- Wenn Nicht-Entwickler Teile des Systems verstehen oder editieren sollen
- Wenn du schnell iterieren willst ohne Implementierungsdetails im Kopf behalten zu müssen
- Für Business-Rules, Validierungen, Transformationen, Workflows
- Überall wo Intent wichtiger ist als Implementierung

## Kern-Konzept

```
Traditionell:     Intent → [Developer] → Code → Ausführung
LLM-Native:       Intent → Spec-File   → [LLM] → Code → Ausführung
```

Der Developer schreibt jetzt **Specs**, nicht Code. Die Spec ist das primäre Artefakt.

## Was eine gute Spec enthält

```markdown
# FunctionName

## Was es tut
Eine klare Beschreibung der Funktion in Alltagssprache.

## Input
- param_name (typ): Was es bedeutet, nicht nur der Typ

## Output  
- Typ und was genau zurückgegeben wird

## Verhalten
- Edge Case 1: Was passiert wenn...
- Edge Case 2: Was passiert wenn...
- Sonderfall: ...

## Beispiele
Input: X → Output: Y
Input: A → Output: B
```

## Implementierung: Spec-Loader Pattern

```python
# spec_loader.py
import anthropic
from pathlib import Path

def compile_spec(spec_file: str, language: str = "python") -> str:
    """Kompiliert eine .spec.md Datei zu ausführbarem Code."""
    spec = Path(spec_file).read_text()
    
    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": f"""Implement the following specification in {language}.
Return ONLY the code, no explanation, no markdown fences.

SPEC:
{spec}"""
        }]
    )
    return response.content[0].text


def load_compiled(spec_file: str, cache_dir: str = ".compiled") -> str:
    """Ladet eine kompilierte Version aus Cache oder kompiliert neu."""
    from pathlib import Path
    import hashlib
    
    spec_path = Path(spec_file)
    spec_content = spec_path.read_text()
    spec_hash = hashlib.md5(spec_content.encode()).hexdigest()[:8]
    
    cache_path = Path(cache_dir) / f"{spec_path.stem}_{spec_hash}.py"
    cache_path.parent.mkdir(exist_ok=True)
    
    if cache_path.exists():
        return cache_path.read_text()
    
    compiled = compile_spec(spec_file)
    cache_path.write_text(compiled)
    return compiled
```

## Usage

```python
# 1. Spec schreiben: validate_email.spec.md
# 2. Kompilieren und ausführen:

code = compile_spec("validate_email.spec.md")
exec(code)  # Funktionen landen im globalen Namespace

# Oder mit Caching:
code = load_compiled("validate_email.spec.md")
exec(code)
```

## Mixed Mode

In echten Projekten mischen sich Spec-Dateien und normaler Code:

```
project/
  core/
    auth.py           # manueller Code (kritisch, performance-sensitiv)
    email.spec.md     # Spec (Business Logic, ändert sich oft)
    validation.spec.md
  api/
    routes.py         # manuell
    responses.spec.md # Spec
```

## Dependencies

- `anthropic` (für compile_spec)
- Python 3.9+

## Quelle

- CodeSpeak: https://codespeak.dev/
- Konzept: Intent-driven development, LLM as compiler
- Extrahiert: 2026-03-16
