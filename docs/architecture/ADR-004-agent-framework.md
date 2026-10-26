# ADR-004: AI Agent Framework Design

**Status:** Accepted
**Date:** October 2026
**Deciders:** Platform Engineering

---

## Context

The DataExtraction platform needs autonomous decision-making to:
1. Monitor Dead Letter Queue and trigger automatic replay
2. Chain downstream workflows after upstream completion (no manual triggering)
3. Throttle workers when infrastructure resources are strained
4. Alert on anomalies before they become outages

We need an agent framework that is: auditable, safe (human-approval gate for destructive actions), lightweight (no heavy framework dependency), and integrated with Temporal.

## Decision

**Custom lightweight agents using the `BaseAgent` abstract class. Agents act exclusively via the Temporal SDK — never by directly accessing databases or scrapers.**

### Agent Architecture

```
Agent Cycle (every N seconds):
  observe() → collect system state via Temporal activities or metrics API
  decide()  → analyze observations, produce AgentDecision
  act()     → execute decision via Temporal SDK (start/signal workflow) OR
              persist to human approval queue if requires_human_approval=True
```

### Critical Design Rules

| Rule | Rationale |
|:-----|:----------|
| Agents call Temporal SDK — never DB directly | All side effects are auditable as Temporal events |
| Agents never call scrapers directly | Scrapers are only invoked via Activities; agents only trigger Workflows |
| Every decision has a mandatory `rationale: str` | Full audit trail of every autonomous action |
| `requires_human_approval=True` for destructive actions | Safety gate — humans can veto in the frontend |
| Agent decisions are idempotent | Re-running observe→decide→act must produce the same outcome |

### Why Not LangChain / LangGraph / AutoGen

| Alternative | Issue |
|:------------|:------|
| LangChain Agents | Heavyweight dependency, abstracts away control flow we need to own, difficult to audit |
| LangGraph | Graph-based; agents here need simpler observe/decide/act loops |
| AutoGen | Multi-agent communication overhead; our agents are task-specific, not general |
| Temporal Workflows AS agents | Would make workflow code unpredictably long-running; agents should be external controllers |

Our agents are **narrow-purpose, single-cycle programs** (5-min cron). A custom base class is 40 lines and fully auditable — far preferable to pulling in a 200+ dependency LangChain install.

### Gemini Integration (Optional Enhancement)

For agents that need natural language reasoning (e.g., interpreting DLQ error patterns), `decide()` can optionally call `gemini-2.0-flash` via the `GEMINI_API_KEY` environment variable:

```python
async def decide(self, obs: dict) -> AgentDecision:
    if self.config.get("use_gemini") and os.getenv("GEMINI_API_KEY"):
        # Ask Gemini to analyze DLQ error patterns
        analysis = await call_gemini(prompt=f"Analyze these DLQ errors: {obs['errors']}")
        # Parse structured response into AgentDecision
    else:
        # Fall back to deterministic threshold logic
        return self._threshold_decide(obs)
```

Gemini is **opt-in** — all agents work fully without it using deterministic thresholds from `config/agents.yaml`.

## Consequences

- **Positive:** Full audit trail — every agent cycle, observation, decision, and action is logged
- **Positive:** Human approval gate prevents runaway automation
- **Positive:** No framework lock-in — agents are plain Python classes
- **Positive:** Temporal integration means agent actions appear in Temporal Web UI as workflow starts/signals
- **Negative:** Agents require their own process/deployment (a simple cron or long-running service)
- **Mitigation:** Add `worker-agents` container to docker-compose as a Phase 4 deliverable
