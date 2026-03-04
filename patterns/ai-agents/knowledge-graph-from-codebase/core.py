"""
knowledge-graph-from-codebase — Generische Referenz-Implementierung
====================================================================
Vereinfachte Python-Version des GitNexus-Konzepts.

Was es zeigt:
  1. Python-Codebase parsen mit ast-Modul (Symbol-Extraktion)
  2. Abhängigkeits-Graph aufbauen (dict-of-sets, kein KuzuDB nötig)
  3. Impact-Analysis: "Was hängt von X ab?" (Upstream-Traversal)
  4. Execution-Flow-Tracing: Entry Points → Execution Paths

Direkt ausführbar: python core.py
Testet sich selbst (analysiert seinen eigenen Source-Code).

Inspiriert von: https://github.com/abhigyanpatwari/GitNexus
Brickbase-Pattern: https://github.com/tricksal/brickbase/tree/main/patterns/ai-agents/knowledge-graph-from-codebase
"""

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from collections import defaultdict, deque
import json


# ============================================================================
# DATA MODEL
# ============================================================================

@dataclass
class Symbol:
    """Ein einzelnes Code-Symbol (Funktion, Klasse, Methode)."""
    uid: str                    # "Function:myfile.py:my_function"
    name: str                   # "my_function"
    kind: str                   # "function" | "class" | "method"
    file_path: str              # "src/myfile.py"
    start_line: int
    end_line: int
    is_exported: bool = True    # In Python: alles ohne _ ist "exportiert"


@dataclass
class KnowledgeGraph:
    """
    Der Knowledge Graph.

    Knoten: Symbole (functions, classes, methods)
    Kanten als Adjazenzlisten:
      - calls[uid] = {uid, uid, ...}      (CALLS: A ruft B auf)
      - called_by[uid] = {uid, uid, ...}  (inverse von calls — für Upstream-Suche)
      - imports[file] = {file, file, ...} (IMPORTS: welche Datei importiert welche)
      - defines[file] = {uid, uid, ...}   (DEFINES: Datei → Symbole)
    """
    symbols: dict[str, Symbol] = field(default_factory=dict)
    calls: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    called_by: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    imports: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    defines: dict[str, set] = field(default_factory=lambda: defaultdict(set))

    def add_symbol(self, symbol: Symbol) -> None:
        self.symbols[symbol.uid] = symbol
        self.defines[symbol.file_path].add(symbol.uid)

    def add_call(self, caller_uid: str, callee_uid: str) -> None:
        """Fügt eine CALLS-Kante hinzu (bidirektional für Traversal)."""
        self.calls[caller_uid].add(callee_uid)
        self.called_by[callee_uid].add(caller_uid)

    def add_import(self, from_file: str, to_file: str) -> None:
        self.imports[from_file].add(to_file)

    @property
    def node_count(self) -> int:
        return len(self.symbols)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.calls.values())


# ============================================================================
# PHASE 1 + 2: AST-PARSING — Symbol-Extraktion
# ============================================================================

def extract_symbols_from_file(file_path: str, content: str) -> list[Symbol]:
    """
    Parsed eine Python-Datei mit dem ast-Modul und extrahiert alle
    Funktionen, Klassen und Methoden als Symbol-Objekte.

    Entspricht dem 'parsing-processor' in GitNexus (tree-sitter-basiert,
    aber das Konzept ist identisch).
    """
    symbols = []
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        return symbols

    # AST traversieren und alle relevanten Knoten finden
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Unterscheide Methoden (innerhalb einer Klasse) von Funktionen
            kind = "function"
            uid = f"Function:{file_path}:{node.name}"

            symbol = Symbol(
                uid=uid,
                name=node.name,
                kind=kind,
                file_path=file_path,
                start_line=node.lineno,
                end_line=getattr(node, 'end_lineno', node.lineno),
                is_exported=not node.name.startswith('_'),
            )
            symbols.append(symbol)

        elif isinstance(node, ast.ClassDef):
            uid = f"Class:{file_path}:{node.name}"
            symbol = Symbol(
                uid=uid,
                name=node.name,
                kind="class",
                file_path=file_path,
                start_line=node.lineno,
                end_line=getattr(node, 'end_lineno', node.lineno),
                is_exported=not node.name.startswith('_'),
            )
            symbols.append(symbol)

    return symbols


# ============================================================================
# PHASE 3: RESOLUTION — Call-Analyse
# ============================================================================

