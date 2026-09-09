"""WebSocket frames pushed during live replay.

Bounded queue with backpressure. On overflow drop `criticality` frames and
never `decision` frames — a console that silently misses a decision is worse
than one that stutters.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from contracts.criticality import Criticality
from contracts.decision import Decision
from contracts.events import Event


class TickFrame(BaseModel):
    type: Literal["tick"] = "tick"
    seq: int
    t: float
    events: list[Event]


class CriticalityFrame(BaseModel):
    type: Literal["criticality"] = "criticality"
    seq: int
    t: float
    items: list[Criticality]


class DecisionFrame(BaseModel):
    type: Literal["decision"] = "decision"
    seq: int
    decision: Decision


class DoneFrame(BaseModel):
    type: Literal["done"] = "done"
    seq: int
    scenario_id: str


Frame = Annotated[
    Union[TickFrame, CriticalityFrame, DecisionFrame, DoneFrame],
    Field(discriminator="type"),
]
