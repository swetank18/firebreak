"""The leakage boundary.

Ground truth must not reach inference or decision code. Two things are stripped:

  Event.cause      the true parent. If the miner sees this it is not mining,
                   it is reading the answer key.
  observed=False   events the real system would never have seen.

This module is worth more than any model in the repo. Everything Lane F
reports is meaningless if it leaks.

Enforced two ways: this function, and an AST test in
service/tests/test_invariants.py asserting `cause` never appears in an
executable line under inference/ or decision/.
"""

from __future__ import annotations

from contracts.events import Event


def redact(events: list[Event]) -> list[Event]:
    """The only form of an event allowed past this boundary."""
    return [e.redacted() for e in events if e.observed]


def observability(events: list[Event]) -> float:
    """Fraction of ground-truth events the system actually gets to see."""
    return sum(1 for e in events if e.observed) / len(events) if events else 0.0