def extract_calls_from_file(
    file_path: str,
    content: str,
    symbol_table: dict[str, Symbol],
) -> list[tuple[str, str]]:
    """
    Findet alle Funktionsaufrufe in einer Datei und versucht sie auf
    bekannte Symbole aufzulösen.

    Gibt Liste von (caller_uid, callee_uid) zurück.

    VEREINFACHUNG: Wir matchen nur nach Name, nicht nach Scope/Typ.
    GitNexus hat hier viel komplexere Language-Aware Resolution.
    """
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        return []

    # Index: name → uid (für schnelle Auflösung)
    name_to_uid: dict[str, list[str]] = defaultdict(list)
    for uid, sym in symbol_table.items():
        name_to_uid[sym.name].append(uid)

    calls = []

    class CallVisitor(ast.NodeVisitor):
        def __init__(self, current_uid: Optional[str]):
            self.current_uid = current_uid

        def visit_Call(self, node):
            # Extrahiere den Namen des Aufrufs
            callee_name = None
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr

            if callee_name and self.current_uid:
                # Finde alle Symbole mit diesem Namen
                candidates = name_to_uid.get(callee_name, [])
                for callee_uid in candidates:
                    if callee_uid != self.current_uid:  # Kein Self-Loop
                        calls.append((self.current_uid, callee_uid))

            self.generic_visit(node)

    # Besuche alle Funktionen/Methoden im File
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            caller_uid = f"Function:{file_path}:{node.name}"
            if caller_uid in symbol_table:
                visitor = CallVisitor(caller_uid)
                visitor.visit(node)

    return calls


def extract_imports_from_file(file_path: str, content: str, all_files: list[str]) -> list[tuple[str, str]]:
    """
    Extrahiert Import-Statements und mappt sie auf bekannte Dateipfade.
    """
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        return []

    # Einfache Mapping-Heuristik: "from mymodule import X" → suche mymodule.py
    imports = []
    file_stem_map = {Path(f).stem: f for f in all_files}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module_name = None
            if isinstance(node, ast.ImportFrom) and node.module:
                # "from foo.bar import X" → "bar"
                module_name = node.module.split('.')[-1]
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split('.')[-1]

            if module_name and module_name in file_stem_map:
                target_file = file_stem_map[module_name]
                if target_file != file_path:
                    imports.append((file_path, target_file))

    return imports


# ============================================================================
# PIPELINE: Alles zusammenführen
# ============================================================================

def build_knowledge_graph(repo_path: str) -> KnowledgeGraph:
    """
    Haupt-Pipeline: Repository → Knowledge Graph

    Phasen (entsprechend GitNexus):
      1. File-Scan
      2. AST-Parsing (Symbol-Extraktion)
      3. Resolution (Imports, Calls)
      [Community Detection und Process-Tracing als separate Funktionen unten]
    """
    graph = KnowledgeGraph()
    repo = Path(repo_path)

    print(f"\n🔍 Scanning: {repo_path}")

    # ── Phase 1: File-Scan ─────────────────────────────────────────────
    python_files = list(repo.rglob("*.py"))
    # Versteckte Ordner und __pycache__ überspringen
    python_files = [
        f for f in python_files
        if not any(part.startswith('.') or part == '__pycache__' for part in f.parts)
    ]
    file_paths = [str(f) for f in python_files]
    print(f"  📁 {len(file_paths)} Python-Dateien gefunden")

    # ── Phase 2: AST-Parsing ───────────────────────────────────────────
    file_contents: dict[str, str] = {}
    for fp in file_paths:
        try:
            content = Path(fp).read_text(encoding='utf-8', errors='ignore')
            file_contents[fp] = content
            symbols = extract_symbols_from_file(fp, content)
            for sym in symbols:
                graph.add_symbol(sym)
        except Exception as e:
            print(f"  ⚠️  Fehler beim Lesen von {fp}: {e}")

    print(f"  🧩 {graph.node_count} Symbole extrahiert")

    # ── Phase 3: Resolution ────────────────────────────────────────────
    # Imports auflösen
    for fp, content in file_contents.items():
        for from_file, to_file in extract_imports_from_file(fp, content, file_paths):
            graph.add_import(from_file, to_file)

    # Calls auflösen
    total_calls = 0
    for fp, content in file_contents.items():
        for caller_uid, callee_uid in extract_calls_from_file(fp, content, graph.symbols):
            graph.add_call(caller_uid, callee_uid)
            total_calls += 1

    print(f"  🔗 {total_calls} Call-Kanten aufgelöst")
    print(f"  📦 {sum(len(v) for v in graph.imports.values())} Import-Kanten aufgelöst")

    return graph


