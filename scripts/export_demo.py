"""Export one real scenario for the console. The renderer computes nothing."""
from __future__ import annotations
import json, numpy as np
from pathlib import Path
from city.topology import chennai
from city.engine import runner
from city.engine.chains import true_chains
from inference.kernel import counting
from inference.criticality.branching import BranchingRatio
from inference.criticality.observable import ObservableState
from service.redact import redact

OUT = Path("console/data"); OUT.mkdir(parents=True, exist_ok=True)
g = chennai.build()

train = [runner.run(g, h, seed=s, tick_s=300.0)
         for h in ("monsoon_flood", "equipment_age") for s in range(8)]
kernel = counting.fit(g, [e for s in train for e in redact(s.events)],
                      horizon_s=259_200.0 * len(train), corpus_id="demo", seed=0)

scen = runner.run(g, "monsoon_flood", seed=90_100, tick_s=300.0)
br = BranchingRatio(g, kernel); obs = ObservableState(g)

# branching ratio at each node's first failure
first, n_at = {}, {}
for e in sorted(redact(scen.events), key=lambda x: x.t):
    if e.kind == "failed" and e.node_id not in first:
        first[e.node_id] = {"t": e.t, "score": round(e.anomaly_score, 3)}
        n_at[e.node_id] = round(br.of(e.node_id, obs.sync()), 3)
    obs.apply(e)

# ground-truth downstream reach per first-failure event
by_id = {e.event_id: e for e in scen.events}
reach = {}
for path in true_chains(scen.events):
    for i, eid in enumerate(path):
        if eid in by_id:
            nid = by_id[eid].node_id
            tail = {by_id[x].node_id for x in path[i+1:] if x in by_id}
            reach[nid] = max(reach.get(nid, 0), len(tail))
health_hit = {}
for path in true_chains(scen.events):
    for i, eid in enumerate(path):
        if eid in by_id:
            nid = by_id[eid].node_id
            if any(by_id[x].node_id.startswith("health.") for x in path[i+1:] if x in by_id):
                health_hit[nid] = 1

nodes = [{"id": n.id, "l": n.layer, "k": n.kind, "lat": round(n.lat, 5), "lon": round(n.lon, 5),
          "pop": n.population_served, "w": n.criticality_weight,
          "buf": int(n.buffer_s)} for n in g.nodes]
deps = [{"s": e.src, "d": e.dst} for e in g.edges if e.relation == "depends_on"]

# the two-alarm pair: closest anomaly scores, most different branching ratio
cands = [(k, v["score"], n_at[k]) for k, v in first.items()
         if k.startswith("power.") and n_at.get(k) is not None]
pair = None; bestgap = -1
for i in range(len(cands)):
    for j in range(i+1, len(cands)):
        a, b = cands[i], cands[j]
        if abs(a[1]-b[1]) <= 0.02:
            gap = abs(a[2]-b[2])
            if gap > bestgap and max(a[2],b[2]) > 0.3:
                bestgap = gap; pair = (a, b) if a[2] > b[2] else (b, a)

timeline = sorted(
    [{"n": nid, "t": int(v["t"]), "s": v["score"], "br": n_at.get(nid, 0),
      "r": reach.get(nid, 0), "h": health_hit.get(nid, 0)} for nid, v in first.items()],
    key=lambda x: x["t"])

payload = {
    "city": g.city_id, "nodes": nodes, "deps": deps, "timeline": timeline,
    "horizon_s": scen.horizon_s,
    "pair": ({"danger": {"id": pair[0][0], "score": pair[0][1], "br": pair[0][2]},
              "decoy":  {"id": pair[1][0], "score": pair[1][1], "br": pair[1][2]}} if pair else None),
    "stats": {"nodes": len(g.nodes), "edges": len(g.edges), "deps": len(deps),
              "diesel": sum(1 for e in g.edges if e.relation=="depends_on"
                            and e.src.startswith("health.gen_") and e.dst.startswith("transport.")),
              "kernel_edges": len(kernel.edges), "rho": round(kernel.spectral_radius, 3),
              "events": len(scen.events), "failures": len(first)},
}
(OUT / "demo.json").write_text(json.dumps(payload, separators=(",", ":")))
print(f"nodes={len(nodes)} deps={len(deps)} timeline={len(timeline)}")
print("pair:", json.dumps(payload["pair"], indent=1) if pair else "none found")
print("bytes:", (OUT/"demo.json").stat().st_size)
