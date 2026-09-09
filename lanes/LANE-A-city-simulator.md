# LANE A — City & Simulator

**You own:** `contracts/`, `city/`, `scenarios/`, `fixtures/`, `scripts/disk_check.sh`
**You do not write:** `inference/`, `decision/`, `console/`, `eval/`
**You block everyone.** Contracts at hour 6 and fixtures at hour 6 are the two things that decide whether five other lanes work in parallel or queue behind you.

Read `docs/00-SHARED-CONTRACTS.md` and `docs/02-CITY-SPEC.md`.

## Hour zero, before any code

Clone and **run** InfraRisk (`srijithbalakrishnan/dreaminsg-integrated-model`, BSD-3). Get the Shelby County testbed producing an interdependent failure. Write what you find into `city/INFRARISK_NOTES.md` with the date: the actual API, what its interdependency model can and cannot express, whether the water-power coupling is configurable, and how long one scenario takes.

**Do not code from this document and do not code from memory.** Every detail here is a starting point to verify. Discovering at hour 20 that InfraRisk cannot express a buffered cross-layer dependency costs the submission.

If InfraRisk cannot express the buffers we need — and it may not, its interdependencies are declared — write the cascade engine yourself and use `wntr` and `pandapower` directly for layer physics. Decide by **hour 4** and record it in `docs/DECISIONS.md`. This is the single biggest architectural fork in the project.

## Build order

| Hours | Deliverable | Gate |
|---|---|---|
| 0–2 | InfraRisk running, `INFRARISK_NOTES.md`, build/write fork decided | You know what you are standing on |
| 2–6 | `contracts/` complete, generators working, `fixtures/city_tiny.json` | **Contract freeze. Five lanes unblocked.** |
| 6–10 | Chennai topology, 5 layers, ~2,000 nodes, cross-layer edges | Graph loads and validates |
| 10–14 | Cascade engine: hazard → physics → dependency → buffers → restoration | One monsoon scenario runs end to end |
| 14–16 | 1,000 seeded runs, power-law fit | **REALISM GATE. Nothing proceeds until green.** |
| 16–20 | `fixtures/scenario_demo.parquet` frozen, `kernel_synthetic.json` | Lane E has the demo; Lane B has ground truth |
| 20–26 | Scenario runner at scale, Parquet+zstd, 4,200-run job scheduled | Lane F can run the ablation overnight |
| 26+ | Support B, C, F. Do not add a sixth layer. |

## The two things that matter most

**1. Buffers.** Without them every dependency propagates instantly, there is no lead time to predict, no deadline to compute, and no reason for this project to exist. Hospital generator fuel, water tank drawdown, telecom battery, crew travel time. Sizes in `city/layers/*/buffers.json`, versioned, on a slide.

**2. Delays must emerge from physics, not from a constant.** This is risk R1 and it is the most likely way the project silently becomes circular. `nominal_delay_s` in the contract is a *prior for the decision layer's cold start* — the generator must never read it. A pump's restart delay comes from its restart procedure; a generator's failure delay comes from fuel burn rate against tank level against resupply travel time over the *current flooded* road network.

If Lane B reports that learned `1/β` correlates above 0.95 with `nominal_delay_s`, that is your bug, not theirs.

## The diesel edge

Build `hospital.generator → transport.road_segment` first, before anything else works. It is the demo, it is the thesis in one edge, and it is the only edge where the "protect the most critical asset" instinct provably fails. Everything else in the city exists to make that edge legible.

## Realism gate — you own it

1,000 seeded scenarios, extract every cascade, complementary CDF of cascade size, MLE power-law fit with Clauset-style `x_min` selection, KS distance. Pass: α ∈ [1.3, 2.5], KS does not reject. Output: `eval/results/realism.md`, generated.

Watch for the bimodal failure — cascades that are either 2 hops or 40 with nothing between. That means the model has a threshold rather than a process, and it will silently invalidate every AUC number Lane F produces.

## Disk

You own `scripts/disk_check.sh`. 9.2 GB free at start. Scenario summaries, never full trajectories. Parquet + zstd. Fail CI above 85 %. Check at every phase gate.
