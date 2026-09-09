"""Chains, near-misses and cascades.

A near-miss and a catastrophe are the same stochastic process observed at
different points in its life. They differ only by length. That is the thesis,
encoded as a type.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from contracts.criticality import Damage

CATASTROPHE_HOPS: int = 6
"""At or above this many hops it is a cascade; below it is a near-miss.

Locked at hour 6. Changing it changes every result in the project.
"""

Split = Literal["train", "val", "test"]


class Chain(BaseModel):
    """A maximal sequence of causally-plausible events.

    Built from (a declared dependency edge exists) AND (0 < dt <= W). Nothing
    else. The miner never reads Event.cause — that field exists only so Lane F
    can score how well parentage was recovered, which is the single most
    important diagnostic in the project.
    """

    chain_id: str
    scenario_id: str
    events: list[str] = Field(description="ordered Event.ids")
    hops: int = Field(ge=0)
    layers_crossed: int = Field(ge=0)
    span_s: float = Field(ge=0.0)
    terminated: bool = Field(description="no further propagation within W of the last event")
    damage: Damage

    @property
    def is_cascade(self) -> bool:
        return self.hops >= CATASTROPHE_HOPS

    @property
    def is_near_miss(self) -> bool:
        return not self.is_cascade


class NearMissCorpus(BaseModel):
    corpus_id: str
    city_id: str
    window_s: float = Field(description="W, the causal attribution window. Tuned on TRAIN ONLY.")
    chains: list[Chain]
    split: Split
