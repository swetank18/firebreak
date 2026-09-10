"""The operator dashboard's live backend. Standard library only.

    python -m service.api        # then open http://127.0.0.1:8000/ops/

Why not FastAPI: this has to start on a venue laptop with no network and no
`pip install`. `http.server` is in the standard library, it is enough for a
handful of JSON endpoints, and a dependency that might not install is worse
than a framework we do not need.

The dashboard runs against this when it is reachable and falls back to the
precomputed matrix in `www/ops/data/` when it is not, so the same page works
served from a static host. `GET /api/health` is how it decides.

Endpoints
    GET  /api/health                        is the engine reachable
    GET  /api/options                       hazards, seeds, budgets it will accept
    POST /api/simulate  {hazard, seed, decide_frac, budget, protect}
                                            runs the engine and the decision layer
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from city.engine import hazard as hz
from city.engine import runner
from city.topology import chennai
from decision.search import InterventionSearch
from eval.damage import damage_of
from inference.criticality.branching import BranchingRatio
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from service import obs
from service.redact import redact

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
WWW = ROOT / "www"
TICK = 300.0
HAZARDS = ["monsoon_flood", "heatwave", "cyber", "equipment_age", "none"]

_lock = threading.Lock()
_state: dict = {}


def _warm() -> dict:
    """City and kernel, built once. The kernel is the part that belongs in the
    cloud in a real deployment; it is fitted here so the command is self-contained."""
    with _lock:
        if _state:
            return _state
        g = chennai.build()
        train = [runner.run(g, h, seed=s, tick_s=TICK)
                 for h in ("monsoon_flood", "equipment_age") for s in range(6)]
        kernel = counting.fit(g, [redact(s.events) for s in train],
                              horizon_s=259_200.0 * len(train), corpus_id="live", seed=0)
        _state.update(g=g, kernel=kernel, br=BranchingRatio(g, kernel))
        log.info("api.warm", extra={"kernel_edges": len(kernel.edges),
                                    "rho": round(kernel.spectral_radius, 4)})
        return _state


def _summary(scen, g) -> dict:
    d = damage_of(scen, g)
    hosp = {n.id for n in g.nodes if n.kind == "hospital"}
    health = {n.id for n in g.nodes if n.layer == "health"}
    failed = {e.node_id for e in scen.events if e.kind == "failed"}
    return {"assets_failed": len(failed), "hospitals_hit": len(failed & hosp),
            "health_hit": len(failed & health), "people": d.people_affected,
            "person_hours": round(d.person_hours_no_power + d.person_hours_no_water, 1),
            "hospital_hours": round(d.hospital_critical_hours, 1),
            "headline": round(d.headline(), 1)}


def simulate(hazard: str, seed: int, decide_frac: float,
             budget: int, protect: float) -> dict:
    """Run the scenario, decide on it, and re-run the counterfactuals.

    Same engine, same decision layer and same damage function the evaluation
    uses — this endpoint is not a demo path with its own arithmetic.
    """
    st = _warm()
    g, kernel, br = st["g"], st["kernel"], st["br"]
    if hazard not in HAZARDS:
        raise ValueError(f"unknown hazard {hazard!r}")
    budget = max(1, min(20, int(budget)))
    protect = max(0.0, min(1.0, float(protect)))
    decide_frac = max(0.02, min(0.9, float(decide_frac)))

    base = runner.run(g, hazard, seed=seed, tick_s=TICK)
    t_dec = base.horizon_s * decide_frac
    seen = [e for e in sorted(redact(base.events), key=lambda x: x.t) if e.t <= t_dec]
    o = ObservableState(g)
    for e in seen:
        o.apply(e)
    s_vec = np.array([o.susceptibility(n.id) for n in g.nodes])
    down = {e.node_id for e in seen if e.kind == "failed"}
    live = list(dict.fromkeys([e.node_id for e in seen if e.kind == "failed"][-25:]))

    ids = {n.id for n in g.nodes}
    targets, dec, top = [], None, None
    if live:
        srch = InterventionSearch(g, kernel, n_rollouts=400,
                                  kinds=("harden", "preposition"), top_k=60)
        dec = srch.decide(base.scenario_id, t_dec, live, s_vec, [], seed=seed,
                          top_n=budget * 4, already_failed=down,
                          keep_nonpositive=True, horizon_s=base.horizon_s - t_dec)
        ranked = sorted(dec.ranked, key=lambda iv: -iv.damage_prevented_headline)
        targets = list(dict.fromkeys(
            iv.action.target for iv in ranked if iv.action.target in ids))[:budget]
        top = ranked[0] if ranked else None

    hosp_rank = sorted((n for n in g.nodes if n.layer == "health"),
                       key=lambda n: -(n.criticality_weight * max(n.population_served, 1)))
    human = [n.id for n in hosp_rank[:budget]]

    runs = {"do_nothing": base}
    if targets:
        runs["firebreak"] = runner.run(g, hazard, seed=seed, tick_s=TICK,
                                       protected={n: protect for n in targets},
                                       protect_at_s=t_dec)
    runs["human"] = runner.run(g, hazard, seed=seed, tick_s=TICK,
                               protected={n: protect for n in human}, protect_at_s=t_dec)

    def timeline(scen):
        ob, out, got = ObservableState(g), [], set()
        for e in sorted(redact(scen.events), key=lambda x: x.t):
            if e.kind == "failed" and e.node_id not in got:
                got.add(e.node_id)
                out.append({"n": e.node_id, "t": int(e.t), "s": round(e.anomaly_score, 3),
                            "br": round(br.of(e.node_id, ob.sync()), 3)})
            ob.apply(e)
        return out

    n_ticks = int(base.horizon_s / TICK)
    field = hz.build(hazard, g, n_ticks, seed)
    lvl = field.level if field.level is not None else np.zeros(n_ticks)
    step = max(1, n_ticks // 180)

    return {
        "key": f"{hazard}-s{seed}-d{int(decide_frac * 100)}",
        "hazard": hazard, "seed": seed, "decide_frac": decide_frac,
        "budget": budget, "protect": protect, "live": True,
        "horizon_s": base.horizon_s, "t_decide_s": t_dec,
        "runs": {k: {"timeline": timeline(v), "summary": _summary(v, g)}
                 for k, v in runs.items()},
        "flood": {"level": [round(float(v), 4) for v in lvl[::step]],
                  "dt_s": step * TICK, "peak": round(float(lvl.max()), 4)},
        "intervention": {
            "targets": targets, "kind": top.action.kind if top else None,
            "cost": round(sum(iv.action.cost for iv in
                              sorted(dec.ranked, key=lambda i: -i.damage_prevented_headline)[:budget]), 1)
                    if dec and dec.ranked else 0,
            "deadline_s": round(top.deadline_s, 1) if top else 0.0,
            "rationale": top.rationale if top else [],
            "compute_ms": round(dec.compute_ms, 1) if dec else 0.0,
        },
        "human_action": {"targets": human},
        "observed_at_decision": len(seen), "down_at_decision": len(down),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WWW), **kw)

    def log_message(self, fmt, *args):        # quiet; service.obs owns logging
        pass

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json(200, {"ok": True, "engine": "live",
                                    "hazards": HAZARDS})
        if path == "/api/options":
            return self._json(200, {"hazards": HAZARDS,
                                    "decide_frac": [0.1, 0.25, 0.4, 0.6],
                                    "budget": [1, 3, 5, 10],
                                    "protect": [0.5, 0.75, 0.9, 1.0]})
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/simulate":
            return self._json(404, {"error": "no such endpoint"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            out = simulate(str(req.get("hazard", "monsoon_flood")),
                           int(req.get("seed", 90105)),
                           float(req.get("decide_frac", 0.25)),
                           int(req.get("budget", 5)),
                           float(req.get("protect", 0.9)))
            log.info("api.simulate", extra={"key": out["key"], "budget": out["budget"]})
            return self._json(200, out)
        except Exception as exc:                       # noqa: BLE001
            log.exception("api.simulate failed")
            return self._json(400, {"error": str(exc)})


def main(port: int = 8000) -> int:
    obs.configure()
    print(f"Firebreak operator API on http://127.0.0.1:{port}/ops/")
    print("warming the city and the kernel (about a minute) ...")
    _warm()
    print("ready. The dashboard will detect the live engine automatically.")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8000))
