"""THE FOUNDATIONAL TEST.

Generate events from a known Hawkes kernel, fit, and check the estimator
recovers it. If this fails, nothing downstream in the project means anything.

Written before the real fitter, per lanes/LANE-B-inference.md hour zero.
"""

from __future__ import annotations

import numpy as np
import pytest

from city.topology import tiny
from inference.kernel import counting, synthetic


@pytest.fixture(scope="module")
def fitted():
    g = tiny.build()
    k = synthetic.make_kernel(g, seed=3, target_rho=0.75)
    # A statistical estimator needs samples. At 4e6 s the corpus gives max
    # n_obs = 9 per edge, which tests nothing. How much operational history is
    # actually required before the kernel is usable is a real deployment
    # question, and it is Lane F's corpus learning-curve experiment.
    H = 60_000_000.0
    events, _ = synthetic.simulate(g, k, horizon_s=H, seed=3)
    est = counting.fit(g, events, horizon_s=H, corpus_id="synthetic", seed=3)
    return g, k, events, est


def test_generator_produces_a_usable_corpus(fitted):
    _, _, events, _ = fitted
    assert len(events) > 500, f"only {len(events)} events; horizon too short to fit anything"
    assert sum(1 for e in events if e.cause) > 100, "no propagation — alpha too small"


def test_estimator_recovers_alpha_ordering(fitted):
    """The ranking must survive even if the scale does not.

    Ordering is what the branching ratio depends on: which node is dangerous is
    a comparison, not an absolute.
    """
    _, k, _, est = fitted
    common = [e for e in est.edges if e in k.alpha and est.edges[e].n_obs >= 10]
    assert len(common) >= 8, f"only {len(common)} well-observed edges"
    true = np.array([k.alpha[e] for e in common])
    got = np.array([est.edges[e].alpha for e in common])
    from scipy.stats import spearmanr
    rho, p = spearmanr(true, got)
    assert rho > 0.3 and p < 0.05, f"alpha ordering not recovered: rho={rho:.3f} p={p:.3g}"


def test_estimator_recovers_delay_scale(fitted):
    """1/beta must track the true mean delay."""
    _, k, _, est = fitted
    common = [e for e in est.edges if e in k.beta and est.edges[e].n_obs >= 10]
    true = np.array([1.0 / k.beta[e] for e in common])
    got = np.array([est.edges[e].mean_delay_s for e in common])
    from scipy.stats import spearmanr
    rho, _ = spearmanr(true, got)
    assert rho > 0.3, f"delay ordering not recovered: rho={rho:.3f}"


def test_subcritical_kernel_is_reported_subcritical(fitted):
    _, _, _, est = fitted
    assert est.spectral_radius > 0, "rho must be positive"
    assert est.is_subcritical, f"generator was subcritical but rho={est.spectral_radius:.2f}"


def test_thin_edges_carry_wider_intervals(fitted):
    _, _, _, est = fitted
    thin = [e for e in est.edges.values() if e.is_thin]
    thick = [e for e in est.edges.values() if not e.is_thin and e.n_obs >= 30]
    if thin and thick:
        w_thin = np.mean([e.ci_high - e.ci_low for e in thin])
        w_thick = np.mean([e.ci_high - e.ci_low for e in thick])
        assert w_thin >= w_thick, "thin edges must not be more confident than thick ones"
