"""The decision loop, runnable on its own. No server, no uplink, no model call.

`EXECUTION.md` non-negotiable 10: a city control room cannot depend on an
internet uplink to decide whether to shed load. Cloud for storage, training and
reporting; the decision loop runs local. That claim is on the architecture
slide, and until now nothing in the repo demonstrated it.

    python -m service.decide --hazard monsoon_flood --seed 90100

Reads a city and a kernel, replays a scenario up to the decision time, and
prints one `Decision` as JSON: what it would do, what it expects that to save,
and when the option expires. Everything between the alarm and the instruction is
arithmetic — a Hawkes kernel, a Monte Carlo rollout and an enumeration — and
every line of it is auditable. No LLM produces any part of this output.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import numpy as np

from city.engine import runner
from city.topology import chennai
from decision.search import InterventionSearch
from inference.criticality.branching import BranchingRatio
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from service import obs
from service.redact import redact

log = logging.getLogger(__name__)
TICK_S = 300.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hazard", default="monsoon_flood")
    ap.add_argument("--seed", type=int, default=90_100)
    ap.add_argument("--at", type=float, default=0.25,
                    help="decide this far through the horizon (fraction)")
    ap.add_argument("--budget", type=int, default=5)
    ap.add_argument("--train-seeds", type=int, default=6,
                    help="scenarios to mine the kernel from")
    ap.add_argument("--rollouts", type=int, default=600)
    ap.add_argument("--quiet", action="store_true", help="suppress the structured log")
    a = ap.parse_args(argv)

    if not a.quiet:
        obs.configure(logging.INFO)

    g = chennai.build()

    # TRAINING is the part that belongs in the cloud. It is here only so the
    # command is self-contained; in a deployment the kernel arrives as a file.
    t0 = time.perf_counter()
    train = [runner.run(g, h, seed=s, tick_s=TICK_S)
             for h in ("monsoon_flood", "equipment_age") for s in range(a.train_seeds)]
    kernel = counting.fit(g, [redact(s.events) for s in train],
                          horizon_s=259_200.0 * len(train), corpus_id="edge", seed=0)
    fit_ms = (time.perf_counter() - t0) * 1000.0

    # THE DECISION LOOP. Everything below runs on whatever is in the control
    # room, from a graph, a kernel, and the alarms seen so far.
    scen = runner.run(g, a.hazard, seed=a.seed, tick_s=TICK_S)
    t_dec = scen.horizon_s * a.at
    seen = [e for e in sorted(redact(scen.events), key=lambda x: x.t) if e.t <= t_dec]

    t1 = time.perf_counter()
    o = ObservableState(g)
    for e in seen:
        o.apply(e)
    world = o.sync()
    s_vec = np.array([o.susceptibility(n.id) for n in g.nodes])
    down = {e.node_id for e in seen if e.kind == "failed"}
    live = list(dict.fromkeys([e.node_id for e in seen if e.kind == "failed"][-25:]))
    if not live:
        print(json.dumps({"error": "nothing has failed yet; nothing to decide on"}))
        return 1

    br = BranchingRatio(g, kernel)
    dangerous = sorted(
        ((n.id, br.of(n.id, world)) for n in g.nodes if n.id not in down),
        key=lambda kv: -kv[1])[:10]

    srch = InterventionSearch(g, kernel, n_rollouts=a.rollouts,
                              kinds=("harden", "preposition"), top_k=60)
    d = srch.decide(scen.scenario_id, t_dec, live, s_vec, [], seed=a.seed,
                    top_n=a.budget, already_failed=down)
    decide_ms = (time.perf_counter() - t1) * 1000.0

    out = {
        "scenario_id": scen.scenario_id,
        "decision_id": d.decision_id,
        "t_s": t_dec,
        "observed": {"events": len(seen), "assets_down": len(down)},
        "kernel": {"edges": len(kernel.edges),
                   "spectral_radius": round(kernel.spectral_radius, 4),
                   "subcritical": kernel.is_subcritical},
        "most_dangerous": [{"node": n, "branching_ratio": round(v, 3),
                            "above_one": v > 1.0} for n, v in dangerous],
        "do_nothing": d.do_nothing_damage.model_dump(),
        "recommended": [
            {"rank": i + 1, "action": iv.action.kind, "target": iv.action.target,
             "cost": iv.action.cost,
             "deadline_s": round(iv.deadline_s, 1),
             "deadline_min": round(iv.deadline_s / 60.0, 1),
             "damage_prevented": round(iv.damage_prevented_headline, 1),
             "benefit_per_cost": round(iv.benefit_per_cost, 1),
             "rationale": iv.rationale}
            for i, iv in enumerate(d.ranked)
        ],
        "timing_ms": {"kernel_fit_offline": round(fit_ms, 1),
                      "decision_loop_local": round(decide_ms, 1)},
        "no_llm_in_this_path": True,
    }
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
