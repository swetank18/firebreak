"""H2 — does LEARNING the kernel from near-misses beat DECLARING it?

    Pre-registered: the near-miss-learned kernel beats a declared /
    expert-elicited interdependency matrix on cascade-volume RMSE, by >= 15%
    relative.

This is the contribution claim. Every system in the prior art declares its
interdependencies: InfraRisk's matrix is written down by hand, and I3 trains on
synthetic scenario sweeps. If a declared matrix predicts cascade volume just as
well as one mined from near-misses, the mining is decoration.

The declared baseline is built the way an engineer actually would, and
deliberately not built to lose:
  * every declared `depends_on` edge gets the same alpha, because that is what
    "A depends on B" means when nobody has measured how strongly
  * the delay comes from `Edge.nominal_delay_s`, the engineering prior already
    in the contract
  * its uniform alpha is CALIBRATED ON THE TRAINING SET to the value that
    minimises training RMSE, so it is not losing merely for want of a scale factor

Both kernels are then given the same observed prefix of the same held-out
scenario and asked the same question: how many more assets fail after this
moment?
"""

from __future__ import annotations

import json
import multiprocessing as mp
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from city.engine import runner
from city.topology import chennai
from contracts.kernel import EdgeKernel, Kernel
from decision.rollout import CascadeRollout
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from inference.relations import propagation_targets
from service.redact import redact

OUT = Path(__file__).parent / "results"
HAZARDS = ["monsoon_flood", "heatwave", "cyber"]
TICK = 300.0
OBSERVE_FRAC = 0.25          # predict from the first quarter of the scenario
N_ROLLOUTS = 400


def _events(args):
    hazard, seed = args
    g = chennai.build()
    return runner.run(g, hazard, seed=seed, tick_s=TICK)


def declared_kernel(g, alpha: float) -> Kernel:
    """The expert-elicited matrix: uniform strength on every declared edge.

    Flow-sibling relations get NOTHING, because a declared interdependency
    matrix does not contain them — load redistribution between peers is not an
    interdependency anybody writes down. That is not a handicap invented for
    this comparison; it is the actual content of the baseline, and it is most of
    why the mined kernel wins. Reported as such.
    """
    edges = {}
    for e in g.edges:
        if e.relation != "depends_on":
            continue
        delay = e.nominal_delay_s if e.nominal_delay_s > 0 else 900.0
        edges[e.id] = EdgeKernel(
            edge_id=e.id, alpha=alpha, beta=1.0 / delay, n_obs=0,
            ci_low=alpha, ci_high=alpha, estimator="counting",
        )
    return Kernel(
        kernel_id=f"declared-a{alpha:.3f}", city_id=g.city_id, corpus_id="declared",
        fitted_at=datetime.now(timezone.utc), edges=edges,
        mu={n.id: 0.0 for n in g.nodes}, spectral_radius=0.0,
    )


def _predict(args) -> tuple[float, float, float]:
    """(actual volume, learned prediction, declared prediction) for one scenario."""
    scen, learned, declared = args
    g = chennai.build()
    t_obs = scen.horizon_s * OBSERVE_FRAC

    seen = [e for e in sorted(redact(scen.events), key=lambda x: x.t) if e.t <= t_obs]
    obs = ObservableState(g)
    for e in seen:
        obs.apply(e)
    s_vec = np.array([obs.susceptibility(n.id) for n in g.nodes])

    before = {e.node_id for e in scen.events if e.kind == "failed" and e.t <= t_obs}
    after = {e.node_id for e in scen.events if e.kind == "failed" and e.t > t_obs}
    actual = float(len(after - before))

    seeds = list(dict.fromkeys(
        [e.node_id for e in seen if e.kind == "failed"][-40:]))
    if not seeds:
        return actual, 0.0, 0.0

    already = np.array([n.id in before for n in g.nodes])
    preds = []
    for k in (learned, declared):
        roll = CascadeRollout(g, k)
        r = roll.run(seeds, s_vec, n_rollouts=N_ROLLOUTS, seed=0, already_failed=already)
        preds.append(max(0.0, r.expected_reach - len(before)))
    return actual, preds[0], preds[1]


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((a - b) ** 2)))


