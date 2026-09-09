"""Events — the unit everything downstream is built from."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EventKind = Literal["anomaly", "degraded", "failed", "restored"]


class Event(BaseModel):
    """One observation on one node at one time.

    Two fields are GROUND TRUTH ONLY and must be stripped by platform/redact.py
    before any inference or decision code sees them: `cause`, and rows with
    `observed=False`. This is the leakage boundary and it is worth more than any
    model in the repo.
    """

    event_id: str
    node_id: str
    t: float = Field(description="seconds since scenario epoch; float, not datetime")
    kind: EventKind
    severity: float = Field(ge=0.0, le=1.0, description="layer-normalised")
    anomaly_score: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "output of the commodity per-stream detector. This is deliberately the whole "
            "of baseline arm A1. Improving it strengthens our own baseline for no gain — "
            "no lane spends time here."
        ),
    )
    observed: bool = Field(default=True, description="False => ground truth only, invisible to the system")
    cause: str | None = Field(
        default=None,
        description="GROUND TRUTH parent event_id. NEVER visible to inference/ or decision/.",
    )

    def redacted(self) -> "Event":
        """The only form allowed past the platform boundary."""
        return self.model_copy(update={"cause": None})
