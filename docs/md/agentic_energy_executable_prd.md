# Product Request Document (PRD)
## Autonomous Agentic Energy Trading & Optimization System (Executable Version)

---

# 1. Overview

## Goal
- Minimize electricity cost
- Maximize solar ROI
- Maximize ESS profit

---

# 2. System Architecture

## Layers

1. Agent Layer (LangGraph)
2. Negotiation Layer (CDA)
3. Execution Layer (Dispatch / Market)
4. MCP Tool Layer
5. Data Layer

---

# 3. State Definition (핵심)

```json
{
  "price": [],
  "load": [],
  "generation": [],
  "ess_soc": 0.5,
  "constraints": {
    "export_limit": 0,
    "soc_min": 0.1,
    "soc_max": 0.9
  }
}
```

---

# 4. Action Space

- ESS charge/discharge
- PV curtailment
- Load shifting
- Market bid

---

# 5. Reward Function (핵심)

```text
Reward =
  w1 * CostSaving
+ w2 * SolarROI
+ w3 * ESSProfit
- w4 * DegradationCost
- w5 * RiskPenalty
```

---

# 6. Agent Design

## Base Agent Interface

```python
class BaseAgent:
    def perceive(self, state): pass
    def reason(self): pass
    def act(self): pass
    def reflect(self, result): pass
```

---

## Strategy Generator

```python
class StrategyGenerator(BaseAgent):
    def act(self):
        return generate_strategies(self.state)
```

---

## Optimizer

```python
class Optimizer(BaseAgent):
    def act(self, strategies):
        return optimize(strategies)
```

---

## Meta Critic

```python
class MetaCritic(BaseAgent):
    def act(self, candidates):
        return select_best(candidates)
```

---

# 7. Negotiation (CDA)

```python
def auction(strategies):
    bids = [s.bid for s in strategies]
    return max(bids)
```

---

# 8. LangGraph Flow

```python
def workflow(state):
    strategies = strategy_agent.act()
    optimized = optimizer.act(strategies)
    selected = critic.act(optimized)
    dispatch(selected)
    return selected
```

---

# 9. MCP Interface

## forecast
## optimize
## policy_check
## dispatch
## kpi

---

# 10. DB Schema (PostgreSQL)

## table: episodes

- id
- state
- action
- reward
- timestamp

---

## table: kpi

- timestamp
- cost_saving
- ess_profit
- roi

---

# 11. API

## POST /run

```json
{
  "goal": "optimize"
}
```

---

## GET /kpi

---

# 12. Execution Loop

```python
while True:
    state = get_state()
    action = workflow(state)
    apply(action)
    reward = evaluate()
    store(state, action, reward)
```

---

# 13. Conclusion

Executable Agentic AI Energy System
