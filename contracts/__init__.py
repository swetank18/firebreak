"""FIREBREAK shared contracts.

Source of truth for every type that crosses a lane boundary. JSON Schema in
`contracts/schema/` and TypeScript in `contracts/ts/` are GENERATED from this
package by `scripts/gen_contracts.sh`. Never hand-edit either.

Contract freeze: hour 6. Changes after that need a dated entry in
docs/00-SHARED-CONTRACTS.md section 10.
"""

from contracts.city import CityGraph, Edge, Layer, Node
from contracts.events import Event, EventKind
from contracts.chains import CATASTROPHE_HOPS, Chain, NearMissCorpus, Split
from contracts.kernel import EdgeKernel, Estimator, Kernel
from contracts.criticality import Criticality, Damage
from contracts.decision import Action, ActionKind, Decision, Intervention
from contracts.scenario import Hazard, Scenario, ScenarioSummary
from contracts.frames import Frame

__all__ = [
    "CityGraph", "Edge", "Layer", "Node",
    "Event", "EventKind",
    "CATASTROPHE_HOPS", "Chain", "NearMissCorpus", "Split",
    "EdgeKernel", "Estimator", "Kernel",
    "Criticality", "Damage",
    "Action", "ActionKind", "Decision", "Intervention",
    "Hazard", "Scenario", "ScenarioSummary",
    "Frame",
]

CONTRACTS_VERSION = "1.0.0"
