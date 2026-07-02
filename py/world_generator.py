#!/usr/bin/env python3
"""Generate Step 1 world state for the emergent supply-chain simulator.

This file intentionally models only the physical world layout:
- agent nodes with unique coordinates,
- material deposit nodes with unique coordinates,
- randomized positive deposit amounts that sum to an exact total,
- validation,
- JSON output.

There is no mining, movement, recipe, trade, price, or economy logic here.
"""

import argparse
import json
import math
import random
from pathlib import Path


BASE_WORLD_WIDTH = 100_000
BASE_WORLD_HEIGHT = 100_000
WORLD_AREA_MULTIPLIER = 3

AGENT_COUNT = 8_200
DEPOSIT_COUNT = 10_000
TOTAL_RESOURCE_UNITS = 10_000_000

DEFAULT_SEED = 42
DEFAULT_OUTPUT_PATH = "generated_world.json"

RESOURCE_TYPES = [
    "iron_ore",
    "copper_ore",
    "coal",
    "stone",
    "crude_oil",
    "water",
    "wood",
    "uranium_ore",
    "fish",
]


def parse_args():
    """Parse configurable generation settings from the command line."""
    parser = argparse.ArgumentParser(
        description="Generate a circular 2D world with agents and material deposits."
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--base-world-width", type=int, default=BASE_WORLD_WIDTH)
    parser.add_argument("--base-world-height", type=int, default=BASE_WORLD_HEIGHT)
    parser.add_argument("--area-multiplier", type=float, default=WORLD_AREA_MULTIPLIER)
    parser.add_argument(
        "--world-radius",
        type=int,
        default=None,
        help="Override the generated circle radius. By default it is derived from the base area and area multiplier.",
    )
    parser.add_argument("--agent-count", type=int, default=AGENT_COUNT)
    parser.add_argument("--deposit-count", type=int, default=DEPOSIT_COUNT)
    parser.add_argument(
        "--total-resource-units",
        type=int,
        default=TOTAL_RESOURCE_UNITS,
    )
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    return parser.parse_args()


def compute_world_radius(base_world_width, base_world_height, area_multiplier):
    """Return an integer radius whose circle is about area_multiplier times larger.

    The old map was a 100,000 x 100,000 square. The new default map is a circle
    whose continuous area is approximately three times that old square:

        pi * radius^2 ~= base_width * base_height * area_multiplier
    """
    if base_world_width <= 0 or base_world_height <= 0:
        raise ValueError("Base world dimensions must be positive.")
    if area_multiplier <= 0:
        raise ValueError("Area multiplier must be positive.")

    target_area = base_world_width * base_world_height * area_multiplier
    return max(1, int(round(math.sqrt(target_area / math.pi))))


def build_metadata(
    seed,
    base_world_width,
    base_world_height,
    area_multiplier,
    world_radius,
    agent_count,
    deposit_count,
    total_resource_units,
):
    """Build the world metadata block used by generation and visualization."""
    world_width = (world_radius * 2) + 1
    world_height = (world_radius * 2) + 1
    target_world_area = base_world_width * base_world_height * area_multiplier

    return {
        "seed": seed,
        "world_shape": "circle",
        "base_world_width": base_world_width,
        "base_world_height": base_world_height,
        "area_multiplier": area_multiplier,
        "target_world_area": target_world_area,
        "actual_continuous_area": math.pi * (world_radius ** 2),
        "world_radius": world_radius,
        "world_center": [world_radius, world_radius],
        "world_width": world_width,
        "world_height": world_height,
        "agent_count": agent_count,
        "deposit_count": deposit_count,
        "total_resource_units": total_resource_units,
        "resource_types": RESOURCE_TYPES,
    }


def is_inside_circle(x, y, center_x, center_y, radius):
    """Return True when an integer coordinate is inside the circular map."""
    dx = x - center_x
    dy = y - center_y
    return (dx * dx) + (dy * dy) <= radius * radius


def generate_unique_coordinates(count, metadata, rng):
    """Return unique integer [x, y] coordinates inside the circular map.

    Coordinates use this convention:
    - x is in [0, world_width - 1]
    - y is in [0, world_height - 1]
    - the coordinate must also fall inside the world circle

    Agents and deposits are generated separately because they are allowed to
    overlap each other. Within each node type, coordinates must be unique.
    """
    world_width = metadata["world_width"]
    world_height = metadata["world_height"]
    center_x, center_y = metadata["world_center"]
    radius = metadata["world_radius"]
    rough_capacity = math.pi * (radius ** 2)

    if count > rough_capacity:
        raise ValueError("Not enough map cells to place all unique coordinates.")

    coordinates = set()
    while len(coordinates) < count:
        x = rng.randrange(world_width)
        y = rng.randrange(world_height)
        if is_inside_circle(x, y, center_x, center_y, radius):
            coordinates.add((x, y))

    # Sorting makes the JSON stable for the same seed, not just statistically
    # equivalent. That helps when comparing generated worlds across runs.
    return [[x, y] for x, y in sorted(coordinates)]


def generate_positive_amounts(count, total, rng):
    """Randomly split total units into count positive integer amounts.

    The trick:
    - sample count - 1 cut points inside the integer range,
    - sort them,
    - take adjacent differences.

    This always produces positive integers and the final sum is exactly total.
    """
    if count <= 0:
        raise ValueError("count must be positive")
    if total < count:
        raise ValueError("total must be at least count so every amount is positive")

    cut_points = sorted(rng.sample(range(1, total), count - 1))
    boundaries = [0, *cut_points, total]
    return [
        boundaries[index + 1] - boundaries[index]
        for index in range(count)
    ]


def build_agents(agent_count, metadata, rng):
    """Build agent nodes with unique ids and unique agent coordinates."""
    coordinates = generate_unique_coordinates(agent_count, metadata, rng)

    return [
        {
            "id": f"agent_{index:05d}",
            "type": "agent",
            "coordinate": coordinate,
        }
        for index, coordinate in enumerate(coordinates, start=1)
    ]


def build_deposits(deposit_count, total_resource_units, metadata, rng):
    """Build material deposit nodes with randomized type, amount, and coordinate."""
    coordinates = generate_unique_coordinates(deposit_count, metadata, rng)
    amounts = generate_positive_amounts(deposit_count, total_resource_units, rng)

    deposits = []
    for index, (coordinate, amount) in enumerate(zip(coordinates, amounts), start=1):
        deposits.append(
            {
                "id": f"deposit_{index:05d}",
                "type": "deposit",
                "item": rng.choice(RESOURCE_TYPES),
                "amount": amount,
                "coordinate": coordinate,
            }
        )

    return deposits


def build_world(
    seed=DEFAULT_SEED,
    base_world_width=BASE_WORLD_WIDTH,
    base_world_height=BASE_WORLD_HEIGHT,
    area_multiplier=WORLD_AREA_MULTIPLIER,
    world_radius=None,
    agent_count=AGENT_COUNT,
    deposit_count=DEPOSIT_COUNT,
    total_resource_units=TOTAL_RESOURCE_UNITS,
):
    """Create the full JSON-serializable world dictionary."""
    rng = random.Random(seed)
    if world_radius is None:
        world_radius = compute_world_radius(
            base_world_width,
            base_world_height,
            area_multiplier,
        )
    if world_radius <= 0:
        raise ValueError("World radius must be positive.")

    metadata = build_metadata(
        seed,
        base_world_width,
        base_world_height,
        area_multiplier,
        world_radius,
        agent_count,
        deposit_count,
        total_resource_units,
    )

    world = {
        "metadata": metadata,
        "agents": build_agents(agent_count, metadata, rng),
        "deposits": build_deposits(
            deposit_count,
            total_resource_units,
            metadata,
            rng,
        ),
    }

    validate_world(world)
    return world


def validate_coordinates(nodes, metadata, label):
    """Validate uniqueness and integer bounds for one node collection."""
    seen_coordinates = set()
    world_width = metadata["world_width"]
    world_height = metadata["world_height"]
    center_x, center_y = metadata["world_center"]
    radius = metadata["world_radius"]

    for node in nodes:
        coordinate = node.get("coordinate")
        if (
            not isinstance(coordinate, list)
            or len(coordinate) != 2
            or not all(isinstance(value, int) for value in coordinate)
        ):
            raise ValueError(f"{label} {node.get('id')} has invalid coordinate")

        x, y = coordinate
        if not (0 <= x < world_width and 0 <= y < world_height):
            raise ValueError(f"{label} {node.get('id')} is outside world bounds")
        if not is_inside_circle(x, y, center_x, center_y, radius):
            raise ValueError(f"{label} {node.get('id')} is outside circular map")

        coordinate_key = (x, y)
        if coordinate_key in seen_coordinates:
            raise ValueError(f"Duplicate {label} coordinate found: {coordinate}")

        seen_coordinates.add(coordinate_key)


def validate_world(world):
    """Check every hard requirement after generation."""
    metadata = world["metadata"]
    agents = world["agents"]
    deposits = world["deposits"]
    allowed_resources = set(metadata["resource_types"])

    if len(agents) != metadata["agent_count"]:
        raise ValueError("Agent count does not match metadata.")
    if len(deposits) != metadata["deposit_count"]:
        raise ValueError("Deposit count does not match metadata.")

    validate_coordinates(
        agents,
        metadata,
        "agent",
    )
    validate_coordinates(
        deposits,
        metadata,
        "deposit",
    )

    total_amount = 0
    for deposit in deposits:
        item = deposit.get("item")
        amount = deposit.get("amount")

        if item not in allowed_resources:
            raise ValueError(f"Unknown deposit item: {item}")
        if not isinstance(amount, int) or amount <= 0:
            raise ValueError(f"Deposit {deposit.get('id')} has invalid amount")

        total_amount += amount

    if total_amount != metadata["total_resource_units"]:
        raise ValueError(
            f"Deposit amounts sum to {total_amount}, "
            f"expected {metadata['total_resource_units']}."
        )

    return True


def save_world(world, output_path):
    """Write the generated world to disk as readable JSON."""
    path = Path(output_path)
    path.write_text(json.dumps(world, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    args = parse_args()
    world = build_world(
        seed=args.seed,
        base_world_width=args.base_world_width,
        base_world_height=args.base_world_height,
        area_multiplier=args.area_multiplier,
        world_radius=args.world_radius,
        agent_count=args.agent_count,
        deposit_count=args.deposit_count,
        total_resource_units=args.total_resource_units,
    )
    output_path = save_world(world, args.output)

    print(f"Wrote {output_path}")
    print(f"Seed: {world['metadata']['seed']}")
    print(f"Shape: {world['metadata']['world_shape']}")
    print(f"Radius: {world['metadata']['world_radius']}")
    print(f"Area multiplier: {world['metadata']['area_multiplier']}")
    print(f"Agents: {len(world['agents'])}")
    print(f"Deposits: {len(world['deposits'])}")
    print(
        "Total resource units: "
        f"{sum(deposit['amount'] for deposit in world['deposits'])}"
    )


if __name__ == "__main__":
    main()
