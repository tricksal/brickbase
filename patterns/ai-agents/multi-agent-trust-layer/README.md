# Pattern: multi-agent-trust-layer

> Trust-scoring and secure delegation between AI agents.

## What It Does

Provides a governance layer that sits between AI agents in a multi-agent system.
Each agent has a **verified identity** tied to an accountable human sponsor and a
**numeric trust score** (0–1000) that rises or falls based on observed behaviour.
Authority is passed from parent to child agents via **time-bounded Delegations**
whose permission scope can only **narrow**, never expand, down the chain.
Every authorization decision is written to an **immutable audit log**.

---

## Core Concepts

| Concept | Description |
|---|---|
| `AgentIdentity` | Verified ID bound to a human sponsor (email) and organization |
| `TrustScore` | Numeric score 0–1000 + full mutation history |
| `TrustLevel` | Qualitative band: SUSPENDED / RESTRICTED / PROBATION / STANDARD / TRUSTED |
| `DelegationScope` | Set of allowed/denied actions + resource limits |
| `Delegation` | Time-bounded authority grant, signed by parent |
| `TrustScoringEngine` | Adjusts scores on events (task success, violations, …) |
| `DelegationManager` | Creates, validates, and revokes delegation chains |
| `MultiAgentPolicyEngine` | Role-based + delegation-based access control |
| `TrustLayer` | Unified facade + audit log |
| `GovernedAgent` | Thin agent wrapper that routes actions through TrustLayer |

---

## Trust Score Bands

| Score | Level | Behaviour |
|---|---|---|
| 900–1000 | TRUSTED | Full autonomy |
| 700–899 | STANDARD | Normal operations |
| 500–699 | PROBATION | Limited autonomy |
| 300–499 | RESTRICTED | Requires human approval |
| 0–299 | SUSPENDED | Cannot act |

Default score changes per event (configurable in `TrustScoringEngine.SCORE_ADJUSTMENTS`):

| Event | Delta |
|---|---|
| task_completed | +10 |
| stayed_in_scope | +5 |
| delegation_success | +15 |
| inaccurate_output | −30 |
| scope_violation_attempt | −50 |
| security_violation | −100 |

---

## Quick Start

```python
from core import TrustLayer, GovernedAgent

# 1. Initialize
tl = TrustLayer()

# 2. Define role policies
tl.policy_engine.add_role_policy("researcher", {
    "base_trust_required": 500,
    "allowed_actions": ["web_search", "summarize", "analyze"],
    "denied_actions": ["send_email", "delete_file"],
})
tl.policy_engine.add_role_policy("orchestrator", {
    "base_trust_required": 800,
    "allowed_actions": [],        # empty = all not explicitly denied
    "denied_actions": ["delete_system_files"],
})

# 3. Register agents
tl.register_agent("orch-1", "alice@org.com", "Acme", ["orchestrator"], initial_trust=900)
tl.register_agent("res-1",  "bob@org.com",   "Acme", ["researcher"],   initial_trust=750)

# 4. Delegate a task
del_id = tl.create_delegation(
    from_agent="orch-1",
    to_agent="res-1",
    scope={
        "allowed_actions": ["web_search", "summarize"],
        "allowed_domains": ["arxiv.org", "github.com"],
        "max_tokens": 20_000,
    },
    task_description="Find recent AI safety papers",
    time_limit_minutes=30,
)

# 5. Execute through a governed agent
agent = GovernedAgent("res-1", tl)
agent.current_delegation = del_id

result = agent.execute("web_search", {"query": "AI safety 2024"})
print(result)  # {"success": True, "result": ..., "trust_score": ...}

# 6. Check audit log
for entry in tl.get_audit_log():
    print(entry)
```

---

## Scope Narrowing (Delegation Chains)

When an agent sub-delegates, the child's effective scope is the **intersection**
of the parent scope and the requested child scope:

```
Orchestrator (all actions allowed)
  └─ Delegation A → Researcher (web_search, summarize)
       └─ Delegation B → SubAgent (summarize only)   ← narrowed
```

Sub-delegations require `max_sub_delegations > 0` in the parent scope.

---

## Files

| File | Purpose |
|---|---|
| `core.py` | All pattern logic – framework-agnostic, no external deps |

---

## Dependencies

Standard library only (`hashlib`, `secrets`, `dataclasses`, `enum`, …).
No LLM framework required – integrates with any agent runtime.

---

## Extending

- **Real crypto:** Replace `DelegationManager._sign()` with Ed25519 / HMAC-SHA256.
- **Persistence:** Swap in-memory dicts for a database (Postgres, Redis, …).
- **Custom events:** Add entries to `TrustScoringEngine.SCORE_ADJUSTMENTS`.
- **LLM integration:** Subclass `GovernedAgent._execute_action()` and call your LLM/tool there.
- **Human-in-the-loop:** Hook into RESTRICTED level to trigger an approval workflow.

---

## Source

Extracted from [Shubhamsaboo/awesome-llm-apps](https://github.com/Shubhamsaboo/awesome-llm-apps)  
Path: `advanced_ai_agents/multi_agent_apps/multi_agent_trust_layer/`
