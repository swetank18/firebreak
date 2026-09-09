# LANE B — Inference: near-miss mining, kernel, branching ratio

**You own:** `inference/`
**You do not write:** anything else. You consume `Event` streams and produce `Kernel` and `Criticality`.
**You are the contribution.** Everything else in this repo is machinery that makes your three numbers legible.

Read `docs/00-SHARED-CONTRACTS.md` §3–5 and `docs/01-THESIS.md`.

## Hour zero, before any code

Write two tests. They do not need the real fitter to exist.

1. **`test_leakage.py`** — the five assertions in `docs/03-EVALUATION.md`. Written before the first fit, not after.
2. **`test_kernel_recovery.py`** — generate events from a known synthetic Hawkes kernel, fit, assert recovered α is within bootstrap CI of true α.

**If the fitter cannot recover its own synthetic ground truth, nothing downstream means anything.** This test is the foundation of the entire project and it costs two hours.

## Build order

| Hours | Deliverable | Gate |
|---|---|---|
| 6–8 | leakage + synthetic-recovery tests written and failing | Foundation laid |
| 8–14 | chain extractor, near-miss corpus from Lane A's scenarios | ≥ 5,000 chains, stats in `corpus.md` |
| 14–18 | **counting estimator** for α, β, μ | Recovers synthetic kernel |
| 18–22 | branching ratio, susceptibility `s_j(t)`, `Criticality` live | Lane C unblocked; H1 measurable |
| 22–28 | bootstrap CIs, calibration, `p_cascade` via Monte Carlo | Reliability diagram exists |
| 28–34 | **MLE estimator** (stretch) | Compared against counting; report both |
| 34+ | Support F. Do not tune on test. |

## Chain extraction

A chain is built from `(a declared dependency edge exists) AND (0 < Δt ≤ W)`. **Nothing else.** You never read `Event.cause` — the platform strips it before you see it, and there is an AST test that enforces this. `cause` exists only so Lane F can score how well you recovered true parentage.

`W`, the causal attribution window, is your main tuning lever. **Tune it on train only** and record the value in `docs/DECISIONS.md`.

`CATASTROPHE_HOPS = 6` separates near-miss from cascade. Locked at hour 6. Changing it changes every result in the project.

## The estimators

**Counting first. It ships and it always works.** For each dependency edge `i → j`: count events at `j` within `W` of an event at `i`, divide by events at `i`, subtract the base rate from `μ_j`. Interpretable, fast, robust, and it will be most of your result.

```
α_ij ≈ (N(j within W of i) − μ_j · W · N(i)) / N(i)
1/β_ij ≈ mean(Δt) over attributed pairs
```

**MLE second, if time allows.** Multivariate Hawkes with exponential kernel has an O(n) recursive log-likelihood; EM is more stable than direct gradient descent. If MLE does not beat counting on held-out cascade-volume RMSE, **say so**. A negative result on your own upgrade is worth more than a quiet swap.

Report `n_obs` and a bootstrap CI on every edge. An α from 3 chains and one from 900 must be visibly different downstream, and Lane C is required to widen its uncertainty on thin edges.

## Susceptibility

`s_j(t) ∈ [0, 2]` — how stressed `j` already is. Must be a **pure function of observable state**: buffer level, load against capacity, whether backup is engaged, whether a redundant path is already down.

Write its definition and justification into `inference/criticality/README.md`. It is the reason branching ratio is time-dependent and centrality is not — which is the whole argument for why the kernel earns its place. If `s_j(t)` is arbitrary, H4 is lost on principle before it is lost on data.

## The number

```
n_i = Σ_j α_ij · s_j(t)
```

`n_i > 1` is the danger threshold. It goes on a slide as one number and it is the answer to the organisers' core-challenge line.

## Your two self-checks

1. **Learned `1/β` must NOT correlate with `nominal_delay_s`.** Above 0.95 across edges means we fit the simulator's config file, not a physical process. That is risk R1 and it is fatal. Report the correlation to Lane A by hour 24 whatever it says.
2. **The learning curve in corpus size must be non-flat.** If performance at 100 chains equals performance at 10,000, near-misses are not where the signal is and the thesis is wrong. This is the near-miss argument made visible; Lane F plots it.

## What you do not do

You do not build a better anomaly detector. `anomaly_score` is commodity, it is deliberately the whole of arm A1, and improving it makes our own baseline stronger for no gain. Leave it alone.