# ============================================================================
# IMPACT ANALYSIS: "Was hängt von X ab?"
# ============================================================================

def impact_analysis(
    graph: KnowledgeGraph,
    target_name: str,
    direction: str = "upstream",  # "upstream" = wer hängt von X ab | "downstream" = was nutzt X
    max_depth: int = 3,
) -> dict:
    """
    Blast-Radius-Analyse: Zeigt alle Symbole, die von target_name betroffen wären.

    Entspricht dem 'impact'-Tool in GitNexus.

    direction="upstream":  Wer RUFT target_name auf? (WILL BREAK bei Änderung)
    direction="downstream": Was RUFT target_name auf? (Was hängt von externen Deps ab?)
    """
    # Finde alle Symbole mit dem gesuchten Namen
    targets = [s for s in graph.symbols.values() if s.name == target_name]

    if not targets:
        return {"error": f"Symbol '{target_name}' nicht gefunden"}

    results = {
        "target": target_name,
        "direction": direction,
        "by_depth": {},
        "summary": {},
    }

    for target in targets:
        # BFS durch den Call-Graph
        visited = set()
        queue = deque([(target.uid, 0)])
        depth_groups: dict[int, list[dict]] = defaultdict(list)

        while queue:
            current_uid, depth = queue.popleft()
            if current_uid in visited or depth > max_depth:
                continue
            visited.add(current_uid)

            if depth > 0:  # Depth 0 ist das Target selbst
                sym = graph.symbols.get(current_uid)
                if sym:
                    depth_groups[depth].append({
                        "uid": sym.uid,
                        "name": sym.name,
                        "kind": sym.kind,
                        "file": sym.file_path,
                        "risk": "WILL BREAK" if depth == 1 else "LIKELY AFFECTED" if depth == 2 else "MAY NEED TESTING",
                    })

            # Nächste Ebene: upstream = wer ruft uns auf, downstream = wen rufen wir auf
            if direction == "upstream":
                neighbors = graph.called_by.get(current_uid, set())
            else:
                neighbors = graph.calls.get(current_uid, set())

            for neighbor_uid in neighbors:
                if neighbor_uid not in visited:
                    queue.append((neighbor_uid, depth + 1))

        # Ergebnisse zusammenfassen
        results["by_depth"].update({
            f"depth_{d}": items
            for d, items in sorted(depth_groups.items())
        })
        results["summary"] = {
            "target_uid": target.uid,
            "total_affected": len(visited) - 1,
            "direct": len(depth_groups.get(1, [])),
            "indirect": len(depth_groups.get(2, [])),
            "transitive": len(depth_groups.get(3, [])),
        }

    return results


# ============================================================================
# PROCESS TRACING: Execution Flows finden
# ============================================================================

def find_entry_points(graph: KnowledgeGraph) -> list[Symbol]:
    """
    Entry Points = Symbole, die NICHT von anderen internen Symbolen aufgerufen werden.
    Entspricht dem ersten Schritt des process-processors in GitNexus.
    """
    all_uids = set(graph.symbols.keys())
    called_uids = set()
    for callee_set in graph.calls.values():
        called_uids.update(callee_set)

    # Entry Points: aufgerufen von niemand intern + exportiert
    entry_points = []
    for uid in all_uids:
        sym = graph.symbols[uid]
        if uid not in called_uids and sym.is_exported:
            entry_points.append(sym)

    return entry_points


def trace_execution_flow(
    graph: KnowledgeGraph,
    entry_point: Symbol,
    max_depth: int = 8,
    max_branching: int = 3,
) -> list[str]:
    """
    Verfolgt den Ausführungspfad von einem Entry Point aus.
    Gibt geordnete Liste von Symbol-UIDs zurück.

    Entspricht dem BFS-Traversal im process-processor.
    """
    trace = []
    visited = set()
    queue = deque([(entry_point.uid, 0)])

    while queue:
        uid, depth = queue.popleft()
        if uid in visited or depth > max_depth:
            continue
        visited.add(uid)
        trace.append(uid)

        callees = list(graph.calls.get(uid, set()))[:max_branching]
        for callee_uid in callees:
            if callee_uid not in visited:
                queue.append((callee_uid, depth + 1))

    return trace


