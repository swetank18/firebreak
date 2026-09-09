# FIREBREAK — Execution Plan

**Code Merge Hackathon V2.0 · AI for Impact · Track: AI for Safety & Security → "The Chain Reaction"**
**Winners are overall, not track-wise. Everything in this document is optimised for that.**

Every agent reads this file and `docs/00-SHARED-CONTRACTS.md` completely before writing a line.
**Contract freeze at hour 6.** After that, contracts change only by unanimous agreement, recorded in the contracts file with a date.

---

## 1. The one sentence

> **Catastrophes are too rare to learn from. Near-misses are the same process stopped early — so we learn the cascade from the failures that did not matter, to prevent the one that will.**

And its corollary, which is the answer to the organisers' own core-challenge line:

> **An abnormality is dangerous exactly when its local branching ratio exceeds 1.**
> Danger is not a property of an event. It is a property of its position in a network.

If a slide, a function or a commit does not serve one of those two sentences, it is out of scope.

---

## 2. What we are building

A decision system for interconnected city infrastructure that, given a live stream of ordinary alarms, answers three questions no deployed system answers today:

1. **Which of these alarms becomes a catastrophe?** — branching ratio, learned from mined near-misses.
2. **What happens if we do nothing?** — Monte Carlo forward simulation over a five-layer city.
3. **What is the single cheapest action that stops it, and when does that option expire?** — counterfactual intervention search with a deadline.

Five planes.

**City plane.** A five-layer Chennai simulation — power, water, transport, telecom, health — with real topology, physics-backed flow, and a discrete-event cascade clock. Built on InfraRisk (BSD-3), not from scratch.

**Inference plane.** Near-miss miner, multivariate Hawkes kernel estimation, live branching-ratio computation. This is the contribution.

**Decision plane.** Counterfactual intervention search over a typed action space, ranked by damage prevented per unit cost, each with an expiry time.

**Evidence plane.** Seven-arm ablation, pre-registered predictions, published SOTA as a baseline arm, honest negative results.

**Console plane.** A live city map, a timeline you can rewind, and six keypresses that are the entire pitch.

---

## 3. The scientific claim, stated so it can be killed

Pre-registered in `docs/PREREGISTRATION.md` **before any results are generated**. Committed. Timestamped. Then we run it and show the diff.

> **H1 (headline).** Ranking alerts by anomaly score predicts eventual cascade at approximately chance (ROC-AUC ∈ [0.45, 0.60]). Ranking by branching ratio does not (ROC-AUC ≥ 0.80).
>
> **H2.** Learning the propagation kernel from near-misses beats a declared/expert-elicited interdependency matrix on cascade-volume RMSE.
>
> **H3.** Counterfactual intervention search prevents strictly more damage than intervening on the highest-centrality node, at equal action budget.
>
> **H4 (the one we expect to lose).** The learned Hawkes kernel beats static betweenness centrality by a wide margin. **We predict it does not** — we expect centrality to capture most of the ranking signal, with the kernel's value showing up in *timing* and *intervention choice* rather than in ranking.

**H4 exists on purpose.** If it fails, we report it on a slide and we are the only team in the building that did. DIVAS reported `p = 1.000` on its own proposed mechanism and that is precisely why the paper reads as credible. Do not quietly drop H4 if it goes against us.

---

## 4. Prior art — what we stand on, and what we are adding

Named loudly on slide 7, never hidden. "We built on a peer-reviewed simulator and benchmarked against published SOTA" reads as research literacy. Teams that hide dependencies look like they are hiding something.

| Work | What it gives us | What it does **not** do |
|---|---|---|
| **InfraRisk** (`srijithbalakrishnan/dreaminsg-integrated-model`, BSD-3) | Peer-reviewed water–power–transport interdependent failure simulation. Wraps `wntr`, `pandapower`, static traffic assignment. Testbeds: Micropolis, Shelby County. | No learning. No intervention selection. Interdependencies are declared. |
| **I³ / Icube** (Tsinghua FIB Lab, arXiv 2503.02890) | Current SOTA for interdependent urban CF prediction. Dual GAE + heterogeneous graph. **We run it unmodified as baseline arm A5.** | Trains on synthetic scenario sweeps. Predicts failure probability. Selects no intervention. |
| **PI-GN-JODE** (arXiv 2603.20838, Mar 2026) | Physics-informed graph neural jump ODEs, temporal cascade progression. Confirms cascade sizes are heavy-tailed power law — cite this for our day-1 realism check. | Power grid only. IEEE 24/118-bus. Prediction only. |
| **Aviation ASRS / NASA precursor work** | The intellectual licence for near-miss mining: accidents do not happen without precursors, and precursors are abundant. | Not networked, not cascade-aware. |
| **Hawkes / ETAS (seismology)** | The kernel. Self-exciting point processes estimating productivity from abundant small events. | Never applied to interdependent infrastructure with intervention search. |

