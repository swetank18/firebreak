# Risks, kill criteria and known failure modes

Ranked by probability × damage. Each has an owner, a detection method and a decision.

## R1 — The simulator telegraphs its own parameters
**Probability: high. Damage: fatal.**

We configure `nominal_delay_s` and an implicit propagation probability, generate events, then "learn" them back. The kernel recovers the config file and the whole result is circular.

*Detection (Lane B, by hour 24):* correlate learned `1/β` against `nominal_delay_s`. **High correlation is the failure signal, not the success signal.**

*Mitigation:* the simulator must generate delays from *physics and buffers* — pump restart time, tank drawdown, generator fuel burn, crew travel over the current road state — not from a per-edge delay constant. `nominal_delay_s` stays in the contract as a prior for the decision layer's cold start and is never used by the generator.

*Kill criterion:* if r > 0.95 across edges and we cannot break the coupling, we report the kernel as validated only on synthetic recovery and drop the "learned from data" claim to "learned from simulation." Honest, weaker, survivable.

## R2 — The near-miss miner recovers nothing
**Probability: medium. Damage: fatal — this is the thesis.**

*Detection (Lane F, by hour 26):* chain-recovery precision/recall against ground-truth `Event.cause`. If it is at chance, near-misses are not observable and the premise fails.

*Mitigation:* the causal window `W` is the main lever, and it must be tuned on **train only**. Second lever: restrict attribution to declared dependency edges, which trades recall for precision — a defensible engineering choice as long as we report both.

*Kill criterion:* below 0.5 precision at any usable recall, pivot the claim from "we mine near-misses from raw logs" to "we learn kernels from *labelled* near-miss chains," which is weaker but still ahead of the literature. Decide by hour 28, not hour 44.

## R3 — Cascade sizes are not heavy-tailed
**Probability: medium. Damage: fatal.** The day-1 gate. See `02-CITY-SPEC.md`.

*Mitigation:* tune buffers and coupling until `ρ(G)` sits just under 1 — the critical regime is where heavy tails live and it is also the only regime where prediction is interesting. Being far from criticality in either direction makes the project pointless.

## R4 — The learned kernel does not beat centrality (H4)
**Probability: high. Damage: none if handled correctly.**

This is pre-registered as expected. It becomes damaging only if we hide it, tune until it disappears, or discover it at hour 44.

*Mitigation:* the timing and intervention-choice argument in `01-THESIS.md` is written in advance. Measure lead-time accuracy and intervention quality separately from ranking, because that is where the kernel should pay.

## R5 — Disk exhaustion
**Probability: high. Damage: high — it kills a build at hour 40.**

9.2 GB free at start. 4,200 scenario runs × full trajectories will not fit.

*Mitigation:* store rollout **summaries**, never trajectories. Parquet + zstd. `scripts/disk_check.sh` fails CI above 85 %. Budget: scenarios ≤ 2 GB, eval ≤ 1 GB, `node_modules` ≤ 600 MB. Lane A owns enforcement; check it at every phase gate, not at the end.

## R6 — Monte Carlo is too slow for a live demo
**Probability: medium. Damage: medium.**

2,000 rollouts × 2,000 nodes must return in under 2 s or beat 4 stalls on stage.

*Mitigation:* vectorised numpy over a flat edge array — **never a NetworkX traversal per rollout**. Precompute the demo scenario entirely and ship it in fixtures; the live path is a bonus, the frozen path is the demo. If it is slow, the demo does not care.

## R7 — I³ will not run on our hardware
**Probability: medium. Damage: low.**

*Mitigation:* arm A5 becomes "published numbers, not reproduced," in those words, on the slide. Never drop the comparison silently.

## R8 — The console does not survive the venue
**Probability: medium. Damage: high — it is the pitch.**

WebGL disabled, projector at an odd aspect ratio, no network for map tiles.

*Mitigation:* 2D fallback from day one reading the identical schema. Map tiles cached locally, never fetched live. Backup video committed. Test on an external display before the day.

## R9 — Scope creep into a fifth layer or a prettier map
**Probability: very high. Damage: high.**

*Mitigation:* the cut order in `EXECUTION.md` §7 is decided in advance precisely so it is not renegotiated at hour 40 by tired people. Telecom goes first. The map is already good enough at hour 24.

## R10 — Reuse suspicion
**Probability: low. Damage: medium.**

*Mitigation:* this is a new repo with a new thesis. InfraRisk and I³ are declared loudly on slide 7 as substrate and baseline. Nothing from PACT, SAMANVAY, DIVAS or Tolouse is copied — only methodology, which is not a deliverable. If asked directly what we reused: InfraRisk for physics, I³ as a baseline, and our own evaluation discipline from prior work. That is a complete and creditable answer.

---

## The four honest limitations, written by us first

Into `docs/LIMITATIONS.md` before the pitch. A judge who finds a limitation you already named is impressed; one who finds a limitation you hid is done with you.

1. Power and water asset topology is synthesised and geo-anchored, not real. Roads and hospitals are a real OSM extract.
2. Near-misses are mined from simulated history. A real utility historian feed is the ask, not a claim.
3. Intervention costs are abstract units, not procurement reality. Ratios are defensible; absolutes are not.
4. The cyber hazard is speculative and labelled as such.
