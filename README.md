# ESC: Emergent Supply Chain Benchmark

ESC is an open-source multi-agent simulation framework for studying whether recognizable supply-chain structures can emerge from decentralized agents operating inside a constrained world.

The project is not meant to hardcode a supply chain. It is meant to define the minimum world requirements and primitive agent abilities needed for supply-chain behavior to appear through interaction.

## Research Question

Can agents placed in a shared world with finite resources, distance, production constraints, limited information, and asynchronous communication naturally produce recognizable supply-chain behavior without manually defining suppliers, manufacturers, firms, markets, or bullwhip effects?

The long-term goal is to create a synthetic benchmark environment for autonomous supply-chain and agentic commerce research.

## Core Hypothesis

Supply-chain decisions depend on more than knowing where things are. They depend on the physical consequences of action: distance, time, reachability, delay, scarcity, congestion, bottlenecks, and downstream effects.

ESC starts with a simple 2D world because it is a controlled place to test whether an agent can learn spatial and action physics from experience:

```text
state + action -> consequence
```

The hypothesis is that if a model can learn useful decision-making behavior in a 2D world, then richer versions of the same idea may help agents reason about real-world geography and logistics. The possible advantage is not better map lookup. It is better action intuition: understanding routes, costs, delays, constraints, and bottlenecks as things experienced through movement and interaction.

## Synthetic Data Motivation

Real supply-chain data is often private, commercially sensitive, fragmented, stale, or unavailable. ESC is meant to generate synthetic but structured data from objective primitives and event logs instead of relying on proprietary company data.

The benchmark should eventually produce records such as movements, observations, production events, messages, trades, inventories, shortages, and delivery delays. Higher-level structures like suppliers, manufacturers, hubs, bottlenecks, and bullwhip-like effects should then be measured from those records after the fact, not manually assigned in advance.

## Design Philosophy

Supply-chain structures should be derived from observed behavior, not created as simulation classes.

For example, ESC should not create a `Supplier` class just because suppliers are expected. Instead, agents should only receive primitive abilities such as:

- move
- observe
- mine
- carry
- place or use machines
- produce items
- store inventory
- send messages
- trade

If an agent repeatedly provides inputs to other agents, then it can later be classified as a supplier from the event log or transaction graph. The role emerges from behavior.

## Structures We Want To Observe

The benchmark is intended to test whether familiar supply-chain structures can arise without hardcoding them:

- suppliers
- manufacturers
- haulers and logistics providers
- firms
- recurring trade relationships
- specialization
- inventory buildup
- shortages
- bottlenecks
- bullwhip-like demand amplification
- regional production hubs
- dependency chains between agents

## Current Implementation

The current version is still an early world and lab layer, not a full economy.

Implemented so far:

- bounded 2D circular coordinate world
- reproducible world generation from random seeds
- configurable agent and material-deposit generation from base world width and height
- deterministic 0-9 surface-code function computed from seed, coordinate, and chaos level
- map-based live-world JSON structure
- id-keyed maps for agents, deposits, and machines
- sparse coordinate index keyed by `"x,y"`
- dashboard UI for creating, saving, selecting, deleting, and inspecting worlds
- canvas visualization with pan, zoom, hover, click, legend, and selected-node details
- experimental one-agent brain lab with blind random path forecasts
- static surface-code prediction shell that predicts every step of a path before movement reveals any answer
- fixed 100-path grading batches with selectable forecast horizon, pass-grade controls, and optional automatic level increases
- cumulative per-world training-time tracking in `worlds_index.json`

The world still has no mining, trade, pricing, production, messaging, route planning, firm formation, or LLM agent behavior.

## Near-Term Roadmap

The next milestone is to turn the current static brain/world lab into a learning simulation core:

- world mutation functions
- event queue
- simulation clock
- event logs
- validated movement events
- weight-update rules for correcting wrong surface predictions
- dashboard controls for step, run, pause, and reset
- live dashboard updates from mutated world state

The immediate goal is to prove that:

1. world state can change safely,
2. the coordinate index stays correct,
3. events can be scheduled and processed,
4. agent movement and learning can happen through time,
5. the dashboard can show updated state without corrupting saved worlds.

Only after that should ESC add mining, machines, messages, trade, production, agent decisions, pricing, and strategy benchmarking.

## Why This Matters

If supply-chain-like behavior emerges from primitives, ESC can become a benchmark for comparing strategies before applying them to real-world operations.

Future strategies to test include:

- centralized planning
- decentralized planning
- information sharing
- supplier diversification
- buffer inventory
- faster communication infrastructure
- pricing and negotiation strategies
- routing strategies
- demand forecasting strategies

The benchmark can then compare whether those strategies reduce costs, delays, shortages, bottlenecks, or bullwhip-like amplification.

## Run The Dashboard

From a Terminal with the local helper commands configured:

```bash
esc-start
```

Then open:

```text
http://127.0.0.1:8000
```

Reusing the same numeric seed intentionally reproduces the same generated world.
Use a different seed when you want a different generated layout.
The generated JSON stores occupied entities only; blank-coordinate surface values
are recomputed from the math function instead of being saved for every point.

For one-agent worlds, the dashboard also includes live play/pause brain controls.
The current frozen baseline runs on the local Python server, so it can continue
forecasting after the browser tab is closed as long as the server is still
running and the Mac is awake.
When the brain is paused, the dashboard saves cumulative elapsed training time
for that world in `worlds_index.json`.

The Training Console lets you select or type a Forecast Length and adjust the
per-step Pass Grade with matching minus/input/plus controls. It shows only the
current batch progress and its most recent Grade. Each batch contains 100 blind
paths.
The dashboard records a grade only after the full batch completes; the grade is
the lowest per-step accuracy, so every step position must reach the selected
threshold before the batch succeeds and training stops. When Auto Increase
Length is enabled, a passing batch instead advances to the next forecast length
and continues. The predictor is
deliberately frozen for now, so it will not improve until weight-update rules
are designed and implemented.

To keep the Mac awake while the dashboard runs:

```bash
ESC_KEEP_AWAKE=1 esc-start
```

Useful local commands:

```bash
esc-status
esc-stop
esc-start
```

Manual fallback:

```bash
cd /Users/chide/Desktop/ESC/py
python3 visualize_world.py
```

## Repository Layout

```text
bin/
  esc-start       start the local dashboard on port 8000
  esc-stop        stop the local dashboard on port 8000
  esc-status      check local dashboard status

py/
  brain.py            run the one-agent internal world-model experiment
  world_generator.py   generate and validate world JSON
  visualize_world.py   serve the dashboard and world-management API
```
