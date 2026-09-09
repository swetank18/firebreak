# The thesis, and how to kill it

## The claim

Cascading failure prediction has been stuck on a data problem. Catastrophes are rare — three per decade in a given city — so there is nothing to train on. The field's response has been to generate synthetic scenario sweeps (I³ trains on generated scenarios; PI-GN-JODE uses 20,000 simulated cases per grid) and to declare interdependency coefficients by expert elicitation (the Input–Output Inoperability Model and the multilayer-network literature).

Both responses inherit the assumptions of whoever wrote the generator or the matrix. That is exactly the failure mode that makes real cascades surprising.

**Our claim is that the training data already exists and nobody has collected it.**

A cascade that killed a city and a cascade that stopped after two hops are the same stochastic process, observed at different points in its life. Same edges, same delays, same propagation mechanics — one simply ran out of momentum. The short ones are abundant, they sit unlabelled in every operational log, and nobody records them *because nobody was hurt*.

This is not a new idea in safety. It is the entire basis of aviation's Aviation Safety Reporting System, built on the premise that accidents do not happen without precursors and precursors are abundant. NASA has published supervised-learning work on precursor identification in exactly this data. What has never been done is applying it to a **networked, multi-sector cascade** and using it to estimate a **propagation kernel** rather than a per-event risk score.

## The formalism

A cascade is a branching process. Model it as a multivariate Hawkes process with an exponential kernel — the same mathematics seismology uses in the ETAS model, where aftershock productivity is estimated from thousands of small tremors and used to reason about large sequences.

For each directed dependency edge `i → j`, `α_ij` is the expected number of failures at `j` produced by one failure at `i`. Collect these into a branching matrix `G`.

- `ρ(G) < 1` — subcritical. Cascades die out.
- `ρ(G) ≥ 1` — supercritical. Cascades explode.

The local branching ratio of node `i` in the current state is `n_i = Σ_j α_ij · s_j(t)`, where `s_j(t)` is susceptibility — how stressed `j` already is.

**`n_i > 1` is the definition of a dangerous abnormality.** It is testable, it is one number, it is independent of how loud the alarm is, and it is exactly what the organisers asked for when they wrote *"distinguish normal abnormality from dangerous abnormality."*

## Why this is not just centrality

The honest objection, and the reason H4 exists.

Betweenness centrality on the dependency graph already ranks nodes by how much passes through them. If cascade risk were purely topological, centrality would capture it and the learned kernel would be decoration.

Three reasons it should not be, each of which is a measurable prediction:

1. **Centrality is static; susceptibility is not.** The same substation is safe on a dry Tuesday and critical during a monsoon when its downstream pump has no diesel buffer. `s_j(t)` is where the time-dependence enters and centrality has no equivalent.
2. **Centrality has no delays.** It cannot tell you a cascade takes six hours rather than six minutes, and the intervention deadline — the operationally useful output — comes entirely from `β`.
3. **Centrality is unweighted by actual propagation probability.** A high-betweenness edge that has never once propagated a failure in 10,000 near-misses is not dangerous, and only the data knows that.

**If H4 fails and centrality matches the kernel on ranking, we report it and we point at (2).** The kernel would still be load-bearing for *timing* and *intervention choice* even if it were not for *ranking*, and that is a real finding, not a consolation prize.

## How to kill this project

Any of these, honestly measured, sinks the thesis. Look for them actively.

1. **The miner recovers nothing.** If mined chains do not match ground-truth `cause` above chance, near-misses are not observable in this data and the whole premise fails. Lane F measures chain-recovery precision/recall against `Event.cause` — this is the single most important diagnostic in the project.
2. **The fitter cannot recover a synthetic kernel.** Tested before the real fitter exists. If it fails here, everything downstream is noise.
3. **The simulator telegraphs its parameters.** If learned `1/β` equals `nominal_delay_s` on every edge, we have fit the generator's config file, not a physical process. Lane B tests for this explicitly.
4. **Cascade sizes are not heavy-tailed.** Then the city model does not behave like real infrastructure and no result transfers. This is the day-1 gate.
5. **Interventions do not beat random.** If counterfactual search does not beat picking a random node at equal budget, there is no decision layer, only an expensive ranker.

Each of these has a named owner and a test. A project that cannot say how it would be wrong has not been evaluated.
