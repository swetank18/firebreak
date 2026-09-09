"""The fixture city must encode the demo contrast, or the tests are theatre.

ss_01 and ss_02 are structurally different: one sits upstream of a hospital via
water, the other feeds households. That difference is the entire pitch, so it is
asserted here rather than assumed.
"""

from __future__ import annotations

import networkx as nx
import pytest

from city.topology import tiny


@pytest.fixture(scope="module")
def g():
    return tiny.build()


@pytest.fixture(scope="module")
def dep(g):
    """Dependency graph, oriented downstream: dst failing hurts src."""
    d = nx.DiGraph()
    d.add_nodes_from(n.id for n in g.nodes)
    for e in g.edges:
        d.add_edge(e.dst, e.src)  # failure travels from dst to src
    return d


def _health_reach(dep, node: str) -> set[str]:
    return {n for n in nx.descendants(dep, node) if n.startswith("health.")}


def test_all_five_layers_present(g):
    assert {n.layer for n in g.nodes} == {"power", "water", "transport", "telecom", "health"}


def test_the_two_alarm_contrast_is_structural(dep):
    """ss_01 reaches a hospital. ss_02 reaches strictly fewer health nodes.

    Same alarm, same score, different position. If this ever equalises the demo
    is dead and beat 2 has nothing to show.
    """
    r1, r2 = _health_reach(dep, "power.ss_01"), _health_reach(dep, "power.ss_02")
    assert "health.hosp_01" in r1
    assert len(r1) > len(r2), f"ss_01 reach {r1} must exceed ss_02 reach {r2}"


def test_the_diesel_edge_exists_and_is_long_delay(g):
    """The node that killed Chennai was a road, because it carried the fuel."""
    e = next(e for e in g.edges if e.src == "health.gen_hosp_01" and e.dst.startswith("transport."))
    assert e.relation == "depends_on"
    assert e.nominal_delay_s >= 3600 * 4, "the diesel edge must be slow enough to create lead time"


def test_hospitals_have_buffers(g):
    """Without buffers every dependency propagates instantly, there is no lead
    time to predict and no deadline to compute."""
    for n in g.nodes:
        if n.kind in ("hospital", "backup_generator"):
            assert n.buffer_s > 0, f"{n.id} has no buffer"


def test_reaching_a_hospital_takes_more_than_one_hop(dep):
    """A one-hop cascade is not a cascade. The path must cross layers."""
    path = nx.shortest_path(dep, "power.ss_01", "health.hosp_01")
    assert len(path) - 1 >= 2, f"path too short: {path}"
    assert len({p.split('.')[0] for p in path}) >= 2


def test_nominal_delay_is_a_prior_not_a_generator_input(g):
    """Risk R1. Documented here so the constraint is visible at the fixture."""
    delays = [e.nominal_delay_s for e in g.dependency_edges()]
    assert len(set(delays)) > 3, "delays must vary; a constant would be trivially recoverable"
