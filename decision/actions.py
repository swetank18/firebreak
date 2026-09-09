"""The action space, as matrix surgery on the propagation kernel.

An intervention is a change to how failure travels. Each kind is one edit to A:

  isolate      cut a node's outgoing propagation entirely      row -> 0
  harden       make a node harder to knock over                col *= (1-m)
  reroute      remove one specific dependency                  cell -> 0
  preposition  refill a buffer, so the node resists longer     col *= (1-m), buffered only
  shed         controlled partial curtailment                  row *= (1-m)

`preposition` is the demo action: it is what the diesel edge demands, and it is
the one a human operator does not reach for, because the instinct is to protect
the important asset rather than the thing that supplies it.
"""

from __future__ import annotations

import json
import pathlib

from scipy.sparse import csr_matrix

from contracts.decision import Action, ActionKind

_COSTS = json.loads((pathlib.Path(__file__).parent.parent / "contracts" / "costs.json").read_text())


def cost_of(kind: ActionKind) -> tuple[float, float]:
    c = _COSTS[kind]
    return float(c["cost"]), float(c["lead_time_s"])


def make(kind: ActionKind, target: str, magnitude: float = 1.0) -> Action:
    cost, lead = cost_of(kind)
    return Action(kind=kind, target=target, magnitude=magnitude, cost=cost, lead_time_s=lead)


def apply(A: csr_matrix, action: Action, idx: dict[str, int]) -> csr_matrix:
    """Return a modified propagation matrix. Never mutates the original."""
    M = A.copy().tolil()
    m = action.magnitude

    if action.kind == "reroute":
        src, _, dst = action.target.partition("->")
        i, j = idx.get(src), idx.get(dst)
        if i is not None and j is not None:
            M[i, j] = 0.0
        return M.tocsr()

    i = idx.get(action.target)
    if i is None:
        return A

    if action.kind == "isolate":
        M[i, :] = 0.0
    elif action.kind == "shed":
        M[i, :] = M[i, :].multiply(1.0 - m)
    elif action.kind in ("harden", "preposition"):
        col = M[:, i].multiply(1.0 - m)
        M[:, i] = col
    return M.tocsr()


def candidates(
    graph_nodes, idx: dict[str, int], seeds: list[str], reach_hint, *, top_k: int = 24,
    kinds: tuple[str, ...] | None = None, exclude: frozenset[str] = frozenset(),
) -> list[Action]:
    """Propose a small, sensible action set.

    Enumerating every action on every node is 5n and pointless — almost all of
    them touch nodes the cascade will never reach. Propose against the nodes
    the rollout says are actually exposed.

    `exclude` drops nodes that are ALREADY DOWN. Hardening an asset that failed
    an hour ago does nothing, and it used to win the ranking anyway: `isolate`
    is the cheapest action, benefit is divided by cost, so the search spent four
    of its five picks isolating assets that had already failed. See
    docs/FINDINGS.md.

    `kinds` restricts the action space to what the evaluating simulator can
    actually apply. Scoring an action the environment cannot represent, and then
    applying a different one, measures nothing.
    """
    out: list[Action] = []
    want = (lambda k: True) if kinds is None else (lambda k: k in kinds)
    ranked = sorted(reach_hint.items(), key=lambda kv: -kv[1])[:top_k]
    for node_id, _ in ranked:
        n = graph_nodes.get(node_id)
        if n is None or node_id in exclude:
            continue
        if want("isolate"):
            out.append(make("isolate", node_id, 1.0))
        if want("harden"):
            out.append(make("harden", node_id, 0.7))
        if want("preposition") and n.buffer_s > 0:
            # only meaningful where there is a reserve to refill
            out.append(make("preposition", node_id, 0.85))
        if want("shed") and n.population_served > 0:
            out.append(make("shed", node_id, 0.5))
    if want("isolate"):
        for s in seeds:
            if s not in exclude:
                out.append(make("isolate", s, 1.0))
    # de-duplicate, keep order
    seen, uniq = set(), []
    for a in out:
        k = (a.kind, a.target)
        if k not in seen:
            seen.add(k)
            uniq.append(a)
    return uniq
