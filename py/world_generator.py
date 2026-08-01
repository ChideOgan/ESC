#!/usr/bin/env python3
"""Generate Step 1 world state for the emergent supply-chain simulator.

This file intentionally models only the physical world layout:
- agent nodes with coordinates,
- material deposit nodes with unique coordinates,
- an id-keyed live-state structure,
- a sparse coordinate occupancy index,
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


DEFAULT_WORLD_RADIUS = 56_419
DEFAULT_CHAOS_LEVEL = 0.5
SURFACE_CODE_COUNT = 10

AGENT_COUNT = 1
DEPOSIT_COUNT = 10_000
TOTAL_RESOURCE_UNITS = 10_000_000

DEFAULT_SEED = 42
DEFAULT_OUTPUT_PATH = "worlds/world_seed_42.json"
ENTITY_TYPES = ("agents", "deposits", "machines")

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
    parser.add_argument("--radius", type=int, default=DEFAULT_WORLD_RADIUS)
    parser.add_argument(
        "--chaos-level",
        type=float,
        default=DEFAULT_CHAOS_LEVEL,
        help="0.0 gives smoother surface codes; 1.0 gives noisier surface codes.",
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


def validate_chaos_level(chaos_level):
    """Validate the surface-code chaos setting."""
    if not isinstance(chaos_level, (int, float)) or isinstance(chaos_level, bool):
        raise ValueError("Chaos level must be a number.")
    if not 0.0 <= chaos_level <= 1.0:
        raise ValueError("Chaos level must be between 0.0 and 1.0.")
    return float(chaos_level)


def validate_world_radius(world_radius):
    """Return a valid positive integer radius for the circular world."""
    if isinstance(world_radius, bool) or not isinstance(world_radius, int):
        raise ValueError("World radius must be an integer.")
    if world_radius <= 0:
        raise ValueError("World radius must be positive.")
    return world_radius


def deterministic_hash(seed, x, y, salt=0):
    """Return a stable integer hash for seed/coordinate inputs.

    Python's built-in hash is randomized between processes, so this uses a tiny
    integer mixer instead. This is for deterministic terrain-like signals, not
    cryptography.
    """
    value = (
        (int(seed) * 374_761_393)
        + (int(x) * 668_265_263)
        + (int(y) * 2_147_483_647)
        + (int(salt) * 1_274_126_177)
    ) & 0xFFFFFFFF
    value ^= value >> 13
    value = (value * 1_274_126_177) & 0xFFFFFFFF
    value ^= value >> 16
    return value


def deterministic_unit_noise(seed, x, y, salt=0):
    """Return a stable pseudo-random value in [0.0, 1.0]."""
    return deterministic_hash(seed, x, y, salt) / 0xFFFFFFFF


def smoothstep(value):
    """Smooth interpolation curve for deterministic coordinate noise."""
    return value * value * (3.0 - (2.0 * value))


def lerp(start, end, amount):
    """Linear interpolation."""
    return start + ((end - start) * amount)


def smooth_noise(seed, x, y, scale, salt=0):
    """Return deterministic smooth noise by interpolating hashed grid corners."""
    if scale <= 0:
        raise ValueError("Noise scale must be positive.")

    scaled_x = x / scale
    scaled_y = y / scale
    x0 = math.floor(scaled_x)
    y0 = math.floor(scaled_y)
    x1 = x0 + 1
    y1 = y0 + 1
    tx = smoothstep(scaled_x - x0)
    ty = smoothstep(scaled_y - y0)

    n00 = deterministic_unit_noise(seed, x0, y0, salt)
    n10 = deterministic_unit_noise(seed, x1, y0, salt)
    n01 = deterministic_unit_noise(seed, x0, y1, salt)
    n11 = deterministic_unit_noise(seed, x1, y1, salt)

    top = lerp(n00, n10, tx)
    bottom = lerp(n01, n11, tx)
    return lerp(top, bottom, ty)


def surface_code(seed, x, y, chaos_level=DEFAULT_CHAOS_LEVEL):
    """Return the deterministic 0-9 surface code for one coordinate.

    This deliberately does not store blank-coordinate data in the world JSON.
    Any part of the simulator can recompute the same value from seed, coordinate,
    and chaos level when it needs to know the local surface signal.
    """
    chaos_level = validate_chaos_level(chaos_level)
    broad = smooth_noise(seed, x, y, scale=8192, salt=11)
    medium = smooth_noise(seed, x, y, scale=1024, salt=23)
    structured_value = (0.65 * broad) + (0.35 * medium)
    chaotic_value = deterministic_unit_noise(seed, x, y, salt=97)
    value = ((1.0 - chaos_level) * structured_value) + (chaos_level * chaotic_value)
    return min(SURFACE_CODE_COUNT - 1, int(value * SURFACE_CODE_COUNT))


def rotating_surface_origin(metadata, world_tick):
    """Return the integer boundary coordinate used as the surface-field origin.

    The origin starts at twelve o'clock and travels one world-coordinate of arc
    length per tick, completing one circuit in roughly ``2 * pi * radius``
    ticks. Keeping the returned coordinate integral lets the terrain function
    continue to use integer x/y inputs.
    """
    radius = validate_world_radius(int(metadata["world_radius"]))
    center_x, center_y = metadata["world_center"]
    orbit_radius = radius
    step_size = int(metadata.get("surface_rotation_step_size", 1))
    # Start at twelve o'clock, then move counterclockwise by one arc-length
    # coordinate per world tick.
    angle = (math.pi / 2) + ((int(world_tick) * step_size) / orbit_radius)

    return [
        int(math.floor(center_x + (orbit_radius * math.cos(angle)) + 0.5)),
        int(math.floor(center_y - (orbit_radius * math.sin(angle)) + 0.5)),
    ]


def rotating_surface_code(metadata, x, y, world_tick):
    """Return a surface code from x/y coordinates relative to the moving origin."""
    origin_x, origin_y = rotating_surface_origin(metadata, world_tick)
    return surface_code(
        metadata.get("seed", 0),
        x - origin_x,
        y - origin_y,
        metadata.get("chaos_level", DEFAULT_CHAOS_LEVEL),
    )


def build_metadata(
    seed,
    chaos_level,
    world_radius,
    agent_count,
    deposit_count,
    total_resource_units,
):
    """Build the world metadata block used by generation and visualization."""
    chaos_level = validate_chaos_level(chaos_level)
    world_radius = validate_world_radius(world_radius)
    world_width = (world_radius * 2) + 1
    world_height = (world_radius * 2) + 1

    return {
        "seed": seed,
        "world_shape": "circle",
        "chaos_level": chaos_level,
        "surface_code_count": SURFACE_CODE_COUNT,
        "surface_coordinate_mode": "rotating_relative",
        "surface_rotation_step_size": 1,
        "actual_continuous_area": math.pi * (world_radius**2),
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


def coordinate_key(coordinate):
    """Return the JSON-safe sparse-index key for a coordinate."""
    return f"{coordinate[0]},{coordinate[1]}"


def empty_coordinate_entry():
    """Return the standard occupancy entry for one occupied coordinate."""
    return {"agents": [], "deposits": [], "machines": []}


def generate_coordinate(metadata, rng):
    """Return one random integer [x, y] coordinate inside the circular map."""
    world_width = metadata["world_width"]
    world_height = metadata["world_height"]
    center_x, center_y = metadata["world_center"]
    radius = metadata["world_radius"]

    while True:
        x = rng.randrange(world_width)
        y = rng.randrange(world_height)
        if is_inside_circle(x, y, center_x, center_y, radius):
            return [x, y]


def generate_coordinates(count, metadata, rng):
    """Return count integer coordinates inside the circular map.

    Coordinates use this convention:
    - x is in [0, world_width - 1]
    - y is in [0, world_height - 1]
    - the coordinate must also fall inside the world circle
    - repeated coordinates are allowed

    This is used for agents because multiple agents can pass through each other
    and occupy the same point.
    """
    coordinates = [generate_coordinate(metadata, rng) for _ in range(count)]

    # Sorting makes the JSON stable for the same seed, not just statistically
    # equivalent. That helps when comparing generated worlds across runs.
    return sorted(coordinates)


def generate_unique_coordinates(count, metadata, rng):
    """Return unique integer [x, y] coordinates inside the circular map.

    Deposits use this because two deposits cannot occupy the same coordinate.
    """
    radius = metadata["world_radius"]
    rough_capacity = math.pi * (radius**2)

    if count > rough_capacity:
        raise ValueError("Not enough map cells to place all unique coordinates.")

    coordinates = set()
    while len(coordinates) < count:
        coordinates.add(tuple(generate_coordinate(metadata, rng)))

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
    return [boundaries[index + 1] - boundaries[index] for index in range(count)]


def build_agents(agent_count, metadata, rng):
    """Build id-keyed agent nodes.

    Agents may share coordinates with agents, deposits, or future machines.
    """
    coordinates = generate_coordinates(agent_count, metadata, rng)
    agents = {}

    for index, coordinate in enumerate(coordinates, start=1):
        agent_id = f"agent_{index:05d}"
        agents[agent_id] = {
            "id": agent_id,
            "type": "agent",
            "coordinate": coordinate,
        }

    return agents


def build_deposits(deposit_count, total_resource_units, metadata, rng):
    """Build id-keyed deposit nodes with randomized type, amount, and coordinate."""
    coordinates = generate_unique_coordinates(deposit_count, metadata, rng)
    amounts = generate_positive_amounts(deposit_count, total_resource_units, rng)

    deposits = {}
    for index, (coordinate, amount) in enumerate(zip(coordinates, amounts), start=1):
        deposit_id = f"deposit_{index:05d}"
        deposits[deposit_id] = {
            "id": deposit_id,
            "type": "deposit",
            "item": rng.choice(RESOURCE_TYPES),
            "amount": amount,
            "coordinate": coordinate,
        }

    return deposits


def build_coordinate_index(agents, deposits, machines):
    """Build a sparse coordinate -> occupants index from live entity maps."""
    coordinates = {}

    for collection_name, entities in (
        ("agents", agents),
        ("deposits", deposits),
        ("machines", machines),
    ):
        for entity_id, entity in entities.items():
            key = coordinate_key(entity["coordinate"])
            coordinates.setdefault(key, empty_coordinate_entry())[collection_name].append(
                entity_id
            )

    return coordinates


def build_world(
    seed=DEFAULT_SEED,
    world_radius=DEFAULT_WORLD_RADIUS,
    chaos_level=DEFAULT_CHAOS_LEVEL,
    agent_count=AGENT_COUNT,
    deposit_count=DEPOSIT_COUNT,
    total_resource_units=TOTAL_RESOURCE_UNITS,
):
    """Create the full JSON-serializable world dictionary."""
    rng = random.Random(seed)
    chaos_level = validate_chaos_level(chaos_level)
    world_radius = validate_world_radius(world_radius)

    metadata = build_metadata(
        seed,
        chaos_level,
        world_radius,
        agent_count,
        deposit_count,
        total_resource_units,
    )

    agents = build_agents(agent_count, metadata, rng)
    deposits = build_deposits(
        deposit_count,
        total_resource_units,
        metadata,
        rng,
    )
    machines = {}

    world = {
        "metadata": metadata,
        "agents": agents,
        "deposits": deposits,
        "machines": machines,
        "coordinates": build_coordinate_index(agents, deposits, machines),
    }

    validate_world(world)
    return world


def validate_coordinate_value(entity, metadata, label):
    """Validate one entity coordinate."""
    world_width = metadata["world_width"]
    world_height = metadata["world_height"]
    center_x, center_y = metadata["world_center"]
    radius = metadata["world_radius"]
    coordinate = entity.get("coordinate")

    if (
        not isinstance(coordinate, list)
        or len(coordinate) != 2
        or not all(isinstance(value, int) for value in coordinate)
    ):
        raise ValueError(f"{label} {entity.get('id')} has invalid coordinate")

    x, y = coordinate
    if not (0 <= x < world_width and 0 <= y < world_height):
        raise ValueError(f"{label} {entity.get('id')} is outside world bounds")
    if not is_inside_circle(x, y, center_x, center_y, radius):
        raise ValueError(f"{label} {entity.get('id')} is outside circular map")


def validate_entity_map(entities, metadata, label):
    """Validate an id-keyed entity map and return coordinate usage."""
    if not isinstance(entities, dict):
        raise ValueError(f"{label} collection must be an id-keyed map.")

    coordinate_usage = {}
    for entity_id, entity in entities.items():
        if not isinstance(entity, dict):
            raise ValueError(f"{label} {entity_id} must be an object.")
        if entity_id != entity.get("id"):
            raise ValueError(f"{label} key {entity_id} does not match inner id.")

        validate_coordinate_value(entity, metadata, label)
        coordinate_usage.setdefault(coordinate_key(entity["coordinate"]), []).append(
            entity_id
        )

    return coordinate_usage


def validate_world(world):
    """Check every hard requirement after generation."""
    metadata = world["metadata"]
    agents = world["agents"]
    deposits = world["deposits"]
    machines = world["machines"]
    coordinates = world["coordinates"]
    allowed_resources = set(metadata["resource_types"])
    chaos_level = metadata.get("chaos_level", DEFAULT_CHAOS_LEVEL)
    validate_chaos_level(chaos_level)

    if len(agents) != metadata["agent_count"]:
        raise ValueError("Agent count does not match metadata.")
    if len(deposits) != metadata["deposit_count"]:
        raise ValueError("Deposit count does not match metadata.")
    if not isinstance(machines, dict):
        raise ValueError("Machines collection must be an id-keyed map.")
    if not isinstance(coordinates, dict):
        raise ValueError("Coordinates must be a sparse coordinate index map.")

    agent_coordinates = validate_entity_map(agents, metadata, "agent")
    deposit_coordinates = validate_entity_map(deposits, metadata, "deposit")
    machine_coordinates = validate_entity_map(machines, metadata, "machine")

    for key, deposit_ids in deposit_coordinates.items():
        if len(deposit_ids) > 1:
            raise ValueError(f"Multiple deposits share coordinate {key}.")

    total_amount = 0
    for deposit in deposits.values():
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

    expected_coordinate_keys = (
        set(agent_coordinates) | set(deposit_coordinates) | set(machine_coordinates)
    )
    actual_coordinate_keys = set(coordinates)
    if actual_coordinate_keys != expected_coordinate_keys:
        missing = sorted(expected_coordinate_keys - actual_coordinate_keys)[:5]
        extra = sorted(actual_coordinate_keys - expected_coordinate_keys)[:5]
        raise ValueError(
            "Coordinate index keys do not match entity coordinates. "
            f"Missing: {missing}. Extra: {extra}."
        )

    for key, entry in coordinates.items():
        if set(entry) != set(ENTITY_TYPES):
            raise ValueError(f"Coordinate {key} has invalid occupancy keys.")

        for collection_name in ENTITY_TYPES:
            if not isinstance(entry[collection_name], list):
                raise ValueError(
                    f"Coordinate {key} {collection_name} entry must be a list."
                )

        if not any(entry[collection_name] for collection_name in ENTITY_TYPES):
            raise ValueError(f"Coordinate {key} is fully empty.")

        for agent_id in entry["agents"]:
            if agent_id not in agents:
                raise ValueError(f"Coordinate {key} references unknown agent {agent_id}.")
            if coordinate_key(agents[agent_id]["coordinate"]) != key:
                raise ValueError(f"Coordinate {key} mismatches agent {agent_id}.")

        for deposit_id in entry["deposits"]:
            if deposit_id not in deposits:
                raise ValueError(
                    f"Coordinate {key} references unknown deposit {deposit_id}."
                )
            if coordinate_key(deposits[deposit_id]["coordinate"]) != key:
                raise ValueError(f"Coordinate {key} mismatches deposit {deposit_id}.")

        for machine_id in entry["machines"]:
            if machine_id not in machines:
                raise ValueError(
                    f"Coordinate {key} references unknown machine {machine_id}."
                )
            if coordinate_key(machines[machine_id]["coordinate"]) != key:
                raise ValueError(f"Coordinate {key} mismatches machine {machine_id}.")

    return True


def save_world(world, output_path):
    """Write the generated world to disk as readable JSON."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(world, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    args = parse_args()
    world = build_world(
        seed=args.seed,
        world_radius=args.radius,
        chaos_level=args.chaos_level,
        agent_count=args.agent_count,
        deposit_count=args.deposit_count,
        total_resource_units=args.total_resource_units,
    )
    output_path = save_world(world, args.output)

    print(f"Wrote {output_path}")
    print(f"Seed: {world['metadata']['seed']}")
    print(f"Shape: {world['metadata']['world_shape']}")
    print(f"Radius: {world['metadata']['world_radius']}")
    print(f"Chaos level: {world['metadata']['chaos_level']}")
    print(f"Agents: {len(world['agents'])}")
    print(f"Deposits: {len(world['deposits'])}")
    print(f"Machines: {len(world['machines'])}")
    print(f"Occupied coordinates: {len(world['coordinates'])}")
    print(
        "Total resource units: "
        f"{sum(deposit['amount'] for deposit in world['deposits'].values())}"
    )


if __name__ == "__main__":
    main()
