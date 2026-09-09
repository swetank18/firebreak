"""Criticality — the danger criterion — and the damage function."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

_WEIGHTS_PATH = Path(__file__).parent / "weights.json"


class Damage(BaseModel):
    """Never collapse to rupees.

    A synthetic money figure is the fastest way to lose a judge who works in
    infrastructure. Report the vector; derive one scalar for ranking from
    versioned weights that appear on a slide.
    """

    person_hours_no_power: float = Field(default=0.0, ge=0.0)
    person_hours_no_water: float = Field(default=0.0, ge=0.0)
    hospital_critical_hours: float = Field(
        default=0.0, ge=0.0, description="facility-hours where a health node lost power OR water"
    )
    people_affected: int = Field(default=0, ge=0)

    def headline(self) -> float:
        """Single scalar for ranking. Weights are versioned and go on a slide.

        A judge is allowed to disagree with our weights. They are not allowed to
        discover we hid them.
        """
        w = _load_weights()
        return (
            w["person_hours_no_power"] * self.person_hours_no_power
            + w["person_hours_no_water"] * self.person_hours_no_water
            + w["hospital_critical_hours"] * self.hospital_critical_hours
        )

    def __add__(self, other: "Damage") -> "Damage":
        return Damage(
            person_hours_no_power=self.person_hours_no_power + other.person_hours_no_power,
            person_hours_no_water=self.person_hours_no_water + other.person_hours_no_water,
            hospital_critical_hours=self.hospital_critical_hours + other.hospital_critical_hours,
            people_affected=self.people_affected + other.people_affected,
        )


def _load_weights() -> dict[str, float]:
    return json.loads(_WEIGHTS_PATH.read_text())


class Criticality(BaseModel):
    """Why one alarm matters and an identical-scoring one does not."""

    node_id: str
    t: float
    branching_ratio: float = Field(
        ge=0.0,
        description=(
            "n_i = sum_j alpha_ij * s_j(t). THE HEADLINE NUMBER. Above 1.0 the cascade "
            "grows; below it dies. This is the whole answer to 'distinguish normal "
            "abnormality from dangerous abnormality'."
        ),
    )
    p_cascade: float = Field(ge=0.0, le=1.0, description="P(chain from here reaches CATASTROPHE_HOPS)")
    expected_reach: float = Field(ge=0.0, description="E[nodes failed]")
    expected_damage: Damage
    time_to_critical_s: float | None = Field(
        default=None, description="None if it never goes critical within the horizon"
    )
    ci_low: float = Field(description="bootstrap CI on branching_ratio")
    ci_high: float
    n_rollouts: int = Field(ge=0)

    DANGER_THRESHOLD: float = 1.0

    @property
    def is_dangerous(self) -> bool:
        return self.branching_ratio > 1.0
