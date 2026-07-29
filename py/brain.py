#!/usr/bin/env python3
"""One-agent internal world-model experiment for ESC.

This is the first runnable brain implementation.

It intentionally does not implement mining, trade, production, messages,
economics, or multi-agent behavior. It only tests whether one agent can learn a
compressed internal model of a generated world from movement and observation.

Hard experiment rule:
    The brain does not store a coordinate -> contents lookup table.

What the brain stores:
    - a tiny fixed base vector,
    - fixed decoder numbers,
    - sequence score state for the current lab draft.

What the simulator stores:
    - the true world JSON,
    - event/training logs,
    - debug metrics.

So the environment may know the real world, but the brain must answer from its
learned weights.
"""

import argparse
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path

from world_generator import (
    DEFAULT_CHAOS_LEVEL,
    coordinate_key,
    empty_coordinate_entry,
    is_inside_circle,
    surface_code,
)


NO_ITEM = "none"
DEFAULT_INDEX_PATH = "worlds_index.json"
DEFAULT_LOG_DIR = ".logs"
ACTION_DELTAS = {
    "move_left": (-1, 0),
    "move_right": (1, 0),
    "move_up": (0, -1),
    "move_down": (0, 1),
}
REVERSE_ACTION = {
    "move_left": "move_right",
    "move_right": "move_left",
    "move_up": "move_down",
    "move_down": "move_up",
}
DIRECTION_CODES = {
    "move_up": 1,
    "move_down": 2,
    "move_left": 3,
    "move_right": 4,
}


class StaticTensorSequenceBrain:
    """Fixed-number sequence predictor for the first surface-code lab.

    This is intentionally dumb. It does not learn yet. It takes a direction,
    combines that direction with a tiny internal vector, and decodes the result
    into a surface-code guess from 0-9.
    """

    def __init__(
        self,
        base_vector=None,
        decoder_bias=7,
        decoder_step_weight=3,
        max_state_values=2048,
    ):
        self.base_vector = list(base_vector or [5])
        self.decoder_bias = decoder_bias
        self.decoder_step_weight = decoder_step_weight
        self.max_state_values = max_state_values

    def initial_state(self):
        """Return the starting vector for one sequence attempt."""
        return list(self.base_vector)

    def predict_surface(self, sequence_state, action, step_number):
        """Predict the next coordinate's surface code without updating weights."""
        action_code = DIRECTION_CODES[action]
        generated_values = [action_code * value for value in sequence_state]
        next_state = [*sequence_state, *generated_values]

        if len(next_state) > self.max_state_values:
            next_state = next_state[-self.max_state_values :]

        weighted_sum = sum(
            (index + 1) * value for index, value in enumerate(generated_values)
        )
        brain_number = (
            weighted_sum
            + (action_code * self.decoder_bias)
            + (step_number * self.decoder_step_weight)
            + len(next_state)
        )
        predicted_surface = abs(int(brain_number)) % 10

        return {
            "predicted_surface": predicted_surface,
            "brain_number": brain_number,
            "action_code": action_code,
            "state_size_before": len(sequence_state),
            "state_size_after": len(next_state),
            "generated_preview": generated_values[:8],
            "next_state": next_state,
        }


def clamp(value, low, high):
    """Clamp a number into a closed interval."""
    return max(low, min(high, value))


def sigmoid(value):
    """Numerically stable sigmoid."""
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def softmax(logits):
    """Return a probability vector for logits."""
    max_logit = max(logits)
    exps = [math.exp(value - max_logit) for value in logits]
    total = sum(exps)
    return [value / total for value in exps]


def dot(weights, features):
    """Small dependency-free dot product."""
    return sum(weight * feature for weight, feature in zip(weights, features))


def vector_update(weights, features, scale):
    """In-place linear weight update."""
    for index, feature in enumerate(features):
        weights[index] += scale * feature


