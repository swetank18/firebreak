"""The near-miss miner.

The thesis, as code: a cascade that killed a city and one that stopped after two
hops are the same process observed at different points in its life. The short
ones are abundant and sit unlabelled in operational logs precisely because
nobody was hurt.

A chain is built from exactly two conditions:

    a declared TOPOLOGY relation exists     AND       0 <= dt <= W

where a topology relation is either a dependency edge (i fails, its dependents
are at risk) or a flow-sibling relation (i fails, its load redistributes onto
peers). Both are needed: measured against ground truth, 83% of real propagation
travels through load redistribution and only 17% through dependency edges, so a
miner that sees only dependencies is capped at 17% recall. See docs/FINDINGS.md.

Same-tick propagation is admitted (dt = 0) because load redistribution resolves
within a tick and the median real delay is 0 s. Simultaneous events are ordered
by arrival sequence, which is observable, not ground truth.

Nothing else. This module never sees Event.cause — service/redact.py strips it
and an AST test enforces it. `cause` exists only so Lane F can score how well
parentage was recovered, which is the single most important diagnostic in the
project.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from contracts.chains import CATASTROPHE_HOPS, Chain
from contracts.city import CityGraph
from contracts.criticality import Damage
from contracts.events import Event

DEFAULT_WINDOW_S = 10_800.0  # W. Tuned on TRAIN ONLY. See docs/DECISIONS.md.


@dataclass
class MinedLink:
    """One attributed propagation: parent event -> child event."""

    parent: str
    child: str
    src_node: str
    dst_node: str
    dt: float
    relation: str  # "depends_on" | "flow_sibling" — reported separately by Lane F


class NearMissMiner:
    def __init__(self, graph: CityGraph, window_s: float = DEFAULT_WINDOW_S):
        self.window_s = window_s
        # node -> nodes that depend on it. If i fails, these are at risk.
        self.dependents: dict[str, list[str]] = defaultdict(list)
        # node -> flow peers that absorb its load when it fails.
        flow_out: dict[str, list[str]] = defaultdict(list)
        flow_in: dict[str, list[str]] = defaultdict(list)
        for e in graph.edges:
            if e.relation == "depends_on":
                self.dependents[e.dst].append(e.src)
            else:
                flow_out[e.src].append(e.dst)
                flow_in[e.dst].append(e.src)
        self.siblings: dict[str, list[str]] = {}
        for n in graph.nodes:
            peers: set[str] = set()
            for parent in flow_out.get(n.id, ()):
                peers.update(flow_in.get(parent, ()))
            peers.discard(n.id)
            self.siblings[n.id] = sorted(peers)

    def _candidates(self, node_id: str) -> list[tuple[str, str]]:
        """(target_node, relation) pairs a failure at node_id could propagate to."""
        out = [(d, "depends_on") for d in self.dependents.get(node_id, ())]
        out += [(s, "flow_sibling") for s in self.siblings.get(node_id, ())]
        return out

    def links(self, events: list[Event]) -> list[MinedLink]:
        """Every (parent, child) pair the two conditions admit.

        Deliberately permissive: one parent may claim several children and one
        child may be claimed by several parents. Resolving that ambiguity is
        the next step, and how we resolve it is a measured choice, not an
        assumption.
        """
        fails = sorted([e for e in events if e.kind in ("failed", "degraded")], key=lambda e: e.t)
        by_node: dict[str, list[Event]] = defaultdict(list)
        for e in fails:
            by_node[e.node_id].append(e)

        out: list[MinedLink] = []
        for parent in fails:
            if parent.kind != "failed":
                continue
            for tgt, rel in self._candidates(parent.node_id):
                for child in by_node.get(tgt, ()):
                    dt = child.t - parent.t
                    # dt == 0 is admitted; order simultaneous events by arrival
                    # sequence, which is observable information.
                    if dt < 0 or dt > self.window_s:
                        continue
                    if dt == 0 and child.event_id <= parent.event_id:
                        continue
                    out.append(MinedLink(parent.event_id, child.event_id,
                                         parent.node_id, tgt, dt, rel))
        return out

    def chains(self, events: list[Event], scenario_id: str) -> list[Chain]:
        """Maximal root-to-leaf paths through the attributed forest.

        Ambiguity rule: a child is attributed to its NEAREST-IN-TIME admissible
        parent. Recorded as a decision because it is a real choice — the
        alternative (attribute to all, weight by 1/n) is measured in Lane F's
        ablation of the miner.
        """
        links = self.links(events)
        by_id = {e.event_id: e for e in events}

        # Nearest-in-time parent wins; dependency edges break ties against
        # flow siblings, because a dependency is the stronger prior.
        best_parent: dict[str, MinedLink] = {}
        for l in links:
            cur = best_parent.get(l.child)
            if cur is None or (l.dt, l.relation != "depends_on") < (cur.dt, cur.relation != "depends_on"):
                best_parent[l.child] = l

        children: dict[str, list[str]] = defaultdict(list)
        has_parent: set[str] = set()
        for child, l in best_parent.items():
            children[l.parent].append(child)
            has_parent.add(child)

        roots = [
            e.event_id
            for e in events
            if e.kind == "failed" and e.event_id not in has_parent
        ]

        chains: list[Chain] = []
        n = 0

        def walk(node: str, acc: list[str]) -> None:
            nonlocal n
            acc = acc + [node]
            kids = children.get(node, [])
            if not kids:
                if len(acc) >= 2:  # a single event is not a chain
                    evs = [by_id[a] for a in acc if a in by_id]
                    layers = {e.node_id.split(".", 1)[0] for e in evs}
                    n += 1
                    chains.append(
                        Chain(
                            chain_id=f"{scenario_id}-c{n:05d}",
                            scenario_id=scenario_id,
                            events=acc,
                            hops=len(acc) - 1,
                            layers_crossed=len(layers),
                            span_s=(evs[-1].t - evs[0].t) if evs else 0.0,
                            terminated=True,
                            damage=Damage(),
                        )
                    )
                return
            for k in kids:
                walk(k, acc)

        for r in roots:
            walk(r, [])
        return chains


def corpus_stats(chains: list[Chain]) -> dict[str, float]:
    if not chains:
        return {"n": 0}
    near = [c for c in chains if c.is_near_miss]
    casc = [c for c in chains if c.is_cascade]
    hops = [c.hops for c in chains]
    return {
        "n_chains": len(chains),
        "n_near_miss": len(near),
        "n_cascade": len(casc),
        "near_miss_ratio": round(len(near) / len(chains), 4),
        "mean_hops": round(sum(hops) / len(hops), 2),
        "max_hops": max(hops),
        "mean_span_s": round(sum(c.span_s for c in chains) / len(chains), 1),
        "multi_layer_frac": round(sum(1 for c in chains if c.layers_crossed > 1) / len(chains), 4),
        "catastrophe_hops": CATASTROPHE_HOPS,
    }
