"""THE LEAKAGE BOUNDARY.

`docs/03-EVALUATION.md` names five assertions and requires them written before
the first fit. They were not written, and two of them would have caught real
faults that shipped:

  * event ids restarted at e000001 in every scenario, so pooling a training
    corpus collided 8,263 of 12,877 ids and silently overwrote mined links
  * every scenario runs over the same 0..horizon clock, so a pooled flat corpus
    let the miner attribute a failure in one scenario to a failure in another —
    2.3x more links than mining each scenario properly, the surplus all phantom

Neither is a leak of ground truth. Both are the same class of error the leakage
tests exist to catch: a boundary that is assumed rather than enforced.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from city.engine import runner
from city.topology import chennai
from inference.kernel import counting
from inference.mining.miner import NearMissMiner
from service.redact import observability, redact

REPO = pathlib.Path(__file__).resolve().parents[2]
GUARDED = ("inference", "decision")


@pytest.fixture(scope="module")
def g():
    # The real city, not the 35-node fixture. Over four short runs the fixture
    # city produces 36 events and no unobserved ones at all, so every assertion
    # below would pass while proving nothing. A leakage test on a corpus too
    # thin to leak is theatre. Half-horizon keeps the whole module under 2 s.
    return chennai.build()


@pytest.fixture(scope="module")
def scenarios(g):
    return [runner.run(g, "monsoon_flood", seed=s, horizon_s=129_600.0, tick_s=300.0)
            for s in range(3)]


# --- 2. ground truth is unreachable from inference/ and decision/ -------------

def test_no_module_under_inference_or_decision_reads_event_cause():
    """AST, not grep: a docstring may say `cause`, an expression may not read it.

    Writing `cause=` is allowed in exactly one place — the synthetic generator
    that FABRICATES known ground truth for the kernel-recovery test. Reading
    someone else's `.cause` is the leak; constructing it when you are the one
    inventing the answer key is not.
    """
    offenders = []
    for pkg in GUARDED:
        for path in sorted((REPO / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "cause":
                    if isinstance(node.ctx, ast.Load):
                        offenders.append(f"{path.relative_to(REPO)}:{node.lineno}")
    assert not offenders, (
        "ground truth is read inside the inference/decision boundary: "
        + "; ".join(offenders)
        + ". If the miner sees Event.cause it is not mining, it is reading the answer key."
    )


# --- 3. no unobserved event, and no cause, crosses the boundary ---------------

def test_redact_strips_cause_and_unobserved(scenarios):
    raw = [e for s in scenarios for e in s.events]
    assert any(e.cause for e in raw), "fixture has no caused events; the test proves nothing"
    assert any(not e.observed for e in raw), "fixture has no unobserved events"

    clean = redact(raw)
    assert all(e.cause is None for e in clean)
    assert all(e.observed for e in clean)
    assert 0.0 < observability(raw) < 1.0


# --- 1 & 5. scenario-level splitting, never event-level ----------------------

def test_event_ids_are_unique_across_scenarios(scenarios):
    ids = [e.event_id for s in scenarios for e in s.events]
    assert len(ids) == len(set(ids)), (
        f"{len(ids) - len(set(ids))} event ids collide across scenarios. Ids used to "
        "restart at e000001 every run, which silently overwrote links when a training "
        "corpus was pooled."
    )


def test_mining_never_attributes_across_a_scenario_boundary(g, scenarios):
    """The leak that looks like a great result.

    Every scenario shares one 0..horizon clock, so concatenating them interleaves
    unrelated runs and the window condition attributes freely between them.
    """
    miner = NearMissMiner(g)
    owner = {}
    for s in scenarios:
        for e in redact(s.events):
            owner[e.event_id] = s.scenario_id

    corpora = [redact(s.events) for s in scenarios]
    for link in miner.links_many(corpora):
        assert owner[link.parent] == owner[link.child], (
            f"link {link.parent} -> {link.child} crosses a scenario boundary "
            f"({owner[link.parent]} -> {owner[link.child]})"
        )


def test_pooling_a_flat_corpus_would_have_been_wrong(g, scenarios):
    """Guards the fix itself: the flat form must be measurably different.

    If this ever stops holding, either the scenarios no longer overlap in time
    or the miner has changed, and the corpus-shaped API has stopped earning its
    keep — in which case delete it deliberately rather than by accident.
    """
    miner = NearMissMiner(g)
    corpora = [redact(s.events) for s in scenarios]
    proper = len(miner.links_many(corpora))
    pooled = len(miner.links([e for c in corpora for e in c]))
    assert pooled > proper, (
        "concatenating scenarios no longer inflates the link count, so this "
        "protection may be obsolete"
    )


# --- 4. the fit depends on the train corpus and nothing else -----------------

def test_kernel_fit_is_a_pure_function_of_the_train_corpus(g, scenarios):
    train, held_out = scenarios[:2], scenarios[2:]
    corpora = [redact(s.events) for s in train]
    a = counting.fit(g, corpora, horizon_s=259_200.0 * len(train), corpus_id="t", seed=0)
    b = counting.fit(g, corpora, horizon_s=259_200.0 * len(train), corpus_id="t", seed=0)
    assert a.edges.keys() == b.edges.keys()
    assert all(a.edges[k].alpha == b.edges[k].alpha for k in a.edges)

    # adding held-out scenarios MUST change the fit; if it does not, the split
    # is not doing anything and the held-out set is not held out
    more = counting.fit(g, corpora + [redact(s.events) for s in held_out],
                        horizon_s=259_200.0 * len(scenarios), corpus_id="t2", seed=0)
    assert (more.edges.keys() != a.edges.keys()
            or any(more.edges[k].n_obs != a.edges[k].n_obs for k in a.edges)), (
        "adding scenarios did not change the kernel — the corpus is not reaching the fit"
    )
