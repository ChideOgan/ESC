# ESC Step 1: Randomized 2D World

This folder contains Step 1 of the emergent supply-chain simulator.

It only generates and visualizes a bounded 2D world with:

- 8,200 agent nodes
- 10,000 material deposit nodes
- exactly 10,000,000 total resource units across deposits
- integer coordinates inside a circular map
- default circular area is about 3x the old 100,000 x 100,000 square

There is no mining, movement, recipe, trade, price, market, or supply-chain logic yet.

## Files

- `world_generator.py` creates and validates `generated_world.json`.
- `generated_world.json` is the generated world state.
- `visualize_world.py` serves a browser-based canvas visualizer.
- `README.md` explains how to run the current step.

## Generate The World

```bash
python3 world_generator.py
```

This uses seed `42` by default and writes:

```text
generated_world.json
```

You can reproduce or change the world with:

```bash
python3 world_generator.py --seed 123 --output generated_world.json
```

Useful options:

```bash
python3 world_generator.py \
  --seed 42 \
  --base-world-width 100000 \
  --base-world-height 100000 \
  --area-multiplier 3 \
  --agent-count 8200 \
  --deposit-count 10000 \
  --total-resource-units 10000000 \
  --output generated_world.json
```

The default radius is derived from:

```text
circle area = base_world_width * base_world_height * area_multiplier
```

With the defaults, the generated circle radius is about `97,721`.

## Visualize The World

```bash
python3 visualize_world.py
```

Then open the printed URL, usually:

```text
http://127.0.0.1:8000
```

The visualizer loads directly from `generated_world.json`.

Controls:

- drag to pan
- mouse wheel to zoom
- hover a node for details
- click a node to pin details
- use `Reset view` to fit the full world again
- use `Reload JSON` after regenerating the world

## Resource Colors

Agents are always black circles.

Deposits use fixed colors by resource type so the same item has the same color across runs:

- `iron_ore`
- `copper_ore`
- `coal`
- `stone`
- `crude_oil`
- `water`
- `wood`
- `uranium_ore`
- `fish`

## JSON Shape

```json
{
  "metadata": {
    "seed": 42,
    "world_shape": "circle",
    "base_world_width": 100000,
    "base_world_height": 100000,
    "area_multiplier": 3,
    "target_world_area": 30000000000,
    "actual_continuous_area": 30000305924.445,
    "world_radius": 97721,
    "world_center": [97721, 97721],
    "world_width": 195443,
    "world_height": 195443,
    "agent_count": 8200,
    "deposit_count": 10000,
    "total_resource_units": 10000000,
    "resource_types": [
      "iron_ore",

      "copper_ore",

      "coal",

      "stone",

      "crude_oil",

      "water",

      "wood",

      "uranium_ore",

      "fish"
    ]
  },
  "agents": [],
  "deposits": []
}
```

The actual generated file includes all agents and deposits.
