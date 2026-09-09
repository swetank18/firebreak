"""Freeze the fixture city and one fixture scenario.

`AGENTS.md` rule 3: everything in `fixtures/` is frozen and sufficient to build
against, so no lane is ever blocked waiting for another. The directory was
empty, which made that promise untrue.

These files are also the determinism check. `EXECUTION.md` section 10 requires
that the same seed and the same city produce byte-identical output; the way to
hold a project to that is to commit the bytes and have CI diff against them.
"""

from __future__ import annotations

import json
from pathlib import Path

from city.engine import runner
from city.topology import tiny

OUT = Path(__file__).parent.parent / "fixtures"
# equipment_age over the full 72 h: the fixture city is 35 assets, and the flood
# footprint barely covers it, so this is the hazard that actually exercises a
# cascade at this scale. A fixture with no events cannot detect a regression.
HAZARD = "equipment_age"
SEED = 11
HORIZON_S = 259_200.0
TICK_S = 300.0


def scenario_json() -> str:
    g = tiny.build()
    s = runner.run(g, HAZARD, seed=SEED, horizon_s=HORIZON_S, tick_s=TICK_S)
    payload = s.model_dump(mode="json")
    # `metadata` carries the git sha and a wall-clock timestamp, which are not
    # part of the simulation and would make every run differ.
    payload.pop("metadata", None)
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def city_json() -> str:
    g = tiny.build()
    return json.dumps(g.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "tiny_city.json").write_text(city_json())
    (OUT / "tiny_scenario.json").write_text(scenario_json())
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()
