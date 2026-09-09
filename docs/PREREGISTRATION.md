# Pre-registration

**Written and committed BEFORE any results exist. The commit timestamp is the point.**
**Owner: Lane F, hour 6–8. Do not edit after the first result lands — the diff goes in `eval/results/prereg_diff.md`.**

Filled in by Lane F. Template below; predictions must be numeric and falsifiable.

## H1 — Anomaly score does not predict cascade; branching ratio does
- **Predicted:** arm A1 ROC-AUC ∈ [0.45, 0.60]. Arm A3 ROC-AUC ≥ 0.80.
- **Measured:** _(after)_

## H2 — Near-miss-learned kernel beats a declared interdependency matrix
- **Predicted:** lower cascade-volume RMSE, ≥ 15 % relative improvement.
- **Measured:** _(after)_

## H3 — Counterfactual search beats centrality-targeted intervention at equal budget
- **Predicted:** strictly more damage prevented at every budget level 1–10.
- **Measured:** _(after)_

## H4 — THE ONE WE EXPECT TO LOSE
- **Predicted:** the learned kernel will **not** beat static betweenness centrality on ranking by a wide margin. We expect A3 − A2 ≤ 0.05 AUC. We predict the kernel's value shows up in **lead-time accuracy and intervention choice**, not in ranking.
- **Measured:** _(after)_
- **If we are right that we lose:** it goes on the slide, with the timing argument from `docs/01-THESIS.md` §"Why this is not just centrality".

---

**Signed:** Lane F · date: ____ · git SHA at registration: ____
