"""Run a scenario and emit the replay artefact.

Deterministic: same seed + same city + same arm produces byte-identical output.
Without that, the paired statistics in the ablation are not paired.
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone

from city.engine import hazard as hz
from city.engine.cascade import CascadeEngine
from contracts import CONTRACTS_VERSION
from contracts.city import CityGraph
from contracts.scenario import Scenario, ScenarioSummary

log = logging.getLogger(__name__)

HORIZON_S = 259_200.0  # 72 hours
TICK_S = 60.0


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        return "unknown"


def run(
    g: CityGraph,
    hazard_name: str = "monsoon_flood",
    seed: int = 0,
    arm: str = "A0",
    horizon_s: float = HORIZON_S,
    tick_s: float = TICK_S,
    protected: dict[str, float] | None = None,
    protect_at_s: float = 0.0,
) -> Scenario:
    n_ticks = int(horizon_s / tick_s)
    field = hz.build(hazard_name, g, n_ticks, seed)
    scenario_id = f"{g.city_id}-{hazard_name}-{arm}-s{seed}"
    engine = CascadeEngine(g, field, seed=seed, tick_s=tick_s,
                           protected=protected, protect_at_s=protect_at_s,
                           event_prefix=f"{scenario_id}/")
    t0 = time.perf_counter()
    events = engine.run(horizon_s)
    # The correlation id every downstream record carries. Silent unless an entry
    # point has called service.obs.configure().
    log.info("scenario.run", extra={
        "scenario_id": scenario_id, "city_id": g.city_id, "hazard": hazard_name,
        "seed": seed, "arm": arm, "n_events": len(events),
        "n_protected": len(protected or {}), "elapsed_ms": (time.perf_counter() - t0) * 1000.0,
    })

    return Scenario(
        scenario_id=scenario_id,
        city_id=g.city_id,
        seed=seed,
        hazard=hazard_name,  # type: ignore[arg-type]
        horizon_s=horizon_s,
        tick_s=tick_s,
        events=events,
        decisions=[],
        arm=arm,
        metadata={
            "git_sha": _git_sha(),
            "contracts_version": CONTRACTS_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def summarise(s: Scenario) -> ScenarioSummary:
    from city.engine.chains import longest_chain_hops

    return ScenarioSummary(
        scenario_id=s.scenario_id,
        city_id=s.city_id,
        seed=s.seed,
        hazard=s.hazard,
        arm=s.arm,
        n_events=len(s.events),
        n_decisions=len(s.decisions),
        max_hops=longest_chain_hops(s.events),
        horizon_s=s.horizon_s,
    )
