"""Canonical identity for propagation relations.

A dependency relation has a real `Edge` and uses its id. A flow-sibling
relation does NOT — siblings are peers under a shared parent, with no edge
between them — so it needs a derived id, and every lane must derive it the
same way.

They did not. The estimator wrote `"src~dst"` and the consumer read
`"src->flow_parent"`, so 80% of the propagation mass silently vanished from the
branching ratio and H1 scored exactly chance. One helper, used by both sides.
"""

from __future__ import annotations

from collections import defaultdict

from contracts.city import CityGraph


def sibling_key(src: str, dst: str) -> str:
    return f"sib:{src}->{dst}"


def propagation_targets(graph: CityGraph) -> dict[str, list[tuple[str, str]]]:
    """parent node -> [(child node, relation_key)] for BOTH mechanisms.

    The single source of truth. If the miner, the estimator and the branching
    ratio all call this, they cannot disagree about what an edge is called.
    """
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    flow_out: dict[str, list[str]] = defaultdict(list)
    flow_in: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        if e.relation == "depends_on":
            out[e.dst].append((e.src, e.id))
        else:
            flow_out[e.src].append(e.dst)
            flow_in[e.dst].append(e.src)
    for src, parents in flow_out.items():
        seen: set[str] = set()
        for p in parents:
            for peer in flow_in.get(p, ()):
                if peer != src and peer not in seen:
                    seen.add(peer)
                    out[src].append((peer, sibling_key(src, peer)))
    return out


def key_of(graph: CityGraph, parent_node: str, child_node: str) -> str | None:
    """Relation key for an observed (parent -> child) propagation."""
    for e in graph.edges:
        if e.relation == "depends_on" and e.dst == parent_node and e.src == child_node:
            return e.id
    return sibling_key(parent_node, child_node)


def parent_node_of(graph: CityGraph, key: str) -> str | None:
    if key.startswith("sib:"):
        return key[4:].split("->", 1)[0]
    for e in graph.edges:
        if e.id == key:
            return e.dst if e.relation == "depends_on" else e.src
    return None
