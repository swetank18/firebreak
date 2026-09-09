# DECISIONS

Append-only. Dated. Signed with your lane letter.

| Date | Lane | Entry |
|---|---|---|
| 2026-09-09 | A | **Contracts source of truth is pydantic, not hand-written JSON Schema.** `docs/00-SHARED-CONTRACTS.md` §intro says JSON Schema is the source and Python is generated. Inverted: pydantic models in `contracts/` are the source, and `scripts/emit_schema.py` generates JSON Schema, from which `npx json-schema-to-typescript` generates TS. One source, two generated outputs — strictly fewer hand-written artefacts than the original plan, and pydantic validators (layer-prefix check on `Node.id`) cannot be expressed in plain JSON Schema. |
| 2026-09-09 | A | **Added `Node.buffer_s` to the contract.** Not in the original spec. Buffers are what create lead time; without them every dependency propagates instantly and there is nothing to predict, no deadline to compute and no reason for the project to exist. It has to be a first-class field, not a layer-specific `attrs` entry, because the decision layer reasons about it and `decision/` may not read layer-specific attributes. |
| 2026-09-09 | A | **FORK RESOLVED: we write our own cascade engine on `wntr` + `pandapower`. We do NOT build on InfraRisk's code.** Verified by reading `infrarisk/src/physical/interdependencies.py`. See `city/INFRARISK_NOTES.md` for the evidence. InfraRisk is credited as design precedent and cited on slide 7 — it is no longer a dependency. |
| 2026-09-09 | A | **Renamed `platform/` to `service/`.** The directory named in `EXECUTION.md` §5 shadowed Python's stdlib `platform` module, which pandas, pyarrow and pytest all import. Every tool worked from outside the repo and nothing worked from inside it, surfacing as a misleading `AttributeError: module 'platform' has no attribute 'python_implementation'`. Regression test in `service/tests/test_no_stdlib_shadowing.py` asserts no top-level package shadows a stdlib name. Found before six lanes ran in parallel against the layout. |
