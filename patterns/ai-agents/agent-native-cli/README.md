# agent-native-cli

> Make any tool controllable by AI agents via a well-designed CLI.

## Was ist das?

Ein Blueprint für CLIs, die **sowohl für Menschen als auch für AI Agents** optimiert sind.
Kern-Idee: CLI ist die universelle Schnittstelle für Agents — strukturiert, selbstdokumentierend, composable.

## Wann benutzen?

- Du willst ein Tool (GIMP, ffmpeg, eigene Software) für Agents zugänglich machen
- Du baust einen Agent der Software steuern muss
- Du willst eine CLI die sowohl interaktiv als auch in Pipelines funktioniert
- Du brauchst reproducible, stateful Agent-Sessions

## Kern-Konzept

Drei Bausteine:

### 1. Dual Output — JSON vs. Human

```python
emit(data={"key": "value"}, message="Human: Key set!")
```
- `--json` Flag → strukturierte JSON-Ausgabe für Agents
- Kein Flag → schöner Text für Menschen
- Agents können Output direkt parsen, keine Regex nötig

### 2. Session mit Undo/Redo

```python
session = Session.load_or_create("my-tool")
session.checkpoint()        # IMMER vor einer Mutation!
session.state["x"] = 42
session.save()
session.undo()              # State zurückrollen
```
- Session überlebt Process-Restarts (auf Disk gespeichert)
- Undo/Redo Stack bis 50 Schritte
- Agent kann Fehler rückgängig machen ohne von vorne anfangen

### 3. REPL Mode

```python
my-tool repl      # Interaktive Shell
> set x 42
> get x
> undo
> exit
```
- Session bleibt "warm" — kein State-Reload zwischen Commands
- Ideal für Agents in Coding-Loops (z.B. Claude Code)
- Auch als Script verwendbar (stdin pipen)

## Why CLI for Agents?

| Eigenschaft | Vorteil für Agents |
|-------------|-------------------|
| `--help` flags | Self-documenting, Agent kann Discovery machen |
| JSON Output | Kein Parsing von Freitext nötig |
| REPL Mode | Warm Session, weniger Overhead |
| Undo/Redo | Fehler behebbar ohne Neustart |
| Composable | Pipes und Chaining |
| Deterministic | Gleicher Command = gleiches Ergebnis |

## Dependencies

```
click>=8.0
```

## Usage

```bash
# Human mode
python core.py status
python core.py set name "Botto"
python core.py get name
python core.py undo

# Agent mode (JSON output)
python core.py --json status
python core.py --json set name "Botto"

# REPL
python core.py repl
```

## Erweitern

1. Neue Commands mit `@cli.command()` hinzufügen
2. Immer `session.checkpoint()` vor Mutations
3. `emit()` statt `print()` oder `click.echo()` für structured output
4. State in `session.state` (dict) speichern — wird automatisch persistiert

## Quelle

- Original: [CLI-Anything — HKUDS](https://github.com/HKUDS/CLI-Anything)
- Extrahiert: 2026-03-13
- Konzept: "Today's Software Serves Humans. Tomorrow's Users will be Agents."
