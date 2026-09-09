"""The six demo beats, asserted against the exported scenario.

`EXECUTION.md` section 10: CI drives the six beats and asserts WHAT EACH BEAT IS
MEANT TO PROVE, not that something returned 200.

Beat 5 is the one that matters. The human-obvious action — harden the most
critical asset — has to FAIL to stop the cascade. If a change ever makes it
succeed, the contrast the whole demo is built on is gone, and we want to learn
that here rather than on stage.

The renderer computes nothing, so everything the demo shows is a field in this
file and everything below can be checked without starting a browser.
"""

from __future__ import annotations

import json
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
DEMO = REPO / "console" / "data" / "demo.json"
ARMS = REPO / "eval" / "results" / "arms.json"
LAYERS = {"power", "water", "transport", "telecom", "health"}


@pytest.fixture(scope="module")
def demo() -> dict:
    if not DEMO.exists():
        pytest.fail(f"{DEMO.relative_to(REPO)} is missing. Run scripts/export_demo.py.")
    return json.loads(DEMO.read_text())


def test_beat1_five_layers_load(demo):
    layers = {n["l"] for n in demo["nodes"]}
    assert layers == LAYERS, f"expected all five layers, got {sorted(layers)}"
    assert len(demo["nodes"]) > 1000
    assert demo["stats"]["diesel"] > 0, (
        "no diesel edge in the city: a hospital generator that depends on a road is "
        "the mechanism the entire pitch is about"
    )


def test_beat2_two_alarms_same_score_different_danger(demo):
    pair = demo.get("pair")
    assert pair, "no two-alarm pair exported; beat 2 has nothing to show"
    d, k = pair["danger"], pair["decoy"]
    assert abs(d["score"] - k["score"]) <= 0.02, (
        f"the two alarms must look alike to a conventional monitor: "
        f"{d['score']} vs {k['score']}"
    )
    assert d["br"] > k["br"], "the flagged alarm must have the higher branching ratio"


def test_beat3_do_nothing_reaches_the_health_layer(demo):
    s = demo["runs"]["do_nothing"]["summary"]
    assert s["health_hit"] > 0, "doing nothing has to reach the health layer or beat 3 has no point"
    assert s["person_hours"] > 0


def test_beat4_firebreak_action_reduces_damage(demo):
    dn = demo["runs"]["do_nothing"]["summary"]
    fb = demo["runs"]["firebreak"]["summary"]
    assert fb["headline"] < dn["headline"], (
        f"Firebreak's action did not reduce damage: {fb['headline']:,.0f} vs "
        f"{dn['headline']:,.0f} for doing nothing"
    )


def test_beat4_intervention_carries_a_real_deadline(demo):
    iv = demo["intervention"]
    assert iv["targets"], "no intervention targets"
    assert iv["deadline_s"] > 0, (
        "the deadline is what turns a prediction into an instruction; a zero deadline "
        "means the solver computed nothing"
    )
    assert iv["rationale"], "an intervention with no rationale is not auditable"


def test_beat5_the_human_obvious_action_still_cascades(demo):
    """THE ONE THAT MUST FAIL."""
    fb = demo["runs"]["firebreak"]["summary"]
    hu = demo["runs"]["human"]["summary"]
    assert hu["headline"] > fb["headline"], (
        f"BEAT 5 NO LONGER FAILS. Hardening the most critical asset "
        f"({hu['headline']:,.0f}) did at least as well as Firebreak's action "
        f"({fb['headline']:,.0f}). That contrast is the whole demo — if this is a real "
        f"improvement, the runbook needs rewriting, not the assertion."
    )


def test_beat5_is_a_fair_comparison(demo):
    """Same budget, or beat 5 proves nothing."""
    assert len(demo["human_action"]["targets"]) == len(demo["intervention"]["targets"])


def test_beat6_every_arm_is_reported(demo):
    if not ARMS.exists():
        pytest.fail("eval/results/arms.json is missing. Run eval/arms.py.")
    a = json.loads(ARMS.read_text())
    arms = {t["arm"] for t in a["arms"]}
    assert {"A0", "A1", "A2", "A3", "A4", "A6"} <= arms, f"arms missing: {sorted(arms)}"
    assert "A5" in a["A5_note"], "A5 must be reported as not-reproduced, not dropped"


def test_beat6_the_oracle_is_actually_a_ceiling(demo):
    """A ceiling that sits below an arm is not a ceiling — it is a bug we shipped once."""
    a = json.loads(ARMS.read_text())
    by = {t["arm"]: t["prevented"] for t in a["arms"]}
    oracle = by["A6"]
    for arm in ("A1", "A2", "A3", "A4"):
        assert by[arm] <= oracle + 1e-6, (
            f"arm {arm} prevented {by[arm]:,.0f}, above the oracle's {oracle:,.0f}. "
            "Either the oracle is misdefined again or its candidate pool is too narrow."
        )
