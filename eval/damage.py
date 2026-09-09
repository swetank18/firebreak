"""The damage function. ONE definition, imported by everything that reports a number.

Both the ablation and the console export need to turn a scenario into damage.
Two copies of this would be two different headline numbers on the same slide,
and the one on the map would silently stop matching the one in the table.
"""

from __future__ import annotations

from contracts.criticality import Damage


def outage_hours(scen, g) -> dict[str, float]:
    """Hours each asset spent down, from paired failed/restored events.

    Damage used to be `population * 4.0` for anything that failed at all — a
    flat constant that made a node down for twenty minutes cost exactly what a
    node down for three days cost. The engine models restoration, including the
    access penalty that slows every repair while the roads are flooded, so an
    intervention that shortens an outage is doing real work. A constant made
    that work invisible.
    """
    horizon_h = scen.horizon_s / 3600.0
    down_since: dict[str, float] = {}
    hours: dict[str, float] = {}
    for e in sorted(scen.events, key=lambda x: x.t):
        if e.kind == "failed" and e.node_id not in down_since:
            down_since[e.node_id] = e.t
        elif e.kind == "restored" and e.node_id in down_since:
            hours[e.node_id] = hours.get(e.node_id, 0.0) + (e.t - down_since.pop(e.node_id)) / 3600.0
    for nid, t0 in down_since.items():  # still down when the horizon ended
        hours[nid] = hours.get(nid, 0.0) + (scen.horizon_s - t0) / 3600.0
    return {k: min(v, horizon_h) for k, v in hours.items()}


def damage_of(scen, g) -> Damage:
    """Person-hours of lost service, plus hospital-critical hours."""
    pop = {n.id: n.population_served for n in g.nodes}
    layer = {n.id: n.layer for n in g.nodes}
    hours = outage_hours(scen, g)
    ph_power = sum(pop.get(n, 0) * h for n, h in hours.items()
                   if layer.get(n) in ("power", "telecom"))
    ph_water = sum(pop.get(n, 0) * h for n, h in hours.items() if layer.get(n) == "water")
    ph_other = sum(pop.get(n, 0) * h for n, h in hours.items()
                   if layer.get(n) not in ("power", "telecom", "water"))
    return Damage(
        person_hours_no_power=ph_power + 0.6 * ph_other,
        person_hours_no_water=ph_water + 0.4 * ph_other,
        hospital_critical_hours=sum(h for n, h in hours.items() if layer.get(n) == "health"),
        people_affected=sum(pop.get(n, 0) for n in hours),
    )
