# LANE D — Platform: API, streaming, persistence, CI, deploy

**You own:** `platform/`, `scripts/`, `.github/`, `Dockerfile`, `docker-compose.yml`, `deploy/`
**You do not write:** `city/`, `inference/`, `decision/`, `console/`, `eval/`
**You are not blocked by anyone after hour 6.** Contracts are enough.

Read `docs/00-SHARED-CONTRACTS.md` §8 and `docs/05-DEPLOYMENT.md`.

## Hour zero

Docker is **not installed** on the build machine. Either install it or decide now that we ship with compose-less run scripts and say so in `deploy/README.md`. Decide by hour 2 — CI's container job depends on it.

Python 3.12.3, Node v20.20.2, git, 16 cores, 14 GB RAM, **9.2 GB disk**.

## Build order

| Hours | Deliverable | Gate |
|---|---|---|
| 6–8 | `scripts/gen_contracts.sh`, pydantic + TS generated from JSON Schema, drift check | **Every lane typechecks** |
| 8–12 | FastAPI skeleton, all `/v1` routes returning fixtures | Lane E is unblocked forever |
| 12–16 | `platform/redact.py` + the leakage boundary test | Inference is safe to wire |
| 16–20 | WebSocket stream, bounded queue, backpressure, `seq` | Console can replay live |
| 20–24 | Postgres + migrations, DuckDB store, correlation IDs | State survives restart |
| 24–30 | Worker pool, bounded memory, checkpointing | 4,200-run job is safe to launch |
| 30–36 | Dockerfile, compose, healthchecks, graceful shutdown | Image builds and starts |
| 36–44 | **CI drives the six beats against the container** | The thing that proves it works |
| 44+ | Deploy, backup video, `LIMITATIONS.md` |

## The redaction boundary — your most important 40 lines

`platform/redact.py` strips `Event.cause` and every `observed=False` row before anything reaches `inference/` or `decision/`.

Test it two ways: a runtime test that a redacted Event has no `cause`, and an **AST grep** asserting the string `cause` does not appear in any executable line under `inference/` or `decision/`. The runtime test catches accidents; the AST test catches someone at hour 30 adding a "just for debugging" access that never gets removed.

This boundary is worth more than any model in the repo. Everything Lane F reports is meaningless if it leaks.

## The invariant tests

Also yours, in `platform/tests/test_invariants.py`:

1. `decision/` imports nothing from `city/`
2. No executable line in `decision/` contains a layer name (`"power"`, `"water"`, `"transport"`, `"telecom"`, `"health"`) — the string-literal loophole
3. No file in `eval/results/` or `scenarios/` has been hand-edited (compare against a manifest hash)
4. Determinism: run one scenario twice, diff the Parquet hash

Test 4 is the one that saves the ablation. Without byte-identical replay, paired statistics are not paired.

## CI — what it must prove

Two jobs. Not "the tests pass."

**`ci`** — unit + integration, typecheck both languages, contract drift, the four invariant tests, leakage tests, `scripts/disk_check.sh`.

**`container`** — build image, start through compose, wait for healthcheck, then drive the six demo beats over HTTP and **assert what each beat is meant to prove**:

- beat 2: the two alerts have equal `anomaly_score` and different `branching_ratio`
- beat 3: the cascade reaches the health layer
- beat 4: the intervention holds it under 3 hops
- **beat 5: the obvious intervention FAILS.** If it ever succeeds, CI breaks. The contrast is the pitch; a green beat 5 means the demo is dead and nobody noticed.
- beat 6: `results.md` exists with every arm row populated

Then assert the WS stream is live, restart with the volume attached and verify decisions and the kernel survived, drive the console headless, record the demo video against that image, soak three minutes. Only then tag the image.

## Backpressure

WebSocket frames are queued with a bound. On overflow, **drop `criticality` frames and never `decision` frames**, and increment a visible counter. A console that silently misses a decision is worse than one that stutters, and a judge will not forgive a demo that shows the wrong state confidently.

## Disk

`scripts/disk_check.sh` fails CI above 85 %. Budget: scenarios ≤ 2 GB, eval ≤ 1 GB, `node_modules` ≤ 600 MB. Run it at every phase gate. Discovering this at hour 40 costs the submission.
