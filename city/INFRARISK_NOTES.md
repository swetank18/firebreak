# InfraRisk — what it is, and why we are not building on it

**Read 2026-09-09 at commit `HEAD` of `srijithbalakrishnan/dreaminsg-integrated-model` (BSD-3).**
Verified by reading the source, not from documentation or memory.

## What it actually does

- `infrarisk/src/physical/interdependencies.py` — `DependencyTable`, two pandas DataFrames:
  `wp_table` (water↔power) and `access_table` (transport access).
- Layer physics via `wntr>=0.3.0` (water) and `pandapower>=2.6.0` (power). Real engines.
- `network_recovery.py` + `repair_crews.py` — restoration crews that travel over the
  *current* transport network.
- `hazards/` — track, radial, fragility-based, random, custom.
- `cyber/` — sensors and a controller (SCADA).
- Testbeds: Micropolis, Shelby County. Conda-only (`environment.yml`), 476 MB checkout.

## Why we are not building on it

Four findings, each verified in source:

1. **No buffers anywhere.** Grep for `buffer|backup|generator|fuel|battery|reserve` across
   `src/` returns only `buffer_of_impact` — a *geometric* hazard radius in metres, unrelated.
   `update_dependencies()` fires immediately: `if res_motor.p_mw == 0` then the pump goes off
   in the same timestep.

   **This is disqualifying.** Buffers are what create lead time. Without them every dependency
   propagates instantly, there is nothing to predict ahead of, no deadline to compute, and no
   reason for this project to exist. Adding buffers means rewriting the propagation entirely.

2. **Three hard-coded coupling types.** `add_pump_motor_coupling`, `add_pump_loadmotor_coupling`,
   `add_gen_reserv_coupling`. `update_dependencies()` is an if/elif chain over
   `(water_type, power_type)` string pairs that directly manipulates `wntr` controls. We need
   roughly nine dependency kinds across five layers; each would be another hard-coded branch.

3. **Three layers, not five.** Power, water, transport only. No telecom and no health — and
   health is where our damage function is measured.

4. **String-parsed component identity.** `get_compon_details()` regexes names like `"Pump"` and
   `"Motor"`. Our contract uses typed, layer-prefixed IDs. Fighting this costs more than
   replacing it.

## What we keep, and credit

Three ideas carry over, and they are cited rather than copied:

- **The architecture pattern** — an integrated multi-layer network with `wntr` and `pandapower`
  as layer physics engines. We use the same engines.
- **Transport access as a first-class dependency** (`add_transpo_access`,
  `transpo_access_no_redundancy`). This is precedent for our diesel edge: the published
  literature already treats road access as a dependency, so our key mechanism is not invented.
- **Repair crews routed over the damaged network**, which produces the "a flooded road hurts
  you twice" effect we need in restoration.

## How this is stated on slide 7

> InfraRisk (Balakrishnan et al., 2022) established the water–power–transport integrated
> simulation pattern, and we follow its architecture and use the same physics engines. Its
> `DependencyTable` propagates failure immediately through three hard-coded coupling types,
> with no buffer model. Buffers are what create lead time, and lead time is what our method
> predicts — so we implement buffered dependency propagation, which is exactly the gap.

**This is a stronger position than reusing the code.** It is honest, it credits the prior work
properly, and it names our contribution against a published baseline instead of hiding inside it.
