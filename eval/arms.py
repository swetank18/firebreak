"""The seven-arm ablation.

One mechanism per arm. Same city, same hazards, same seeds, same damage
weights — nothing else moves. That is the DIVAS rule and it is why the
comparison can be believed.

Interventions are applied IN THE ENGINE and the scenario is re-run on the same
seed with paired randomness, so this is a true counterfactual rather than a
score under our own rollout model. Scoring under our own model would flatter
arm A4 by construction.

  A0  do nothing                          the floor
  A1  rank by anomaly score               WHAT EVERY OTHER TEAM BUILDS
  A2  rank by static betweenness          topology, no learning
  A3  rank by branching ratio             our inference
  A4  A3 + counterfactual search          full Firebreak
  A5  I3 (Tsinghua, published SOTA)       see note
  A6  oracle, perfect foresight           the ceiling

Kernel ablation (does the model earn its place?) runs the same ladder with
alpha replaced by random / uniform / expert-declared values.
"""

from __future__ import annotations

import json
import multiprocessing as mp
from pathlib import Path

import networkx as nx
import numpy as np

from city.engine import runner
from city.topology import chennai
from eval.damage import damage_of as _damage
from inference.criticality.branching import BranchingRatio
from inference.criticality.observable import ObservableState
from inference.kernel import counting
from service.redact import redact

OUT = Path(__file__).parent / "results"
HAZARDS = ["monsoon_flood", "heatwave", "cyber"]
BUDGET = 5                 # an operator can act on a handful of things
DECIDE_AT_FRAC = 0.25      # act a quarter of the way in
PROTECT = 0.9
TICK = 300.0
ORACLE_POOL = 30        # candidates the greedy oracle may choose among


def _centrality(g) -> dict[str, float]:
    d = nx.DiGraph()
    d.add_nodes_from(n.id for n in g.nodes)
    for e in g.edges:
        d.add_edge(e.dst, e.src)
    return nx.betweenness_centrality(d, k=min(200, len(g.nodes)), seed=0)


