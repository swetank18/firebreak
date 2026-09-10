"""Export a MATRIX of scenarios, so the operator dashboard has something to control.

The console replays one frozen scenario. An operator picks the situation: which
hazard, which seed, how big a budget, how late the call is made. On a static
host we cannot run the engine, so the reachable combinations are precomputed
here and the dashboard loads them. `service/api.py` runs the same thing live
when there is a Python process available, and the dashboard prefers it.

The city itself is written once and shared; only what differs per scenario is
written per scenario.
"""
from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import numpy as np

from city.engine import hazard as hz
from city.engine import runner
from city.engine.chains import true_chains
from city.topology import chennai
from decision.search import InterventionSearch
from eval.damage import damage_of
from inference.criticality.branching import BranchingRatio
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from service.redact import redact

OUT = Path("www/ops/data")
TICK = 300.0
BUDGET = 5
PROTECT = 0.9
HAZARDS = ["monsoon_flood", "heatwave", "cyber", "equipment_age"]
SEEDS = [90_105, 90_210, 90_311]
DECIDE_FRACS = [0.25]


def _summary(scen, g):
    d = damage_of(scen, g)
    hosp = {n.id for n in g.nodes if n.kind == "hospital"}
    health = {n.id for n in g.nodes if n.layer == "health"}
    failed = {e.node_id for e in scen.events if e.kind == "failed"}
    return {"assets_failed": len(failed), "hospitals_hit": len(failed & hosp),
            "health_hit": len(failed & health), "people": d.people_affected,
            "person_hours": round(d.person_hours_no_power + d.person_hours_no_water, 1),
            "hospital_hours": round(d.hospital_critical_hours, 1),
            "headline": round(d.headline(), 1)}


def _timeline(scen, g, br):
    """Alerts as an operator sees them, plus the outcome they cannot see.

    `h` is ground truth: did a chain from this failure go on to reach the health
    layer? It is what makes the dashboard's hindsight toggle mean something —
    without it there is no way to show that ranking by danger puts the alarms
    that mattered at the top. It is labelled as hindsight in the UI.
    """
    by_id = {e.event_id: e for e in scen.events}
    reach, health = {}, {}
    for path in true_chains(scen.events):
        for i, eid in enumerate(path):
            if eid not in by_id:
                continue
            nid = by_id[eid].node_id
            tail = {by_id[x].node_id for x in path[i + 1:] if x in by_id}
            reach[nid] = max(reach.get(nid, 0), len(tail))
            if any(x.startswith("health.") for x in tail):
                health[nid] = 1

    obs = ObservableState(g)
    out, seen = [], set()
    for e in sorted(redact(scen.events), key=lambda x: x.t):
        if e.kind == "failed" and e.node_id not in seen:
            seen.add(e.node_id)
            out.append({"n": e.node_id, "t": int(e.t), "s": round(e.anomaly_score, 3),
                        "br": round(br.of(e.node_id, obs.sync()), 3),
                        "r": reach.get(e.node_id, 0), "h": health.get(e.node_id, 0)})
        obs.apply(e)
    return out


