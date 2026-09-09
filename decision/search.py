"""Counterfactual intervention search.

This is what the literature does not have. I3 and PI-GN-JODE both predict
cascades; read their own framing and they say prediction "supports proactive
intervention". Neither selects one.

For each candidate action, re-simulate the cascade with that action applied and
score it by damage prevented per unit cost:

    score(a) = (E[damage | nothing] - E[damage | a]) / cost(a)

The do-nothing counterfactual is mandatory on every Decision. A recommendation
without it is a suggestion, and this project is about consequences.

Each intervention carries a DEADLINE: the latest moment at which ordering it
still yields >= 90% of its current benefit, found by re-running with the action
applied progressively later. A prediction without a deadline is a weather
forecast; with one it is an instruction.
"""

from __future__ import annotations

import time
import uuid

import numpy as np

from contracts.city import CityGraph
from contracts.criticality import Criticality
from contracts.decision import Action, Decision, Intervention
from contracts.kernel import Kernel
from decision import actions as A
from decision.rollout import CascadeRollout

DEADLINE_RETENTION = 0.90


class InterventionSearch:
    def __init__(self, graph: CityGraph, kernel: Kernel, *, n_rollouts: int = 600,
                 kinds: tuple[str, ...] | None = None, top_k: int = 24):
        self.graph = graph
        self.roll = CascadeRollout(graph, kernel)
        self.node_by_id = {n.id: n for n in graph.nodes}
        self.n_dependents: dict[str, int] = {}
        for e in graph.edges:
            if e.relation == "depends_on":
                self.n_dependents[e.dst] = self.n_dependents.get(e.dst, 0) + 1
        self.n_rollouts = n_rollouts
        # Restrict the action space to what the evaluating environment can apply.
        # None means the full space.
        self.kinds = kinds
        self.top_k = top_k

    def _reach_hint(self, seeds: list[str], s_vec: np.ndarray, seed: int) -> dict[str, float]:
        """Which nodes does the cascade actually threaten? Only propose there."""
        base = self.roll.run(seeds, s_vec, n_rollouts=200, seed=seed)
        # one extra pass recording per-node hit frequency
        rng = np.random.default_rng(seed + 1)
        R, n = 200, self.roll.n
        failed = np.zeros((R, n), dtype=bool)
        active = np.zeros((R, n), dtype=bool)
        for sd in seeds:
            if sd in self.roll.idx:
                active[:, self.roll.idx[sd]] = True
        failed |= active
        for _ in range(8):
            if not active.any():
                break
            lam = np.asarray(active.astype(np.float32) @ self.roll.A) * s_vec[None, :]
            p = 1.0 - np.exp(-lam)
            p[failed] = 0.0
            new = rng.random((R, n)) < p
            if not new.any():
                break
            failed |= new
            active = new
        freq = failed.mean(axis=0)
        weight = freq * (1.0 + self.roll.pop / max(self.roll.pop.max(), 1.0)) * self.roll.weight
        # Widened from 40. Once the assets that are already down are excluded,
        # a narrow hint leaves the search with almost nothing to propose — on a
        # mid-scenario decision it returned two candidates, both the same node,
        # so the arm could not even spend its budget.
        n_hint = max(80, self.top_k * 3)
        return {self.roll.nodes[i].id: float(weight[i]) for i in np.argsort(-weight)[:n_hint]
                if weight[i] > 0}

    def _deadline(self, action: Action, seeds, s_vec, benefit_now: float, seed: int) -> float:
        """Latest delay at which the action still retains 90% of its benefit."""
        if benefit_now <= 0:
            return 0.0
        Am = A.apply(self.roll.A, action, self.roll.idx)
        base = self.roll.run(seeds, s_vec, n_rollouts=400, seed=seed)
        base_mean = float(base.damage_samples.mean())
        # Benefit decays monotonically as the action lands later, so walk out
        # until it drops below the retention floor.
        best = 0
        for k in range(1, 7):
            r = self.roll.run(seeds, s_vec, n_rollouts=400, seed=seed,
                              A=Am, apply_at_generation=k)
            b = base_mean - float(r.damage_samples.mean())
            if b >= DEADLINE_RETENTION * benefit_now:
                best = k
            else:
                break
        # generations -> seconds, using the delay actually on the exposed edges
        return float(best * np.median(self.roll.mean_delay_in))

    def decide(
        self,
        scenario_id: str,
        t: float,
        seeds: list[str],
        s_vec: np.ndarray,
        trigger: list[Criticality],
        *,
        seed: int = 0,
        top_n: int = 5,
        already_failed: set[str] | None = None,
        keep_nonpositive: bool = False,
    ) -> Decision:
        """Rank interventions and return the best, each with a deadline.

        `already_failed` is what is ALREADY down at time `t`.

        Two things depend on it: those assets are not proposed as targets, and
        the rollout counts them as failed rather than re-failing them, which
        otherwise inflates every candidate's estimated benefit.
        """
        t0 = time.perf_counter()
        down = set(already_failed or ())
        af = (np.array([n.id in down for n in self.graph.nodes]) if down else None)
        base = self.roll.run(seeds, s_vec, n_rollouts=self.n_rollouts, seed=seed,
                             already_failed=af)
        base_dmg = float(base.damage_samples.mean())

        hint = self._reach_hint(seeds, s_vec, seed)
        cands = A.candidates(self.node_by_id, self.roll.idx, seeds, hint,
                             top_k=self.top_k, kinds=self.kinds, exclude=frozenset(down))

        scored: list[Intervention] = []
        for a in cands:
            Am = A.apply(self.roll.A, a, self.roll.idx)
            r = self.roll.run(seeds, s_vec, n_rollouts=self.n_rollouts, seed=seed, A=Am,
                              already_failed=af)
            prevented = base_dmg - float(r.damage_samples.mean())
            if prevented <= 0 and not keep_nonpositive:
                # The product declines to recommend an action it cannot show a
                # benefit for. An ABLATION arm still has to spend its budget, or
                # it is being compared at a different budget from every other
                # arm, so the ablation asks for the full ranking.
                continue
            saved = _damage_delta(base.damage, r.damage)
            scored.append(
                Intervention(
                    action=a,
                    damage_prevented=saved,
                    damage_prevented_headline=prevented,
                    benefit_per_cost=prevented / max(a.cost, 1e-9),
                    p_success=float(1.0 - r.p_cascade),
                    deadline_s=0.0,
                    rationale=_rationale(a, base, r, self.node_by_id.get(a.target),
                                         self.n_dependents.get(a.target, 0)),
                    n_rollouts=self.n_rollouts,
                )
            )

        scored.sort(key=lambda i: -i.benefit_per_cost)
        top = scored[:top_n]
        for iv in top:
            iv.deadline_s = self._deadline(iv.action, seeds, s_vec,
                                           iv.damage_prevented_headline, seed)

        return Decision(
            decision_id=f"d-{uuid.uuid4().hex[:8]}",
            scenario_id=scenario_id,
            t=t,
            trigger=trigger,
            do_nothing_damage=base.damage,
            ranked=top,
            compute_ms=(time.perf_counter() - t0) * 1000.0,
            seed=seed,
        )


