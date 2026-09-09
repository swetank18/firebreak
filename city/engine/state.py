"""Node state during a scenario run.

Two things propagate failure, and the engine needs both:

  intra-layer  load redistribution (Motter-Lai). A failed node sheds its load
               onto siblings; capacity = (1 + tolerance) * initial_load. This is
               what makes cascade sizes heavy-tailed, which is the realism gate.

  cross-layer  buffered dependency drawdown. A node whose dependency has failed
               burns its buffer, then degrades, then fails. This is what creates
               lead time, and lead time is what the whole method predicts.

Either mechanism alone gives you a power law with no lead time, or lead time
with no power law.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    OPERATIONAL = "operational"
    DEGRADED = "degraded"
    FAILED = "failed"
    RESTORED = "restored"


@dataclass
class NodeState:
    node_id: str
    layer: str
    status: Status = Status.OPERATIONAL

    capacity: float = 0.0
    load: float = 0.0
    initial_load: float = 0.0

    buffer_s: float = 0.0
    buffer_remaining_s: float = 0.0
    drawing_down: bool = False

    hazard_stress: float = 0.0
    failed_at: float | None = None
    restore_at: float | None = None
    cause_event: str | None = None
    population_served: int = 0
    criticality_weight: float = 1.0

    def __post_init__(self) -> None:
        self.buffer_remaining_s = self.buffer_s

    @property
    def is_up(self) -> bool:
        return self.status in (Status.OPERATIONAL, Status.RESTORED)

    @property
    def utilisation(self) -> float:
        return self.load / self.capacity if self.capacity > 0 else 0.0

    @property
    def susceptibility(self) -> float:
        """s_j(t) in [0, 2] — how stressed this node already is.

        A pure function of observable state, as Lane B requires. This is the
        reason branching ratio is time-dependent and static centrality is not,
        which is the whole argument for why the learned kernel earns its place
        (see docs/01-THESIS.md, "Why this is not just centrality").

        Three observable contributions:
          utilisation      a node at capacity fails from a smaller nudge
          buffer depletion a node already burning its reserve has less runway
          hazard stress    exogenous conditions at this location
        """
        if not self.is_up:
            return 2.0
        util = min(self.utilisation, 1.5) / 1.5
        depleted = 0.0
        if self.buffer_s > 0:
            depleted = 1.0 - (self.buffer_remaining_s / self.buffer_s)
        s = 0.6 + 0.7 * util + 0.5 * depleted + 0.4 * self.hazard_stress
        return max(0.0, min(2.0, s))


@dataclass
class WorldState:
    """Everything mutable in one scenario run."""

    t: float = 0.0
    nodes: dict[str, NodeState] = field(default_factory=dict)
    tick_s: float = 60.0

    def up(self) -> list[str]:
        return [n for n, s in self.nodes.items() if s.is_up]

    def down(self) -> list[str]:
        return [n for n, s in self.nodes.items() if not s.is_up]

    def health_down(self) -> list[str]:
        return [n for n in self.down() if n.startswith("health.")]
