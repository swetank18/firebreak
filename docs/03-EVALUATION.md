# Evaluation — the part that wins

**Owner: Lane F.** This document is the reason the project is credible. Everything else is machinery that feeds it.

## Pre-registration

`docs/PREREGISTRATION.md` is written and committed **before any results exist**, containing the four hypotheses from `EXECUTION.md` §3 with predicted effect directions and rough magnitudes. Timestamped by the commit.

When results land, `eval/results/prereg_diff.md` shows what we predicted against what we measured. **Where we were wrong, that is the slide.** No hackathon team does this and it converts a judge from evaluating a demo to evaluating a study.

## The seven arms

One mechanism per arm. Nothing else changes: same city, same hazards, same seeds, same scenarios, same damage weights. This is the DIVAS rule and it is why the ablation will be believed.

| Arm | What it is | What it adds |
|---|---|---|
| **A0** | do nothing | the floor — how bad is it unmanaged |
| **A1** | rank alerts by `anomaly_score`, intervene on top-k | **what every other team builds** |
| **A2** | rank by static betweenness centrality on the dependency graph | topology, no learning |
| **A3** | rank by branching ratio from the learned kernel | **our inference** |
| **A4** | A3 + counterfactual intervention search | **our decision layer — full Firebreak** |
| **A5** | I³ (Tsinghua, arXiv 2503.02890) run unmodified | **published SOTA as baseline, not a strawman** |
| **A6** | oracle with perfect foresight | the ceiling — what fraction do we capture |

A0 and A6 bracket everything. A1 is the field. A5 is the literature. A4 is us. Report the fraction of oracle captured, not just raw wins.

**If Icube needs a GPU we do not have,** A5 becomes "published numbers, not reproduced," stated in exactly those words on the slide. Dropping the comparison silently is worse than admitting the constraint.

## Metrics

**Primary — the headline claim (H1).**
ROC-AUC for *"does an anomaly at this node, at this time, become a cascade of ≥ 6 hops?"* Computed per arm over the pooled test scenarios, with bootstrap CIs.

Prediction: A1 ≈ 0.5, A3 ≥ 0.80. If A1 lands at 0.7 the claim is softened, honestly, on the slide.

**Operational.**
- Damage avoided vs A0, as a `Damage` vector and as the weighted headline
- Cascades prevented (reached < 6 hops when A0 reached ≥ 6)
- Lead time: minutes between the first flagged alert and the first health-layer impact
- Alert precision @ k for k ∈ {1, 3, 5, 10} — an operator can act on three things, not thirty
- False-alarm rate at matched recall — **the cost of saying "evacuate" when nothing happens is real and must be reported**

**Diagnostic — these decide whether the thesis holds at all.**
- **Chain recovery**: precision/recall of mined chains against ground-truth `Event.cause`. *The single most important number in the project.* If the miner cannot recover true parentage, near-misses are not observable and the premise fails.
- Kernel recovery on `fixtures/kernel_synthetic.json` — recovered α within bootstrap CI of true α
- Calibration of `p_cascade`: reliability diagram + Brier score. A branching ratio nobody can trust is not a safety property.
- Learned `1/β` vs `nominal_delay_s` correlation — **high correlation is a failure**, it means we fit the config file
- Estimator comparison: counting vs MLE on the same corpus

**Sweeps.**
- Observability: what fraction of events are `observed` (1.0 → 0.3). Where does A4 degrade to A1? This is the honest deployment answer.
- Corpus size: chains from 100 → 10,000. **The learning curve is the near-miss argument made visible** — if performance is flat in corpus size, near-misses are not where the signal is.
- Action budget: 1 → 10 interventions.

## Splits and leakage

Temporal split on scenario start time. Train / val / test = 60 / 20 / 20. **Test touched exactly once**, at the end, by one person, recorded in `docs/DECISIONS.md`.

`service/tests/test_leakage.py` asserts (all tests live under `service/tests/`, which is where `pytest.ini` points; the spec named `inference/tests/`):

1. No chain in the train corpus contains an event with `t` after the val boundary.
2. No `Event.cause` field is reachable from `inference/` or `decision/` — AST grep, not a runtime check.
3. No `observed=False` event reaches either module.
4. Kernel fitted on train produces identical predictions when val is deleted from disk.
5. **Scenario-level, not event-level, splitting** — chains from the same scenario never straddle a boundary. This is the leak that looks like a great result.

Leaks 4 and 5 are the ones that will actually happen. Write them first.

**They were not written first, and 5 happened.** Every kernel was fitted on
scenarios concatenated into one flat list, which collided event ids across runs
and let the miner attribute a failure in one scenario to a failure in another —
2.31x more links than mining each scenario properly. See `docs/FINDINGS.md`.
The tests exist now, and they run against a corpus dense enough to leak: on the
35-node fixture city all five pass while proving nothing.

## Generated, never typed

`eval/results/` is produced entirely by `scripts/run_eval.sh`. Contains `results.md`, `realism.md`, `corpus.md`, `prereg_diff.md`, plus figures. **Nothing in it is ever hand-edited.**

Every number that appears on a slide carries a provenance comment naming the script and the git SHA that produced it. If a number cannot be traced to a script, it does not go on a slide.

## Statistics

Paired comparisons wherever arms share a seed — same scenario, different arm, so pair on `scenario_id`.

- Binary outcomes (cascade prevented / not): **exact McNemar** on paired outcomes
- Continuous (damage avoided): paired bootstrap, 10,000 resamples, report the CI not just the point estimate
- Proportions: **Wilson intervals**, never normal approximation
- Multiple arms: report unadjusted p-values *and* Holm-corrected, say which

Minimum 200 scenarios per arm, 3 seeds. That is 4,200 runs total; at 16 cores it is an overnight job — schedule it, do not discover it at hour 44.

## The results table that goes on the slide

```
arm  mechanism added          AUC    cascades   damage      lead    oracle
                                     prevented  avoided     time    captured
A0   —                        —      0/200      0           —       0%
A1   anomaly score            0.5?   ?          ?           ?       ?
A2   + centrality             ?      ?          ?           ?       ?
A3   + learned kernel         ?      ?          ?           ?       ?
A4   + counterfactual search  ?      ?          ?           ?       ?
A5   I³ (published SOTA)      ?      ?          ?           ?       ?
A6   oracle                   1.0    200/200    max         —       100%
```

Fill it with a script. If A3 does not beat A2 by much, **that is H4 and it goes on the slide as a finding**, with the timing and intervention-choice argument from `01-THESIS.md`. It is not a failure; it is the only slide in the room a judge will fully believe.
