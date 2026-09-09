"""The 40-node fixture city.

Hand-checkable, used in every unit test, and deliberately shaped so the demo
cascade exists in miniature:

    power.ss_01 --> water.pump_01 --> water.main_01 --> health.hosp_01
                                                            ^
                              health.hosp_01 runs on generator fuel (buffer),
                              and refuelling depends on transport.road_03.

    power.ss_02 --> residential only. No downstream health node.

ss_01 and ss_02 are given IDENTICAL anomaly scores by the scenario generator.
One has a branching ratio above 1 and one does not. That contrast is the whole
pitch, so it lives in the fixture rather than only in the big city.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from contracts.city import CityGraph, Edge, Node

# Chennai-ish anchor so the fixture renders on the same basemap as the real city.
_LAT0, _LON0 = 13.0827, 80.2707


def _n(
    id: str,
    kind: str,
    dlat: float,
    dlon: float,
    *,
    pop: int = 0,
    weight: float = 1.0,
    buffer_s: float = 0.0,
    capacity: float | None = None,
) -> Node:
    return Node(
        id=id,
        layer=id.split(".", 1)[0],  # type: ignore[arg-type]
        kind=kind,
        lat=_LAT0 + dlat,
        lon=_LON0 + dlon,
        capacity=capacity,
        population_served=pop,
        criticality_weight=weight,
        buffer_s=buffer_s,
    )


def _e(src: str, dst: str, relation: str, delay: float = 0.0) -> Edge:
    return Edge(
        id=f"{src}->{dst}",
        src=src,
        dst=dst,
        relation=relation,  # type: ignore[arg-type]
        nominal_delay_s=delay,
    )


def build() -> CityGraph:
    nodes: list[Node] = [
        # --- power (8) ---
        _n("power.grid_01", "intertie", 0.00, 0.00, capacity=50_000),
        _n("power.ss_01", "substation", 0.01, 0.01, pop=18_000, capacity=12_000),
        _n("power.ss_02", "substation", 0.01, -0.01, pop=16_000, capacity=12_000),
        _n("power.fdr_01", "feeder", 0.02, 0.01, pop=9_000),
        _n("power.fdr_02", "feeder", 0.02, 0.02, pop=9_000),
        _n("power.fdr_03", "feeder", 0.02, -0.01, pop=8_000),
        _n("power.fdr_04", "feeder", 0.02, -0.02, pop=8_000),
        _n("power.gen_01", "diesel_plant", -0.01, 0.00, capacity=2_000),
        # --- water (7) ---
        _n("water.wtp_01", "treatment", 0.03, 0.00, pop=40_000, weight=2.0, capacity=60.0),
        _n("water.pump_01", "pumping_station", 0.03, 0.01, pop=22_000, weight=1.8, capacity=30.0),
        _n("water.pump_02", "pumping_station", 0.03, -0.01, pop=18_000, weight=1.8, capacity=25.0),
        _n("water.res_01", "reservoir", 0.04, 0.00, buffer_s=10_800.0, capacity=500.0),
        _n("water.main_01", "trunk_main", 0.035, 0.015, pop=12_000),
        _n("water.main_02", "trunk_main", 0.035, -0.015, pop=10_000),
        _n("water.main_03", "trunk_main", 0.045, 0.005, pop=8_000),
        # --- transport (10) ---
        *[
            _n(f"transport.road_{i:02d}", "road_segment", 0.005 * i, 0.004 * (i % 5) - 0.008)
            for i in range(1, 11)
        ],
        # --- telecom (5) ---
        _n("telecom.tower_01", "tower", 0.015, 0.02, pop=20_000, buffer_s=14_400.0),
        _n("telecom.tower_02", "tower", 0.015, -0.02, pop=18_000, buffer_s=14_400.0),
        _n("telecom.tower_03", "tower", 0.045, 0.01, pop=15_000, buffer_s=10_800.0),
        _n("telecom.bh_01", "backhaul", 0.02, 0.00, buffer_s=21_600.0),
        _n("telecom.scada_01", "scada_link", 0.03, 0.005),
        # --- health (5) ---
        _n("health.hosp_01", "hospital", 0.04, 0.02, pop=6_000, weight=5.0, buffer_s=21_600.0),
        _n("health.hosp_02", "hospital", 0.04, -0.02, pop=5_000, weight=5.0, buffer_s=28_800.0),
        _n("health.phc_01", "primary_care", 0.05, 0.01, pop=2_000, weight=2.5, buffer_s=7_200.0),
        _n("health.gen_hosp_01", "backup_generator", 0.041, 0.021, weight=4.0, buffer_s=21_600.0),
        _n("health.gen_hosp_02", "backup_generator", 0.041, -0.021, weight=4.0, buffer_s=28_800.0),
    ]

    edges: list[Edge] = [
        # power distribution (flow)
        _e("power.ss_01", "power.grid_01", "flow"),
        _e("power.ss_02", "power.grid_01", "flow"),
        _e("power.fdr_01", "power.ss_01", "flow"),
        _e("power.fdr_02", "power.ss_01", "flow"),
        _e("power.fdr_03", "power.ss_02", "flow"),
        _e("power.fdr_04", "power.ss_02", "flow"),
        # ---- THE CASCADE PATH: ss_01 carries water, which carries the hospital ----
        _e("water.pump_01", "power.fdr_01", "depends_on", 0.0),
        _e("water.wtp_01", "power.fdr_02", "depends_on", 0.0),
        _e("water.main_01", "water.pump_01", "flow", 600.0),
        _e("water.main_03", "water.wtp_01", "flow", 900.0),
        _e("water.res_01", "water.wtp_01", "flow", 1_800.0),
        _e("health.hosp_01", "water.main_01", "depends_on", 7_200.0),
        _e("health.hosp_01", "power.fdr_01", "depends_on", 0.0),
        _e("health.hosp_01", "health.gen_hosp_01", "depends_on", 0.0),
        # ---- THE DIESEL EDGE: the node that killed Chennai was a road ----
        _e("health.gen_hosp_01", "transport.road_03", "depends_on", 21_600.0),
        _e("health.gen_hosp_02", "transport.road_07", "depends_on", 28_800.0),
        # ---- THE DECOY: ss_02 feeds households and nothing else ----
        _e("water.pump_02", "power.fdr_03", "depends_on", 0.0),
        _e("water.main_02", "water.pump_02", "flow", 600.0),
        _e("health.hosp_02", "water.main_02", "depends_on", 10_800.0),
        _e("health.hosp_02", "health.gen_hosp_02", "depends_on", 0.0),
        # telecom
        _e("telecom.tower_01", "power.fdr_02", "depends_on", 0.0),
        _e("telecom.tower_02", "power.fdr_04", "depends_on", 0.0),
        _e("telecom.tower_03", "power.fdr_01", "depends_on", 0.0),
        _e("telecom.bh_01", "power.grid_01", "depends_on", 0.0),
        _e("telecom.tower_01", "telecom.bh_01", "flow"),
        _e("telecom.tower_02", "telecom.bh_01", "flow"),
        _e("telecom.tower_03", "telecom.bh_01", "flow"),
        # SCADA: losing remote control means manual operation, i.e. slower restoration
        _e("telecom.scada_01", "telecom.bh_01", "depends_on", 0.0),
        _e("water.pump_01", "telecom.scada_01", "depends_on", 0.0),
        _e("water.pump_02", "telecom.scada_01", "depends_on", 0.0),
        # roads: crews and fuel travel over them
        *[_e(f"transport.road_{i:02d}", f"transport.road_{i+1:02d}", "flow") for i in range(1, 10)],
        _e("health.phc_01", "transport.road_05", "depends_on", 14_400.0),
        _e("health.phc_01", "power.fdr_02", "depends_on", 0.0),
        _e("power.gen_01", "transport.road_09", "depends_on", 36_000.0),
    ]

    payload = "|".join(sorted(n.id for n in nodes)) + "||" + "|".join(sorted(e.id for e in edges))
    return CityGraph(
        city_id="tiny_v1",
        built_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
        source_hash=hashlib.sha256(payload.encode()).hexdigest()[:16],
        nodes=nodes,
        edges=edges,
    )


if __name__ == "__main__":
    g = build()
    print(f"tiny_v1: {len(g.nodes)} nodes, {len(g.edges)} edges, hash {g.source_hash}")
    for layer in ("power", "water", "transport", "telecom", "health"):
        print(f"  {layer:10s} {sum(1 for n in g.nodes if n.layer == layer):3d}")
    print(f"  dependency edges: {len(g.dependency_edges())}")
    print(f"  cross-layer:      {sum(1 for e in g.edges if e.is_cross_layer)}")
