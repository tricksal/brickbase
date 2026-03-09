"""
vector-graph-memory — Brickbase Pattern
========================================
Hybrid memory system for AI agents combining vector search (semantic)
with a knowledge graph (relationships + temporal reasoning).

Inspired by Supermemory's architecture (supermemory.ai / Dhravya Shah).

Key concepts:
- Memories are nodes in a graph, linked by semantic and explicit relationships
- Each memory has an `is_latest` flag for temporal reasoning
- Old versions are kept (audit trail) but excluded from default search
- A simple decay mechanism marks stale memories as inactive
"""

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Memory:
    """A single unit of memory (node in the graph)."""
    id: str
    content: str
    created_at: float  # Unix timestamp
    updated_at: float
    is_latest: bool = True       # False for superseded versions
    is_active: bool = True       # False for decayed/forgotten memories
    confidence: float = 1.0      # 0.0-1.0, decreases with decay
    access_count: int = 0        # How often this memory was retrieved
    last_accessed: Optional[float] = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(cls, content: str, metadata: dict = None) -> "Memory":
        now = time.time()
        memory_id = hashlib.sha256(f"{content}{now}".encode()).hexdigest()[:12]
        return cls(
            id=memory_id,
            content=content,
            created_at=now,
            updated_at=now,
            metadata=metadata or {}
        )


@dataclass
class MemoryEdge:
    """A relationship between two memory nodes."""
    source_id: str
    target_id: str
    relation: str   # "supersedes", "related_to", "contradicts", "supports"
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Vector-Graph Memory Store
# ---------------------------------------------------------------------------

class VectorGraphMemory:
    """
    Hybrid memory store: in-memory vector search + graph relationships.

    For production, replace the in-memory vector store with a proper
    embedding model + pgvector/Chroma/Pinecone. The graph logic stays the same.
    """

    def __init__(self, decay_after_days: float = 30.0, decay_rate: float = 0.1):
        """
        Args:
            decay_after_days: Memories not accessed for this long start decaying.
            decay_rate: Confidence reduction per decay cycle (0.0-1.0).
        """
        self.memories: dict[str, Memory] = {}
        self.edges: list[MemoryEdge] = []
        self.decay_after_seconds = decay_after_days * 86400
        self.decay_rate = decay_rate

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    def add(self, content: str, metadata: dict = None) -> Memory:
        """
        Add a new memory. Checks for existing similar memory and
        creates an update relationship if found.
        """
        memory = Memory.create(content, metadata)

        # Check for existing memory with same "topic" (naive: same first 40 chars)
        existing = self._find_similar(content)
        if existing:
            # Mark old version as superseded
            existing.is_latest = False
            existing.updated_at = time.time()
            # Create graph edge: new supersedes old
            edge = MemoryEdge(
                source_id=memory.id,
                target_id=existing.id,
                relation="supersedes"
            )
            self.edges.append(edge)

        self.memories[memory.id] = memory
        return memory

    def update(self, memory_id: str, new_content: str) -> Optional[Memory]:
        """Explicitly update a memory — creates new version, marks old."""
        if memory_id not in self.memories:
            return None
        old = self.memories[memory_id]
        return self.add(new_content, metadata={**old.metadata, "previous_id": memory_id})

    def link(self, source_id: str, target_id: str, relation: str, weight: float = 1.0):
        """Manually create a relationship between two memories."""
        if source_id not in self.memories or target_id not in self.memories:
            raise ValueError("Both memory IDs must exist")
        edge = MemoryEdge(source_id, target_id, relation, weight)
        self.edges.append(edge)

    # ------------------------------------------------------------------
    # Read Operations
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 5,
        include_graph: bool = True,
        only_latest: bool = True
    ) -> list[Memory]:
        """
        Search memories. In production: replace with embedding similarity.
        Returns top_k memories, optionally expanded via graph traversal.

        Args:
            query: Search query text.
            top_k: Number of direct matches to return.
            include_graph: Also return graph-linked memories.
            only_latest: Skip superseded memory versions.
        """
        # --- Simple keyword search (replace with embedding similarity) ---
        candidates = [
            m for m in self.memories.values()
            if m.is_active
            and (not only_latest or m.is_latest)
        ]

        scored = []
        query_lower = query.lower()
        for m in candidates:
            # Naive scoring: word overlap (replace with cosine similarity)
            words = set(query_lower.split())
            content_words = set(m.content.lower().split())
            overlap = len(words & content_words)
            if overlap > 0:
                score = overlap / max(len(words), 1)
                scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        direct_results = [m for _, m in scored[:top_k]]

        # --- Update access tracking ---
        for m in direct_results:
            m.access_count += 1
            m.last_accessed = time.time()

        if not include_graph:
            return direct_results

        # --- Graph expansion: add linked memories ---
        result_ids = {m.id for m in direct_results}
        expanded = list(direct_results)

        for mem in direct_results:
            linked = self._get_linked(mem.id, relation="related_to")
            for linked_mem in linked:
                if linked_mem.id not in result_ids and linked_mem.is_active:
                    expanded.append(linked_mem)
                    result_ids.add(linked_mem.id)

        return expanded

    def get(self, memory_id: str) -> Optional[Memory]:
        """Retrieve a specific memory by ID."""
        mem = self.memories.get(memory_id)
        if mem:
            mem.access_count += 1
            mem.last_accessed = time.time()
        return mem

    def get_history(self, memory_id: str) -> list[Memory]:
        """Return all versions of a memory (latest + superseded)."""
        history = [self.memories[memory_id]]
        # Follow 'supersedes' edges backward
        current_id = memory_id
        while True:
            superseded = None
            for edge in self.edges:
                if edge.source_id == current_id and edge.relation == "supersedes":
                    superseded = self.memories.get(edge.target_id)
                    break
            if not superseded:
                break
            history.append(superseded)
            current_id = superseded.id
        return history

    # ------------------------------------------------------------------
    # Decay (Auto-Forgetting)
    # ------------------------------------------------------------------

    def run_decay(self) -> int:
        """
        Apply decay to memories not accessed for `decay_after_days`.
        Returns number of memories decayed/deactivated.
        """
        now = time.time()
        decayed_count = 0

        for mem in self.memories.values():
            if not mem.is_active:
                continue
            last = mem.last_accessed or mem.created_at
            age = now - last
            if age > self.decay_after_seconds:
                mem.confidence = max(0.0, mem.confidence - self.decay_rate)
                if mem.confidence <= 0.0:
                    mem.is_active = False
                    decayed_count += 1

        return decayed_count

    # ------------------------------------------------------------------
    # Persistence (simple JSON)
    # ------------------------------------------------------------------

    def export(self) -> dict:
        """Export all memories and edges as JSON-serializable dict."""
        return {
            "memories": {k: asdict(v) for k, v in self.memories.items()},
            "edges": [asdict(e) for e in self.edges],
            "exported_at": datetime.now(timezone.utc).isoformat()
        }

    def load(self, data: dict):
        """Load memories from exported dict."""
        self.memories = {
            k: Memory(**v) for k, v in data.get("memories", {}).items()
        }
        self.edges = [MemoryEdge(**e) for e in data.get("edges", [])]

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    def _find_similar(self, content: str, threshold: int = 4) -> Optional[Memory]:
        """
        Naive similarity: find existing memory with high word overlap.
        Replace with embedding cosine similarity in production.
        """
        words = set(content.lower().split())
        for mem in self.memories.values():
            if not mem.is_latest:
                continue
            overlap = len(words & set(mem.content.lower().split()))
            if overlap >= threshold:
                return mem
        return None

    def _get_linked(self, memory_id: str, relation: str = None) -> list[Memory]:
        """Return all memories linked to the given memory."""
        linked = []
        for edge in self.edges:
            if edge.source_id == memory_id:
                if relation is None or edge.relation == relation:
                    target = self.memories.get(edge.target_id)
                    if target:
                        linked.append(target)
        return linked


