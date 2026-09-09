# DECISIONS

Append-only. Dated. Signed with your lane letter.

| Date | Lane | Entry |
|---|---|---|
| 2026-09-09 | A | **Contracts source of truth is pydantic, not hand-written JSON Schema.** `docs/00-SHARED-CONTRACTS.md` §intro says JSON Schema is the source and Python is generated. Inverted: pydantic models in `contracts/` are the source, and `scripts/emit_schema.py` generates JSON Schema, from which `npx json-schema-to-typescript` generates TS. One source, two generated outputs — strictly fewer hand-written artefacts than the original plan, and pydantic validators (layer-prefix check on `Node.id`) cannot be expressed in plain JSON Schema. |
| 2026-09-09 | A | **Added `Node.buffer_s` to the contract.** Not in the original spec. Buffers are what create lead time; without them every dependency propagates instantly and there is nothing to predict, no deadline to compute and no reason for the project to exist. It has to be a first-class field, not a layer-specific `attrs` entry, because the decision layer reasons about it and `decision/` may not read layer-specific attributes. |
