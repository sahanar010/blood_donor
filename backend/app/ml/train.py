"""Train the acceptance model on SIMULATED data.   Run from backend/:

    python -m app.ml.train                      # ~1 minute
    python -m app.ml.train --requests 8000 --rounds 600

Writes models/acceptance_xgb.json (+ acceptance_meta.json with metrics). Restart the API (or call
POST /admin/ml/reload) to pick up a new model.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from app.ml.evaluate import evaluate
from app.ml.features import FEATURES, MONOTONE
from app.ml.simulate import simulate

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"


def main() -> None:
    import xgboost as xgb  # imported here so the rest of the package works without it

    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=4000, help="simulated training requests (x ~20 donors each)")
    ap.add_argument("--rounds", type=int, default=400)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, default=MODELS_DIR)
    a = ap.parse_args()

    print("Simulating (separate donor pools for train / validation / test)...")
    train = simulate(a.requests, seed=a.seed)
    valid = simulate(max(500, a.requests // 4), seed=a.seed + 1)
    test = simulate(max(1000, a.requests // 3), seed=a.seed + 2)
    print(f"  train {len(train.y):,} rows | valid {len(valid.y):,} | test {len(test.y):,} | acceptance rate {train.y.mean():.1%}")

    dtrain = xgb.DMatrix(train.X, label=train.y, feature_names=FEATURES)
    dvalid = xgb.DMatrix(valid.X, label=valid.y, feature_names=FEATURES)
    params = {
        "objective": "binary:logistic", "eval_metric": "logloss", "tree_method": "hist",
        "max_depth": 4, "eta": 0.06, "subsample": 0.8, "colsample_bytree": 0.8, "min_child_weight": 10,
        "lambda": 2.0, "seed": a.seed,
        "monotone_constraints": "(" + ",".join(str(MONOTONE.get(f, 0)) for f in FEATURES) + ")",
    }
    booster = xgb.train(params, dtrain, num_boost_round=a.rounds, evals=[(dvalid, "valid")],
                        early_stopping_rounds=30, verbose_eval=50)
    booster = booster[: booster.best_iteration + 1]    # keep only the best trees, so serving needs no extra args
    print(f"Kept {booster.num_boosted_rounds()} trees")

    metrics = evaluate(lambda X: booster.predict(xgb.DMatrix(X, feature_names=FEATURES)), test)
    importance = booster.get_score(importance_type="gain")
    top = sorted(importance.items(), key=lambda kv: -kv[1])

    a.out.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(a.out / "acceptance_xgb.json"))
    meta = {
        "features": FEATURES, "trained_at": datetime.now(timezone.utc).isoformat(),
        "xgboost_version": xgb.__version__, "data_source": "synthetic-simulation",
        "train_rows": int(len(train.y)), "test_metrics": metrics,
        "feature_gain": {k: round(float(v), 2) for k, v in top},
    }
    (a.out / "acceptance_meta.json").write_text(json.dumps(meta, indent=2))

    print("\n=== Held-out test (unseen donors, SIMULATED data) ===")
    print(f"AUC {metrics['auc']}  (ceiling if hidden traits were known: {metrics['oracle_auc']})")
    print(f"Log-loss {metrics['logloss']} vs {metrics['baseline_logloss']} for always predicting the base rate | Brier {metrics['brier']}")
    print("Expected acceptance among the top 3 contacted donors:")
    for k, v in metrics["top3_expected_acceptance"].items():
        print(f"  {k:<18} {v:.3f}")
    print("Most influential features:", ", ".join(k for k, _ in top[:5]))
    print(f"Saved to {a.out}/")


if __name__ == "__main__":
    main()
