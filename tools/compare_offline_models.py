"""Train outside CI runners and compare rules, linear softmax and an 8-unit MLP."""

import argparse
import hashlib
import json
import math
import random
import resource
import sys
import time
from pathlib import Path

from radea.core.offline import analyze
from radea.core.tiny import DIMENSIONS, HIDDEN, LABELS, classify, features, forward


def train(rows, neural):
    rng = random.Random(42)
    width = HIDDEN if neural else DIMENSIONS
    weights = {
        "output": [[rng.uniform(-0.1, 0.1) for _ in range(width)] for _ in LABELS],
        "bias": [0.0] * len(LABELS),
        "threshold": 0.0,
    }
    if neural:
        weights.update(
            {
                "hidden": [
                    [rng.uniform(-0.1, 0.1) for _ in range(DIMENSIONS)] for _ in range(HIDDEN)
                ],
                "hidden_bias": [0.0] * HIDDEN,
            }
        )
    samples = [(features(row["text"]), LABELS.index(row["category"])) for row in rows]
    for _ in range(250):
        rng.shuffle(samples)
        for x, label in samples:
            hidden, scores = forward(weights, x)
            exp = [math.exp(score - max(scores)) for score in scores]
            error = [value / sum(exp) - (index == label) for index, value in enumerate(exp)]
            inputs = hidden if neural else x
            if neural:
                delta = [
                    sum(error[k] * weights["output"][k][j] for k in range(len(LABELS)))
                    * (1 - hidden[j] ** 2)
                    for j in range(HIDDEN)
                ]
                for j in range(HIDDEN):
                    for i in range(DIMENSIONS):
                        weights["hidden"][j][i] -= 0.2 * delta[j] * x[i]
                    weights["hidden_bias"][j] -= 0.2 * delta[j]
            for k in range(len(LABELS)):
                for j in range(width):
                    weights["output"][k][j] -= 0.2 * error[k] * inputs[j]
                weights["bias"][k] -= 0.2 * error[k]
    return weights


def score(rows, predict):
    start = time.perf_counter()
    predictions = [predict(row["text"]) for row in rows]
    elapsed = time.perf_counter() - start
    confusion = {label: {other: 0 for other in LABELS} for label in LABELS}
    for row, prediction in zip(rows, predictions):
        confusion[row["category"]][prediction] += 1
    f1 = []
    for label in LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in LABELS if other != label)
        fn = sum(confusion[label][other] for other in LABELS if other != label)
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)
    return {
        "cases": len(rows),
        "accuracy": sum(row["category"] == pred for row, pred in zip(rows, predictions))
        / len(rows),
        "macro_f1": sum(f1) / len(f1),
        "confusion": confusion,
        "unknown_rate": predictions.count("unknown") / len(rows),
        "batch_seconds": round(elapsed, 6),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", action="store_true", help="Explicit developer-only training")
    parser.add_argument("--output", type=Path, default=Path("docs/offline-comparison.json"))
    args = parser.parse_args()
    raw = Path("examples/offline/corpus.json").read_bytes()
    corpus = json.loads(raw)["cases"]
    train_rows = [row for row in corpus if row["split"] == "train"]
    calibration = [row for row in corpus if row["split"] == "calibration"]
    test = [row for row in corpus if row["split"] == "test"]
    reports = {"offline": score(test, lambda text: analyze("debug", {"case:L1": text})["category"])}
    for variant in ("offline-linear", "offline-neural"):
        path = Path("src/radea/data") / (variant + ".json")
        if args.train:
            weights = train(train_rows, variant == "offline-neural")
            # Select abstention margin using calibration only; test remains untouched.
            candidates = []
            for threshold in (0.0, 0.25, 0.5, 1.0, 2.0):
                weights["threshold"] = threshold
                quality = score(calibration, lambda text: classify(weights, text)[0])["macro_f1"]
                candidates.append((quality, threshold))
            weights["threshold"] = max(candidates)[1]
            weights["corpus_sha256"] = hashlib.sha256(raw).hexdigest()
            weights["training"] = "seed=42; epochs=250; family split; experimental local failures"
            path.write_text(json.dumps(weights, separators=(",", ":")) + "\n")
        weights = json.loads(path.read_text())
        if weights["corpus_sha256"] != hashlib.sha256(raw).hexdigest():
            raise ValueError("Corpus changed; retrain explicitly before comparing")
        reports[variant] = {
            **score(test, lambda text: classify(weights, text)[0]),
            "artifact_bytes": path.stat().st_size,
            "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "threshold": weights["threshold"],
        }
    args.output.write_text(
        json.dumps(
            {
                "corpus_sha256": hashlib.sha256(raw).hexdigest(),
                "splits": {
                    "train": len(train_rows),
                    "calibration": len(calibration),
                    "test": len(test),
                },
                "limitations": "Small reproduced failures, not production accuracy. "
                "Same process RSS includes all comparisons; no GPU.",
                "platform": sys.platform,
                "process_peak_rss_mib": round(
                    resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    / (1024 * 1024 if sys.platform == "darwin" else 1024),
                    2,
                ),
                "results": reports,
            },
            indent=2,
        )
        + "\n"
    )
    print(args.output)


if __name__ == "__main__":
    main()
