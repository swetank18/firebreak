"""Batched Monte Carlo cascade rollout.

Consumes a CityGraph and a Kernel. Imports nothing from `city/` — the decision
layer must never know it is looking at a water pump rather than a node with a
dependency profile, or the domain-agnostic claim is a lie. Enforced by an AST
test in service/tests/test_invariants.py.

The model is the branching process the kernel describes. For one generation,
node j's arrival intensity is the summed alpha from every parent that failed
last generation, thinned by j's susceptibility:

    lambda_j = sum_{i in newly_failed} alpha_ij * s_j
    P(j fails) = 1 - exp(-lambda_j)

which is Poisson thinning, and it batches: with F an (R, n) boolean of
newly-failed nodes across R rollouts, `F @ A` gives every intensity at once.
That is one sparse matmul per generation instead of a Python loop per rollout,
which is what keeps 2000 rollouts under the 2 s the demo needs.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix

from contracts.city import CityGraph
from contracts.criticality import Damage
from contracts.kernel import Kernel
from inference.relations import propagation_targets

MAX_GENERATIONS = 12


@dataclass
class RolloutResult:
    p_cascade: float
    expected_reach: float
    damage: Damage
    mean_time_to_protected_s: float | None
    n_rollouts: int
    # per-rollout totals, kept so callers can bootstrap rather than trust a point
    reach_samples: np.ndarray
    damage_samples: np.ndarray


class CascadeRollout:
    """Everything needed to answer 'what happens next, and what if we act'."""

    def __init__(self, graph: CityGraph, kernel: Kernel, *, cascade_hops: int = 6):
        self.cascade_hops = cascade_hops
        self.nodes = list(graph.nodes)
        self.idx = {n.id: i for i, n in enumerate(self.nodes)}
        self.n = len(self.nodes)

        self.pop = np.array([n.population_served for n in self.nodes], dtype=float)
        self.weight = np.array([n.criticality_weight for n in self.nodes], dtype=float)
        # NOT `n.layer == ...`: the invariant is that no executable line here
        # names a layer. The city declares the protected class in the contract.
        self.is_protected = np.array([n.protected_class for n in self.nodes])
        self.buffer_s = np.array([n.buffer_s for n in self.nodes], dtype=float)

        rows, cols, vals, delays = [], [], [], []
        for parent, kids in propagation_targets(graph).items():
            pi = self.idx.get(parent)
            if pi is None:
                continue
            for child, key in kids:
                ek = kernel.edges.get(key)
                ci = self.idx.get(child)
                if ek is None or ci is None:
                    continue
                rows.append(pi)
                cols.append(ci)
                vals.append(ek.alpha)
                delays.append(ek.mean_delay_s)
        shape = (self.n, self.n)
        self.A = csr_matrix((vals, (rows, cols)), shape=shape)
        self.D = csr_matrix((delays, (rows, cols)), shape=shape)
        # mean inbound delay per node, for time-to-impact
        deg = np.asarray((self.D > 0).sum(axis=0)).ravel()
        tot = np.asarray(self.D.sum(axis=0)).ravel()
        self.mean_delay_in = np.where(deg > 0, tot / np.maximum(deg, 1), 900.0)

    # ------------------------------------------------------------------ core

    def run(
        self,
        seeds: list[str],
        s_vec: np.ndarray,
        *,
        n_rollouts: int = 800,
        seed: int = 0,
        A: csr_matrix | None = None,
        already_failed: np.ndarray | None = None,
        apply_at_generation: int = 0,
    ) -> RolloutResult:
        """Roll the cascade forward from `seeds` under the current state.

        `A` is the propagation matrix AFTER an intervention — that is how a
        candidate is scored. `apply_at_generation` delays the switch, so the
        cascade runs unmodified for k generations first. That is how the
        deadline is found: benefit decays as k rises, and the deadline is the
        largest k still retaining 90% of the benefit of acting now.
        """
        rng = np.random.default_rng(seed)
        R = n_rollouts
        seed_ix = [self.idx[s] for s in seeds if s in self.idx]
        if not seed_ix:
            return self._empty(R)

        A_before = self.A
        A_after = self.A if A is None else A

        failed = np.zeros((R, self.n), dtype=bool)
        if already_failed is not None:
            failed |= already_failed[None, :]
        active = np.zeros((R, self.n), dtype=bool)
        active[:, seed_ix] = True
        failed |= active

        depth = np.zeros(R, dtype=int)
        t_prot = np.full(R, np.nan)
        elapsed = 0.0

        for gen in range(MAX_GENERATIONS):
            if not active.any():
                break
            # unmodified until the action lands, modified after
            Am = A_before if gen < apply_at_generation else A_after
            # intensity into every node from everything that just failed
            lam = active.astype(np.float32) @ Am
            lam = np.asarray(lam) * s_vec[None, :]
            p = 1.0 - np.exp(-lam)
            p[failed] = 0.0
            new = rng.random((R, self.n)) < p
            if not new.any():
                break

            elapsed += float(np.mean(self.mean_delay_in[new.any(axis=0)])) if new.any() else 0.0
            hit_prot = (new & self.is_protected[None, :]).any(axis=1)
            first = hit_prot & np.isnan(t_prot)
            t_prot[first] = elapsed

            failed |= new
            active = new
            depth += new.any(axis=1).astype(int)

        reach = failed.sum(axis=1).astype(float)
        # damage: people-hours, weighted, plus hospital-critical hours
        hours = 4.0  # mean outage hours per failed asset in the horizon
        ph = (failed * self.pop[None, :]).sum(axis=1) * hours
        hosp_h = (failed & self.is_protected[None, :]).sum(axis=1) * hours
        weighted = (failed * (self.pop * self.weight)[None, :]).sum(axis=1) * hours

        dmg = Damage(
            person_hours_no_power=float(ph.mean() * 0.6),
            person_hours_no_water=float(ph.mean() * 0.4),
            hospital_critical_hours=float(hosp_h.mean()),
            people_affected=int((failed * self.pop[None, :]).sum(axis=1).mean()),
        )
        return RolloutResult(
            p_cascade=float((depth >= self.cascade_hops).mean()),
            expected_reach=float(reach.mean()),
            damage=dmg,
            mean_time_to_protected_s=(float(np.nanmean(t_prot))
                                      if not np.all(np.isnan(t_prot)) else None),
            n_rollouts=R,
            reach_samples=reach,
            damage_samples=weighted,
        )

    def _empty(self, R: int) -> RolloutResult:
        return RolloutResult(0.0, 0.0, Damage(), None, R, np.zeros(R), np.zeros(R))