def _one(args) -> dict:
    hazard, seed, kernel, cent, arms = args
    g = chennai.build()
    base = runner.run(g, hazard, seed=seed, tick_s=TICK)
    t_dec = base.horizon_s * DECIDE_AT_FRAC

    pop_of = {n.id: n.population_served for n in g.nodes}
    first_fail_t: dict[str, float] = {}
    for e in base.events:
        if e.kind == "failed" and e.node_id not in first_fail_t:
            first_fail_t[e.node_id] = e.t

    obs = ObservableState(g)
    seen = [e for e in sorted(redact(base.events), key=lambda x: x.t) if e.t <= t_dec]
    for e in seen:
        obs.apply(e)
    world = obs.sync()
    s_vec = np.array([obs.susceptibility(n.id) for n in g.nodes])
    live = [e.node_id for e in seen if e.kind == "failed"][-25:]
    live = list(dict.fromkeys(live))
    failed_by_t_dec = {e.node_id for e in seen if e.kind == "failed"}

    br = BranchingRatio(g, kernel)
    scores: dict[str, float] = {}
    for e in seen:
        scores[e.node_id] = max(scores.get(e.node_id, 0.0), e.anomaly_score)

    picks: dict[str, list[str]] = {}
    # No arm may spend its budget on an asset that is already down — protecting a
    # failed node is a no-op in the engine, and an arm that wastes picks on them
    # is being scored on a bookkeeping artefact rather than on its ranking.
    def _top(d: dict[str, float]) -> list[str]:
        return [k for k, _ in sorted(d.items(), key=lambda kv: -kv[1])
                if k not in failed_by_t_dec][:BUDGET]

    if "A1" in arms:
        picks["A1"] = _top(scores)
    if "A2" in arms:
        picks["A2"] = _top(cent)
    if "A3" in arms:
        picks["A3"] = _top({n.id: br.of(n.id, world) for n in g.nodes})
    if "A4" in arms:
        from decision.search import InterventionSearch
        # EVERY ARM PROTECTS FIVE NODES. The arms may differ in HOW they choose,
        # and in nothing else, or the comparison stops being about selection.
        #
        # So the search runs over the action the engine can actually apply —
        # harden and preposition, both of which make a node resist. It used to
        # run over the full space, rank by benefit-per-COST, and hand back four
        # `isolate` actions on assets that had already failed; the evaluation
        # then applied generic protection to those dead assets and A4 measured
        # 0.1% against A2's 10.5%. See docs/FINDINGS.md.
        #
        # Ranked by raw damage prevented, not per unit cost, because the budget
        # here is a COUNT of interventions. Cost-weighted ranking is a different
        # mechanism and would not belong in this arm.
        srch = InterventionSearch(g, kernel, n_rollouts=400,
                                  kinds=("harden", "preposition"), top_k=60)
        d = srch.decide(base.scenario_id, t_dec, live or [g.nodes[0].id], s_vec, [],
                        seed=seed, top_n=BUDGET * 4, already_failed=set(failed_by_t_dec),
                        keep_nonpositive=True, horizon_s=base.horizon_s - t_dec)
        ids = {n.id for n in g.nodes}
        ranked = sorted(d.ranked, key=lambda iv: -iv.damage_prevented_headline)
        picks["A4"] = list(dict.fromkeys(
            iv.action.target for iv in ranked if iv.action.target in ids))[:BUDGET]
    d0 = _damage(base, g)

    if "AR" in arms:
        # THE CHANCE BASELINE, and the arm this ablation most needed.
        # A random 5-asset intervention has a standard deviation of ~176,000 on
        # a single scenario and a range of -777,000 to +659,000. Without this
        # arm the table reports a 0.4% effect as though it were an effect.
        # Seeded from the scenario seed, so it is paired like everything else.
        rng = np.random.default_rng(500_000 + seed)
        savable = [n.id for n in g.nodes if n.id not in failed_by_t_dec]
        picks["AR"] = [str(x) for x in rng.choice(savable, size=BUDGET, replace=False)]

    if "A6" in arms:
        # ORACLE — perfect foresight, greedy, evaluated by RE-RUNNING THE ENGINE.
        #
        # The previous oracle ranked nodes by blame count (how many downstream
        # failures each was credited with) and read BELOW arm A2, which is
        # impossible for a ceiling. Blame count is not damage: a node causing
        # fifty small failures outranks one causing a hospital outage.
        #
        # The pool deliberately CONTAINS EVERY OTHER ARM'S PICKS, so the ceiling
        # is never an artefact of the oracle not having been offered what an arm
        # chose. Greedy over a pool is a lower bound on the true optimum — it is
        # achievable rather than optimal, and an arm beating it would be a real
        # result, not a bug. Stated in eval/results/arms.md.
        # The pool must be DIVERSE, not ranked by population. Roads serve no
        # population at all and the diesel edge — a hospital generator that
        # needs a road to be refuelled — is the whole thesis of this project. A
        # pool ordered by population would never offer the oracle a road.
        by = {e.event_id: e for e in base.events}
        blame: dict[str, int] = {}
        for e in base.events:
            if e.cause and e.cause in by:
                blame[by[e.cause].node_id] = blame.get(by[e.cause].node_id, 0) + 1
        # ONLY ASSETS THAT ARE STILL SAVABLE. Protection lands at t_dec and
        # cannot resurrect anything already down, so an asset that failed before
        # then is a no-op that costs the oracle a pool slot. Including them makes
        # the ceiling read LOWER than it truly is, which flatters every arm
        # measured against it — the direction of error to be least comfortable
        # with, since the oracle exists to be unflattering.
        fs = {n for n, t in first_fail_t.items() if t > t_dec}
        top = lambda d, k: [n for n, _ in sorted(  # noqa: E731
            ((n, v) for n, v in d.items() if n in fs), key=lambda kv: -kv[1])[:k]]
        pool = list(dict.fromkeys(
            [n for ns in picks.values() for n in ns]
            + top(pop_of, 10) + top(blame, 10) + top(cent, 8)
        ))[:ORACLE_POOL]
        chosen: list[str] = []
        best = d0.headline()
        for _ in range(BUDGET):
            step_best, step_node = best, None
            for c in pool:
                if c in chosen:
                    continue
                alt = runner.run(g, hazard, seed=seed, tick_s=TICK,
                                 protected={n: PROTECT for n in chosen + [c]},
                                 protect_at_s=t_dec)
                v = _damage(alt, g).headline()
                if v < step_best:
                    step_best, step_node = v, c
            if step_node is None:
                break
            chosen.append(step_node)
            best = step_best
        picks["A6"] = chosen

    row = {"hazard": hazard, "seed": seed, "A0": d0.headline(),
           "A0_people": d0.people_affected, "A0_hosp": d0.hospital_critical_hours}
    for arm, nodes in picks.items():
        alt = runner.run(g, hazard, seed=seed, tick_s=TICK,
                         protected={n: PROTECT for n in nodes}, protect_at_s=t_dec)
        da = _damage(alt, g)
        row[arm] = da.headline()
        row[arm + "_people"] = da.people_affected
        row[arm + "_hosp"] = da.hospital_critical_hours
        row[arm + "_picks"] = nodes
    return row