**The gap, in one line:** the literature predicts cascades; nobody picks the firebreak.

---

## 5. Repository layout and strict ownership

Single repo, `main` only. Strict file ownership — you do not edit another lane's directory, you open an issue in `docs/BLOCKERS.md`. Commit every 90 minutes.

```
firebreak/
├── contracts/         OWNER: A   pydantic + TS types, JSON schemas, scenario format
├── city/              OWNER: A   topology build, 5 layers, InfraRisk adapter
│   ├── layers/                   power, water, transport, telecom, health
│   ├── topology/                 Chennai extract, OSM ingest, geo anchors
│   └── engine/                   discrete-event cascade clock, scenario runner
├── scenarios/         OWNER: A   seeded scenario JSON. Append only. Never hand-edited.
├── inference/         OWNER: B   near-miss miner, Hawkes fitter, branching ratio
│   ├── mining/                   chain extraction from event history
│   ├── kernel/                   alpha/beta estimation, counting + MLE
│   └── criticality/              live branching ratio, susceptibility state
├── decision/          OWNER: C   action space, counterfactual rollout, deadline solver
├── platform/          OWNER: D   FastAPI, WebSocket, persistence, CI, deploy
├── console/           OWNER: E   MapLibre + deck.gl city view, timeline, demo keys
├── eval/              OWNER: F   seven arms, metrics, results.md. NEVER hand-edited.
│   └── baselines/                I³ adapter, centrality, oracle
├── fixtures/          SHARED, append only
├── docs/              SHARED
└── scripts/
```

**The rule that makes this work: nothing in `decision/` imports anything from `city/`.**

The decision layer consumes a *graph and a kernel*, never a simulator. If an intervention scorer needs to know it is looking at a water pump rather than a node with a dependency profile, the design is wrong and the whole "domain-agnostic engine" claim on slide 8 is a lie. Enforce it with an AST-grep test in `platform/tests/test_invariants.py`, and a second test that catches the loophole: no executable line in `decision/` may name a layer — a string literal comparing against `"water"` passes an import check and still couples the engine.

This is the same invariant that made PACT's core/rails split defensible. It is worth a test.

---

## 6. Non-negotiables

Each of these is paid for in blood on a previous project. Violating one costs more than it saves.

1. **Day-1 realism gate.** Before anything is built on the simulator, verify the cascade size distribution is heavy-tailed (power-law, α ∈ [1.3, 2.5] on the tail). If every cascade is tiny or everything collapses, the generator is broken and *everything above it is invalid*. This is the coincidence-factor lesson from SAMANVAY, and it is the highest-likelihood silent failure in this project. **Gate: no lane past hour 8 until this passes.**
2. **Leakage test before training.** Write the temporal-split leakage unit test *before* the first fit. Near-miss chains that straddle the split boundary are the obvious leak; there are two others in `docs/03-EVALUATION.md`.
3. **Test set touched exactly once.** Walk-forward validation for everything else.
4. **Every number on every slide is produced by a script.** `eval/results/results.md` is generated. If a number is typed by a human it is wrong by construction.
5. **No LLM in the decision path.** Kernel estimation is statistics, rollout is Monte Carlo, intervention search is enumeration plus scoring. A decision about which neighbourhood loses water has to be explainable line by line. An LLM may narrate the output; it may never produce it.
6. **The renderer computes nothing.** The console replays precomputed scenario JSON. A 2D node-grid fallback reading the identical schema exists from day one. This is what saved SAMANVAY's demo and it will save this one.
7. **Each ablation arm adds exactly one mechanism.** Seven arms, one delta each. This is the DIVAS rule and it is why the ablation will be believed.
8. **Report the negative result.** H4 especially.
9. **The demo runs off keypresses 1–6. Nothing is typed on stage.**
10. **Edge-deployable decision path.** A city control room cannot depend on an internet uplink to decide whether to shed load. Cloud for storage, training and reporting; the decision loop runs local. Say this out loud on the architecture slide.

---

## 7. Phase plan

Hours, not dates — compresses to a 36-hour sprint or stretches to two weeks. Gates are hard: do not start the next phase until the gate passes.

| Phase | Hours | Deliverable | Gate |
|---|---|---|---|
| **P0 Contracts** | 0–6 | `contracts/` frozen, fixtures published, all lanes can code against types | Every lane has a green typecheck against fixtures |
| **P1 City** | 6–16 | 5-layer Chennai loads, one scenario runs end to end, scenario JSON emitted | **Power-law realism gate passes** |
| **P2 Mining** | 12–22 | Near-miss corpus extracted, ≥5,000 chains, labelled | Corpus stats published in `eval/results/corpus.md` |
| **P3 Kernel** | 20–30 | α/β estimated per edge, branching ratio computable live | Leakage test green; H1 measurable |
| **P4 Decision** | 26–36 | Action space, counterfactual rollout, deadline solver | Interventions returned in <2s for 2,000 rollouts |
| **P5 Console** | 16–40 | City map, cascade animation, rewind timeline, 6 keys | Demo runs offline from JSON, 2D fallback works |
| **P6 Evidence** | 30–44 | 7 arms run, `results.md` generated, pre-reg diff written | Every slide number traced to a script |
| **P7 Harden** | 40–48 | Docker, CI drives the beats, deploy, backup video recorded | CI green on a clean clone |

