# Deployment — what "industry grade" means, as a checklist

**Owner: Lane D.** Every line here is enforced by CI or it is a wish.

## Topology

```
                    ┌──────────── CLOUD ────────────┐
                    │  training · storage · reports │
                    │  corpus, kernels, eval, S3    │
                    └───────────────┬───────────────┘
                                    │ kernel push (versioned, signed)
                                    │ telemetry pull (async, lossy-ok)
┌────────────────── EDGE — the control room ───────────────────┐
│  ingest → detect → mine → criticality → decide → console     │
│  runs with the uplink cut. Postgres local. Kernel cached.    │
└──────────────────────────────────────────────────────────────┘
```

**The decision loop runs at the edge.** A city control room cannot depend on an internet uplink to decide whether to shed load — this is the same argument as not putting a distribution transformer behind a 4G modem. Cloud does training, storage and reporting. If the link is down, the last-good kernel keeps working and the console says how stale it is.

Put this on the architecture slide. It is the answer to "is this actually deployable."

## Services

| Service | Stack | Notes |
|---|---|---|
| `api` | FastAPI, Python 3.12, uvicorn | REST + WebSocket, `/v1` |
| `worker` | Python, multiprocessing over 16 cores | Monte Carlo rollouts, kernel fits. Bounded pool. |
| `db` | PostgreSQL 16 | live operational state, decisions, audit |
| `store` | DuckDB over Parquet+zstd | scenarios, corpus, eval. Append-once, read-many, single writer. |
| `console` | Next.js 16 + MapLibre GL + deck.gl | static export where possible |

DuckDB and Postgres both, deliberately: the analytical store and the operational store have opposite access patterns and forcing one to do both is how the soak test dies.

## Non-negotiable engineering

- **Contracts generated, not hand-written.** One JSON Schema source → pydantic + TypeScript. `scripts/gen_contracts.sh`. **CI fails on drift** — a hand-edited generated file is a build break.
- **Determinism.** Same seed + same `city_id` + same arm ⇒ byte-identical scenario Parquet. There is a CI test that runs a scenario twice and diffs the hash. Without this the ablation means nothing.
- **Correlation IDs.** Every log line inside a scenario run carries `scenario_id`; every decision carries `decision_id`. Structured JSON logs.
- **Migrations**, versioned, forward-only. Never `CREATE TABLE IF NOT EXISTS`.
- **Backpressure.** WebSocket frames are queued with a bound; on overflow drop *criticality* frames and never *decision* frames, and increment a visible counter. A console that silently misses a decision is worse than one that stutters.
- **Health, readiness, graceful shutdown.** The worker finishes its current rollout batch and checkpoints.
- **Redaction boundary.** `service/redact.py` strips `Event.cause` and `observed=False` before anything reaches `inference/` or `decision/`. Tested. See contracts §2.
- **Resource caps.** Rollout batch size and worker memory bounded by config, because 8 GB available and 2,000 rollouts × 2,000 nodes is not free.

## CI — what it must actually prove

Not "the tests pass." Two jobs, mirroring what worked on PACT:

**`ci`** — unit + integration tests, typecheck both languages, contract-drift check, AST invariant tests (`decision/` imports nothing from `city/`; no layer name appears in an executable line in `decision/`), leakage tests, disk check.

**`container`** — builds the image, starts it through compose, waits for healthcheck, then **drives the six demo beats against it over HTTP**:

- beat 2 asserts the two alerts have *equal* anomaly scores and *different* criticality
- beat 3 asserts the cascade reaches the health layer
- beat 4 asserts the intervention stops it under 3 hops
- **beat 5 asserts the obvious intervention FAILS** — if it ever succeeds, the demo's whole contrast is gone and CI must break
- beat 6 asserts `results.md` exists and every arm row is populated

Then: assert the SSE/WS stream is live, restart with the volume attached and check decisions and the kernel survived, drive every console surface headless, record the demo video against that image, soak for three minutes.

Only after all of that does the image get tagged. What ships is the artefact that was tested, not a second build.

## Deploy target

Needs a host that runs a **persistent process** — the worker pool, the WebSocket and the scenario runner all outlive a request, so this is not serverless-deployable. Render or Fly with a disk. Document the two traps in the single-port build in `deploy/README.md`.

Free tiers have no disk. If we deploy on one, scenarios do not survive a restart — say so in `LIMITATIONS.md` rather than letting a judge find an empty database.

## Security posture

Small but real, and it costs an hour:

- No PII anywhere. Events are asset IDs and timestamps. Populations are aggregate counts by service area. Write this down — "no appliance-level or person-level data ever leaves the site" is a deployment argument, not a privacy footnote.
- Kernel artefacts are signed and versioned; the edge refuses an unsigned kernel.
- API keys via environment only, never committed. A pre-commit hook greps for them.
- The console is read-only against live state. Interventions are *recommendations*; the system never actuates. Say this out loud — an advisory system is deployable in a real utility and an actuating one is not.
