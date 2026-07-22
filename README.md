# ESC: Emergent Supply Chain Benchmark

ESC is an open-source multi-agent simulation framework for studying whether recognizable supply-chain structures can emerge from decentralized agents operating inside a constrained world.

The project is not meant to hardcode a supply chain. It is meant to define the minimum world requirements and primitive agent abilities needed for supply-chain behavior to appear through interaction.

## Research Question

Can agents placed in a shared world with finite resources, distance, production constraints, limited information, and asynchronous communication naturally produce recognizable supply-chain behavior without manually defining suppliers, manufacturers, firms, markets, or bullwhip effects?

The long-term goal is to create a synthetic benchmark environment for autonomous supply-chain and agentic commerce research, especially because real supply-chain data is often private, commercially sensitive, fragmented, or unavailable.

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

The current version is Step 1: world generation and inspection.

Implemented so far:

- bounded 2D coordinate world
- reproducible world generation from random seeds
- 8,200 agent nodes
- 10,000 material deposit nodes
- 10,000,000 total resource units
- map-based live-world JSON structure
- id-keyed agent and deposit maps
- sparse coordinate index keyed by `"x,y"`
- empty machines map placeholder
- dashboard UI for creating, saving, selecting, and inspecting generated worlds
- pan, zoom, hover, click, legend, and selected-node details in the dashboard

The world is intentionally not intelligent yet. There is no mining, trade, pricing, production, messaging, route planning, firm formation, or LLM agent behavior.

## Near-Term Roadmap

The next milestone is the simulation core:

- world mutation functions
- event queue
- simulation clock
- simple movement events
- event logs
- dashboard controls for step/run/pause
- live dashboard updates from mutated world state

The immediate goal is to prove that:

1. world state can change safely,
2. the coordinate index stays correct,
3. events can be scheduled and processed,
4. agent movement can happen through time,
5. the dashboard can show updated state.

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
  world_generator.py   generate and validate world JSON
  visualize_world.py   serve the dashboard and world-management API
  README.md            implementation notes for the current Python prototype
```
