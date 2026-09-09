# AGENTS.md — how coding agents work in this repo

Read `EXECUTION.md`, then `docs/00-SHARED-CONTRACTS.md`, then your lane file in `lanes/`. Then start.

## Rules

1. **Own your directory. Never edit another lane's.** If you are blocked by another lane, append to `docs/BLOCKERS.md` with the lane, the contract field, and what you need. Do not reach across and patch it.
2. **Code against contracts, not against other lanes' code.** If you are importing from another lane's internals, stop — that is a contract gap.
3. **Fixtures unblock you.** Everything in `fixtures/` is frozen and sufficient to build against. There is never a reason to sit idle.
4. **Commit every 90 minutes**, working or not, with a message that says what is not done yet.
5. **Tests before the thing they test**, for anything that touches a number that reaches a slide. Specifically: the leakage test before the first fit, the synthetic-kernel recovery test before the real fitter, the invariant test before the decision layer.
6. **Never hand-edit anything in `eval/results/` or `scenarios/`.** They are generated. If a number is wrong, the script is wrong.
7. **No LLM in the decision path.** See `EXECUTION.md` §6.5.
8. **When a result contradicts the plan, report it.** Do not tune until it agrees. `docs/FINDINGS.md` is where surprises go, and surprises are the most valuable output this project has.

## Definition of done for any task

- Types come from `contracts/`, generated not hand-written
- Deterministic under a fixed seed
- A test that would fail if the behaviour regressed
- Structured log line with the scenario correlation ID
- Runs on the fixture city in under 5 s, or it has a documented reason not to

## Disk

9.2 GB free. Check before you generate. `scripts/disk_check.sh` fails CI above 85 %. Store rollout summaries, never full trajectories.

## Communication

- `docs/BLOCKERS.md` — I am stuck, here is the exact contract field I need
- `docs/FINDINGS.md` — this surprised me, here is the evidence
- `docs/DECISIONS.md` — I made a judgement call, here is what and why
- `docs/LIMITATIONS.md` — this does not work and a judge will find it

All four are append-only, dated, and signed with the lane letter.
