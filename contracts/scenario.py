"""Scenarios — the replay format.

Everything the console renders and everything the evaluation scores is a
scenario file. Deterministic, seeded, byte-identical across runs.

The renderer computes nothing. If the console needs a number it is a field
here, not a calculation in TypeScript.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from contracts.decision import Decision
from contracts.events import Event

Hazard = Literal["monsoon_flood", "heatwave", "equipment_age", "cyber", "none"]

ARMS = ("A0", "A1", "A2", "A3", "A4", "A5", "A6")
ARM_LABELS = {
    "A0": "do nothing",
    "A1": "rank by anomaly score",
    "A2": "+ static centrality",
    "A3": "+ learned kernel (branching ratio)",
    "A4": "+ counterfactual intervention search",
    "A5": "I3 (Tsinghua, published SOTA)",
    "A6": "oracle (perfect foresight)",
}


class ScenarioSummary(BaseModel):
    scenario_id: str
    city_id: str
    seed: int
    hazard: Hazard
    arm: str
    n_events: int
    n_decisions: int
    max_hops: int
    horizon_s: float


class Scenario(BaseModel):
    scenario_id: str
    city_id: str
    seed: int
    hazard: Hazard
    horizon_s: float = Field(default=259200.0, description="72 hours")
    tick_s: float = Field(default=60.0)
    events: list[Event] = Field(description="ground truth, full — redact before inference")
    decisions: list[Decision] = Field(default_factory=list, description="empty for arm A0")
    arm: str
    metadata: dict[str, str] = Field(
        default_factory=dict, description="git sha, contracts version, wall clock, host"
    )