# ---------------------------------------------------------------------------
# Memory-Router Pattern (Drop-in Proxy)
# ---------------------------------------------------------------------------

class MemoryRouter:
    """
    Drop-in wrapper around any LLM client that injects relevant memories
    into each call and implicitly saves key facts from the response.

    Usage:
        memory = VectorGraphMemory()
        router = MemoryRouter(memory, llm_client=your_openai_client)
        response = router.chat("What did we discuss last week?")
    """

    def __init__(self, memory: VectorGraphMemory, llm_client=None):
        self.memory = memory
        self.llm = llm_client
        self._hooks: list = []  # list of callables: (user_msg, response) -> Memory|None

    def add_hook(self, hook_fn):
        """
        Register a hook that runs after each LLM call.
        Hook signature: fn(user_message: str, response: str) -> str | None
        If it returns a string, that string is saved as a new memory.
        """
        self._hooks.append(hook_fn)

    def chat(self, message: str, system: str = None, top_k: int = 3) -> str:
        """
        Chat with memory injection. Retrieves relevant context,
        calls the LLM, then runs hooks to save implicit memories.
        """
        # 1. Retrieve relevant memories
        relevant = self.memory.search(message, top_k=top_k)
        memory_context = self._format_context(relevant)

        # 2. Build messages with injected memory
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        if memory_context:
            messages.append({
                "role": "system",
                "content": f"[Relevant memories]\n{memory_context}"
            })
        messages.append({"role": "user", "content": message})

        # 3. Call LLM (placeholder — replace with actual client call)
        if self.llm:
            response = self.llm.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages
            ).choices[0].message.content
        else:
            response = "[LLM not configured — inject your own client]"

        # 4. Run implicit-save hooks
        for hook in self._hooks:
            to_save = hook(message, response)
            if to_save:
                self.memory.add(to_save, metadata={"source": "hook"})

        return response

    def _format_context(self, memories: list[Memory]) -> str:
        if not memories:
            return ""
        lines = []
        for m in memories:
            date = datetime.fromtimestamp(m.created_at).strftime("%Y-%m-%d")
            lines.append(f"- [{date}] {m.content}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Quick Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    store = VectorGraphMemory(decay_after_days=7)

    # Add some memories
    m1 = store.add("User prefers Python over JavaScript", {"category": "preference"})
    m2 = store.add("User is building a Kognio learning app with FastAPI")
    m3 = store.add("User updated: Kognio is now live at kognio.de with Stripe")
    store.link(m3.id, m2.id, "related_to")

    # Search
    results = store.search("Kognio project", top_k=2)
    print("Search results:")
    for r in results:
        print(f"  [{r.id}] latest={r.is_latest} | {r.content}")

    # Show graph history
    print("\nKognio memory history:")
    for r in store.get_history(m3.id):
        print(f"  [{r.id}] is_latest={r.is_latest} | {r.content}")

    # Export/Import
    data = store.export()
    print(f"\nExported {len(data['memories'])} memories, {len(data['edges'])} edges")

    # Memory Router example (no LLM configured)
    router = MemoryRouter(store)

    # Add a hook: if response mentions a preference, save it
    def preference_hook(msg, resp):
        if "prefer" in resp.lower() or "use" in resp.lower():
            return f"[From conversation] {msg[:60]}"
        return None

    router.add_hook(preference_hook)
    reply = router.chat("How should I structure my Python project?")
    print(f"\nRouter reply: {reply}")
