"""Model-agnostic evaluation: takes any predict_proba(X) callable."""
from __future__ import annotations

import dataclasses
from typing import Callable

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from app.matching import Weights, rank
from app.ml.simulate import Dataset

ML_HEAVY = Weights(distance=0.25, availability=0.15, reliability=0.15, travel=0.10, ml=0.30, rating=0.05)


def evaluate(predict_proba: Callable[[np.ndarray], np.ndarray], ds: Dataset) -> dict:
    p = np.clip(predict_proba(ds.X), 1e-6, 1 - 1e-6)
    base = float(ds.y.mean())
    out = {
        "rows": int(len(ds.y)), "base_rate": round(base, 3),
        "auc": round(float(roc_auc_score(ds.y, p)), 4),
        "oracle_auc": round(float(roc_auc_score(ds.y, ds.true_p)), 4),   # ceiling: knows hidden traits
        "logloss": round(float(log_loss(ds.y, p)), 4),
        "baseline_logloss": round(float(log_loss(ds.y, np.full_like(p, base))), 4),
        "brier": round(float(brier_score_loss(ds.y, p)), 4),
    }
    out["top3_expected_acceptance"] = _top3(p, ds)
    return out


def _top3(p: np.ndarray, ds: Dataset) -> dict:
    """Mean TRUE acceptance probability of the 3 donors each strategy would contact first."""
    res: dict[str, list[float]] = {k: [] for k in ("random", "rules_only", "ml_only", "hybrid_10pct_ml", "hybrid_30pct_ml", "oracle")}
    start = 0
    for fl, ctx in zip(ds.feats, ds.ctxs):
        n = len(fl)
        if n < 3:
            start += n
            continue
        tp, pp = ds.true_p[start:start + n], p[start:start + n]
        idx = {f.donor_id: i for i, f in enumerate(fl)}
        with_ml = [dataclasses.replace(f, ml_probability=float(pp[i])) for i, f in enumerate(fl)]

        def exp_of(matches) -> float:
            return float(np.mean([tp[idx[m.donor_id]] for m in matches]))

        res["random"].append(float(tp.mean()))
        res["rules_only"].append(exp_of(rank(fl, ctx, Weights(), 3)))
        res["ml_only"].append(float(tp[np.argsort(-pp)[:3]].mean()))
        res["hybrid_10pct_ml"].append(exp_of(rank(with_ml, ctx, Weights(), 3)))
        res["hybrid_30pct_ml"].append(exp_of(rank(with_ml, ctx, ML_HEAVY, 3)))
        res["oracle"].append(float(np.sort(tp)[-3:].mean()))
        start += n
    return {k: round(float(np.mean(v)), 4) for k, v in res.items()}
