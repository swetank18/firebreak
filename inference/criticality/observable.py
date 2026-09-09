"""Reconstruct node state from the event stream alone.

The inference layer cannot see the engine's internals — it sees the same thing
a control room sees: a sequence of alarms. So susceptibility has to be computed
from that, and this module is the honest version of `NodeState.susceptibility`.

Three observable contributions, matching the contract:
  degraded    the node has announced it is drawing down a reserve
  dependency  how many of its dependencies are currently down
  recency     how much alarm activity it has seen lately
"""

from __future__ import annotations

from collections import defaultdict, deque

from city.engine.state import NodeState, Status, WorldState
from contracts.city import CityGraph
from contracts.events import Event

RECENCY_WINDOW_S = 3_600.0


class ObservableState:
    """Replays observed events and answers "what did we know at time t"."""

    def __init__(self, graph: CityGraph):
        self.graph = graph
        self.depends_on: dict[str, list[str]] = defaultdict(list)
        for e in graph.edges:
            if e.relation == "depends_on":
                self.depends_on[e.src].append(e.dst)
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self.world = WorldState()
        for n in graph.nodes:
            self.world.nodes[n.id] = NodeState(
                node_id=n.id, layer=n.layer, capacity=1.0, load=0.0,
                initial_load=0.0, buffer_s=n.buffer_s,
                population_served=n.population_served,
                criticality_weight=n.criticality_weight,
            )

    def apply(self, e: Event) -> None:
        st = self.world.nodes.get(e.node_id)
        if st is None:
            return
        self.world.t = e.t
        if e.kind == "failed":
            st.status = Status.FAILED
        elif e.kind == "degraded":
            st.status = Status.DEGRADED
            st.drawing_down = True
        elif e.kind == "restored":
            st.status = Status.RESTORED
            st.drawing_down = False
            st.buffer_remaining_s = st.buffer_s
        q = self._recent[e.node_id]
        q.append(e.t)
        while q and q[0] < e.t - RECENCY_WINDOW_S:
            q.popleft()

    def susceptibility(self, node_id: str) -> float:
        """s_j(t) in [0, 2], from observables only."""
        st = self.world.nodes.get(node_id)
        if st is None:
            return 1.0
        if not st.is_up:
            return 2.0
        deps = self.depends_on.get(node_id, [])
        dep_down = (
            sum(1 for d in deps if not self.world.nodes[d].is_up) / len(deps) if deps else 0.0
        )
        drawing = 1.0 if st.drawing_down else 0.0
        churn = min(len(self._recent.get(node_id, ())), 5) / 5.0
        s = 0.6 + 0.8 * dep_down + 0.4 * drawing + 0.2 * churn
        return max(0.0, min(2.0, s))

    def sync(self) -> WorldState:
        """Push observable susceptibility into the world so BranchingRatio reads it."""
        for nid, st in self.world.nodes.items():
            s = self.susceptibility(nid)
            # encode via load/capacity so NodeState.susceptibility reproduces it
            st.capacity = 1.0
            st.load = max(0.0, (s - 0.6 - (0.5 if st.drawing_down else 0.0)) / 0.7) * 1.5
        return self.world


class _DirectWorld(WorldState):
    pass
