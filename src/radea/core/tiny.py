"""Experimental CPU classifiers. Safe JSON weights, fixed bounded feature space."""

import hashlib
import json
import math
import re
from functools import lru_cache
from importlib.resources import files

DIMENSIONS = 128
HIDDEN = 8
LABELS = ("code_error", "dependency_drift", "config_issue", "flaky_infra", "unknown")


def features(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    tokens = re.findall(r"[a-z_]{2,40}", text[:32000].lower())
    for token in set(tokens):
        index = int.from_bytes(hashlib.blake2s(token.encode(), digest_size=4).digest(), "big")
        vector[index % DIMENSIONS] = 1.0
    length = math.sqrt(sum(vector)) or 1.0
    return [value / length for value in vector]


def forward(weights, x):
    hidden = [
        math.tanh(sum(a * b for a, b in zip(row, x)) + bias)
        for row, bias in zip(weights.get("hidden", []), weights.get("hidden_bias", []))
    ]
    inputs = hidden if hidden else x
    scores = [
        sum(a * b for a, b in zip(row, inputs)) + bias
        for row, bias in zip(weights["output"], weights["bias"])
    ]
    return hidden, scores


@lru_cache(maxsize=2)
def load(variant: str) -> tuple[dict, str]:
    if variant not in {"offline-linear", "offline-neural"}:
        raise ValueError("Unknown local classifier")
    with files("radea").joinpath("data", variant + ".json").open("rb") as stream:
        raw = stream.read(128001)
    if len(raw) > 128000:
        raise ValueError("Classifier exceeds size budget")
    data = json.loads(raw)
    width = HIDDEN if variant == "offline-neural" else DIMENSIONS
    shapes = {"output": (len(LABELS), width), "bias": (len(LABELS),)}
    if variant == "offline-neural":
        shapes.update({"hidden": (HIDDEN, DIMENSIONS), "hidden_bias": (HIDDEN,)})
    for key, shape in shapes.items():
        values = data[key]
        if not isinstance(values, list) or len(values) != shape[0]:
            raise ValueError("Invalid classifier shape")
        if len(shape) == 2:
            if any(not isinstance(row, list) or len(row) != shape[1] for row in values):
                raise ValueError("Invalid classifier width")
            values = [value for row in values for value in row]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            raise ValueError("Invalid classifier weights")
    if type(data.get("threshold")) not in (int, float) or not (0 <= data["threshold"] <= 100):
        raise ValueError("Invalid abstention threshold")
    return data, hashlib.sha256(raw).hexdigest()


def classify(weights: dict, text: str) -> tuple[str, float]:
    vector = features(text)
    if not any(vector):
        return "unknown", 0.0
    _, scores = forward(weights, vector)
    order = sorted(range(len(scores)), key=scores.__getitem__, reverse=True)
    margin = scores[order[0]] - scores[order[1]]
    label = LABELS[order[0]] if margin >= weights["threshold"] else "unknown"
    return label, margin


def predict(text: str, variant: str) -> dict:
    weights, digest = load(variant)
    label, margin = classify(weights, text)
    return {
        "category": label,
        "score_margin": round(margin, 4),
        "calibrated_probability": False,
        "experimental": True,
        "artifact_sha256": digest,
        "variant": variant,
        "scope": "category hint only; never overrides rules or policy",
    }