def json_dump(path, data):
    """Write readable JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def json_load(path):
    """Read JSON."""
    return json.loads(path.read_text(encoding="utf-8"))


def timestamp():
    """Return a compact UTC-ish timestamp for local filenames."""
    return time.strftime("%Y%m%dT%H%M%S")


@dataclass
class SpatialFeatureEncoder:
    """Coordinate encoder used by the learned world model.

    This is a random Fourier-style feature map. The projections are learned
    configuration, not observed coordinate memory.
    """

    world_width: int
    world_height: int
    projections: list

    @classmethod
    def create(cls, metadata, feature_pairs, rng):
        """Create deterministic random spatial features for one run."""
        projections = []
        for _ in range(feature_pairs):
            # Mixed low/high frequencies help the model represent smooth
            # structure and sharper location-specific variation.
            frequency_scale = rng.choice((1, 2, 4, 8, 16, 32))
            fx = rng.uniform(-frequency_scale, frequency_scale)
            fy = rng.uniform(-frequency_scale, frequency_scale)
            phase = rng.random()
            projections.append([fx, fy, phase])

        return cls(
            world_width=metadata["world_width"],
            world_height=metadata["world_height"],
            projections=projections,
        )

    def normalize(self, coordinate):
        """Normalize integer coordinates to roughly [-1, 1]."""
        x, y = coordinate
        x_denominator = max(1, self.world_width - 1)
        y_denominator = max(1, self.world_height - 1)
        x_norm = (2.0 * x / x_denominator) - 1.0
        y_norm = (2.0 * y / y_denominator) - 1.0
        return x_norm, y_norm

    def encode(self, coordinate):
        """Return numeric coordinate features."""
        x_norm, y_norm = self.normalize(coordinate)
        features = [
            1.0,
            x_norm,
            y_norm,
            x_norm * x_norm,
            y_norm * y_norm,
            x_norm * y_norm,
        ]

        for fx, fy, phase in self.projections:
            angle = 2.0 * math.pi * ((fx * x_norm) + (fy * y_norm) + phase)
            features.append(math.sin(angle))
            features.append(math.cos(angle))

        return features

    def to_dict(self):
        """Serialize encoder config."""
        return {
            "world_width": self.world_width,
            "world_height": self.world_height,
            "projections": self.projections,
        }

    @classmethod
    def from_dict(cls, data):
        """Load encoder config."""
        return cls(
            world_width=data["world_width"],
            world_height=data["world_height"],
            projections=data["projections"],
        )


@dataclass
class LinearCellWorldModel:
    """Tiny learned model: coordinate -> expected cell contents.

    The model has no explicit table of visited coordinates. It only stores
    weights over coordinate features.
    """

    encoder: SpatialFeatureEncoder
    item_classes: list
    deposit_weights: list
    item_weights: list
    amount_weights: list
    learning_rate: float
    amount_scale: float

    @classmethod
    def create(cls, metadata, feature_pairs, learning_rate, rng):
        """Create a small randomly initialized world model."""
        encoder = SpatialFeatureEncoder.create(metadata, feature_pairs, rng)
        item_classes = [NO_ITEM, *metadata["resource_types"]]
        feature_count = len(encoder.encode([0, 0]))

        def weights():
            return [rng.uniform(-0.01, 0.01) for _ in range(feature_count)]

        average_deposit = metadata["total_resource_units"] / max(
            1, metadata["deposit_count"]
        )
        amount_scale = max(1.0, average_deposit * 10.0)

        return cls(
            encoder=encoder,
            item_classes=item_classes,
            deposit_weights=weights(),
            item_weights=[weights() for _ in item_classes],
            amount_weights=weights(),
            learning_rate=learning_rate,
            amount_scale=amount_scale,
        )

    def predict_cell(self, coordinate):
        """Predict the cell contents at a coordinate."""
        features = self.encoder.encode(coordinate)
        deposit_probability = sigmoid(dot(self.deposit_weights, features))
        item_logits = [dot(weights, features) for weights in self.item_weights]
        item_values = softmax(item_logits)
        amount_probability = sigmoid(dot(self.amount_weights, features))

        item_probabilities = {
            item: probability
            for item, probability in zip(self.item_classes, item_values)
            if item != NO_ITEM
        }
        best_item_index = max(range(len(item_values)), key=item_values.__getitem__)
        best_item = self.item_classes[best_item_index]

        return {
            "coordinate": list(coordinate),
            "deposit_probability": deposit_probability,
            "best_item": None if best_item == NO_ITEM else best_item,
            "best_item_probability": item_values[best_item_index],
            "item_probabilities": item_probabilities,
            "amount_estimate": amount_probability * self.amount_scale,
            "confidence": max(deposit_probability, 1.0 - deposit_probability),
            "uncertainty": deposit_probability * (1.0 - deposit_probability) * 4.0,
        }

    def train_on_observation(self, observation):
        """Update model weights from one observed cell."""
        coordinate = observation["coordinate"]
        cell = observation["cell"]
        features = self.encoder.encode(coordinate)

        deposit_target = 1.0 if cell["has_deposit"] else 0.0
        deposit_prediction = sigmoid(dot(self.deposit_weights, features))
        deposit_error = deposit_target - deposit_prediction
        vector_update(
            self.deposit_weights,
            features,
            self.learning_rate * deposit_error,
        )

        item_target = cell["item"] if cell["has_deposit"] else NO_ITEM
        target_index = self.item_classes.index(item_target)
        item_logits = [dot(weights, features) for weights in self.item_weights]
        item_probabilities = softmax(item_logits)

        for index, weights in enumerate(self.item_weights):
            target_value = 1.0 if index == target_index else 0.0
            vector_update(
                weights,
                features,
                self.learning_rate * (target_value - item_probabilities[index]),
            )

        amount_target = clamp(cell["amount"] / self.amount_scale, 0.0, 1.0)
        amount_prediction = sigmoid(dot(self.amount_weights, features))
        amount_error = amount_target - amount_prediction
        # Include sigmoid derivative so amount updates do not explode.
        amount_step = amount_error * amount_prediction * (1.0 - amount_prediction)
        vector_update(
            self.amount_weights,
            features,
            self.learning_rate * amount_step,
        )

        return {
            "deposit_abs_error": abs(deposit_error),
            "item_target_probability": item_probabilities[target_index],
            "item_error": 1.0 - item_probabilities[target_index],
            "amount_abs_error": abs(amount_error),
        }

    def to_dict(self):
        """Serialize model weights."""
        return {
            "encoder": self.encoder.to_dict(),
            "item_classes": self.item_classes,
            "deposit_weights": self.deposit_weights,
            "item_weights": self.item_weights,
            "amount_weights": self.amount_weights,
            "learning_rate": self.learning_rate,
            "amount_scale": self.amount_scale,
        }

    @classmethod
    def from_dict(cls, data):
        """Load model weights."""
        return cls(
            encoder=SpatialFeatureEncoder.from_dict(data["encoder"]),
            item_classes=data["item_classes"],
            deposit_weights=data["deposit_weights"],
            item_weights=data["item_weights"],
            amount_weights=data["amount_weights"],
            learning_rate=data["learning_rate"],
            amount_scale=data["amount_scale"],
        )


class InternalMapBrain:
    """Action chooser plus learned world model.

    This object is the agent's brain. It is not allowed to store a visited-cell
    dictionary. The closest thing to memory here is its learned weights and
    short recency state.
    """

    def __init__(self, model, rng, epsilon=0.15, last_action=None):
        self.model = model
        self.rng = rng
        self.epsilon = epsilon
        self.last_action = last_action

    @classmethod
    def create(cls, metadata, feature_pairs, learning_rate, epsilon, rng):
        """Create a fresh brain."""
        model = LinearCellWorldModel.create(
            metadata=metadata,
            feature_pairs=feature_pairs,
            learning_rate=learning_rate,
            rng=rng,
        )
        return cls(model=model, rng=rng, epsilon=epsilon)

    def predict_actions(self, coordinate, valid_actions, step_size):
        """Predict the result of each valid movement action."""
        predictions = {}
        for action in valid_actions:
            next_coordinate = apply_action(coordinate, action, step_size)
            predicted_cell = self.model.predict_cell(next_coordinate)
            predictions[action] = {
                "action": action,
                "predicted_coordinate": next_coordinate,
                "predicted_cell": predicted_cell,
                "score": self.action_score(action, predicted_cell),
            }
        return predictions

    def action_score(self, action, predicted_cell):
        """Score one action for exploration.

        This is deliberately not a supply-chain reward. It mostly prefers
        uncertain places so the model can learn the world.
        """
        score = predicted_cell["uncertainty"]

        if self.last_action and action == REVERSE_ACTION.get(self.last_action):
            score -= 0.08

        # Tiny noise breaks ties without becoming the policy.
        score += self.rng.uniform(0.0, 0.001)
        return score

    def choose_action(self, predictions):
        """Choose a movement action from predictions."""
        if not predictions:
            raise ValueError("No valid actions are available.")

        actions = list(predictions)
        if self.rng.random() < self.epsilon:
            action = self.rng.choice(actions)
        else:
            action = max(actions, key=lambda candidate: predictions[candidate]["score"])

        self.last_action = action
        return action

    def learn(self, observation):
        """Update the internal model from one observation."""
        return self.model.train_on_observation(observation)

    def query_coordinate(self, coordinate):
        """Ask the learned model what it expects at one coordinate."""
        return self.model.predict_cell(coordinate)

    def direction_to_item(self, coordinate, item, metadata, step_size):
        """Choose the best immediate direction toward an item by model belief."""
        valid_actions = valid_actions_from_coordinate(coordinate, metadata, step_size)
        predictions = self.predict_actions(coordinate, valid_actions, step_size)
        if not predictions:
            return {"item": item, "direction": None, "reason": "no valid actions"}

        def item_score(action):
            predicted = predictions[action]["predicted_cell"]
            return predicted["item_probabilities"].get(item, 0.0)

        best_action = max(valid_actions, key=item_score)
        return {
            "item": item,
            "direction": best_action,
            "predicted_coordinate": predictions[best_action]["predicted_coordinate"],
            "item_probability": item_score(best_action),
            "all_directions": {
                action: predictions[action]["predicted_cell"]["item_probabilities"].get(
                    item,
                    0.0,
                )
                for action in valid_actions
            },
        }

    def to_dict(self, agent_id, coordinate, steps_trained):
        """Serialize brain state."""
        return {
            "format": "esc_internal_map_brain_v1",
            "agent_id": agent_id,
            "current_coordinate": coordinate,
            "steps_trained": steps_trained,
            "epsilon": self.epsilon,
            "last_action": self.last_action,
            "model": self.model.to_dict(),
        }

    @classmethod
    def from_dict(cls, data, rng):
        """Load brain state."""
        return cls(
            model=LinearCellWorldModel.from_dict(data["model"]),
            rng=rng,
            epsilon=data.get("epsilon", 0.15),
            last_action=data.get("last_action"),
        )


class WorldEnvironment:
    """True world wrapper for the one-agent movement experiment."""

    def __init__(self, world):
        self.world = world
        if len(world["agents"]) != 1:
            raise ValueError(
                f"brain.py expects exactly one agent, found {len(world['agents'])}."
            )

        self.agent_id = next(iter(world["agents"]))

    @property
    def metadata(self):
        """World metadata."""
        return self.world["metadata"]

    @property
    def agent(self):
        """The single active agent."""
        return self.world["agents"][self.agent_id]

    @property
    def coordinate(self):
        """Current agent coordinate."""
        return list(self.agent["coordinate"])

    def set_agent_coordinate(self, coordinate):
        """Place the agent at a coordinate while keeping the sparse index valid."""
        old_coordinate = self.coordinate
        old_key = coordinate_key(old_coordinate)
        old_entry = self.world["coordinates"].get(old_key)
        if old_entry and self.agent_id in old_entry["agents"]:
            old_entry["agents"].remove(self.agent_id)
            if all(not old_entry[collection] for collection in old_entry):
                del self.world["coordinates"][old_key]

        self.agent["coordinate"] = list(coordinate)
        new_key = coordinate_key(coordinate)
        new_entry = self.world["coordinates"].setdefault(
            new_key,
            empty_coordinate_entry(),
        )
        if self.agent_id not in new_entry["agents"]:
            new_entry["agents"].append(self.agent_id)

    def valid_actions(self, step_size):
        """Return movement actions that stay inside the circular map."""
        return valid_actions_from_coordinate(self.coordinate, self.metadata, step_size)

    def move(self, action, step_size):
        """Move the agent and return the new coordinate."""
        if action not in self.valid_actions(step_size):
            raise ValueError(f"Invalid action from {self.coordinate}: {action}")

        new_coordinate = apply_action(self.coordinate, action, step_size)
        self.set_agent_coordinate(new_coordinate)
        return new_coordinate

    def observe(self, last_action=None, last_prediction_error=None):
        """Return what the agent can observe at its current coordinate."""
        coordinate = self.coordinate
        x, y = coordinate
        surface = surface_code(
            self.metadata.get("seed", 0),
            x,
            y,
            self.metadata.get("chaos_level", DEFAULT_CHAOS_LEVEL),
        )
        key = coordinate_key(coordinate)
        entry = self.world["coordinates"].get(key, empty_coordinate_entry())
        deposit_id = entry["deposits"][0] if entry["deposits"] else None

        if deposit_id:
            deposit = self.world["deposits"][deposit_id]
            cell = {
                "surface_code": surface,
                "has_deposit": True,
                "deposit_id": deposit_id,
                "item": deposit["item"],
                "amount": deposit["amount"],
            }
        else:
            cell = {
                "surface_code": surface,
                "has_deposit": False,
                "deposit_id": None,
                "item": None,
                "amount": 0,
            }

        return {
            "agent_id": self.agent_id,
            "coordinate": coordinate,
            "cell": cell,
            "last_action": last_action,
            "last_prediction_error": last_prediction_error,
        }


def apply_action(coordinate, action, step_size):
    """Return the coordinate that would result from an action."""
    if action not in ACTION_DELTAS:
        raise ValueError(f"Unknown action: {action}")

    dx, dy = ACTION_DELTAS[action]
    return [coordinate[0] + (dx * step_size), coordinate[1] + (dy * step_size)]


def is_valid_coordinate(coordinate, metadata):
    """Return True if a coordinate is inside the world."""
    x, y = coordinate
    if not (0 <= x < metadata["world_width"] and 0 <= y < metadata["world_height"]):
        return False

    if metadata.get("world_shape") == "circle":
        center_x, center_y = metadata["world_center"]
        return is_inside_circle(x, y, center_x, center_y, metadata["world_radius"])

    return True


def valid_actions_from_coordinate(coordinate, metadata, step_size):
    """Return all movement actions that stay inside the world."""
    actions = []
    for action in ACTION_DELTAS:
        candidate = apply_action(coordinate, action, step_size)
        if is_valid_coordinate(candidate, metadata):
            actions.append(action)
    return actions


def prediction_error(predicted_cell, actual_cell, amount_scale):
    """Score how wrong a predicted cell was."""
    deposit_target = 1.0 if actual_cell["has_deposit"] else 0.0
    deposit_error = abs(deposit_target - predicted_cell["deposit_probability"])

    expected_item = actual_cell["item"] if actual_cell["has_deposit"] else NO_ITEM
    if expected_item == NO_ITEM:
        best_none_probability = 1.0 - predicted_cell["deposit_probability"]
        item_error = 1.0 - best_none_probability
    else:
        item_error = 1.0 - predicted_cell["item_probabilities"].get(expected_item, 0.0)

    amount_target = actual_cell["amount"] / max(1.0, amount_scale)
    amount_error = abs(amount_target - (predicted_cell["amount_estimate"] / amount_scale))

    return {
        "total": (0.50 * deposit_error) + (0.35 * item_error) + (0.15 * amount_error),
        "deposit": deposit_error,
        "item": item_error,
        "amount": amount_error,
    }


def selected_world_from_index(index_path):
    """Return the selected world JSON path from worlds_index.json."""
    index = json_load(index_path)
    world_id = index.get("selected_world_id")
    if not world_id:
        raise ValueError("No selected world id found in worlds_index.json.")

    for world in index.get("worlds", []):
        if world["id"] == world_id:
            return index_path.parent / world["file_path"]

    raise ValueError(f"Selected world id not found in index: {world_id}")


def load_world(world_path):
    """Load a world JSON file."""
    world = json_load(world_path)
    required = {"metadata", "agents", "deposits", "machines", "coordinates"}
    missing = required - set(world)
    if missing:
        raise ValueError(f"World file is missing keys: {sorted(missing)}")
    return world


def default_log_path():
    """Return a default local JSONL log path."""
    return Path(DEFAULT_LOG_DIR) / f"brain_run_{timestamp()}.jsonl"


def default_model_path(world_seed):
    """Return a default local model path."""
    return Path(DEFAULT_LOG_DIR) / f"brain_model_seed_{world_seed}_{timestamp()}.json"


def write_jsonl(file_handle, record):
    """Write one JSON record per line."""
    file_handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def load_brain(model_path, rng):
    """Load a saved brain file."""
    data = json_load(model_path)
    if data.get("format") != "esc_internal_map_brain_v1":
        raise ValueError("Unsupported brain model format.")
    return InternalMapBrain.from_dict(data, rng), data


def run_training(args):
    """Run the one-agent internal-map training loop."""
    rng = random.Random(args.seed)
    world_path = Path(args.world) if args.world else selected_world_from_index(Path(args.index))
    world = load_world(world_path)
    env = WorldEnvironment(world)
    metadata = env.metadata

    if args.model_in:
        brain, saved_state = load_brain(Path(args.model_in), rng)
        if saved_state.get("current_coordinate"):
            env.set_agent_coordinate(saved_state["current_coordinate"])
        steps_trained = int(saved_state.get("steps_trained", 0))
    else:
        brain = InternalMapBrain.create(
            metadata=metadata,
            feature_pairs=args.features,
            learning_rate=args.learning_rate,
            epsilon=args.epsilon,
            rng=rng,
        )
        steps_trained = 0

    log_path = Path(args.log) if args.log else default_log_path()
    model_path = Path(args.model_out) if args.model_out else default_model_path(
        metadata["seed"]
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)

    unique_coordinates_seen = {coordinate_key(env.coordinate)}
    deposit_ids_seen = set()
    current_observation = env.observe()
    if current_observation["cell"]["deposit_id"]:
        deposit_ids_seen.add(current_observation["cell"]["deposit_id"])
    initial_loss = brain.learn(current_observation)

    with log_path.open("a", encoding="utf-8") as log_file:
        write_jsonl(
            log_file,
            {
                "type": "initial_observation",
                "world_path": str(world_path),
                "agent_id": env.agent_id,
                "coordinate": env.coordinate,
                "observation": current_observation,
                "train_loss": initial_loss,
            },
        )

        for local_step in range(1, args.steps + 1):
            before = env.coordinate
            valid_actions = env.valid_actions(args.step_size)
            predictions = brain.predict_actions(before, valid_actions, args.step_size)
            action = brain.choose_action(predictions)
            predicted = predictions[action]

            env.move(action, args.step_size)
            actual_observation = env.observe(last_action=action)
            error = prediction_error(
                predicted["predicted_cell"],
                actual_observation["cell"],
                brain.model.amount_scale,
            )
            actual_observation["last_prediction_error"] = error["total"]
            train_loss = brain.learn(actual_observation)
            steps_trained += 1

            unique_coordinates_seen.add(coordinate_key(env.coordinate))
            if actual_observation["cell"]["deposit_id"]:
                deposit_ids_seen.add(actual_observation["cell"]["deposit_id"])

            record = {
                "type": "brain_step",
                "step": steps_trained,
                "local_step": local_step,
                "agent_id": env.agent_id,
                "from": before,
                "to": env.coordinate,
                "action": action,
                "valid_actions": valid_actions,
                "prediction": predicted,
                "observation": actual_observation,
                "prediction_error": error,
                "train_loss": train_loss,
            }
            write_jsonl(log_file, record)

            if args.report_every and local_step % args.report_every == 0:
                print(
                    "step "
                    f"{steps_trained}: coord={env.coordinate} action={action} "
                    f"error={error['total']:.4f} "
                    f"unique_coords={len(unique_coordinates_seen)} "
                    f"deposits_seen={len(deposit_ids_seen)}"
                )

    model_data = brain.to_dict(
        agent_id=env.agent_id,
        coordinate=env.coordinate,
        steps_trained=steps_trained,
    )
    model_data["world_path"] = str(world_path)
    model_data["log_path"] = str(log_path)
    json_dump(model_path, model_data)

    print("Brain run complete.")
    print(f"World: {world_path}")
    print(f"Agent: {env.agent_id}")
    print(f"Current coordinate: {env.coordinate}")
    print(f"Steps trained: {steps_trained}")
    print(f"Unique coordinates seen this run: {len(unique_coordinates_seen)}")
    print(f"Deposits seen this run: {len(deposit_ids_seen)}")
    print(f"Log: {log_path}")
    print(f"Model: {model_path}")

    print_query_summary(brain, env.coordinate, metadata, args)


def print_query_summary(brain, coordinate, metadata, args):
    """Print a few structured brain queries after a run."""
    current_prediction = brain.query_coordinate(coordinate)
    print("\nQuery: predict_at_current")
    print(json.dumps(current_prediction, indent=2))

    if args.query_offset:
        offset_x, offset_y = args.query_offset
        target = [coordinate[0] + offset_x, coordinate[1] + offset_y]
        print("\nQuery: predict_coordinate_offset")
        print(
            json.dumps(
                {
                    "from": coordinate,
                    "offset": [offset_x, offset_y],
                    "target": target,
                    "prediction": brain.query_coordinate(target),
                },
                indent=2,
            )
        )

    if args.query_item:
        print("\nQuery: direction_to_item")
        print(
            json.dumps(
                brain.direction_to_item(
                    coordinate,
                    args.query_item,
                    metadata,
                    args.step_size,
                ),
                indent=2,
            )
        )


def parse_args():
    """Parse CLI settings."""
    parser = argparse.ArgumentParser(
        description="Run the ESC one-agent internal world-model experiment."
    )
    parser.add_argument(
        "--world",
        default=None,
        help="World JSON path. Defaults to selected world in worlds_index.json.",
    )
    parser.add_argument("--index", default=DEFAULT_INDEX_PATH)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--step-size", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--features", type=int, default=96)
    parser.add_argument("--learning-rate", type=float, default=0.03)
    parser.add_argument("--epsilon", type=float, default=0.15)
    parser.add_argument("--report-every", type=int, default=100)
    parser.add_argument("--log", default=None)
    parser.add_argument("--model-in", default=None)
    parser.add_argument("--model-out", default=None)
    parser.add_argument(
        "--query-offset",
        nargs=2,
        type=int,
        metavar=("DX", "DY"),
        default=None,
    )
    parser.add_argument("--query-item", default="stone")
    return parser.parse_args()


def main():
    """CLI entrypoint."""
    run_training(parse_args())


if __name__ == "__main__":
    main()
