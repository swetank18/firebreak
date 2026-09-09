"""Contract round-trips and the invariants every lane depends on."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import contracts as C
from city.topology import tiny


def test_node_id_must_be_layer_prefixed():
    with pytest.raises(ValidationError):
        C.Node(id="ss_022", layer="power", kind="substation", lat=0, lon=0)
    C.Node(id="power.ss_022", layer="power", kind="substation", lat=0, lon=0)


def test_event_redaction_strips_ground_truth():
    """The leakage boundary. Worth more than any model in the repo."""
    e = C.Event(
        event_id="e1", node_id="power.ss_01", t=0.0, kind="failed",
        severity=0.9, anomaly_score=0.61, cause="e0",
    )
    assert e.cause == "e0"
    assert e.redacted().cause is None


def test_damage_headline_uses_versioned_weights():
    d = C.Damage(person_hours_no_power=100, person_hours_no_water=50, hospital_critical_hours=4)
    assert d.headline() == pytest.approx(1.0 * 100 + 1.5 * 50 + 200.0 * 4)


def test_damage_is_additive():
    a = C.Damage(person_hours_no_power=10, people_affected=5)
    b = C.Damage(person_hours_no_power=7, people_affected=3)
    assert (a + b).person_hours_no_power == 17
    assert (a + b).people_affected == 8


def test_danger_threshold_is_one():
    def crit(n: float) -> C.Criticality:
        return C.Criticality(
            node_id="power.ss_01", t=0, branching_ratio=n, p_cascade=0.5,
            expected_reach=1, expected_damage=C.Damage(), ci_low=0, ci_high=2, n_rollouts=10,
        )
    assert not crit(0.99).is_dangerous
    assert crit(1.01).is_dangerous


def test_chain_splits_near_miss_from_cascade_at_the_locked_constant():
    def chain(hops: int) -> C.Chain:
        return C.Chain(
            chain_id="c", scenario_id="s", events=["e"] * (hops + 1), hops=hops,
            layers_crossed=1, span_s=60, terminated=True, damage=C.Damage(),
        )
    assert chain(C.CATASTROPHE_HOPS - 1).is_near_miss
    assert chain(C.CATASTROPHE_HOPS).is_cascade


def test_thin_kernel_edges_are_flagged_for_uncertainty_widening():
    thin = C.EdgeKernel(edge_id="e", alpha=0.8, beta=0.001, n_obs=3, ci_low=0.1, ci_high=1.9, estimator="counting")
    thick = C.EdgeKernel(edge_id="e", alpha=0.8, beta=0.001, n_obs=900, ci_low=0.78, ci_high=0.82, estimator="counting")
    assert thin.is_thin and not thick.is_thin
    assert thick.mean_delay_s == pytest.approx(1000.0)