def detect_processes(graph: KnowledgeGraph, max_processes: int = 10) -> list[dict]:
    """
    Erkennt Execution Flows (Prozesse) im Knowledge Graph.
    """
    entry_points = find_entry_points(graph)
    processes = []

    for ep in entry_points[:max_processes]:
        trace = trace_execution_flow(graph, ep)
        if len(trace) < 2:  # Min. 2 Schritte für sinnvollen Prozess
            continue

        terminal_uid = trace[-1]
        terminal = graph.symbols.get(terminal_uid)

        processes.append({
            "id": f"proc_{ep.name}",
            "label": f"{ep.name} → {terminal.name if terminal else '?'}",
            "entry_point": ep.uid,
            "terminal": terminal_uid,
            "step_count": len(trace),
            "trace": trace,
            "steps": [
                {"step": i + 1, "uid": uid, "name": graph.symbols[uid].name}
                for i, uid in enumerate(trace)
                if uid in graph.symbols
            ],
        })

    return processes


# ============================================================================
# QUERY: Hybrid-Suche (vereinfachter BM25)
# ============================================================================

def search_symbols(graph: KnowledgeGraph, query: str, limit: int = 10) -> list[dict]:
    """
    Einfache Keyword-Suche über alle Symbole.
    In GitNexus: BM25 + semantische Vektoren + RRF-Kombinierung.
    Hier: Substring-Matching als Demonstration.
    """
    query_lower = query.lower()
    results = []

    for uid, sym in graph.symbols.items():
        score = 0.0
        # Exakter Name-Match: höchster Score
        if query_lower == sym.name.lower():
            score = 1.0
        # Name enthält Query
        elif query_lower in sym.name.lower():
            score = 0.7
        # Dateiname enthält Query
        elif query_lower in sym.file_path.lower():
            score = 0.3

        if score > 0:
            results.append({
                "uid": uid,
                "name": sym.name,
                "kind": sym.kind,
                "file": sym.file_path,
                "score": score,
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


# ============================================================================
# DEMO: Selbst-Analyse
# ============================================================================

def demo():
    """
    Demo: Analysiert dieses Skript selbst und zeigt die wichtigsten Konzepte.
    """
    this_file = __file__
    this_dir = str(Path(this_file).parent)

    print("=" * 60)
    print("🧱 Knowledge Graph from Codebase — Demo")
    print("=" * 60)

    # ── Schritt 1: Graph aufbauen ───────────────────────────────────────
    graph = build_knowledge_graph(this_dir)

    print(f"\n📊 Graph-Stats:")
    print(f"   Symbole: {graph.node_count}")
    print(f"   CALLS-Kanten: {graph.edge_count}")
    print(f"   IMPORTS-Kanten: {sum(len(v) for v in graph.imports.values())}")

    # ── Schritt 2: Alle Symbole zeigen ─────────────────────────────────
    print(f"\n🧩 Symbole in diesem File:")
    for uid, sym in graph.symbols.items():
        exported = "✓" if sym.is_exported else "·"
        print(f"   {exported} [{sym.kind:8}] {sym.name} (L{sym.start_line})")

    # ── Schritt 3: Impact Analysis ─────────────────────────────────────
    print(f"\n💥 Impact Analysis: Wer hängt von 'extract_symbols_from_file' ab?")
    impact = impact_analysis(graph, "extract_symbols_from_file", direction="upstream")
    if "error" not in impact:
        print(f"   Summary: {json.dumps(impact['summary'], indent=4)}")
        for depth_key, items in impact["by_depth"].items():
            print(f"\n   {depth_key}:")
            for item in items:
                print(f"     → {item['name']} ({item['risk']}) in {Path(item['file']).name}")
    else:
        print(f"   {impact['error']}")

    # ── Schritt 4: Execution Flows ─────────────────────────────────────
    print(f"\n🔄 Execution Flows (Entry Points → Traces):")
    processes = detect_processes(graph, max_processes=5)
    for proc in processes:
        step_names = [s["name"] for s in proc["steps"]]
        print(f"   [{proc['id']}] {proc['label']} ({proc['step_count']} Schritte)")
        print(f"     Trace: {' → '.join(step_names[:5])}{'...' if len(step_names) > 5 else ''}")

    # ── Schritt 5: Suche ───────────────────────────────────────────────
    print(f"\n🔍 Symbol-Suche: 'impact'")
    results = search_symbols(graph, "impact")
    for r in results[:5]:
        print(f"   [{r['score']:.1f}] {r['name']} ({r['kind']}) in {Path(r['file']).name}")

    print(f"\n✅ Demo abgeschlossen!")
    print(f"   → Für Production: GitNexus nutzt Tree-sitter, KuzuDB, HNSW-Vektoren, Leiden-Clustering")
    print(f"   → https://github.com/abhigyanpatwari/GitNexus")


if __name__ == "__main__":
    demo()
