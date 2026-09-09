# LANE C — Decision: counterfactual intervention search

**You own:** `decision/`
**You do not write:** anything else. You consume a `CityGraph`, a `Kernel` and `Criticality`, and you produce `Decision`.
**You are what the literature does not have.** I³ and PI-GN-JODE both predict cascades. Neither selects an intervention. That gap is this directory.

Read `docs/00-SHARED-CONTRACTS.md` §6.

## The invariant that defines this lane

**Nothing in `decision/` imports anything from `city/`.**

You consume a graph and a kernel, never a simulator. If a scorer needs to know it is looking at a water pump rather than a node with a dependency profile, the design is wrong and the domain-agnostic claim on slide 8 is a lie.

Two tests in `service/tests/test_invariants.py` enforce it: an AST grep on imports, and a second that catches the loophole — **no executable line in `decision/` may contain a layer name.** A string literal comparing against `"water"` passes an import check and still couples the engine.

This is the same invariant that made PACT's `core`/`rails` split defensible. It is worth the test.

## Build order

You are not blocked. Code against `fixtures/kernel_synthetic.json` from hour 6.

| Hours | Deliverable | Gate |
|---|---|---|
| 6–10 | action space, cost model, rollout interface against fixture kernel | Runs on `city_tiny` |
| 10–16 | vectorised Monte Carlo rollout | **2,000 rollouts × 2,000 nodes < 2 s** |
| 16–22 | counterfactual scoring, ranking by benefit per cost | `Decision` returned end to end |
| 22–26 | deadline solver | Every intervention carries an expiry |
| 26–30 | rationale templates, uncertainty widening on thin edges | Console-ready |
| 30+ | Support E and F. |

## The action space

Five kinds, in `contracts/costs.json`, versioned, on a slide.

| Kind | Effect | Realistic? |
|---|---|---|
| `isolate` | cut a node's outgoing dependency edges | yes — sectionalising is routine |
| `harden` | multiply a node's failure probability down | yes — sandbagging, temporary pumps |
| `reroute` | shift a dependency to an alternate parent | yes where redundancy exists |
| `preposition` | place a resource (fuel, crew, generator) to shorten a buffer refill | **yes — this is the demo action** |
| `shed` | controlled partial failure to prevent total failure | yes — load shedding is standard practice |

`preposition` is the one that wins beat 4, because it is the action a human would not pick and it is the one the diesel edge demands.

## Scoring

```
score(a) = (E[damage | ∅] − E[damage | a]) / cost(a)
```

`E[damage | ∅]` — the do-nothing counterfactual — is **mandatory on every Decision**. A recommendation without its counterfactual is a suggestion, and this project is about consequences.

Rank descending. Return the top 5, because an operator can act on three things and not on thirty.

## The deadline — the thing that makes it operational

```
deadline_s = max { τ : E[damage | a applied at t+τ] ≤ 1.1 × E[damage | a applied now] }
```

The latest moment at which ordering the action still yields ≥ 90 % of its current benefit. Found by binary search over τ with the rollout as the oracle — cheap, because rollouts are already vectorised.

A prediction without a deadline is a weather forecast. A prediction with one is an instruction. This field is why the console can show a countdown, and the countdown is why beat 4 feels urgent.

## Performance — this is your hard constraint

2,000 rollouts over 2,000 nodes in under 2 s, ×5 actions ×3 budget levels.

**Vectorised numpy over a flat edge array. Never a NetworkX traversal per rollout.** Represent the cascade as a sparse adjacency in CSR, sample all rollouts as one batched operation over the time axis. Use all 16 cores through the worker pool, but the single-threaded path must already be close.

If it is slow at hour 20, precompute the demo scenario entirely into fixtures and treat the live path as a bonus. The demo must never wait on a solver.

## Rationale — templated, never generated

```
"prevents propagation to health.hosp_004 in 71 % of rollouts;
 that path carries 40 % of expected damage;
 alternative action 'harden hospital' prevents 12 %"
```

Built by template from rollout statistics. **No LLM authors a field the decision depends on.** An LLM may narrate a completed `Decision` for the console; it may never produce one. A decision about which neighbourhood loses water has to be explainable line by line, and that is a deployment argument as much as an ethical one.

## Uncertainty

When `EdgeKernel.n_obs` is small, the CI on α is wide, and your rollouts must reflect that — sample α from its bootstrap distribution rather than using the point estimate. A confident recommendation built on three observations is the exact failure mode that gets a safety system switched off after its first bad call.
