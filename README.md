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
- **I³ / Icube** (Tsinghua FIB Lab, arXiv 2503.02890) — current SOTA for interdependent urban cascade prediction. Intended as baseline arm A5, not as a strawman. **We did not reproduce it on our hardware, so A5 is published numbers only** — stated in the arms table where the row would be, rather than the comparison being quietly dropped.
- **PI-GN-JODE** (arXiv 2603.20838) — physics-informed graph neural jump ODEs; source for the heavy-tailed cascade-size check. **That check failed here and we report it**: our tail is exponential, not power-law, and the literature's result is established for transmission grids rather than multi-sector lifeline networks.
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

Built and measured. Every number below is produced by a script in `eval/` and regenerated on demand; none is typed by hand.

| | Where |
|---|---|
| Five-layer Chennai twin, cascade engine, realism gate | `city/`, `eval/realism.py` |
| Near-miss miner, Hawkes kernel, branching ratio | `inference/`, `eval/recovery.py` |
| Counterfactual intervention search with deadlines | `decision/`, `eval/arms.py` |
| Seven-arm ablation, H1–H4, pre-registration diff | `eval/results/results.md`, `eval/results/prereg_diff.md` |
| The six-beat demo, offline | `www/index.html`, `scripts/export_demo.py` |
| The decision loop, runnable with no server or uplink | `python -m service.decide` |

**Two of four pre-registered predictions went against us and both are reported** — see `eval/results/prereg_diff.md`. So did the power-law realism check, which is kept and reported as failing rather than deleted. What we found by measuring rather than by reading is in `docs/FINDINGS.md`, and what does not work is in `docs/LIMITATIONS.md`, written by us before a judge writes it for us.

### Running it

```bash
pip install -r requirements.txt
pytest                          # invariants, leakage, determinism, and the six demo beats
python eval/realism.py          # the day-1 gate; nothing downstream means anything without it
python eval/h1.py               # which alarm becomes a catastrophe
python eval/h2.py               # mined kernel vs declared interdependency matrix
python eval/arms.py             # the seven-arm ablation
python eval/report.py           # assembles results.md and the pre-registration diff
python scripts/export_demo.py   # regenerates the demo scenario
python scripts/build_site.py    # rebuilds www/index.html from the results
bash scripts/run_eval.sh        # all of the above, in dependency order
```

If this machine has ROS on the Python path, its pytest plugins fail to import
(`launch_testing` needs `yaml`) and break collection before any of our tests
run. Nothing here uses them: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest`.

The decision path runs on its own, with no server and no network — which is the
whole of the edge-deployability claim, so it is a command rather than a slide:

```bash
python -m service.decide --hazard monsoon_flood --seed 90100
```

It prints one `Decision` as JSON: the alarms it considers dangerous and why, what
happens if nobody acts, the cheapest action that changes that, and **the minute
at which that option expires**. Every step between the alarm and the instruction
is a Hawkes kernel, a Monte Carlo rollout and an enumeration. No LLM produces any
part of it.
