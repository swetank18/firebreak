"""The counting estimator.

Ships first and always works. For each candidate propagation edge i -> j:

    alpha_ij ~ (children at j attributed to parents at i) / (events at i)
    1/beta_ij ~ mean dt over those attributed pairs

Interpretable, fast, robust, and it will be most of the result. MLE is the
stretch upgrade in lanes/LANE-B-inference.md; if MLE does not beat this on
held-out cascade-volume RMSE, we say so.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from contracts.city import CityGraph
from contracts.events import Event
from contracts.kernel import EdgeKernel, Kernel
from inference.mining.miner import DEFAULT_WINDOW_S, NearMissMiner
from inference.relations import propagation_targets, sibling_key

N_BOOTSTRAP = 200


def fit(
    graph: CityGraph,
    events: list[Event] | list[list[Event]],
    *,
    window_s: float = DEFAULT_WINDOW_S,
    horizon_s: float | None = None,
    corpus_id: str = "adhoc",
    seed: int = 0,
) -> Kernel:
    """Fit from OBSERVABLE events only. `events` must already be redacted.

    Pass a LIST OF SCENARIOS (`[[Event, ...], [Event, ...]]`) whenever the
    corpus spans more than one run. A flat list is accepted and treated as a
    single scenario, which is correct only if it really is one — every scenario
    shares the same 0..horizon clock, so a pooled flat list lets the miner
    attribute a failure in one run to a failure in another.
    """
    corpora: list[list[Event]]
    if events and isinstance(events[0], list):
        corpora = events  # type: ignore[assignment]
    else:
        corpora = [events]  # type: ignore[list-item]
    flat: list[Event] = [e for c in corpora for e in c]

    miner = NearMissMiner(graph, window_s)
    links = miner.links_many(corpora)

    # one parent per child, matching what the chain builder commits to
    best: dict[str, object] = {}
    for l in links:
        cur = best.get(l.child)
        if cur is None or (l.dt, l.relation != "depends_on") < (
            cur.dt, cur.relation != "depends_on"  # type: ignore[attr-defined]
        ):
            best[l.child] = l

    node_of = {e.event_id: e.node_id for e in flat}
    n_events_at: dict[str, int] = defaultdict(int)
    for e in flat:
        if e.kind == "failed":
            n_events_at[e.node_id] += 1

    # ONE canonical key per relation, shared with the consumer. See
    # inference/relations.py — deriving this twice cost H1 its entire signal.
    targets = propagation_targets(graph)
    edge_id_of: dict[tuple[str, str], str] = {}
    parent_of_edge: dict[str, str] = {}
    child_of_edge: dict[str, str] = {}
    for parent, kids in targets.items():
        for child, key in kids:
            edge_id_of[(parent, child)] = key
            parent_of_edge[key] = parent
            child_of_edge[key] = child

    per_edge_dts: dict[str, list[float]] = defaultdict(list)
    for l in best.values():
        eid = edge_id_of.get((l.src_node, l.dst_node))  # type: ignore[attr-defined]
        if eid is None:
            eid = sibling_key(l.src_node, l.dst_node)  # type: ignore[attr-defined]
            parent_of_edge[eid] = l.src_node  # type: ignore[attr-defined]
            child_of_edge[eid] = l.dst_node  # type: ignore[attr-defined]
        per_edge_dts[eid].append(l.dt)  # type: ignore[attr-defined]

    rng = np.random.default_rng(seed)
    edges: dict[str, EdgeKernel] = {}
    for eid, dts in per_edge_dts.items():
        parent_node = parent_of_edge.get(eid)
        denom = n_events_at.get(parent_node, 0) if parent_node else 0
        if denom <= 0:
            continue
        n_obs = len(dts)
        alpha = n_obs / denom
        arr = np.asarray(dts, dtype=float)
        mean_dt = float(arr.mean())
        # dt == 0 is real (same-tick redistribution); floor beta so it stays finite
        beta = 1.0 / max(mean_dt, 30.0)

        if n_obs >= 5:
            boot = rng.choice(arr, size=(N_BOOTSTRAP, n_obs), replace=True)
            counts = np.full(N_BOOTSTRAP, n_obs, dtype=float)
            a_boot = counts / denom
            jitter = rng.binomial(denom, min(alpha, 1.0), size=N_BOOTSTRAP) / denom
            a_boot = 0.5 * a_boot + 0.5 * jitter
            lo, hi = np.percentile(a_boot, [2.5, 97.5])
        else:
            lo, hi = 0.0, min(1.0, alpha * 3)

        edges[eid] = EdgeKernel(
            edge_id=eid, alpha=float(alpha), beta=float(beta), n_obs=n_obs,
            ci_low=float(lo), ci_high=float(hi), estimator="counting",
        )

    T = horizon_s or (max((e.t for e in flat), default=1.0) or 1.0)
    mu = {n.id: n_events_at.get(n.id, 0) / T for n in graph.nodes}

    # rho(G) is the SPECTRAL RADIUS of the branching matrix, not the max row
    # sum. The row sum is only an upper bound and it read 10.1 on a system we
    # had already measured as subcritical. Power iteration on the sparse matrix.
    idx = {n.id: i for i, n in enumerate(graph.nodes)}
    rows, cols, vals = [], [], []
    for eid, ek in edges.items():
        p = parent_of_edge.get(eid)
        c = child_of_edge.get(eid)
        if p in idx and c in idx:
            rows.append(idx[p]); cols.append(idx[c]); vals.append(ek.alpha)
    rho = 0.0
    if vals:
        from scipy.sparse import coo_matrix
        G = coo_matrix((vals, (rows, cols)), shape=(len(idx), len(idx))).tocsr()
        v = np.ones(len(idx)) / np.sqrt(len(idx))
        for _ in range(200):
            w = G.T @ v
            nrm = float(np.linalg.norm(w))
            if nrm < 1e-12:
                break
            v = w / nrm
            rho = nrm

    return Kernel(
        kernel_id=f"k-{corpus_id}-{len(edges)}",
        city_id=graph.city_id,
        corpus_id=corpus_id,
        fitted_at=datetime.now(timezone.utc),
        edges=edges,
        mu=mu,
        spectral_radius=float(rho),
    )
