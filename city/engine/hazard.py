"""Hazards — exogenous stress that starts cascades.

monsoon_flood is the primary and is anchored to the December 2015 Chennai
event: rain floods low-lying assets, roads become impassable, and crucially the
roads that go first are the ones that carry the diesel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from contracts.city import CityGraph


@dataclass
class HazardField:
    """Per-node exogenous stress in [0, 1] over time."""

    name: str
    stress: dict[str, np.ndarray]  # node_id -> stress per tick
    n_ticks: int

    def at(self, node_id: str, tick: int) -> float:
        arr = self.stress.get(node_id)
        if arr is None or tick >= len(arr):
            return 0.0
        return float(arr[tick])


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def monsoon_flood(g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    """A flood front crossing the city, low-lying assets worst hit.

    Elevation is not in the topology, so latitude stands in as a proxy and is
    labelled as such in LIMITATIONS.md. Roads and substations are the exposed
    classes; a hospital's own building is not directly flooded, which is the
    point — it fails through its dependencies, not from the water.
    """
    rng = _rng(seed)
    lats = np.array([n.lat for n in g.nodes])
    lo, hi = lats.min(), lats.max()
    peak = int(n_ticks * 0.35)
    exposure = {"road_segment": 1.0, "substation": 0.8, "feeder": 0.7,
                "pumping_station": 0.6, "treatment": 0.5, "tower": 0.4}

    stress: dict[str, np.ndarray] = {}
    for n in g.nodes:
        e = exposure.get(n.kind, 0.15)
        # low-lying assets flood earlier and deeper
        low = 1.0 - ((n.lat - lo) / (hi - lo + 1e-9))
        arr = np.zeros(n_ticks)
        for k in range(n_ticks):
            phase = math.exp(-((k - peak) ** 2) / (2 * (n_ticks * 0.18) ** 2))
            arr[k] = e * (0.35 + 0.65 * low) * phase
        arr *= rng.uniform(0.75, 1.25)
        stress[n.id] = np.clip(arr, 0.0, 1.0)
    return HazardField("monsoon_flood", stress, n_ticks)


def heatwave(g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    """Load spike plus transformer derating. Diurnal, peaks each evening."""
    rng = _rng(seed)
    exposure = {"substation": 0.9, "feeder": 0.8, "intertie": 0.6, "pumping_station": 0.4}
    stress: dict[str, np.ndarray] = {}
    ticks_per_day = max(1, n_ticks // 3)
    for n in g.nodes:
        e = exposure.get(n.kind, 0.1)
        k = np.arange(n_ticks)
        diurnal = 0.5 + 0.5 * np.sin(2 * math.pi * (k / ticks_per_day) - math.pi / 2)
        stress[n.id] = np.clip(e * diurnal * rng.uniform(0.8, 1.2), 0.0, 1.0)
    return HazardField("heatwave", stress, n_ticks)


def equipment_age(g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    """Slowly rising background failure intensity.

    This is the hazard that generates the near-miss corpus at scale: lots of
    small independent failures, most of which propagate one or two hops and
    stop. Those truncated chains are the training data.
    """
    rng = _rng(seed)
    stress = {n.id: np.full(n_ticks, rng.uniform(0.03, 0.14)) for n in g.nodes}
    return HazardField("equipment_age", stress, n_ticks)


def cyber(g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    """SCADA and telecom loss without physical damage. Speculative; labelled."""
    rng = _rng(seed)
    onset = int(n_ticks * 0.25)
    stress: dict[str, np.ndarray] = {}
    for n in g.nodes:
        e = 0.9 if n.layer == "telecom" or n.kind == "scada_link" else 0.05
        arr = np.zeros(n_ticks)
        arr[onset:] = e * rng.uniform(0.8, 1.2)
        stress[n.id] = np.clip(arr, 0.0, 1.0)
    return HazardField("cyber", stress, n_ticks)


def none_(g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    """Background only. Needed for the base-rate corpus."""
    return HazardField("none", {n.id: np.full(n_ticks, 0.01) for n in g.nodes}, n_ticks)


HAZARDS = {
    "monsoon_flood": monsoon_flood,
    "heatwave": heatwave,
    "equipment_age": equipment_age,
    "cyber": cyber,
    "none": none_,
}


def build(name: str, g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    return HAZARDS[name](g, n_ticks, seed)
