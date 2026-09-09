# FIREBREAK — Shared Contracts

**Every lane reads this file completely before writing code. Contract freeze at hour 6.**
**After the freeze, a change requires agreement from every affected lane and a dated entry in §10.**

These types are the only thing lanes are allowed to assume about each other. If you need a field that is not here, you need a contract change, not a local workaround.

Source of truth: `contracts/schema/*.json` (JSON Schema). Python types are generated to `contracts/python/`, TypeScript to `contracts/ts/`. **Do not hand-write either side.** `scripts/gen_contracts.sh` regenerates both; CI fails on drift.

---

## 1. The city graph

Five layers. Every node belongs to exactly one layer. Every edge is either *intra*-layer (flow) or *inter*-layer (dependency).

```python
Layer = Literal["power", "water", "transport", "telecom", "health"]

class Node(BaseModel):
    id: str                      # "power.ss_042" — layer prefix is mandatory
    layer: Layer
    kind: str                    # "substation" | "pump" | "road_segment" | "tower" | "hospital" | ...
    lat: float
    lon: float
    capacity: float | None       # layer-native units; None for pure topology nodes
    population_served: int       # 0 if it serves no one directly. Drives the damage function.
    criticality_weight: float    # 1.0 default; hospitals and water treatment > 1. See §5.
    attrs: dict[str, float]      # layer-specific. Never read this from decision/.

class Edge(BaseModel):
    id: str
    src: str                     # Node.id
    dst: str                     # Node.id
    relation: Literal["flow", "depends_on"]
    # flow  : physical conveyance inside a layer (a line, a main, a road)
    # depends_on : src requires dst to function. Cross-layer edges are always depends_on.
    nominal_delay_s: float       # engineering estimate. A PRIOR for the kernel, never the kernel.
    attrs: dict[str, float]

class CityGraph(BaseModel):
    city_id: str                 # "chennai_v1"
    built_at: datetime
    source_hash: str             # hash of the topology inputs. Changes => new city_id.
    nodes: list[Node]
    edges: list[Edge]
```

**`nominal_delay_s` is a prior, not a measurement.** Lane B must never fit a kernel that simply reproduces it — if the learned delay equals the nominal delay on every edge, the miner is broken or the simulator is trivially telegraphing its own parameters. That check belongs in Lane B's test suite.

---

## 2. Events and the event stream

The single unit of everything downstream.

```python
class Event(BaseModel):
    event_id: str
    node_id: str
    t: float                     # seconds since scenario epoch. Float, not datetime.
    kind: Literal["anomaly", "degraded", "failed", "restored"]
    severity: float              # 0..1, layer-normalised
    anomaly_score: float         # 0..1 from the commodity detector. THE BASELINE SIGNAL.
    observed: bool               # False => ground truth only, invisible to the system
    cause: str | None            # ground truth parent event_id. NEVER visible to inference.
```

Two fields are ground-truth-only and **must be stripped by the platform before any inference or decision code sees an Event**: `cause`, and `observed=False` rows. Lane D owns `service/redact.py` and a test that asserts an un-redacted Event cannot reach `inference/` or `decision/`. This is the leakage boundary; it is worth more than any model.

`anomaly_score` is deliberately the whole of arm A1. It comes from a commodity per-stream detector. Making it *good* is not a contribution and no lane should spend time there.

---

## 3. Chains, near-misses and cascades

A **chain** is a maximal sequence of causally-plausible events. A **near-miss** is a short chain. A **cascade** is a long one. They differ only by length — that is the thesis, encoded as a type.

```python
class Chain(BaseModel):
    chain_id: str
    scenario_id: str
    events: list[str]            # ordered Event.ids
    hops: int                    # len(events) - 1
    layers_crossed: int
    span_s: float                # t_last - t_first
    terminated: bool             # no further propagation within W of the last event
    damage: Damage               # realised, see §5

CATASTROPHE_HOPS = 6            # >= this is a cascade. Below is a near-miss.
                                # Locked at hour 6. Changing it changes every result.

class NearMissCorpus(BaseModel):
    corpus_id: str
    city_id: str
    window_s: float              # W, the causal attribution window
    chains: list[Chain]
    split: Literal["train", "val", "test"]
```

**Chain extraction is Lane B's, and it never reads `Event.cause`.** A chain is built from `(dependency edge exists) AND (0 < Δt ≤ W)` and nothing else. `cause` exists only so Lane F can score how well the miner recovered true parentage — that is a reported metric, not an input.

---

## 4. The kernel

Multivariate Hawkes with an exponential kernel, one pair of parameters per directed dependency edge.

```
λ_j(t) = μ_j + Σ_i Σ_{t_k ∈ H_i, t_k < t}  α_ij · β_ij · exp(−β_ij (t − t_k))
```

