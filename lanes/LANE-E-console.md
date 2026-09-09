# LANE E — Console: the city view and the six keys

**You own:** `console/`
**You do not write:** anything else.
**You are not blocked after hour 6.** You build against `fixtures/scenario_demo.parquet` and never wait for a model.

Read `docs/00-SHARED-CONTRACTS.md` §7–8 and `docs/04-DEMO-RUNBOOK.md`.

## The rule that decides whether the demo survives

**The renderer computes nothing.**

Every number on screen is a field on a contract. If the console needs a value, it is added to the contract — it is never calculated in TypeScript. A branching ratio computed twice, once in Python and once in the browser, will disagree at hour 44 in front of judges.

This is the rule that saved the SAMANVAY demo and it will save this one.

## The 2D fallback exists from day one

Not at the end. **Day one.** A plain node-grid view reading the identical `Scenario` schema — no map tiles, no WebGL, no deck.gl. The same six keys work.

Venue projectors disable WebGL, run at strange aspect ratios and have no network for tiles. If the 3D view fails you press the same keys and nobody in the room knows anything went wrong.

## Build order

| Hours | Deliverable | Gate |
|---|---|---|
| 6–10 | Next.js scaffold, contract types wired, **2D fallback grid rendering a fixture** | Something replays |
| 10–16 | MapLibre + deck.gl, Chennai basemap tiles cached locally, 5 layers | The city exists |
| 16–22 | Cascade animation along edges with real delays, timeline scrubber | Beat 3 works |
| 22–28 | **Rewind + counterfactual replay** | Beats 4 and 5 work — this is the demo |
| 28–32 | Criticality panel, intervention cards, deadline countdown | Beat 2 and the urgency |
| 32–36 | Arms table view, pre-registration diff | Beat 6 |
| 36–40 | Keybindings 1–6, offline check, external-display test | Rehearsable |

## Stack

Next.js 16 + React + TypeScript + Tailwind. **MapLibre GL** for the basemap, **deck.gl** for the layers — not raw Three.js. This is geospatial data over a real city and deck.gl's `ScatterplotLayer` / `ArcLayer` / `TripsLayer` do in a day what Three.js does in a week, and look better doing it.

Tiles cached to disk at build time. **Never fetched live.** The demo runs with the network cable out.

## The visual language

| Layer | Colour | Mark |
|---|---|---|
| power | amber | nodes + feeder arcs |
| water | blue | nodes + trunk mains |
| transport | grey | road segments, red when impassable |
| telecom | violet | towers, dimming with battery |
| health | white | facilities — **these are the ones that matter, keep them brightest** |

Cross-layer `depends_on` edges are the story. Draw them faint by default, and **light them as the cascade travels** so a judge watches the failure move from power to water to hospital without anyone narrating it.

Criticality: node halo scaled by `branching_ratio`, and **the threshold at 1.0 is a hard visual break** — below it a thin ring, above it a filled pulse. The judges must be able to see the criterion, not just be told it.

## The rewind — beats 4 and 5

The single most important interaction in the project.

Scrub to `t=0`, call `POST /v1/counterfactual` with an action, receive a replayed `Scenario`, and play it back against the original in a ghosted overlay so both futures are visible at once. The counter for people affected runs on both.

Beat 5 must visibly fail. Do not soften it, do not animate it kindly. The whole pitch is that the obvious action does not work.

## Keybindings

`1`–`6` per the runbook. No other input. No terminal on screen, no IDE, no `npm run dev` visible to judges. A presenter timer is shown on the presenter's screen only.

## What you do not build

No settings page, no auth, no dark-mode toggle, no responsive mobile layout, no login. This is a control-room display shown once on a projector. Every hour spent on chrome is an hour not spent on the rewind.