def main(n_seeds: int = 20) -> int:
    g = chennai.build()
    print("fitting kernel on train scenarios...")
    tr = [runner.run(g, h, seed=s, tick_s=TICK)
          for h in ("monsoon_flood", "equipment_age") for s in range(6)]
    kernel = counting.fit(g, [redact(s.events) for s in tr],
                          horizon_s=259_200.0 * len(tr), corpus_id="arms", seed=0)
    print(f"  {len(kernel.edges)} edges, rho={kernel.spectral_radius:.3f}")
    print("computing betweenness...")
    cent = _centrality(g)

    arms = ["AR", "A1", "A2", "A3", "A4", "A6"]
    jobs = [(h, 70_000 + s, kernel, cent, arms) for h in HAZARDS for s in range(n_seeds)]
    print(f"running {len(jobs)} scenarios x {len(arms)+1} arms...")
    with mp.Pool(min(mp.cpu_count(), 12)) as pool:
        rows = pool.map(_one, jobs, chunksize=1)

    OUT.mkdir(parents=True, exist_ok=True)
    labels = {"A0": "do nothing", "AR": "**random 5 assets (chance)**",
              "A1": "rank by anomaly score",
              "A2": "+ static betweenness", "A3": "+ branching ratio",
              "A4": "+ counterfactual search", "A6": "oracle (perfect foresight)"}
    order = ["A0", "AR", "A1", "A2", "A3", "A4", "A6"]
    base = np.array([r["A0"] for r in rows])
    oracle_prev = base - np.array([r["A6"] for r in rows])
    chance_prev = base - np.array([r["AR"] for r in rows])
    rng = np.random.default_rng(0)
    boot_ix = rng.integers(0, len(rows), size=(2000, len(rows)))

    def paired_test(diff: np.ndarray) -> tuple[float, float]:
        """Wilcoxon signed-rank on the per-scenario paired difference.

        The mean is the wrong estimator here. Damage prevented is heavy-tailed
        across scenarios — an intervention does nothing in most runs and a great
        deal in a few — so a mean with a bootstrap CI can straddle zero while the
        arm wins in almost every scenario it is run on. A2's interval spanned
        [-8,134, 2,395,643] on exactly that pattern. `docs/03-EVALUATION.md` asks
        for paired comparisons and p-values, and this is the paired test that
        survives the tail. Returns (win rate, p).
        """
        from scipy.stats import wilcoxon

        nz = diff[diff != 0]
        win = float((diff > 0).mean())
        if len(nz) < 6:
            return win, 1.0
        try:
            return win, float(wilcoxon(nz, alternative="greater").pvalue)
        except ValueError:
            return win, 1.0

    def ci(x: np.ndarray) -> tuple[float, float]:
        """Paired bootstrap over SCENARIOS. Arms share seeds, so the difference
        is paired and the resample must be over scenarios, not over arms."""
        m = x[boot_ix].mean(axis=1)
        return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))

    table = []
    for arm in order:
        v = np.array([r[arm] for r in rows])
        prevented = base - v
        lo, hi = ci(prevented)
        # Against chance, paired scenario by scenario. "Beats doing nothing" is
        # the wrong question: a random 5-asset pick beats doing nothing too.
        vs_chance = prevented - chance_prev
        c_lo, c_hi = ci(vs_chance)
        win, pval = paired_test(vs_chance)
        # Holm correction across the four candidate arms, applied below.
        beats_chance = bool(c_lo > 0)
        # Aggregate share of the ceiling, not a mean of per-scenario ratios:
        # with prevented values that can be negative, a mean of ratios is not a
        # stable estimator and can be dominated by one small denominator.
        denom = float(oracle_prev.sum())
        frac = float(prevented.sum() / denom) if denom > 0 else 0.0
        hosp = np.array([r[arm + "_hosp"] for r in rows])
        h0 = np.array([r["A0_hosp"] for r in rows])
        table.append({
            "arm": arm, "mechanism": labels[arm],
            "damage": round(float(v.mean()), 1),
            "prevented": round(float(prevented.mean()), 1),
            "prevented_ci": [round(lo, 1), round(hi, 1)],
            "prevented_pct": round(float(prevented.mean() / base.mean() * 100), 2),
            "vs_chance": round(float(vs_chance.mean()), 1),
            "vs_chance_ci": [round(c_lo, 1), round(c_hi, 1)],
            "beats_chance_95": beats_chance,
            "median_vs_chance": round(float(np.median(vs_chance)), 1),
            "win_rate_vs_chance": round(win, 3),
            "p_wilcoxon_vs_chance": pval,
            "hosp_hours_saved": round(float((h0 - hosp).mean()), 2),
            "oracle_captured_pct": round(frac * 100, 1),
        })

    # Holm-Bonferroni across the four arms actually being tested. Reported
    # alongside the unadjusted p, because testing four arms and quoting the
    # smallest raw p is how a null result becomes a finding.
    tested = [t for t in table if t["arm"] in ("A1", "A2", "A3", "A4")]
    for rank, t in enumerate(sorted(tested, key=lambda x: x["p_wilcoxon_vs_chance"])):
        t["p_holm"] = min(1.0, t["p_wilcoxon_vs_chance"] * (len(tested) - rank))
    for t in table:
        t.setdefault("p_holm", None)
        t["p_wilcoxon_vs_chance"] = (None if t["arm"] in ("A0", "AR")
                                     else float(f"{t['p_wilcoxon_vs_chance']:.2e}"))
        t["significant_vs_chance"] = bool(
            t.get("p_holm") is not None and t["p_holm"] < 0.05)

    report = {"n_scenarios": len(rows), "budget": BUDGET, "protect": PROTECT,
              # Per-scenario rows are persisted so the analysis can be redone
              # without re-running 60 scenarios x 140 engine calls. Re-running an
              # experiment to change an estimator is how estimators get chosen
              # for their answers.
              "per_scenario": [{k: v for k, v in r.items() if not k.endswith("_picks")}
                               for r in rows],
              "kernel_edges": len(kernel.edges), "arms": table,
              "chance_arm": "AR",
              "note": ("Read vs_chance, not prevented. A random 5-asset pick already "
                       "prevents damage; the only honest question is whether an arm "
                       "beats it. Intervals are a paired bootstrap over scenarios."),
              "A5_note": "I3 (Tsinghua, arXiv 2503.02890) not reproduced — published "
                         "numbers only. Stated rather than dropped."}
    (OUT / "arms.json").write_text(json.dumps(report, indent=2) + "\n")

    beat = [t["arm"] for t in table if t.get("significant_vs_chance")]
    L = ["# Seven-arm ablation", "", "Generated by `eval/arms.py`. Never hand-edited.", "",
         f"- {len(rows)} scenarios across {len(HAZARDS)} hazards, held-out seeds",
         f"- budget: **{BUDGET} interventions**, applied at {DECIDE_AT_FRAC:.0%} of the horizon",
         "- interventions applied **in the engine** and re-run on the same seed with paired",
         "  randomness — a true counterfactual, not a score under our own rollout model",
         "- 95% intervals are a **paired bootstrap over scenarios**, since every arm sees the",
         "  same seeds", "",
         "**Read the `vs chance` columns, not `prevented`.** Protecting five assets at",
         "random already prevents damage, with a standard deviation of roughly 176,000 on a",
         "single scenario. Arm **AR** is that baseline and the only honest question is",
         "whether an arm beats it.", "",
         "Damage prevented is **heavy-tailed across scenarios** — an intervention does",
         "nothing in most runs and a great deal in a few — so the mean is a poor estimator",
         "and its bootstrap interval is wide almost regardless of the effect. The verdict",
         "column is a **Wilcoxon signed-rank test on the paired per-scenario difference**,",
         "Holm-corrected across the four arms tested. Both are shown; neither is hidden.", "",
         "| arm | mechanism | prevented | 95% CI | vs chance (mean) | median | win rate | p (Holm) | beats chance | % of oracle |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for t in table:
        lo, hi = t["prevented_ci"]
        if t["arm"] in ("A0", "AR"):
            mark, ptxt, wr, med = "—", "—", "—", "—"
        else:
            mark = "**yes**" if t.get("significant_vs_chance") else "no"
            ph = t.get("p_holm")
            ptxt = "—" if ph is None else f"{ph:.3f}"
            wr = f"{t['win_rate_vs_chance']:.0%}"
            med = f"{t['median_vs_chance']:,.0f}"
        L.append(f"| {t['arm']} | {t['mechanism']} | {t['prevented']:,.0f} | "
                 f"[{lo:,.0f}, {hi:,.0f}] | {t['vs_chance']:,.0f} | {med} | {wr} | "
                 f"{ptxt} | {mark} | {t['oracle_captured_pct']:.0f}% |")
    L += ["",
          ("**Arms that beat a random five-asset pick (Wilcoxon, Holm-corrected, p < 0.05): "
           + (", ".join(beat) if beat else "NONE") + ".**"),
          "",
          "**A5 — I³ (Tsinghua, arXiv 2503.02890): not reproduced.** Published numbers only.",
          "Stated rather than quietly dropped.", ""]
    (OUT / "arms.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