def _damage_delta(a, b):
    from contracts.criticality import Damage

    return Damage(
        person_hours_no_power=max(0.0, a.person_hours_no_power - b.person_hours_no_power),
        person_hours_no_water=max(0.0, a.person_hours_no_water - b.person_hours_no_water),
        hospital_critical_hours=max(0.0, a.hospital_critical_hours - b.hospital_critical_hours),
        people_affected=max(0, a.people_affected - b.people_affected),
    )


def _rationale(action: Action, base, alt, node, n_dependents: int = 0) -> list[str]:
    """Templated from rollout statistics. NEVER LLM-generated.

    A decision about which neighbourhood loses water has to be explainable line
    by line, and that is a deployment argument as much as an ethical one.
    """
    out = []
    drop = base.expected_reach - alt.expected_reach
    if drop > 0:
        out.append(f"contains {drop:.0f} of {base.expected_reach:.0f} expected asset failures")
    hosp = base.damage.hospital_critical_hours - alt.damage.hospital_critical_hours
    if hosp > 0:
        out.append(f"prevents {hosp:.0f} hospital-critical hours")
    if base.p_cascade > 0:
        out.append(f"cuts cascade probability {base.p_cascade:.0%} to {alt.p_cascade:.0%}")
    if node is not None and node.buffer_s > 0 and action.kind == "preposition":
        out.append(f"target holds a {node.buffer_s/3600:.0f} h reserve that resupply must reach")
    if node is not None and node.population_served == 0 and n_dependents:
        # Structural, not "this is a road". The decision layer is not allowed to
        # know what a road is, and the sentence is truer this way: what makes the
        # target matter is that things depend on it while it serves no one itself.
        out.append(f"target serves no population directly, yet {n_dependents} "
                   "assets depend on it — invisible to any load-ranked alarm")
    return out or ["reduces expected damage under rollout"]