def main(n_train: int = 8, n_test: int = 10) -> int:
    g = chennai.build()
    print(f"H2: generating {n_train * len(HAZARDS)} train scenarios...")
    train_jobs = [(h, s) for h in HAZARDS for s in range(n_train)]
    test_jobs = [(h, 95_000 + s) for h in HAZARDS for s in range(n_test)]  # fresh seed range
    with mp.Pool(min(mp.cpu_count(), 12)) as pool:
        train = pool.map(_events, train_jobs, chunksize=1)
        test = pool.map(_events, test_jobs, chunksize=1)

    learned = counting.fit(g, [e for s in train for e in redact(s.events)],
                           horizon_s=259_200.0 * len(train), corpus_id="h2train", seed=0)
    print(f"  learned kernel: {len(learned.edges)} edges, rho={learned.spectral_radius:.3f}")

    # Calibrate the declared matrix's one free parameter ON TRAINING DATA.
    print("calibrating the declared matrix on train (so it does not lose on scale)...")
    grid = [0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0]
    best_alpha, best_rmse = grid[0], float("inf")
    for alpha in grid:
        dk = declared_kernel(g, alpha)
        with mp.Pool(min(mp.cpu_count(), 12)) as pool:
            rows = pool.map(_predict, [(s, learned, dk) for s in train], chunksize=1)
        act = np.array([r[0] for r in rows])
        dec = np.array([r[2] for r in rows])
        r = _rmse(act, dec)
        print(f"  alpha={alpha:<5} train RMSE {r:8.1f}")
        if r < best_rmse:
            best_alpha, best_rmse = alpha, r
    print(f"  chosen alpha = {best_alpha}")
    dk = declared_kernel(g, best_alpha)

    print(f"scoring {len(test)} held-out scenarios...")
    with mp.Pool(min(mp.cpu_count(), 12)) as pool:
        rows = pool.map(_predict, [(s, learned, dk) for s in test], chunksize=1)

    actual = np.array([r[0] for r in rows])
    lrn = np.array([r[1] for r in rows])
    dec = np.array([r[2] for r in rows])
    rmse_l, rmse_d = _rmse(actual, lrn), _rmse(actual, dec)
    rel = (rmse_d - rmse_l) / rmse_d if rmse_d > 0 else 0.0
    passed = bool(rel >= 0.15)

    report = {
        "n_train": len(train), "n_test": len(test),
        "observe_frac": OBSERVE_FRAC, "n_rollouts": N_ROLLOUTS,
        "declared_alpha_calibrated_on_train": best_alpha,
        "declared_edges": len(dk.edges), "learned_edges": len(learned.edges),
        "mean_actual_volume": round(float(actual.mean()), 1),
        "rmse_learned": round(rmse_l, 2),
        "rmse_declared": round(rmse_d, 2),
        "relative_improvement": round(float(rel), 4),
        "predicted": ">= 0.15 relative improvement",
        "H2_PASSED": passed,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "h2.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        "# H2 — learned kernel vs declared interdependency matrix", "",
        "Generated by `eval/h2.py`. Never hand-edited. Pre-registered before running.", "",
        "Both kernels see the same first "
        f"{OBSERVE_FRAC:.0%} of the same held-out scenario and answer the same",
        "question: **how many more assets fail after this moment?**", "",
        f"- train: {len(train)} scenarios · test: {len(test)} held out, fresh seed range",
        f"- declared matrix: {len(dk.edges)} declared edges, uniform alpha = {best_alpha} "
        "(calibrated on train, so it does not lose for want of a scale factor)",
        f"- learned kernel: {len(learned.edges)} edges mined from near-misses",
        f"- mean actual cascade volume: {actual.mean():.1f} assets", "",
        "| kernel | RMSE on cascade volume |", "|---|---|",
        f"| declared / expert-elicited | {rmse_d:.1f} |",
        f"| **learned from near-misses** | **{rmse_l:.1f}** |",
        f"| relative improvement | **{rel:+.1%}** |", "",
        f"## H2 {'HOLDS' if passed else 'DOES NOT HOLD AS STATED'}", "",
        f"Pre-registered: >= 15% relative improvement. Measured: **{rel:+.1%}**.", "",
        "**Where the difference comes from, stated plainly.** A declared matrix contains",
        "declared dependencies and nothing else. It has no entry for load redistribution",
        "between flow-peers, because that is not an interdependency anyone writes down —",
        "and load redistribution is **80% of the propagation mass in this system** (see",
        "`docs/FINDINGS.md`). So this result is less 'our estimator is better' than",
        "'most of what propagates failure was never in the matrix to begin with'. That is",
        "the honest reading, and it is a stronger argument for mining than a tuned",
        "estimator would have been.", "",
    ]
    (OUT / "h2.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
