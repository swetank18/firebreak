# LANE F — Evaluation: the seven arms and the evidence

**You own:** `eval/`, `docs/PREREGISTRATION.md`, `docs/FINDINGS.md`
**You do not write:** anything else.
**You are the pitch.** Slides 7 and 8 are your output. Everyone else builds the machine; you produce the reason to believe it.

Read `docs/03-EVALUATION.md` in full — it is your specification.

## Hour zero, before any result exists

Write `docs/PREREGISTRATION.md`. The four hypotheses, predicted directions, rough magnitudes. **Commit it.** The timestamp is the point.

Nobody at this hackathon will do this, and it converts a judge from evaluating a demo into evaluating a study. It costs an hour.

Include **H4, the one we expect to lose** — that the learned kernel will not beat static centrality on ranking by much. Predicting your own null result in advance and then reporting it is the most credible thing available to this project.

## Build order

| Hours | Deliverable | Gate |
|---|---|---|
| 6–8 | `PREREGISTRATION.md` committed | Timestamped before results |
| 8–14 | metrics module, damage weights, statistics (McNemar, Wilson, paired bootstrap) | Tested on synthetic |
| 14–20 | arms A0, A1, A2 — the ones needing no learned model | Baselines exist early |
| 20–26 | **chain-recovery diagnostic** against `Event.cause` | **The thesis check — report by hour 26** |
| 26–32 | arms A3, A4 wired; A6 oracle | Full ladder runs |
| 32–36 | A5 — I³ adapter, or "published numbers, not reproduced" | The SOTA comparison |
| 36–42 | 4,200-run job, `results.md` generated, sweeps and figures | The table is real |
| 42–46 | `prereg_diff.md`, test set touched **once** | Slides 7 and 8 |

## Your two most important numbers

**1. Chain recovery precision/recall** against ground-truth `Event.cause`, by hour 26.

If the miner cannot recover true parentage above chance, near-misses are not observable and the thesis fails. **Report this the moment you have it, whatever it says.** Hour 26 leaves time to pivot the claim to "learned from labelled chains"; hour 44 does not.

**2. The H1 AUC ladder.** A1 at chance, A3 well above. This is the headline claim and the sentence that beats every other team in the building — *"ranking alerts by how loud they are predicts catastrophe about as well as a coin."*

## The arms

Seven. One mechanism per arm, nothing else changes — same city, same hazards, same seeds, same weights. This is the DIVAS rule and it is why the ablation will be believed.

A0 floor · A1 the field · A2 topology · A3 our inference · A4 full Firebreak · **A5 published SOTA** · A6 oracle.

Report **fraction of oracle captured**, not just raw wins. "We capture 71 % of what perfect foresight achieves" is a far stronger sentence than "we beat the baseline."

## Statistics

Pair on `scenario_id` — same scenario, different arm. Exact McNemar for binary outcomes, paired bootstrap (10,000 resamples) for continuous, Wilson intervals for proportions. Report unadjusted and Holm-corrected p-values, and say which.

200 scenarios × 7 arms × 3 seeds = 4,200 runs. Overnight on 16 cores. **Schedule it at hour 36, do not discover it at hour 44.**

## Generated, never typed

`eval/results/` is produced entirely by `scripts/run_eval.sh`. Every number on every slide carries a provenance comment with the script and git SHA. **If a number cannot be traced to a script, it does not go on a slide.**

Lane D's invariant test compares `eval/results/` against a manifest hash and fails CI if anything was hand-edited.

## Findings

`docs/FINDINGS.md` is where surprises go, and surprises are the most valuable output this project has. When a result contradicts the plan, write it down. **Do not tune until it agrees.**

The two most likely findings, both worth a slide:

- H4 loses — centrality matches the kernel on ranking. Then measure and report where the kernel *does* pay: lead-time accuracy and intervention choice. That argument is pre-written in `01-THESIS.md`.
- The corpus learning curve is flat — performance at 100 chains equals 10,000. That would mean near-misses are not where the signal is, and it is the one finding that genuinely wounds the thesis. Report it anyway. A team that publishes the result that hurts them is the team the judges believe about everything else.
