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

- `world_generator.py` creates and validates world JSON files.
- `visualize_world.py` serves the browser dashboard and world-management API.
- `worlds_index.json` tracks saved worlds for the dashboard sidebar. It is local runtime data.
- `worlds/` is where generated world JSON files are saved. It is local runtime data.
- `README.md` explains how to run the current step.

## Generate The World

```bash
python3 world_generator.py
```

This uses seed `42` by default and writes:

```text
worlds/world_seed_42.json
```

You can reproduce or change the world with:

```bash
python3 world_generator.py --seed 123 --output worlds/world_seed_123.json
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
  --output worlds/world_seed_42.json
```

The default radius is derived from:

```text
circle area = base_world_width * base_world_height * area_multiplier
```

With the defaults, the generated circle radius is about `97,721`.

## Run The Dashboard

```bash
python3 visualize_world.py
```

Then open the printed URL, usually:

```text
http://127.0.0.1:8000
```

The dashboard opens with a floating sidebar and loads the selected world
from `worlds_index.json`. If there are no saved worlds yet, it opens with an
empty list and the Create World panel ready to use.

Controls:

- drag to pan
- mouse wheel to zoom
- hover a node for details
- click a node to pin details
- use `Reset view` to fit the full world again
- use `Reload world` after changing the selected world file
- use the sidebar search to filter worlds by display name or seed
- use the create icon in the sidebar to open the Create World panel

## Generate A World From The UI

1. Run the dashboard with `python3 visualize_world.py`.
2. Open `http://127.0.0.1:8000`.
3. Click the create icon at the top of the sidebar.
4. Adjust the generation settings.
5. Click `Generate World`.

The dashboard calls the same `world_generator.py` logic, saves the new world as
a separate JSON file under `worlds/`, adds it to `worlds_index.json`, and loads
it into the canvas.

The Create World panel currently supports:

- `seed`
- `base_world_width`
- `base_world_height`
- `area_multiplier`
- `agent_count`
- `deposit_count`
- `total_resource_units`
- `output / world name`

This still only generates static world snapshots. It does not start a running
simulation.

## Saved Worlds

`worlds_index.json` is a lightweight dashboard index. It tracks:

- `id`
- `display_name`
- `seed`
- `file_path`
- `created_at`

Worlds created from the UI are saved separately in `worlds/`. The dashboard does
not require a global `generated_world.json` file anymore.

The dashboard sidebar reads from `worlds_index.json`. Clicking a world loads its
JSON into the visualization.

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

The generated file is shaped like the live simulation state. Instead of lists,
entities are stored in id-keyed maps so future runtime code can update one
object directly by id.

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
  "agents": {
    "agent_00001": {
      "id": "agent_00001",
      "type": "agent",
      "coordinate": [24, 52]
    }
  },
  "deposits": {
    "deposit_00001": {
      "id": "deposit_00001",
      "type": "deposit",
      "item": "iron_ore",
      "amount": 123,
      "coordinate": [24, 52]
    }
  },
  "machines": {},
  "coordinates": {
    "24,52": {
      "agents": ["agent_00001"],
      "deposits": ["deposit_00001"],
      "machines": []
    }
  }
}
```

The actual generated file includes all agents, deposits, and occupied coordinate
entries.

## Runtime Structure

- `agents` is a map keyed by agent id.
- `deposits` is a map keyed by deposit id.
- `machines` is a map keyed by machine id and is empty for now.
- `coordinates` is a sparse coordinate index keyed by `"x,y"`.
- each coordinate entry contains `agents`, `deposits`, and `machines` lists.
- multiple agents may occupy the same coordinate.
- deposits may share coordinates with agents, but not with other deposits.
- empty coordinates are not stored.
