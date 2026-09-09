"""Ground-truth chain reconstruction.

This module is allowed to read Event.cause because it produces the LABELS that
Lane F scores the miner against. The miner in inference/ has no access to it —
that boundary is enforced by service/redact.py and an AST test.
"""

from __future__ import annotations

from collections import defaultdict

from contracts.events import Event


def true_chains(events: list[Event]) -> list[list[str]]:
    """Every root-to-leaf path through the ground-truth causal forest."""
    by_id = {e.event_id: e for e in events}
    children: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []
    for e in events:
        if e.kind != "failed":
            continue
        if e.cause and e.cause in by_id:
            children[e.cause].append(e.event_id)
        else:
            roots.append(e.event_id)

    paths: list[list[str]] = []

    def walk(node: str, acc: list[str]) -> None:
        acc = acc + [node]
        kids = children.get(node, [])
        if not kids:
            paths.append(acc)
            return
        for k in kids:
            walk(k, acc)

    for r in roots:
        walk(r, [])
    return paths


def longest_chain_hops(events: list[Event]) -> int:
    paths = true_chains(events)
    return max((len(p) - 1 for p in paths), default=0)


def cascade_sizes(events: list[Event]) -> list[int]:
    """Size of each causal tree — the distribution the realism gate tests.

    Historical blackout data shows cascade sizes follow a heavy-tailed power
    law. If ours does not, the simulator does not behave like real
    infrastructure and no result above it transfers.
    """
    by_id = {e.event_id: e for e in events}
    children: dict[str, list[str]] = defaultdict(list)
    roots: list[str] = []
    for e in events:
        if e.kind != "failed":
            continue
        if e.cause and e.cause in by_id:
            children[e.cause].append(e.event_id)
        else:
            roots.append(e.event_id)

    sizes = []
    for r in roots:
        seen, stack = set(), [r]
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(children.get(n, []))
        sizes.append(len(seen))
    return sizes
