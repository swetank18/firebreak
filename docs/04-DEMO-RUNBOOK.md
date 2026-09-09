# Demo runbook — six keys, nothing typed

**Owner: Lane E, with Lane F on the numbers.** Rehearse it five times. The person presenting does not touch a terminal.

Everything runs from `fixtures/scenario_demo.parquet`, frozen. **Offline. No network. No live model call.** If the wifi dies mid-pitch nothing changes.

---

## The six beats

### `1` — The city
Chennai loads. Five layers fade in: power (amber), water (blue), roads (grey), telecom (violet), hospitals (white). Rotate once, settle.

> "Five systems. Twelve hundred assets. Nobody manages them together, because nobody owns them together."

### `2` — Two alarms
Monsoon scenario starts. Two amber alerts appear — Substation 14 and Substation 22 — with **identical anomaly scores, 0.61 and 0.61**, shown side by side. Firebreak flags 22 red and leaves 14 amber.

> "Same alarm. Same score. Every monitoring system in this city treats these as identical. We don't."

Pause. Let them read the two identical numbers.

### `3` — Do nothing
Play at 60×. 14 does nothing all night. 22 propagates: substation → Kodungaiyur pumping → water mains → four hospitals → generators drawing down → **the diesel route floods** → generators die at hour six. Counter climbs to 60,000 people, four hospitals dark.

> "The branching ratio at 22 was 1.4. Above one, a cascade grows. That is the whole criterion."

### `4` — Rewind and intervene
Scrub back to `t=0`. Apply Firebreak's top intervention — **pre-position diesel at the two hospitals on the flood-exposed route**, cost 2 units, deadline 34 minutes. Replay. The cascade dies at hop two. Counter stops at 3,000.

> "Not the biggest node. Not the loudest alarm. A road, because the road carried the fuel."

### `5` — The intervention that fails
Rewind again. Apply the human-obvious action: **harden the hospital itself**, the most critical asset on the map, same cost budget. Replay. **It still cascades.** Counter climbs to 51,000.

> "This is what an experienced operator does. It is the right instinct and it does not work, because the hospital was never the problem."

**Beat 5 must fail.** If a code change ever makes beat 5 succeed, the demo is broken — CI asserts the failure, not a 200.

### `6` — The evidence
Cut to the arms table. Seven rows. AUC column: A1 at chance, A3 and A4 well above. Pre-registration diff beside it, including where we were wrong.

> "Ranking alerts by how loud they are predicts catastrophe about as well as a coin. We pre-registered that claim before we ran it. Here is the diff."

Stop. Do not thank them yet — take the question.

---

## Rules

- **The renderer computes nothing.** Every number on screen is a field in the scenario file.
- **2D fallback exists from day one** — same schema, plain node grid, no map tiles, no WebGL. If deck.gl fails on the venue projector, press the same six keys.
- **Backup video committed**, recorded against the built image, same six beats. If the laptop dies, play it.
- Timer visible to the presenter only.
- No terminal on screen. No IDE. No `npm run dev` in front of judges.

## Likely questions

**Is any of this an LLM?** No. Kernel estimation is a Hawkes MLE, rollout is Monte Carlo, intervention search is enumeration and scoring. Every decision is auditable line by line. An LLM writes nothing the decision depends on.

**Is the city real?** Roads and hospitals are a real OSM extract. Power and water asset topology is synthesised and geo-anchored, because it is not public — and that is stated in our limitations before you ask.

**Hasn't Tsinghua already done this?** I³ predicts cascade probability and volume. It selects no intervention and it trains on synthetic sweeps. We run it unmodified as arm A5 — it is our baseline, not our competitor.

**Where does the near-miss data come from in a real deployment?** SCADA historians already log every trip, every voltage excursion, every pump restart. Utilities keep years of it and analyse almost none of it. We need event timestamps and asset IDs — nothing else, and nothing that identifies a person.

**What if the branching ratio is wrong?** Then the deadline is wrong and we say so — every `Criticality` carries a bootstrap CI, and thin edges (`n_obs` small) widen it. Calibration is reported as a reliability diagram, because a safety number nobody can trust is not a safety number.

**Have you tested on real cascade data?** No. Real datasets underneath the layers, a simulated city on top, and honest labelling of which is which. A real utility historian feed is the ask.

## The ask — close on this, not on "thank you"

Two things. **One utility or municipal historian feed** — the near-miss data already exists and nobody is looking at it. And **a mentor who has sat in a city control room during a monsoon**, because the intervention cost model is the part we cannot get right from outside.