- `α_ij` — **branching ratio contribution**: expected number of failures at `j` caused by one failure at `i`. Dimensionless.
- `β_ij` — decay rate, `1/β` is the mean propagation delay in seconds.
- `μ_j` — background intensity at `j` (spontaneous failure).

```python
class EdgeKernel(BaseModel):
    edge_id: str
    alpha: float                 # >= 0
    beta: float                  # > 0
    n_obs: int                   # near-miss chains supporting this estimate
    ci_low: float                # bootstrap CI on alpha
    ci_high: float
    estimator: Literal["counting", "mle"]

class Kernel(BaseModel):
    kernel_id: str
    city_id: str
    corpus_id: str
    fitted_at: datetime
    edges: dict[str, EdgeKernel]
    mu: dict[str, float]         # node_id -> background intensity
    spectral_radius: float       # ρ(G) where G_ij = alpha_ij. ρ >= 1 => globally supercritical.
```

**Two estimators, in this order.** `counting` ships first and always works: for each dependency edge, count how often an event at `j` follows an event at `i` within `W`, divide by events at `i`, subtract the base rate. Interpretable, fast, robust. `mle` is the stretch upgrade. Lane F reports both; if MLE does not beat counting, say so.

`n_obs` and the CI are not decoration. An α estimated from 3 chains and one from 900 must be visibly different downstream, and the decision layer is required to widen its uncertainty on thin edges.

---

## 5. Criticality — the danger criterion

```python
class Criticality(BaseModel):
    node_id: str
    t: float
    branching_ratio: float       # n_i = Σ_j α_ij · s_j(t)   <- THE HEADLINE NUMBER
    p_cascade: float             # P(chain from here reaches CATASTROPHE_HOPS)
    expected_reach: float        # E[nodes failed]
    expected_damage: Damage
    time_to_critical_s: float | None   # None if it never goes critical in the horizon
    ci_low: float                # on branching_ratio
    ci_high: float
    n_rollouts: int
```

`s_j(t)` is the **susceptibility** of node `j` at time `t` — a state multiplier in `[0, 2]` reflecting existing stress (already degraded, at capacity, no backup). Lane B owns its definition; it must be a pure function of observable state and it must be written down in `inference/criticality/README.md` with its justification.

**`branching_ratio > 1` is the danger threshold.** That is the entire answer to "distinguish normal abnormality from dangerous abnormality" and it goes on a slide as one number.

### Damage

Never collapse to rupees. A synthetic money figure is the fastest way to lose a judge who works in infrastructure.

```python
class Damage(BaseModel):
    person_hours_no_power: float
    person_hours_no_water: float
    hospital_critical_hours: float    # facility-hours where a health node lost power OR water
    people_affected: int
    def headline(self) -> float:      # the single scalar for ranking, weights in contracts/weights.json
        ...
```

Weights live in `contracts/weights.json`, are versioned, and appear on a slide. A judge is allowed to disagree with our weights; they are not allowed to discover we hid them.

---

## 6. Interventions and decisions

```python
ActionKind = Literal["isolate", "harden", "reroute", "preposition", "shed"]

class Action(BaseModel):
    kind: ActionKind
    target: str                  # Node.id or Edge.id
    magnitude: float             # kind-specific, normalised 0..1
    cost: float                  # abstract units, from contracts/costs.json
    lead_time_s: float           # how long until it takes effect once ordered

class Intervention(BaseModel):
    action: Action
    damage_prevented: Damage
    damage_prevented_headline: float
    benefit_per_cost: float
    p_success: float
    deadline_s: float            # latest t at which ordering it still yields >= 90% of current benefit
    rationale: list[str]         # ordered, human-readable, generated from the rollout — NOT an LLM
    n_rollouts: int

class Decision(BaseModel):
    decision_id: str
    scenario_id: str
    t: float
    trigger: list[Criticality]   # what made us decide now
    do_nothing_damage: Damage    # the counterfactual baseline. Always present.
    ranked: list[Intervention]   # descending benefit_per_cost
    compute_ms: float
    seed: int
```

`do_nothing_damage` is mandatory on every Decision. A recommendation without its counterfactual is a suggestion, and this project is about consequences.

`rationale` is generated by template from the rollout statistics — "prevents propagation to health.hosp_004 in 71 % of rollouts; that path carries 40 % of expected damage". **It is never LLM-generated.** An LLM may narrate a Decision for the console; it may never author a field the decision depends on.

---

## 7. Scenarios — the replay format

Everything the console renders, and everything the evaluation scores, is a scenario file. Deterministic, seeded, replayable, byte-identical across runs.

