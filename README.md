# FIREBREAK

**Catastrophes are too rare to learn from. Near-misses are the same process stopped early — so we learn the cascade from the failures that did not matter, to prevent the one that will.**

A decision system for interconnected city infrastructure. Given a stream of ordinary alarms, it answers the three questions no deployed system answers: which alarm becomes a catastrophe, what happens if we do nothing, and what is the cheapest action that stops it — with a deadline.

Code Merge Hackathon V2.0 · AI for Impact · Track: AI for Safety & Security → "The Chain Reaction"

---

## The criterion

> **An abnormality is dangerous exactly when its local branching ratio exceeds 1.**
>
> `n_i = Σ_j α_ij · s_j(t)`

Danger is not a property of an event. It is a property of its position in a network. A chiller running 3 °C hot is unremarkable in isolation and a catastrophe if it sits upstream of the room that runs the oxygen pumps.

`α_ij` — the expected number of failures at `j` caused by one failure at `i` — is estimated from **mined near-misses**, not from expert-declared interdependency matrices and not from synthetic scenario sweeps. That is the contribution.

## Where to start

| You are | Read |
|---|---|
| **any agent, first** | [`EXECUTION.md`](EXECUTION.md) then [`docs/00-SHARED-CONTRACTS.md`](docs/00-SHARED-CONTRACTS.md) |
| a coding agent | [`AGENTS.md`](AGENTS.md), then your lane in [`lanes/`](lanes/) |
| wondering if it's true | [`docs/01-THESIS.md`](docs/01-THESIS.md) — including how to kill it |
| building the city | [`docs/02-CITY-SPEC.md`](docs/02-CITY-SPEC.md) |
| proving it works | [`docs/03-EVALUATION.md`](docs/03-EVALUATION.md) |
| presenting it | [`docs/04-DEMO-RUNBOOK.md`](docs/04-DEMO-RUNBOOK.md) |
| shipping it | [`docs/05-DEPLOYMENT.md`](docs/05-DEPLOYMENT.md) |
| worried | [`docs/06-RISKS.md`](docs/06-RISKS.md) |

## Lanes

Six, running in parallel from hour 6 behind a frozen contract.

| Lane | Owns | The one thing |
|---|---|---|
| **A** City & Simulator | `city/`, `contracts/`, `scenarios/` | Delays must emerge from physics, not from a constant |
| **B** Inference | `inference/` | Learned `1/β` must **not** correlate with `nominal_delay_s` |
| **C** Decision | `decision/` | Imports nothing from `city/` — enforced by AST test |
| **D** Platform | `service/`, CI, deploy | The redaction boundary; CI drives the six beats |
| **E** Console | `console/` | The renderer computes nothing; 2D fallback from day one |
| **F** Evaluation | `eval/` | Pre-register before results; report H4 even when it loses |

## What we stand on

Declared loudly, never hidden.

- **InfraRisk** (`srijithbalakrishnan/dreaminsg-integrated-model`, BSD-3) — peer-reviewed water–power–transport interdependent failure simulation. Our substrate.
- **I³ / Icube** (Tsinghua FIB Lab, arXiv 2503.02890) — current SOTA for interdependent urban cascade prediction. **Our baseline arm A5, not our strawman.**
- **PI-GN-JODE** (arXiv 2603.20838) — physics-informed graph neural jump ODEs; source for the heavy-tailed cascade-size check.
- **Hawkes / ETAS** — the kernel, borrowed from seismology.
- **Aviation ASRS / NASA precursor work** — the licence for mining near-misses.

The gap all of them leave: **the literature predicts cascades; nobody picks the firebreak.**

## The demo

Six keypresses, offline, nothing typed.

1. Chennai, five layers
2. Two alarms, **identical scores**, one flagged red
3. Do nothing → cascade to four hospitals, 60,000 people
4. Rewind, apply Firebreak's action → dies at hop two
5. Rewind, apply the human-obvious action → **still cascades**
6. The seven-arm table and the pre-registration diff

Beat 5 must fail. CI asserts that it does.

## Status

Planning complete. No code yet. Open decisions in `EXECUTION.md` §12 — submission deadline, team size, and whether the Chennai topology is a real OSM extract or geo-anchored synthetic.