def _one(args) -> tuple[str, dict]:
    hazard, seed, frac, kernel = args
    g = chennai.build()
    br = BranchingRatio(g, kernel)
    base = runner.run(g, hazard, seed=seed, tick_s=TICK)
    t_dec = base.horizon_s * frac

    seen = [e for e in sorted(redact(base.events), key=lambda x: x.t) if e.t <= t_dec]
    obs = ObservableState(g)
    for e in seen:
        obs.apply(e)
    s_vec = np.array([obs.susceptibility(n.id) for n in g.nodes])
    down = {e.node_id for e in seen if e.kind == "failed"}
    live = list(dict.fromkeys([e.node_id for e in seen if e.kind == "failed"][-25:]))

    ids = {n.id for n in g.nodes}
    fb_targets, dec = [], None
    if live:
        srch = InterventionSearch(g, kernel, n_rollouts=400,
                                  kinds=("harden", "preposition"), top_k=60)
        dec = srch.decide(base.scenario_id, t_dec, live, s_vec, [], seed=seed,
                          top_n=BUDGET * 4, already_failed=down, keep_nonpositive=True,
                          horizon_s=base.horizon_s - t_dec)
        ranked = sorted(dec.ranked, key=lambda iv: -iv.damage_prevented_headline)
        fb_targets = list(dict.fromkeys(
            iv.action.target for iv in ranked if iv.action.target in ids))[:BUDGET]

    hosp_rank = sorted((n for n in g.nodes if n.layer == "health"),
                       key=lambda n: -(n.criticality_weight * max(n.population_served, 1)))
    hu_targets = [n.id for n in hosp_rank[:BUDGET]]

    runs = {"do_nothing": base}
    if fb_targets:
        runs["firebreak"] = runner.run(g, hazard, seed=seed, tick_s=TICK,
                                       protected={n: PROTECT for n in fb_targets},
                                       protect_at_s=t_dec)
    runs["human"] = runner.run(g, hazard, seed=seed, tick_s=TICK,
                               protected={n: PROTECT for n in hu_targets},
                               protect_at_s=t_dec)

    n_ticks = int(base.horizon_s / TICK)
    field = hz.build(hazard, g, n_ticks, seed)
    lvl = field.level if field.level is not None else np.zeros(n_ticks)
    step = max(1, n_ticks // 180)

    top = None
    if dec and dec.ranked:
        top = sorted(dec.ranked, key=lambda iv: -iv.damage_prevented_headline)[0]

    key = f"{hazard}-s{seed}-d{int(frac * 100)}"
    return key, {
        "key": key, "hazard": hazard, "seed": seed, "decide_frac": frac,
        "horizon_s": base.horizon_s, "t_decide_s": t_dec,
        "runs": {k: {"timeline": _timeline(v, g, br), "summary": _summary(v, g)}
                 for k, v in runs.items()},
        "flood": {"level": [round(float(v), 4) for v in lvl[::step]],
                  "dt_s": step * TICK, "peak": round(float(lvl.max()), 4)},
        "intervention": {
            "targets": fb_targets,
            "kind": top.action.kind if top else None,
            "cost": round(sum(iv.action.cost for iv in
                              sorted(dec.ranked, key=lambda i: -i.damage_prevented_headline)[:BUDGET]), 1)
                    if dec and dec.ranked else 0,
            "deadline_s": round(top.deadline_s, 1) if top else 0.0,
            "rationale": top.rationale if top else [],
            "compute_ms": round(dec.compute_ms, 1) if dec else 0.0,
        },
        "human_action": {"targets": hu_targets},
        "observed_at_decision": len(seen),
        "down_at_decision": len(down),
    }


def main() -> int:
    g = chennai.build()
    print("fitting the kernel once, shared across the matrix...")
    tr = [runner.run(g, h, seed=s, tick_s=TICK)
          for h in ("monsoon_flood", "equipment_age") for s in range(6)]
    kernel = counting.fit(g, [redact(s.events) for s in tr],
                          horizon_s=259_200.0 * len(tr), corpus_id="matrix", seed=0)
    print(f"  {len(kernel.edges)} edges, rho={kernel.spectral_radius:.3f}")

    OUT.mkdir(parents=True, exist_ok=True)
    nidx = {n.id: i for i, n in enumerate(g.nodes)}
    lats = [n.lat for n in g.nodes]
    lo, hi = min(lats), max(lats)
    (OUT / "city.json").write_text(json.dumps({
        "city": g.city_id,
        "nodes": [{"id": n.id, "l": n.layer, "k": n.kind,
                   "lat": round(n.lat, 5), "lon": round(n.lon, 5),
                   "pop": n.population_served, "buf": int(n.buffer_s),
                   "e": round((n.lat - lo) / (hi - lo + 1e-9), 4)} for n in g.nodes],
        "deps": [{"s": e.src, "d": e.dst} for e in g.edges if e.relation == "depends_on"],
        "flow": [[nidx[e.src], nidx[e.dst]] for e in g.edges if e.relation == "flow"],
        "stats": {"nodes": len(g.nodes), "edges": len(g.edges),
                  "kernel_edges": len(kernel.edges),
                  "rho": round(kernel.spectral_radius, 3)},
    }, separators=(",", ":")))

    jobs = [(h, s, f, kernel) for h in HAZARDS for s in SEEDS for f in DECIDE_FRACS]
    print(f"running {len(jobs)} scenarios x 3 counterfactuals...")
    with mp.Pool(min(mp.cpu_count(), 12)) as pool:
        results = pool.map(_one, jobs, chunksize=1)

    index = []
    for key, payload in results:
        (OUT / f"{key}.json").write_text(json.dumps(payload, separators=(",", ":")))
        s0 = payload["runs"]["do_nothing"]["summary"]
        index.append({"key": key, "hazard": payload["hazard"], "seed": payload["seed"],
                      "decide_frac": payload["decide_frac"],
                      "assets_failed": s0["assets_failed"],
                      "hospitals_hit": s0["hospitals_hit"], "people": s0["people"],
                      "headline": s0["headline"],
                      "has_action": bool(payload["intervention"]["targets"])})
    index.sort(key=lambda r: (r["hazard"], r["seed"]))
    (OUT / "index.json").write_text(json.dumps(
        {"scenarios": index, "budget": BUDGET, "protect": PROTECT,
         "generated_from": "scripts/export_matrix.py"}, indent=1))

    print(f"\n{'scenario':34} {'assets':>7} {'hosp':>5} {'people':>10} {'action':>7}")
    for r in index:
        print(f"{r['key']:34} {r['assets_failed']:7d} {r['hospitals_hit']:5d} "
              f"{r['people']:10,d} {'yes' if r['has_action'] else 'none':>7}")
    print(f"\nwrote {len(index)} scenarios to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
