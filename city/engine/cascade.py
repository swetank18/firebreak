"""The cascade engine.

One tick does five things in order:

  1. hazard        exogenous stress lands on exposed assets
  2. direct        stressed nodes fail probabilistically
  3. redistribute  a failed node sheds its load onto flow-neighbours; anyone
                   pushed past capacity overloads and fails (Motter-Lai)
  4. drawdown      a node whose dependency is down burns its buffer, then
                   degrades, then fails
  5. restore       crews arrive over the CURRENT road network

RISK R1, THE ONE THAT MAKES THIS CIRCULAR: `Edge.nominal_delay_s` is never read
here. Propagation delay emerges from buffer size divided by a drawdown rate that
varies with load and hazard. If Lane B ever recovers 1/beta correlating above
0.95 with nominal_delay_s, this file is the bug.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from city.engine.hazard import HazardField
from city.engine.state import NodeState, Status, WorldState
from contracts.city import CityGraph
from contracts.events import Event

# capacity = (1 + TOLERANCE) * initial_load.
# This single number sets how close the system sits to criticality, and
# criticality is where heavy tails live. It is the primary knob for the
# realism gate — see docs/02-CITY-SPEC.md.
TOLERANCE = 0.35

# Exogenous ignition intensity: expected ignitions per SECOND per unit
# (hazard stress x susceptibility). A rate, not a per-tick probability.
#
# This was `p = 0.0016 * stress * susceptibility` applied once per tick, which
# made tick size — a pure discretisation choice — change the modelled physics:
# the same seed and scenario gave 611 exogenous ignitions at tick_s=60 and 177
# at tick_s=600. Every scenario also saturated (92% of the city down, seed
# spread 0.90-0.94), so no intervention could move the outcome and the whole
# ablation measured nothing. See docs/FINDINGS.md.
IGNITION_RATE_HZ = 1.0e-5


@dataclass
class Indices:
    """Precomputed adjacency. Built once per city, reused across every run."""

    graph: CityGraph
    flow_out: dict[str, list[str]] = field(default_factory=dict)
    flow_in: dict[str, list[str]] = field(default_factory=dict)
    depends_on: dict[str, list[str]] = field(default_factory=dict)
    dependents: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, g: CityGraph) -> "Indices":
        ix = cls(graph=g)
        for n in g.nodes:
            ix.flow_out.setdefault(n.id, [])
            ix.flow_in.setdefault(n.id, [])
            ix.depends_on.setdefault(n.id, [])
            ix.dependents.setdefault(n.id, [])
        for e in g.edges:
            if e.relation == "flow":
                ix.flow_out[e.src].append(e.dst)
                ix.flow_in[e.dst].append(e.src)
            else:
                ix.depends_on[e.src].append(e.dst)
                ix.dependents[e.dst].append(e.src)
        return ix

    def siblings(self, node_id: str) -> list[str]:
        """Flow-peers that can absorb shed load: anything sharing a parent."""
        out: set[str] = set()
        for parent in self.flow_out.get(node_id, []):
            out.update(self.flow_in.get(parent, []))
        out.discard(node_id)
        return sorted(out)


class CascadeEngine:
    def __init__(self, g: CityGraph, hazard: HazardField, seed: int, tick_s: float = 60.0,
                 protected: dict[str, float] | None = None, protect_at_s: float = 0.0,
                 event_prefix: str = ""):
        """`protected` maps node_id -> protection in [0,1], applied at
        `protect_at_s`. This is how an arm's chosen intervention is tested: the
        real engine re-runs on the same seed with the protection in place, so
        the comparison is a true counterfactual rather than a score under our
        own rollout model — which would flatter arm A4 by construction."""
        self.g = g
        self.ix = Indices.build(g)
        self.hazard = hazard
        self.tick_s = tick_s
        self.rng = np.random.default_rng(seed)
        self.seed_value = seed
        self.protected = protected or {}
        self.protect_at_s = protect_at_s
        # PAIRED RANDOMNESS. One generator drawn sequentially means protecting
        # any node shifts every later draw for every other node, so arm-to-arm
        # differences would be stream drift rather than effect. A precomputed
        # (tick x node) field indexed by position makes each node's draw
        # identical across arms. See docs/FINDINGS.md.
        self._nidx = {n.id: i for i, n in enumerate(g.nodes)}
        self._field: np.ndarray | None = None
        self._tick = 0
        self.events: list[Event] = []
        self._eid = 0
        # Event ids must be unique ACROSS scenarios, not just within one. They
        # used to restart at e000001 every run, so pooling a training corpus
        # collided 8,263 of 12,877 ids and silently overwrote mined links.
        # See docs/FINDINGS.md.
        self._prefix = event_prefix
        self.world = WorldState(tick_s=tick_s)
        for n in g.nodes:
            base = float(n.capacity) if n.capacity else 100.0
            load = base / (1.0 + TOLERANCE)
            self.world.nodes[n.id] = NodeState(
                node_id=n.id,
                layer=n.layer,
                capacity=base,
                load=load,
                initial_load=load,
                buffer_s=n.buffer_s,
                population_served=n.population_served,
                criticality_weight=n.criticality_weight,
            )

    # ---------------------------------------------------------------- events

    def _emit(self, node_id: str, kind: str, severity: float, cause: str | None) -> str:
        self._eid += 1
        eid = f"{self._prefix}e{self._eid:06d}"
        s = self.world.nodes[node_id]
        # The commodity detector: loud when a node is stressed, blind to position.
        # Deliberately position-agnostic — that is the whole of baseline arm A1.
        noise = (self._u(node_id, 2) - 0.5) * 0.1
        score = float(np.clip(0.35 * s.susceptibility + 0.30 * severity + noise, 0.0, 1.0))
        self.events.append(
            Event(
                event_id=eid,
                node_id=node_id,
                t=self.world.t,
                kind=kind,  # type: ignore[arg-type]
                severity=float(np.clip(severity, 0.0, 1.0)),
                anomaly_score=score,
                    observed=bool(self._u(node_id, 3) < 0.92),
                cause=cause,
            )
        )
        return eid

    def _fail(self, node_id: str, severity: float, cause: str | None) -> str | None:
        s = self.world.nodes[node_id]
        if not s.is_up:
            return None
        s.status = Status.FAILED
        s.failed_at = self.world.t
        eid = self._emit(node_id, "failed", severity, cause)
        s.cause_event = eid
        # restoration: base repair plus travel over the road network as it is now
        base = 1800.0 + 5400.0 * self._u(node_id, 1)
        s.restore_at = self.world.t + base * self._access_penalty()
        self._shed_load(node_id, eid)
        return eid

    def _access_penalty(self) -> float:
        """A flooded road hurts twice: once directly, once by slowing every repair.

        InfraRisk models transport access as a first-class dependency; this is
        the same idea, and it is why restoration is not a constant.
        """
        roads = [s for s in self.world.nodes.values() if s.layer == "transport"]
        if not roads:
            return 1.0
        down = sum(1 for s in roads if not s.is_up) / len(roads)
        return 1.0 + 4.0 * down

    # ------------------------------------------------------- the five stages

    def _u(self, node_id: str, stream: int = 0) -> float:
        """Draw for `node_id` at the current tick, stable across arms."""
        if self._field is None:
            return float(self.rng.random())
        i = self._nidx.get(node_id, 0)
        return float(self._field[self._tick % self._field.shape[0], i, stream])

    def _stage_hazard(self, tick: int) -> None:
        for nid, s in self.world.nodes.items():
            s.hazard_stress = self.hazard.at(nid, tick)

    def _prot(self, node_id: str) -> float:
        if self.world.t < self.protect_at_s:
            return 0.0
        return self.protected.get(node_id, 0.0)

    def _stage_direct(self) -> None:
        for nid, s in list(self.world.nodes.items()):
            if not s.is_up or s.hazard_stress <= 0:
                continue
            lam = IGNITION_RATE_HZ * s.hazard_stress * s.susceptibility * (1.0 - self._prot(nid))
            p = -math.expm1(-lam * self.tick_s)  # tick-size invariant
            if self._u(nid, 0) < p:
                self._fail(nid, s.hazard_stress, cause=None)  # exogenous

    def _shed_load(self, failed: str, cause_eid: str) -> None:
        """Motter-Lai: redistribute to flow-peers by spare capacity."""
        s = self.world.nodes[failed]
        load, s.load = s.load, 0.0
        if load <= 0:
            return
        peers = [p for p in self.ix.siblings(failed) if self.world.nodes[p].is_up]
        if not peers:
            return
        spare = {p: max(0.0, self.world.nodes[p].capacity - self.world.nodes[p].load) for p in peers}
        total = sum(spare.values())
        for p in peers:
            share = (spare[p] / total) if total > 0 else (1.0 / len(peers))
            self.world.nodes[p].load += load * share

    def _stage_overload(self) -> None:
        for nid, s in list(self.world.nodes.items()):
            if not s.is_up or s.capacity <= 0:
                continue
            if s.load > s.capacity * (1.0 + 2.0 * self._prot(nid)):
                parent = next(
                    (p for p in self.ix.siblings(nid) if not self.world.nodes[p].is_up), None
                )
                cause = self.world.nodes[parent].cause_event if parent else None
                self._fail(nid, min(1.0, s.load / s.capacity - 1.0), cause=cause)

    def _stage_drawdown(self) -> None:
        """Cross-layer buffered dependency. Where lead time comes from."""
        for nid, s in list(self.world.nodes.items()):
            if not s.is_up:
                continue
            deps_down = [d for d in self.ix.depends_on.get(nid, []) if not self.world.nodes[d].is_up]
            if not deps_down:
                if s.drawing_down:  # dependency came back before the buffer ran out
                    s.drawing_down = False
                    s.buffer_remaining_s = min(s.buffer_s, s.buffer_remaining_s + self.tick_s * 2)
                continue

            culprit = self.world.nodes[deps_down[0]].cause_event
            if s.buffer_remaining_s <= 0:
                self._fail(nid, 1.0, cause=culprit)
                continue

            if not s.drawing_down:
                s.drawing_down = True
                self._emit(nid, "degraded", 0.5, culprit)
            # Drawdown is NOT a constant. It runs faster under load and hazard,
            # which is what stops the learned kernel recovering a config value.
            rate = 1.0 + 0.8 * s.utilisation + 1.2 * s.hazard_stress + 0.5 * (len(deps_down) - 1)
            # prepositioned fuel/crew slows the drawdown; that is the whole
            # mechanism behind the diesel edge
            rate *= (1.0 - 0.9 * self._prot(nid))
            s.buffer_remaining_s -= self.tick_s * max(rate, 0.0)

    def _stage_restore(self) -> None:
        for nid, s in self.world.nodes.items():
            if s.is_up or s.restore_at is None or self.world.t < s.restore_at:
                continue
            if any(not self.world.nodes[d].is_up for d in self.ix.depends_on.get(nid, [])):
                continue  # cannot come back while a dependency is still down
            s.status = Status.RESTORED
            s.load = s.initial_load
            s.buffer_remaining_s = s.buffer_s
            s.drawing_down = False
            s.restore_at = None
            self._emit(nid, "restored", 0.0, None)

    # ------------------------------------------------------------------ run

    def run(self, horizon_s: float) -> list[Event]:
        n_ticks = int(horizon_s / self.tick_s)
        # one field for the whole run, from the scenario seed only
        self._field = np.random.default_rng(self.seed_value).random(
            (n_ticks, len(self._nidx), 4)
        )
        for tick in range(n_ticks):
            self._tick = tick
            self.world.t = tick * self.tick_s
            self._stage_hazard(tick)
            self._stage_direct()
            self._stage_overload()
            self._stage_drawdown()
            self._stage_restore()
        return self.events
