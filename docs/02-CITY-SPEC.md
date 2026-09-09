# The city — five-layer Chennai twin

**Owner: Lane A.** Everything here is a target, not a wish; the numbers are chosen so the whole thing runs on 16 cores and 8 GB.

## Why Chennai

December 2015. Rain floods substations, so power goes down. Water pumping loses power, so treatment stops. Hospitals lose water and grid power together and fall back to diesel. The roads are flooded, so diesel resupply cannot reach them. Telecom towers on backup die next, so people cannot call for help and ambulances cannot route.

Four systems, one cascade, and the node that killed it was **a road** — because it carried the diesel. No monitoring system in that city was broken that night. Every one of them reported its own alarm correctly. Not one could say *"this alarm is the one that ends with hospitals dark in six hours."*

We are pitching at SRM, in Chennai. Some of the judges evacuated. This is not a hypothetical for that room.

## Scale targets

| Layer | Nodes | Engine | Notes |
|---|---|---|---|
| power | ~120 | `pandapower` | substations, feeders, generators. DC power flow is sufficient. |
| water | ~80 | `wntr` | treatment, pumping stations, reservoirs, trunk mains |
| transport | ~1,500 segments | static traffic assignment | only ~200 are logistics-critical; the rest are context |
| telecom | ~200 | topology only | towers, backhaul, backup-power state |
| health | ~40 | topology only | hospitals, PHCs, blood banks, oxygen plants |
| **cross-layer** | ~600 `depends_on` edges | — | this is where the project lives |

~2,000 nodes, ~5,000 edges. Large enough to be a city, small enough that 2,000 Monte Carlo rollouts finish in under two seconds.

## Topology sourcing — decide at hour 4, record the choice

**Option 1, real extract (preferred).** OSM extract for Chennai gives roads, hospitals and built-up areas directly. Power and water topology are not public at asset level — synthesise them plausibly, anchored to real geography (substations at real substation locations where OSM has them, service areas by Voronoi over population raster), and **label the synthesis honestly in the console and on the slide**.

**Option 2, Micropolis/Shelby geo-anchored.** InfraRisk ships validated testbeds. Re-project one onto Chennai coordinates. Faster, less compelling, fully defensible.

Whichever is chosen, `docs/DECISIONS.md` records it with the reason, and `LIMITATIONS.md` says exactly which layers are real and which are synthesised. **Never let a judge discover that themselves.**

## Interdependency edges — the ones that matter

These are the edges the whole project is about. Each is a `depends_on` with a `nominal_delay_s` prior.

| From | To | Delay prior | Why |
|---|---|---|---|
| water pump | power feeder | 0 s | instant; no pumping without power |
| water treatment | power feeder | 0 s | |
| hospital | power feeder | 0 s (then generator) | generator gives a *buffer*, not immunity |
| hospital generator | **road segment** (diesel route) | 4–12 h | **the Chennai node.** Buffer depletes, resupply must arrive. |
| hospital | water main | 2–6 h | tank buffer |
| telecom tower | power feeder | 2–8 h | battery backup |
| ambulance routing | road segment | 0 s | |
| pump | telecom (SCADA) | 0 s | remote control lost ⇒ manual operation ⇒ slower restoration |
| road segment | flood depth (hazard) | — | hazard-driven, not a node dependency |

**The diesel edge is the demo.** It is a long-delay, cross-layer, non-obvious dependency where the "protect the hospital" instinct fails and the correct action is to protect a road or pre-position fuel. Build it first and make sure the simulator reproduces it.

## The cascade engine

Discrete-event, 60 s ticks, 72 h horizon.

1. **Hazard** drives exogenous stress (flood depth per cell, temperature, load).
2. **Physics** resolves flow per layer: `pandapower` for power, `wntr` for hydraulics, traffic assignment for roads. A node that cannot meet demand goes `degraded`, then `failed`.
3. **Dependency** propagation: a `failed` node makes its dependents draw down their buffer; when a buffer empties, the dependent degrades.
4. **Restoration**: crews with travel time over the *current* road network — which is why a flooded road makes everything worse twice.
5. **Emit** `Event` rows with ground-truth `cause`.

**Buffers are what make this interesting.** Without them every dependency propagates instantly and there is no lead time to predict, no deadline to compute, and no reason for the project to exist. Buffer sizes go in `city/layers/*/buffers.json`, versioned, on a slide.

## Hazards

| Hazard | Drives | Realistic? |
|---|---|---|
| `monsoon_flood` | flood depth raster over time, road impassability, substation inundation | **primary.** Anchored to 2015 rainfall. |
| `heatwave` | load spike, transformer derating, water demand spike | yes |
| `equipment_age` | rising background failure intensity `μ` | yes — this is how the near-miss corpus is generated at scale |
| `cyber` | SCADA/telecom loss without physical damage | speculative; label it so |
| `none` | background only | needed for the base-rate corpus |

## The day-1 realism gate — nothing proceeds until this passes

Run 1,000 seeded scenarios. Extract every cascade. Plot the complementary CDF of cascade size.

**Pass:** the tail is heavy — power-law with α ∈ [1.3, 2.5], fitted by maximum likelihood with a Clauset-style `x_min` selection, and a Kolmogorov–Smirnov distance that does not reject.

**Why this is the gate:** historical blackout data consistently shows cascade sizes follow a heavy-tailed power law — large events occur far more often than a normal distribution would predict. This is stated in the PI-GN-JODE introduction and it is the single cheapest external check on whether our simulator behaves like real infrastructure.

**Fail modes and what they mean:**
- All cascades tiny ⇒ buffers too large or `α` too small. Nothing to predict.
- Everything collapses ⇒ `ρ(G) ≥ 1` globally. Every scenario is a catastrophe and there is no discrimination to measure.
- Bimodal, nothing between ⇒ the model has a threshold, not a process. This is the subtle one and it will silently invalidate the AUC result.

---

### What actually happened — this section is superseded, and kept

**The power-law criterion above failed, and it is still run and still reported as
failing** in `eval/results/realism.md`. A Vuong likelihood-ratio test favours an
exponential tail decisively at every `x_min`. The literature's power-law result
(Dobson/Carreras, restated in PI-GN-JODE) is established for *transmission-grid
blackouts*; this is a multi-sector urban lifeline network, where it is not.
Asserting it here would have been an unexamined transfer between domains. See
`docs/FINDINGS.md`.

**The gate now tests what the project actually needs of the simulator:** cascade
sizes spanning orders of magnitude, a tail far heavier than thin-tailed, neither
all-tiny nor all-collapse, not bimodal — and one check that was missing entirely
and cost an entire ablation:

**Scenario contingency.** Every fail mode listed above is about the *cascade size
distribution*. None of them asks what fraction of the CITY ends up down in a
given scenario, and those are different questions. The size distribution passed
cleanly the whole time 92% of assets were failing in every run, with a
seed-to-seed spread of 0.90–0.94 — so no five-node intervention could move any
outcome and the seven-arm ablation was measuring nothing at all. **Prediction
only matters where the outcome is contingent**, and the gate now checks that for
every hazard.

Owner: Lane A. Output: `eval/results/realism.md`, generated. **No lane proceeds past hour 8 until this is green**, because every number produced before it is provisional.