**If you run out of time, cut in this order:** telecom layer → MLE Hawkes (keep the counting estimator) → I³ baseline arm → 3D map (keep 2D) → deployment. **Never cut:** the realism gate, the near-miss miner, the intervention search, the rewind demo, or the pre-registration.

---

## 8. Lane assignments

Six lanes. Read your own file in `lanes/` after this one.

| Lane | Owner | Directory | Blocks | Blocked by |
|---|---|---|---|---|
| **A — City & Simulator** | | `contracts/`, `city/`, `scenarios/` | everyone | nothing |
| **B — Inference** | | `inference/` | C, F | A (event stream) |
| **C — Decision** | | `decision/` | E, F | B (kernel) — but codes against fixture kernel from hour 6 |
| **D — Platform** | | `platform/` | E | contracts only |
| **E — Console** | | `console/` | nothing | contracts only — codes against fixture scenarios |
| **F — Evaluation** | | `eval/` | the pitch | A, B, C |

**D and E start at hour 6 on fixtures and are never blocked again.** That is the entire point of the contract freeze. If a lane is idle waiting for another lane, the contracts were wrong.

---

## 9. Machine constraints — read this before you `pip install`

Measured on the build machine, 2026-09-09:

- **Disk: 9.2 GB free of 192 GB (95 % full).** This is the binding constraint. Monte Carlo output and `node_modules` will eat it. Store rollout *summaries*, never full trajectories. Parquet + zstd for everything in `scenarios/` and `eval/`. Budget: city+scenarios ≤ 2 GB, eval ≤ 1 GB, node_modules ≤ 600 MB. Lane A owns a `scripts/disk_check.sh` that fails CI above 85 %.
- CPU: 16 cores. RAM: 14 GB total, ~8 GB available. Monte Carlo is embarrassingly parallel — use all 16, but cap worker memory.
- Python 3.12.3, Node v20.20.2, git. **No Docker, no uv installed** — Lane D installs Docker or we ship with compose-less run scripts and say so.

---

## 10. What "industry grade" means here, concretely

Not a wish. A checklist Lane D owns and CI enforces.

- Typed contracts, generated to both Python (pydantic) and TypeScript from one JSON Schema source
- Structured logging with a correlation ID per scenario run and per decision
- Deterministic and replayable: same seed, same scenario JSON, byte-identical
- Health checks, graceful shutdown, bounded queues, backpressure on the WebSocket
- Migrations, not `CREATE TABLE IF NOT EXISTS`
- CI that **builds the image, starts it, and drives the six demo beats against it over HTTP** — asserting what each beat is meant to prove, not that it returned 200. Beat 5 has to *fail to prevent the cascade* or the contrast it exists to draw is not there.
- A backup demo video recorded against the built image, committed
- An honest `LIMITATIONS.md`. Written by us, before a judge writes it for us.

---

## 11. The pitch skeleton, mapped to the organisers' template

| Slide | Content |
|---|---|
| 1 Title | FIREBREAK · "Danger is not a property of an event. It is a property of its position in a network." |
| 2 Problem | Chennai 2015. Four systems, one cascade, and the killer node was a road — because it carried the diesel. Every monitor worked perfectly. None could name the alarm that mattered. |
| 3 Solution | Learn the cascade from near-misses. Rank by branching ratio. Choose the intervention by simulating futures. |
| 4 Features | Near-miss miner · branching-ratio danger criterion · counterfactual intervention with a deadline · five-layer city twin |
| 5 Architecture | Five planes; decision path runs at the edge, no uplink |
| 6 Prototype | Live console + repo + video. **The six keypresses.** |
| 7 Innovation | The gap table from §4. Hawkes from near-misses. I³ as our baseline, not our strawman. |
| 8 Impact | Person-hours of service loss avoided; H4 negative result; limitations we found ourselves |
| 9 Team | — |

---

## 12. Open decisions — resolve before hour 6

1. **Submission deadline and team size.** Everything above is phase-gated; these two numbers set the cut line in §7.
2. **Chennai topology fidelity.** Real OSM extract with anonymised utility placement, or a Micropolis-style synthetic city geo-anchored to Chennai? Real is more compelling and slower. Lane A decides at hour 4 and records it in `docs/02-CITY-SPEC.md`.
3. **Does I³ run on our hardware?** If Icube needs a GPU we do not have, arm A5 becomes "published numbers, not reproduced" and we say so explicitly rather than dropping the comparison.
