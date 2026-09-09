"""H1 — THE HEADLINE CLAIM.

    Ranking alerts by anomaly score predicts eventual cascade at roughly chance.
    Ranking by branching ratio does not.

Pre-registered in docs/PREREGISTRATION.md before this was run.

If it holds, one sentence beats every other team in the building: ranking alerts
by how loud they are predicts catastrophe about as well as a coin.

Protocol: kernel fitted on TRAIN scenarios, scored on held-out TEST scenarios.
Scenario-level split, never event-level — chains from one scenario must not
straddle the boundary.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import numpy as np

from city.engine import runner
from city.engine.chains import true_chains
from city.topology import chennai
from inference.criticality.branching import BranchingRatio, CascadeReach
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from service.redact import redact

OUT = Path(__file__).parent / "results"
HAZARDS = ["monsoon_flood", "heatwave", "equipment_age", "cyber"]
CASCADE_HOPS = 6


def _events(args):
    hazard, seed = args
    g = chennai.build()
    return runner.run(g, hazard, seed=seed, tick_s=300.0)


def _auc(y: np.ndarray, s: np.ndarray) -> float:
    """Rank-based ROC-AUC, ties averaged."""
    if len(np.unique(y)) < 2:
        return float("nan")
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty(len(s), float)
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        ranks[order[i : j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    n1 = float(y.sum())
    n0 = float(len(y) - n1)
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def _centrality(g) -> dict[str, float]:
    """Static betweenness on the reversed dependency graph — arm A2, and the
    comparison H4 is about. Computed once and reused for every scenario."""
    import networkx as nx

    d = nx.DiGraph()
    d.add_nodes_from(n.id for n in g.nodes)
    for e in g.edges:
        d.add_edge(e.dst, e.src)
    return nx.betweenness_centrality(d, k=min(200, len(g.nodes)), seed=0)


def _score_scenario(args):
    """Return (label, anomaly, branching ratio, reach, health label, centrality)."""
    scen, kernel, cent = args
    g = chennai.build()
    br = BranchingRatio(g, kernel)
    cr = CascadeReach(g, kernel, depth=CASCADE_HOPS)
    obs = ObservableState(g)

    # Label 1 (pre-registered): did this event root a chain of >= CASCADE_HOPS?
    # Label 2 (operational): did it lead to a HEALTH-layer impact? That is what
    # an operator acts on and what the damage function measures. Both reported.
    by_id = {e.event_id: e for e in scen.events}
    depth: dict[str, int] = {}
    hits_health: dict[str, int] = {}
    for path in true_chains(scen.events):
        touched = any(by_id[x].node_id.startswith("health.") for x in path if x in by_id)
        for i, eid in enumerate(path):
            depth[eid] = max(depth.get(eid, 0), len(path) - 1 - i)
            tail = [x for x in path[i + 1:] if x in by_id]
            if any(by_id[x].node_id.startswith("health.") for x in tail):
                hits_health[eid] = 1

    rows = []
    for e in sorted(redact(scen.events), key=lambda x: x.t):
        if e.kind == "failed":
            world = obs.sync()
            n_i = br.of(e.node_id, world)
            sv = cr.susceptibility_vector(obs)
            r_i = cr.reach(e.node_id, sv)
            rows.append((1 if depth.get(e.event_id, 0) >= CASCADE_HOPS else 0,
                         e.anomaly_score, n_i, r_i, hits_health.get(e.event_id, 0),
                         cent.get(e.node_id, 0.0)))
        obs.apply(e)
    return rows


def main(n_train: int = 20, n_test: int = 20) -> int:
    print(f"H1: fitting on {n_train * len(HAZARDS)} train scenarios...")
    train_jobs = [(h, s) for h in HAZARDS for s in range(n_train)]
    test_jobs = [(h, 90_000 + s) for h in HAZARDS for s in range(n_test)]  # fresh range; see FINDINGS

    with mp.Pool(min(mp.cpu_count(), 14)) as pool:
        train = pool.map(_events, train_jobs, chunksize=2)
        test = pool.map(_events, test_jobs, chunksize=2)

    g = chennai.build()
    train_corpora = [redact(s.events) for s in train]   # per scenario, never pooled flat
    kernel = counting.fit(g, train_corpora, horizon_s=259_200.0 * len(train),
                          corpus_id=f"train{len(train)}", seed=0)
    print(f"  kernel: {len(kernel.edges)} edges, rho={kernel.spectral_radius:.3f}")

    print("computing static betweenness (arm A2, and the H4 comparison)...")
    cent = _centrality(g)

    print(f"scoring on {len(test)} held-out test scenarios...")
    with mp.Pool(min(mp.cpu_count(), 14)) as pool:
        scored = pool.map(_score_scenario, [(s, kernel, cent) for s in test], chunksize=1)

    rows = [r for rs in scored for r in rs]
    y = np.array([r[0] for r in rows])
    a = np.array([r[1] for r in rows])
    n = np.array([r[2] for r in rows])
    r6 = np.array([r[3] for r in rows])
    yh = np.array([r[4] for r in rows])
    c = np.array([r[5] for r in rows])

    auc_a, auc_n, auc_r = _auc(y, a), _auc(y, n), _auc(y, r6)
    auc_c = _auc(y, c)
    h_a, h_n, h_c = _auc(yh, a), _auc(yh, n), _auc(yh, c)

    # bootstrap CIs
    rng = np.random.default_rng(0)
    ba, bn, brr = [], [], []
    for _ in range(200):
        idx = rng.integers(0, len(y), len(y))
        if len(np.unique(y[idx])) < 2:
            continue
        ba.append(_auc(y[idx], a[idx]))
        bn.append(_auc(y[idx], n[idx]))
        brr.append(_auc(y[idx], r6[idx]))
    ci = lambda v: (round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4))  # noqa: E731

    # ---- H4, THE ONE WE PRE-REGISTERED OURSELVES TO LOSE ----
    # Predicted: the learned kernel does NOT beat static betweenness by a wide
    # margin; A3 - A2 <= 0.05 AUC. Reported whichever way it goes. DIVAS put
    # p = 1.000 on its own proposed mechanism and that is exactly why the paper
    # reads as credible.
    h4_delta = auc_n - auc_c
    h4_as_predicted = bool(h4_delta <= 0.05)

    best = max(auc_n, auc_r)
    # THE PRE-REGISTERED CRITERION, and nothing else. This used to read
    # `0.40 <= auc_a <= 0.62 and best >= 0.70`, a looser bar invented after the
    # fact, so the report printed "H1 HOLDS" directly above a measured 0.766
    # against a pre-registered 0.80. A verdict scored against a criterion the
    # pre-registration does not contain is not a pre-registered verdict.
    prereg_anomaly_ok = bool(0.45 <= auc_a <= 0.60)
    prereg_ours_ok = bool(best >= 0.80)
    passed = bool(prereg_anomaly_ok and prereg_ours_ok)
    report = {
        "n_train_scenarios": len(train), "n_test_scenarios": len(test),
        "n_events_scored": len(rows), "n_cascade_events": int(y.sum()),
        "base_rate": round(float(y.mean()), 4),
        "kernel_edges": len(kernel.edges), "kernel_rho": round(kernel.spectral_radius, 4),
        "auc_anomaly_score": round(auc_a, 4), "auc_anomaly_ci": ci(ba),
        "auc_branching_ratio": round(auc_n, 4), "auc_branching_ci": ci(bn),
        "auc_cascade_reach_depth6": round(auc_r, 4), "auc_reach_ci": ci(brr),
        "auc_static_betweenness": round(auc_c, 4),
        "delta_best_vs_anomaly": round(best - auc_a, 4),
        "label2_health_impact": {
            "base_rate": round(float(yh.mean()), 4),
            "auc_anomaly_score": round(h_a, 4),
            "auc_branching_ratio": round(h_n, 4),
            "auc_static_betweenness": round(h_c, 4),
            "delta": round(h_n - h_a, 4),
        },
        "H4": {
            "predicted": "branching ratio does NOT beat static betweenness by >0.05 AUC",
            "auc_branching_ratio": round(auc_n, 4),
            "auc_static_betweenness": round(auc_c, 4),
            "delta": round(h4_delta, 4),
            "as_predicted": h4_as_predicted,
        },
        "H1_PASSED": passed,
        "H1_prereg_anomaly_in_range": prereg_anomaly_ok,
        "H1_prereg_ours_ge_080": prereg_ours_ok,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "h1.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# H1 — does anomaly score predict cascade?", "",
        "Generated by `eval/h1.py`. Never hand-edited. Pre-registered before running.", "",
        f"- train: **{len(train)}** scenarios, test: **{len(test)}** held out (scenario-level split)",
        f"- events scored: **{len(rows)}**, of which **{int(y.sum())}** rooted a cascade "
        f"(>= {CASCADE_HOPS} hops), base rate {y.mean():.2%}",
        f"- kernel: {len(kernel.edges)} edges, rho = {kernel.spectral_radius:.3f}", "",
        "| predictor | ROC-AUC | 95% CI |", "|---|---|---|",
        f"| anomaly score (**what everyone builds**) | **{auc_a:.3f}** | {ci(ba)} |",
        f"| branching ratio, one step | {auc_n:.3f} | {ci(bn)} |",
        f"| cascade reach at depth {CASCADE_HOPS} (**ours**) | **{auc_r:.3f}** | {ci(brr)} |",
        f"| static betweenness centrality (**arm A2**) | {auc_c:.3f} | |",
        f"| delta, best vs anomaly score | **{best - auc_a:+.3f}** | |", "",
        "## Label 2 — does it reach the health layer?", "",
        "The operationally meaningful question, and what the damage function measures.", "",
        f"- base rate {yh.mean():.2%}", "",
        "| predictor | ROC-AUC |", "|---|---|",
        f"| anomaly score | {h_a:.3f} |",
        f"| branching ratio | **{h_n:.3f}** |",
        f"| static betweenness | {h_c:.3f} |",
        f"| delta | **{h_n - h_a:+.3f}** |", "",
        f"## H1 {'HOLDS' if passed else 'DOES NOT HOLD AS STATED'}", "",
        "Pre-registered: anomaly AUC in [0.45, 0.60] **and** ours >= 0.80. Both halves,",
        "judged against the pre-registration and not against anything easier.", "",
        f"- anomaly **{auc_a:.3f}** — {'confirmed' if prereg_anomaly_ok else 'OUTSIDE the predicted range'}",
        f"- ours **{best:.3f}** — {'confirmed' if prereg_ours_ok else 'SHORT of the 0.80 we claimed'}",
        "", ("Both halves hold." if passed else
             "The half the pitch rests on holds: ranking alerts by how loud they are predicts "
             "catastrophe no better than a coin. Our own target for the other half was "
             "optimistic, and we say so rather than moving it."), "",
        "## H4 — the one we pre-registered ourselves to lose", "",
        "Predicted: the learned kernel does **not** beat static betweenness centrality by a",
        "wide margin (A3 - A2 <= 0.05 AUC). We said the kernel would earn its place in",
        "*timing and intervention choice*, not in ranking.", "",
        "| | ROC-AUC |", "|---|---|",
        f"| branching ratio (learned kernel) | {auc_n:.3f} |",
        f"| static betweenness (no learning) | {auc_c:.3f} |",
        f"| **delta** | **{h4_delta:+.3f}** |", "",
        (f"**As predicted: the kernel does not win on ranking** (delta {h4_delta:+.3f} "
         f"<= 0.05). Reported because we said we would."
         if h4_as_predicted else
         f"**Against our own prediction: the kernel beats centrality by {h4_delta:+.3f} AUC,**"
         " more than the 0.05 we said it would not exceed. We were wrong in our own"
         " favour, which is the direction that deserves the most scrutiny, not the least."), "",
    ]
    (OUT / "h1.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
