"""Same seed, same city, byte-identical output.

`EXECUTION.md` section 10 asks for deterministic and replayable runs, and
`AGENTS.md`'s definition of done asks for determinism under a fixed seed.
Neither had a test. Without one, the paired statistics in the ablation are not
actually paired and nobody would find out.

The fixtures in `fixtures/` are the committed bytes. If this test fails, either
the engine changed behaviour — in which case regenerate them deliberately with
`python scripts/emit_fixtures.py` and say so in the commit — or something is
non-deterministic, which is a bug.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from city.engine import runner
from city.engine.cascade import Indices
from city.topology import tiny
from scripts import emit_fixtures

FIXTURES = pathlib.Path(__file__).resolve().parents[2] / "fixtures"


def test_fixture_city_is_frozen():
    f = FIXTURES / "tiny_city.json"
    if not f.exists():
        pytest.fail(f"{f.name} missing. Run scripts/emit_fixtures.py.")
    assert f.read_text() == emit_fixtures.city_json(), (
        "the fixture city has drifted from city/topology/tiny.py. If the topology "
        "changed on purpose, regenerate with scripts/emit_fixtures.py and say so."
    )


def test_fixture_scenario_replays_byte_identically():
    f = FIXTURES / "tiny_scenario.json"
    if not f.exists():
        pytest.fail(f"{f.name} missing. Run scripts/emit_fixtures.py.")
    assert f.read_text() == emit_fixtures.scenario_json(), (
        "replaying the fixture seed did not reproduce the committed bytes. Either the "
        "engine changed behaviour, or something in it is non-deterministic — and if it "
        "is the latter, every paired comparison in eval/ is measuring stream drift."
    )


def test_two_runs_of_the_same_seed_agree():
    """Determinism within a process, independent of the committed fixture."""
    g = tiny.build()
    a = runner.run(g, emit_fixtures.HAZARD, seed=7, horizon_s=259_200.0, tick_s=300.0)
    b = runner.run(g, emit_fixtures.HAZARD, seed=7, horizon_s=259_200.0, tick_s=300.0)
    assert [e.model_dump() for e in a.events] == [e.model_dump() for e in b.events]


def _run(g, **kw):
    return runner.run(g, emit_fixtures.HAZARD, seed=emit_fixtures.SEED,
                      horizon_s=emit_fixtures.HORIZON_S, tick_s=300.0, **kw)


def _first_failures(scen) -> dict[str, float]:
    out: dict[str, float] = {}
    for e in scen.events:
        if e.kind == "failed" and e.node_id not in out:
            out[e.node_id] = e.t
    return out


def test_an_inert_intervention_changes_nothing():
    """Applying protection after the horizon must reproduce the base run exactly."""
    g = tiny.build()
    base = _run(g)
    late = _run(g, protected={n.id: 1.0 for n in g.nodes},
                protect_at_s=emit_fixtures.HORIZON_S * 10)
    assert [e.model_dump() for e in base.events] == [e.model_dump() for e in late.events]


def test_protecting_a_sink_leaves_every_other_node_untouched():
    """PAIRED RANDOMNESS — the fault that would have faked the entire ablation.

    The engine drew from one sequential generator, so protecting any node
    shifted every later draw for every other node: protecting 1 node of 1069
    moved total failures by -21, which is divergence, not effect. A precomputed
    (tick x node) field indexed by position makes a node's draw identical across
    arms whatever any other node did. See docs/FINDINGS.md.

    A sink — nothing depends on it, and it has no flow-peer to shed load onto —
    can affect nothing downstream by construction. So protecting one must leave
    every other node's failure time bit-for-bit unchanged. Under a sequential
    generator it would not, which is precisely the regression this catches.
    """
    g = tiny.build()
    ix = Indices.build(g)
    # A sink here means: nothing declares a dependency on it, and it has no
    # flow-peer to shed load onto. Transport is excluded because a road's
    # failure also slows every repair in the city through the access penalty,
    # so it is never structurally inert.
    sinks = [n.id for n in g.nodes
             if not ix.dependents.get(n.id) and not ix.siblings(n.id)
             and n.layer != "transport"]
    base = _run(g)
    base_first = _first_failures(base)
    target = next((s for s in sinks if s in base_first), None)
    if target is None:
        pytest.skip("no failing sink node in the fixture run")

    alt = _first_failures(_run(g, protected={target: 1.0}, protect_at_s=0.0))
    for nid, t in base_first.items():
        if nid == target:
            continue
        assert alt.get(nid) == t, (
            f"protecting the sink {target} moved {nid} from t={t} to t={alt.get(nid)}. "
            "The random field is not paired across arms, and every arm-to-arm "
            "difference in eval/ would be stream drift rather than effect."
        )
