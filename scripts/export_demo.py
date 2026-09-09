"""Export the demo scenario for the console. THE RENDERER COMPUTES NOTHING.

Three runs of the SAME seed with the SAME paired randomness, which is what
makes them a true rewind rather than three unrelated simulations:

  do_nothing  the cascade as it happens
  firebreak   the intervention the decision layer chose, applied at t_decide
  human       the human-obvious action — harden the most critical asset —
              at the SAME budget

Beat 5 of the runbook requires the human-obvious action to FAIL to stop the
cascade. That is asserted here and in service/tests/test_demo_beats.py; if a
change ever makes it succeed, the demo's whole contrast is gone and we want to
find out from CI rather than on stage.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from city.engine import runner
from city.engine.chains import true_chains
from city.topology import chennai
from decision.search import InterventionSearch
from eval.damage import damage_of
from inference.criticality.branching import BranchingRatio
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from service.redact import redact

OUT = Path("console/data")
TICK = 300.0
BUDGET = 5             # same budget for Firebreak and for the human
PROTECT = 0.9
DECIDE_AT_FRAC = 0.25
CANDIDATE_SEEDS = [90_100 + i for i in range(8)]


def _timeline(scen, g, br, kernel):
    """First failure per node, with the branching ratio as it was at that moment."""
    obs = ObservableState(g)
    first, n_at = {}, {}
    for e in sorted(redact(scen.events), key=lambda x: x.t):
        if e.kind == "failed" and e.node_id not in first:
            first[e.node_id] = {"t": e.t, "score": round(e.anomaly_score, 3)}
            n_at[e.node_id] = round(br.of(e.node_id, obs.sync()), 3)
        obs.apply(e)

    by_id = {e.event_id: e for e in scen.events}
    reach, health_hit = {}, {}
    for path in true_chains(scen.events):
        for i, eid in enumerate(path):
            if eid not in by_id:
                continue
            nid = by_id[eid].node_id
            tail = {by_id[x].node_id for x in path[i + 1:] if x in by_id}
            reach[nid] = max(reach.get(nid, 0), len(tail))
            if any(x.startswith("health.") for x in tail):
                health_hit[nid] = 1
    return sorted(
        [{"n": nid, "t": int(v["t"]), "s": v["score"], "br": n_at.get(nid, 0),
          "r": reach.get(nid, 0), "h": health_hit.get(nid, 0)} for nid, v in first.items()],
        key=lambda x: x["t"],
    )


def _summary(scen, g):
    d = damage_of(scen, g)
    health = {n.id for n in g.nodes if n.layer == "health"}
    hosp = {n.id for n in g.nodes if n.kind == "hospital"}
    failed = {e.node_id for e in scen.events if e.kind == "failed"}
    return {
        "assets_failed": len(failed),
        "hospitals_hit": len(failed & hosp),
        "health_hit": len(failed & health),
        "people": d.people_affected,
        "person_hours": round(d.person_hours_no_power + d.person_hours_no_water, 1),
        "hospital_hours": round(d.hospital_critical_hours, 1),
        "headline": round(d.headline(), 1),
    }


def main() -> int:
    g = chennai.build()
    print("fitting kernel on train scenarios...")
    train = [runner.run(g, h, seed=s, tick_s=TICK)
             for h in ("monsoon_flood", "equipment_age") for s in range(8)]
    kernel = counting.fit(g, [redact(s.events) for s in train],
                          horizon_s=259_200.0 * len(train), corpus_id="demo", seed=0)
    br = BranchingRatio(g, kernel)
    print(f"  {len(kernel.edges)} edges, rho={kernel.spectral_radius:.3f}")

    hosp_rank = sorted((n for n in g.nodes if n.layer == "health"),
                       key=lambda n: -(n.criticality_weight * max(n.population_served, 1)))
    human_targets = [n.id for n in hosp_rank[:BUDGET]]

    # Pick the demo seed. Every candidate is scored the same way and the count
    # is reported: this is ONE illustrative scenario, and the evidence is the
    # 36-scenario ablation in eval/results/arms.md, not this run.
    best = None
    for seed in CANDIDATE_SEEDS:
        base = runner.run(g, "monsoon_flood", seed=seed, tick_s=TICK)
        t_dec = base.horizon_s * DECIDE_AT_FRAC
        d0 = damage_of(base, g)
        if d0.hospital_critical_hours <= 0:
            continue

        obs = ObservableState(g)
        seen = [e for e in sorted(redact(base.events), key=lambda x: x.t) if e.t <= t_dec]
        for e in seen:
            obs.apply(e)
        s_vec = np.array([obs.susceptibility(n.id) for n in g.nodes])
        live = list(dict.fromkeys(
            [e.node_id for e in seen if e.kind == "failed"][-25:])) or [g.nodes[0].id]

        # Restricted to the actions the engine can apply, and forbidden from
        # spending the budget on assets that are already down. See eval/arms.py.
        down = {e.node_id for e in seen if e.kind == "failed"}
        srch = InterventionSearch(g, kernel, n_rollouts=400,
                                  kinds=("harden", "preposition"), top_k=60)
        dec = srch.decide(base.scenario_id, t_dec, live, s_vec, [], seed=seed,
                          top_n=BUDGET * 4, already_failed=down)
        ids = {n.id for n in g.nodes}
        ranked = sorted(dec.ranked, key=lambda iv: -iv.damage_prevented_headline)
        fb_targets = list(dict.fromkeys(
            iv.action.target for iv in ranked if iv.action.target in ids))[:BUDGET]
        if not fb_targets:
            continue

        fb = runner.run(g, "monsoon_flood", seed=seed, tick_s=TICK,
                        protected={n: PROTECT for n in fb_targets}, protect_at_s=t_dec)
        hu = runner.run(g, "monsoon_flood", seed=seed, tick_s=TICK,
                        protected={n: PROTECT for n in human_targets}, protect_at_s=t_dec)
        d_fb, d_hu = damage_of(fb, g), damage_of(hu, g)
        gap = (d_hu.headline() - d_fb.headline()) / max(d0.headline(), 1.0)
        print(f"  seed {seed}: do-nothing {d0.headline():,.0f}  firebreak {d_fb.headline():,.0f}  "
              f"human {d_hu.headline():,.0f}  gap {gap:+.1%}")
        if best is None or gap > best["gap"]:
            best = {"seed": seed, "gap": gap, "base": base, "fb": fb, "hu": hu,
                    "t_dec": t_dec, "dec": dec, "fb_targets": fb_targets}

    if best is None:
        raise SystemExit("no candidate seed produced a usable demo scenario")

    seed = best["seed"]
    print(f"\nchosen seed {seed} from {len(CANDIDATE_SEEDS)} candidates scored")

    runs = {}
    for key, scen in (("do_nothing", best["base"]), ("firebreak", best["fb"]),
                      ("human", best["hu"])):
        runs[key] = {"timeline": _timeline(scen, g, br, kernel), "summary": _summary(scen, g)}

    # BEAT 5 MUST FAIL. Asserted at export time, not discovered on stage.
    s0, sf, sh = (runs[k]["summary"] for k in ("do_nothing", "firebreak", "human"))
    beat5_fails = sh["headline"] > sf["headline"]
    if not beat5_fails:
        raise SystemExit(
            f"BEAT 5 NO LONGER FAILS: the human-obvious action ({sh['headline']:,.0f}) did not "
            f"do worse than Firebreak's ({sf['headline']:,.0f}). The demo's contrast is gone.")

    ranked_best = sorted(best["dec"].ranked, key=lambda iv: -iv.damage_prevented_headline)
    top = ranked_best[0] if ranked_best else None
    nodes = [{"id": n.id, "l": n.layer, "k": n.kind, "lat": round(n.lat, 5), "lon": round(n.lon, 5),
              "pop": n.population_served, "w": n.criticality_weight,
              "buf": int(n.buffer_s)} for n in g.nodes]
    deps = [{"s": e.src, "d": e.dst} for e in g.edges if e.relation == "depends_on"]

    tl0 = runs["do_nothing"]["timeline"]
    first = {r["n"]: r for r in tl0}
    cands = [(r["n"], r["s"], r["br"]) for r in tl0 if r["n"].startswith("power.") and r["br"]]
    pair, bestgap = None, -1
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            a, b = cands[i], cands[j]
            if abs(a[1] - b[1]) <= 0.02:
                gap = abs(a[2] - b[2])
                if gap > bestgap and max(a[2], b[2]) > 0.3:
                    bestgap, pair = gap, ((a, b) if a[2] > b[2] else (b, a))

    payload = {
        "city": g.city_id, "seed": seed, "nodes": nodes, "deps": deps,
        "horizon_s": best["base"].horizon_s, "t_decide_s": best["t_dec"],
        "runs": runs,
        "timeline": tl0,          # kept: the 2D fallback reads this directly
        "intervention": {
            "targets": best["fb_targets"],
            "kind": top.action.kind if top else None,
            "cost": sum(iv.action.cost for iv in ranked_best[:BUDGET]),
            "deadline_s": top.deadline_s if top else 0.0,
            "rationale": top.rationale if top else [],
            "compute_ms": round(best["dec"].compute_ms, 1),
        },
        "human_action": {"targets": human_targets,
                         "label": "harden the most critical asset"},
        "pair": ({"danger": {"id": pair[0][0], "score": pair[0][1], "br": pair[0][2]},
                  "decoy": {"id": pair[1][0], "score": pair[1][1], "br": pair[1][2]}}
                 if pair else None),
        "stats": {"nodes": len(g.nodes), "edges": len(g.edges), "deps": len(deps),
                  "diesel": sum(1 for e in g.edges if e.relation == "depends_on"
                                and e.src.startswith("health.gen_")
                                and e.dst.startswith("transport.")),
                  "kernel_edges": len(kernel.edges), "rho": round(kernel.spectral_radius, 3),
                  "events": len(best["base"].events), "failures": len(first),
                  "seeds_considered": len(CANDIDATE_SEEDS)},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "demo.json").write_text(json.dumps(payload, separators=(",", ":")))

    print(f"\n{'run':12} {'assets':>8} {'hosp':>6} {'people':>10} {'person-hours':>14} {'headline':>12}")
    for k in ("do_nothing", "firebreak", "human"):
        s = runs[k]["summary"]
        print(f"{k:12} {s['assets_failed']:8d} {s['hospitals_hit']:6d} {s['people']:10,d} "
              f"{s['person_hours']:14,.0f} {s['headline']:12,.0f}")
    print(f"\nBEAT 5 FAILS AS REQUIRED: human {sh['headline']:,.0f} > firebreak {sf['headline']:,.0f}")
    print(f"bytes: {(OUT/'demo.json').stat().st_size:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
