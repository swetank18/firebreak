"""Generate events from a KNOWN Hawkes kernel.

This exists so the estimator can be proved against ground truth it cannot see.
If the fitter cannot recover its own synthetic kernel, every downstream number
is noise. Written before the real estimator, per lanes/LANE-B-inference.md.

The generator is a branching process, which is what a Hawkes process is:

    background events arrive at rate mu_j
    each event at i spawns an offspring at j with probability alpha_ij,
    after a delay drawn from Exp(beta_ij)
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from contracts.city import CityGraph
from contracts.events import Event


@dataclass
class TrueKernel:
    """Ground truth the estimator is scored against."""

    alpha: dict[str, float]  # edge_id -> branching ratio contribution
    beta: dict[str, float]   # edge_id -> decay rate
    mu: dict[str, float]     # node_id -> background intensity (per second)


def make_kernel(g: CityGraph, seed: int = 0, target_rho: float = 0.75) -> TrueKernel:
    """A plausible kernel, scaled so the process is subcritical.

    target_rho below 1 keeps cascades finite. Above 1 the generator never
    terminates, which is a useful thing to be able to demonstrate.
    """
    rng = np.random.default_rng(seed)
    alpha, beta = {}, {}
    # candidate propagation edges: dependency and flow, same as the miner sees
    for e in g.edges:
        a = float(rng.uniform(0.05, 0.55))
        # mean delay 60s..3h; dependency edges are slower (buffers)
        mean_delay = float(rng.uniform(600, 10_800) if e.relation == "depends_on"
                           else rng.uniform(60, 900))
        alpha[e.id] = a
        beta[e.id] = 1.0 / mean_delay

    # scale alpha so the max per-node outgoing sum sits at target_rho
    out: dict[str, float] = {}
    for e in g.edges:
        out[e.dst if e.relation == "depends_on" else e.src] = (
            out.get(e.dst if e.relation == "depends_on" else e.src, 0.0) + alpha[e.id]
        )
    peak = max(out.values()) if out else 1.0
    scale = target_rho / peak if peak > 0 else 1.0
    alpha = {k: v * scale for k, v in alpha.items()}

    mu = {n.id: float(rng.uniform(2e-6, 8e-6)) for n in g.nodes}
    return TrueKernel(alpha=alpha, beta=beta, mu=mu)


def simulate(
    g: CityGraph, k: TrueKernel, horizon_s: float, seed: int = 0
) -> tuple[list[Event], dict[str, str]]:
    """Run the branching process. Returns (events, event_id -> edge_id used).

    The edge map is ground truth for scoring which edge produced which link.
    """
    rng = np.random.default_rng(seed)
    # parent node -> [(child node, edge_id)]
    children: dict[str, list[tuple[str, str]]] = {}
    flow_out: dict[str, list[str]] = {}
    flow_in: dict[str, list[str]] = {}
    for e in g.edges:
        if e.relation == "depends_on":
            children.setdefault(e.dst, []).append((e.src, e.id))
        else:
            flow_out.setdefault(e.src, []).append(e.dst)
            flow_in.setdefault(e.dst, []).append(e.src)
    for e in g.edges:
        if e.relation == "flow":
            for peer in flow_in.get(e.dst, ()):
                if peer != e.src:
                    children.setdefault(e.src, []).append((peer, e.id))

    events: list[Event] = []
    edge_of: dict[str, str] = {}
    n = 0

    def emit(node: str, t: float, cause: str | None, edge_id: str | None) -> str:
        nonlocal n
        n += 1
        eid = f"h{n:07d}"
        events.append(Event(event_id=eid, node_id=node, t=t, kind="failed",
                            severity=0.8, anomaly_score=float(rng.random()),
                            observed=True, cause=cause))
        if edge_id:
            edge_of[eid] = edge_id
        return eid

    # immigrants
    heap: list[tuple[float, int, str, str]] = []
    tie = 0
    for node, mu in k.mu.items():
        n_bg = rng.poisson(mu * horizon_s)
        for t in rng.uniform(0, horizon_s, n_bg):
            tie += 1
            heap.append((float(t), tie, node, ""))
    heapq.heapify(heap)

    while heap:
        t, _, node, parent = heapq.heappop(heap)
        eid = emit(node, t, parent or None, edge_of.get(parent) if parent else None)
        for child_node, edge_id in children.get(node, ()):
            if rng.random() < k.alpha.get(edge_id, 0.0):
                dt = float(rng.exponential(1.0 / k.beta[edge_id]))
                if t + dt <= horizon_s:
                    tie += 1
                    heapq.heappush(heap, (t + dt, tie, child_node, eid))
                    edge_of[eid + "->" + child_node] = edge_id

    events.sort(key=lambda e: e.t)
    return events, edge_of
