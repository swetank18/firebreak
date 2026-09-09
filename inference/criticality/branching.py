"""Branching ratio — the headline number.

    n_i = sum_j alpha_ij * s_j(t)

n_i > 1 means a failure at i is expected to produce more than one downstream
failure, so the cascade grows. Below 1 it dies out. That is the whole answer to
the organisers' core-challenge line, "distinguish normal abnormality from
dangerous abnormality", and it is one number.

The point is that this is INDEPENDENT of how loud the alarm is. Two nodes with
identical anomaly scores can differ by an order of magnitude here, because
danger is a property of position, not of the event.
"""

from __future__ import annotations

from city.engine.state import WorldState
from contracts.city import CityGraph
from contracts.criticality import Criticality, Damage
from contracts.kernel import Kernel
from inference.relations import propagation_targets

DANGER_THRESHOLD = 1.0


class BranchingRatio:
    def __init__(self, graph: CityGraph, kernel: Kernel):
        self.graph = graph
        self.kernel = kernel
        # Same helper the estimator uses. Not a copy of the logic — the copy
        # is what broke H1.
        self.out = propagation_targets(graph)

    def of(self, node_id: str, world: WorldState) -> float:
        """n_i in the current state."""
        total = 0.0
        for child, edge_id in self.out.get(node_id, ()):
            ek = self.kernel.edges.get(edge_id)
            if ek is None:
                continue
            st = world.nodes.get(child)
            s = st.susceptibility if st else 1.0
            total += ek.alpha * s
        return total

    def interval(self, node_id: str, world: WorldState) -> tuple[float, float]:
        """Bootstrap interval on n_i, widened by thin edges."""
        lo = hi = 0.0
        for child, edge_id in self.out.get(node_id, ()):
            ek = self.kernel.edges.get(edge_id)
            if ek is None:
                continue
            st = world.nodes.get(child)
            s = st.susceptibility if st else 1.0
            lo += ek.ci_low * s
            hi += ek.ci_high * s
        return lo, hi

    def all(self, world: WorldState) -> dict[str, float]:
        return {n.id: self.of(n.id, world) for n in self.graph.nodes}

    def criticality(
        self, node_id: str, world: WorldState, *, p_cascade: float = 0.0,
        reach: float = 0.0, damage: Damage | None = None, n_rollouts: int = 0,
    ) -> Criticality:
        n = self.of(node_id, world)
        lo, hi = self.interval(node_id, world)
        return Criticality(
            node_id=node_id, t=world.t, branching_ratio=n,
            p_cascade=p_cascade, expected_reach=reach,
            expected_damage=damage or Damage(),
            ci_low=lo, ci_high=hi, n_rollouts=n_rollouts,
        )


class CascadeReach:
    """Expected reach at depth K — the multi-hop predictor.

    The one-step branching ratio n_i answers "does this grow", which is the
    danger CRITERION. But the label we predict is "does a chain of >= K hops
    follow", and a one-step statistic is the wrong shape for a K-step question:
    a node with n_i = 0.9 feeding a chain of hubs is more dangerous than one
    with n_i = 1.1 feeding dead ends.

    For a branching process with matrix M = A diag(s), expected total offspring
    within K generations from seed i is

        sum_{k=1..K} (e_i^T M^k) 1

    which is K sparse products. Exact for the branching model, no sampling.
    """

    def __init__(self, graph: CityGraph, kernel: Kernel, depth: int = 6):
        import numpy as np
        from scipy.sparse import coo_matrix

        self.depth = depth
        self.idx = {n.id: i for i, n in enumerate(graph.nodes)}
        self.n = len(self.idx)
        out = propagation_targets(graph)
        rows, cols, vals = [], [], []
        for parent, kids in out.items():
            pi = self.idx.get(parent)
            if pi is None:
                continue
            for child, key in kids:
                ek = kernel.edges.get(key)
                ci = self.idx.get(child)
                if ek is None or ci is None:
                    continue
                rows.append(pi); cols.append(ci); vals.append(ek.alpha)
        self.A = coo_matrix((vals, (rows, cols)), shape=(self.n, self.n)).tocsr()
        self._np = np

    def reach(self, node_id: str, s_vec) -> float:
        np = self._np
        i = self.idx.get(node_id)
        if i is None or self.A.nnz == 0:
            return 0.0
        v = np.zeros(self.n)
        v[i] = 1.0
        total = 0.0
        for _ in range(self.depth):
            v = (v @ self.A) * s_vec
            m = float(v.sum())
            if m < 1e-9:
                break
            total += m
        return total

    def susceptibility_vector(self, obs) -> "object":
        np = self._np
        return np.array([obs.susceptibility(nid) for nid in self.idx], dtype=float)
