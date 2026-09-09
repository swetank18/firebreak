"""Emit JSON Schema from the pydantic contracts. Source of truth is Python."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

import contracts as C

OUT = Path(__file__).parent.parent / "contracts" / "schema"

MODELS = [
    C.Node, C.Edge, C.CityGraph,
    C.Event,
    C.Chain, C.NearMissCorpus,
    C.EdgeKernel, C.Kernel,
    C.Damage, C.Criticality,
    C.Action, C.Intervention, C.Decision,
    C.Scenario, C.ScenarioSummary,
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for m in MODELS:
        schema = m.model_json_schema()
        (OUT / f"{m.__name__}.json").write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    frame = TypeAdapter(C.Frame).json_schema()
    (OUT / "Frame.json").write_text(json.dumps(frame, indent=2, sort_keys=True) + "\n")
    print(f"wrote {len(MODELS) + 1} schemas to {OUT}")


if __name__ == "__main__":
    main()
