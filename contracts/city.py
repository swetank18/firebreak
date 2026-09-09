"""The city graph: five layers, flow edges within, dependency edges across."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Layer = Literal["power", "water", "transport", "telecom", "health"]

LAYERS: tuple[Layer, ...] = ("power", "water", "transport", "telecom", "health")


class Node(BaseModel):
    """One asset. Belongs to exactly one layer."""

    id: str = Field(description="'power.ss_042' — the layer prefix is mandatory")
    layer: Layer
    kind: str = Field(description="substation | pump | road_segment | tower | hospital | ...")
    lat: float
    lon: float
    capacity: float | None = Field(
        default=None, description="layer-native units; None for pure topology nodes"
    )
    population_served: int = Field(
        default=0, ge=0, description="0 if it serves no one directly; drives the damage function"
    )
    criticality_weight: float = Field(
        default=1.0, ge=0.0, description="hospitals and water treatment sit above 1.0"
    )
    buffer_s: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "how long this node survives after its dependencies fail — generator fuel, "
            "tank drawdown, battery. Buffers are why lead time exists; without them every "
            "dependency propagates instantly and the project has no reason to exist."
        ),
    )
    protected_class: bool = Field(
        default=False,
        description=(
            "This asset's outage is counted and reported separately — hospitals here, "
            "but a city could mark shelters or schools. CONTRACT AMENDMENT 2026-09-09: "
            "added so the decision layer can weigh a critical facility WITHOUT naming a "
            "layer. `decision/` may not contain the literal 'health', and a string "
            "comparison against a layer couples the engine just as an import would. "
            "See docs/DECISIONS.md."
        ),
    )
    attrs: dict[str, float] = Field(default_factory=dict, description="layer-specific; never read from decision/")

    @field_validator("id")
    @classmethod
    def _layer_prefixed(cls, v: str) -> str:
        head = v.split(".", 1)[0]
        if head not in LAYERS:
            raise ValueError(f"node id must be prefixed with a layer, got {v!r}")
        return v


class Edge(BaseModel):
    """flow = conveyance inside a layer. depends_on = src requires dst to function."""

    id: str
    src: str
    dst: str
    relation: Literal["flow", "depends_on"]
    nominal_delay_s: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "ENGINEERING PRIOR ONLY. A cold-start hint for the decision layer. "
            "The simulator must never read this to generate delays and the kernel must "
            "never recover it — see risk R1. Learned 1/beta correlating above 0.95 with "
            "this field means we fit the config file, not a physical process."
        ),
    )
    attrs: dict[str, float] = Field(default_factory=dict)

    @property
    def is_cross_layer(self) -> bool:
        return self.src.split(".", 1)[0] != self.dst.split(".", 1)[0]


class CityGraph(BaseModel):
    city_id: str
    built_at: datetime
    source_hash: str = Field(description="hash of topology inputs; a change means a new city_id")
    nodes: list[Node]
    edges: list[Edge]

    def node_index(self) -> dict[str, int]:
        return {n.id: i for i, n in enumerate(self.nodes)}

    def dependency_edges(self) -> list[Edge]:
        return [e for e in self.edges if e.relation == "depends_on"]