```python
class Scenario(BaseModel):
    scenario_id: str
    city_id: str
    seed: int
    hazard: Literal["monsoon_flood", "heatwave", "equipment_age", "cyber", "none"]
    horizon_s: float
    tick_s: float                # 60.0
    events: list[Event]          # ground truth, full
    decisions: list[Decision]    # empty for arm A0
    arm: str                     # "A0".."A6"
    metadata: dict[str, str]     # git sha, contracts version, wall clock, host
```

Written as Parquet + zstd to `scenarios/`, one directory per `city_id`. **Append only. Never hand-edited.**

**The renderer computes nothing.** `console/` reads `Scenario` and draws it. If the console needs a number, it is a field on the contract, not a calculation in TypeScript. This rule is why the demo survives a laptop with no network.

---

## 8. Wire formats

REST, `/v1`, JSON. WebSocket at `/v1/stream/{scenario_id}` pushes frames during live replay.

| Method | Path | Returns |
|---|---|---|
| `GET` | `/v1/city/{city_id}` | `CityGraph` |
| `GET` | `/v1/scenarios` | `list[ScenarioSummary]` |
| `GET` | `/v1/scenarios/{id}` | `Scenario` |
| `POST` | `/v1/scenarios` | run a new scenario; `{hazard, seed, arm}` → `ScenarioSummary` |
| `GET` | `/v1/criticality/{scenario_id}?t=` | `list[Criticality]` |
| `POST` | `/v1/decide` | `{scenario_id, t}` → `Decision` |
| `POST` | `/v1/counterfactual` | `{scenario_id, t, action}` → replayed `Scenario` — **this is the rewind** |
| `GET` | `/v1/kernel/{kernel_id}` | `Kernel` |
| `GET` | `/v1/eval/results` | generated `results.md` as JSON |

WebSocket frame:

```typescript
type Frame =
  | { type: "tick";        t: number; events: Event[] }
  | { type: "criticality"; t: number; items: Criticality[] }
  | { type: "decision";    decision: Decision }
  | { type: "done";        scenario_id: string }
```

Bounded queue, backpressure, and a `seq` on every frame so the console can detect a gap. Lane D owns this.

---

## 9. Fixtures

`fixtures/` is **append only** and exists so Lanes C, D, E and F are never blocked.

Published by Lane A no later than hour 6:

- `fixtures/city_tiny.json` — 40 nodes, 5 layers, hand-checkable, used in every unit test
- `fixtures/city_chennai_v1.json` — the real one
- `fixtures/kernel_synthetic.json` — a kernel with known α, so Lane B can prove the fitter recovers it
- `fixtures/scenario_demo.parquet` — the exact scenario the demo uses, frozen
- `fixtures/corpus_small.parquet` — 500 chains for fast tests

**`kernel_synthetic.json` is how Lane B proves the estimator works at all.** Generate events from a known Hawkes kernel, fit, and assert recovery within CI. If the fitter cannot recover its own synthetic ground truth, nothing downstream means anything. This test is written before the real fitter.

---

## 10. Change log

Contract changes after the hour-6 freeze go here, dated, with the lanes that agreed.

| Date | Change | Lanes | Reason |
|---|---|---|---|
| — | initial freeze | all | — |
| 2026-09-09 | `Node.buffer_s` added | A, B, C | Buffers create lead time. Without them every dependency propagates instantly, there is no deadline to compute, and the project has no reason to exist. It must be first-class rather than a layer-specific `attrs` entry, because `decision/` reasons about it and may not read layer-specific attributes. |
| 2026-09-09 | canonical `sib:{src}->{dst}` key for flow-sibling relations | A, B, C | Sibling relations have no `Edge`, so `Edge.id` did not cover them and two lanes derived the identity differently. The estimator wrote `src~dst`, the consumer read `src->flow_parent`, and 80% of the propagation mass silently vanished from the branching ratio — H1 scored exactly 0.500 with no error raised. One helper in `inference/relations.py`, used by both sides. |
| 2026-09-09 | `Node.protected_class` added | A, C | So `decision/` can weigh a critical facility **without naming a layer**. `EXECUTION.md` §5 forbids any executable line in `decision/` from naming a layer, because a string comparison against `"water"` couples the engine exactly as an import does; `rollout.py` had `n.layer == "health"` and the AST test that should have caught it had never been written. Chennai sets the flag for the health layer; another city could mark shelters or schools. |
| 2026-09-09 | `Event.event_id` is unique across scenarios, not within one | A, B, F | Ids restarted at `e000001` every run, so a pooled training corpus collided 8,263 of 12,877 ids and the kernel fitter's one-parent-per-child map silently overwrote links between scenarios. Ids now carry the scenario id. |
