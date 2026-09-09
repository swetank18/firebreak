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

# Share of the city, by elevation rank, under water at the flood peak.
FLOOD_PEAK_FRAC = 0.35

# Per-hazard intensity, expressed relative to the monsoon flood.
#
# The flood is the one hazard with a real anchor: December 2015, when roughly a
# third of Chennai was inundated and about 60% of the city lost power. Its
# intensity is 1.0 by definition and `CascadeEngine.IGNITION_RATE_HZ` is
# calibrated against it.
#
# The other four have NO comparable anchor. They are synthetic, and their
# intensities are a judgement call calibrated to a stated operational profile
# rather than to a measured event — see docs/DECISIONS.md and LIMITATIONS.md:
#   equipment_age  a background maintenance rate: many ignitions city-wide,
#                  almost all propagating one or two hops and stopping. This is
#                  the near-miss corpus generator, so it must stay SMALL.
#   heatwave       sustained power stress, contingent outcome.
#   cyber          telecom loss, propagating to water through SCADA.
#   none           base rate only.
INTENSITY = {
    "monsoon_flood": 1.0,
    "heatwave": 0.15,
    "cyber": 0.25,
    "equipment_age": 0.06,
    "none": 0.05,
}


@dataclass
class HazardField:
    """Per-node exogenous stress in [0, 1] over time."""

    name: str
    stress: dict[str, np.ndarray]  # node_id -> stress per tick
    n_ticks: int
    # For hazards that have a physical field behind the stress, the field
    # itself. The flood keeps its water level here so the console can show the
    # water that actually drove the cascade rather than an animation of one.
    # In the same normalised-elevation units as `elevation`.
    level: np.ndarray | None = None
    elevation: dict[str, float] | None = None

    def at(self, node_id: str, tick: int) -> float:
        arr = self.stress.get(node_id)
        if arr is None or tick >= len(arr):
            return 0.0
        return float(arr[tick])


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def monsoon_flood(g: CityGraph, n_ticks: int, seed: int) -> HazardField:
    """An inundation front: the water level rises, peaks, and recedes.

    An asset is stressed only while the water level exceeds its elevation, so
    the hazard has a genuine FOOTPRINT — assets on high ground are never
    touched. The previous version gave every asset in the city at least 35% of
    its exposure for the whole event, which meant a flood behaved like a
    city-wide degradation and every scenario ended in total collapse. A flood
    inundates a region. See docs/FINDINGS.md.

    Elevation is not in the topology, so latitude stands in as a proxy and is
    labelled as such in LIMITATIONS.md. Roads and substations are the exposed
    classes; a hospital's own building is not directly flooded, which is the
    point — it fails through its dependencies, not from the water.
    """
    rng = _rng(seed)
    lats = np.array([n.lat for n in g.nodes])
    lo, hi = lats.min(), lats.max()
    peak = int(n_ticks * 0.35)
    sigma = n_ticks * 0.18
    exposure = {"road_segment": 1.0, "substation": 0.8, "feeder": 0.7,
                "pumping_station": 0.6, "treatment": 0.5, "tower": 0.4}

    # Fraction of the city (by elevation rank) under water at the peak.
    # Anchored to December 2015, when roughly a third of Chennai was inundated.
    peak_level = FLOOD_PEAK_FRAC * rng.uniform(0.85, 1.15)
    level = peak_level * np.exp(-((np.arange(n_ticks) - peak) ** 2) / (2 * sigma**2))

    stress: dict[str, np.ndarray] = {}
    elevation: dict[str, float] = {}
    for n in g.nodes:
        e = exposure.get(n.kind, 0.15)
        elev = (n.lat - lo) / (hi - lo + 1e-9)          # 0 = lowest ground
        depth = np.clip(level - elev, 0.0, None)        # zero outside the footprint
        stress[n.id] = np.clip(e * (depth / max(peak_level, 1e-9)) * rng.uniform(0.75, 1.25),
                               0.0, 1.0)
        elevation[n.id] = float(elev)
    return HazardField("monsoon_flood", stress, n_ticks, level=level, elevation=elevation)


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
    """Build a hazard field and apply its intensity relative to the flood."""
    f = HAZARDS[name](g, n_ticks, seed)
    k = INTENSITY.get(name, 1.0)
    if k != 1.0:
        f.stress = {nid: arr * k for nid, arr in f.stress.items()}
    return f
