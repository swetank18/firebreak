# LIMITATIONS

Append-only. Dated. Signed with your lane letter.

| Date | Lane | Entry |
|---|---|---|
| 2026-09-09 | A | **Cascade sizes are exponential-tailed, not power-law.** We set a day-1 realism gate expecting a power law, found the opposite via a Vuong likelihood-ratio test (exponential favoured at every x_min, p ~ 0), and report it rather than tuning to hit the target. The literature's power-law result is established for transmission-grid blackouts; this is a multi-sector urban lifeline network where it is not. Consequence: our system sits subcritical, so absolute cascade frequencies should not be read as calibrated to a real city. Relative comparisons between arms — which is what every result in this project rests on — are unaffected, because all arms run on the identical simulator. |
| 2026-09-09 | A | Power and water asset topology is **synthesised and geo-anchored**, not real. Asset-level utility data is not public in India. Road and facility counts follow the real city's shape. |
| 2026-09-09 | A | Layer physics is a **capacity-flow resolver, not hydraulics or power flow**. `wntr` and `pandapower` plug in behind `city/engine/physics.py` later. The cascade mechanism is the contribution; the hydraulics are not. |
| 2026-09-09 | A | Flood exposure uses **latitude as a proxy for elevation**, because elevation is not in the topology. |
| 2026-09-09 | A | Intervention costs are **abstract units**, not procurement reality. Ratios are defensible; absolutes are not. |
