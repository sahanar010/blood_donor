"""Serving side: loads the trained model once and plugs into matching_service as `ml_scorer`.

If xgboost isn't installed, the model file is missing, or the feature list doesn't match,
get_ml_scorer() returns None and ranking falls back to the rule-based score (the ML weight is
redistributed automatically). The API never fails because of the ML layer.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

from app.matching import DonorFeatures, RequestContext
from app.ml.features import FEATURES, feature_matrix

log = logging.getLogger("ml")


class AcceptanceModel:
    def __init__(self, booster, meta: dict):
        self._booster, self.meta = booster, meta

    def __call__(self, feats: list[DonorFeatures], ctx: RequestContext) -> dict[int, float]:
        import xgboost as xgb
        probs = self._booster.predict(xgb.DMatrix(feature_matrix(feats, ctx), feature_names=FEATURES))
        return {f.donor_id: float(p) for f, p in zip(feats, probs)}


def load_model(model_path: str | Path) -> AcceptanceModel | None:
    path = Path(model_path)
    meta_path = path.with_name("acceptance_meta.json")
    if not path.exists():
        log.warning("ML model not found at %s - ranking uses rules only (run: python -m app.ml.train)", path)
        return None
    try:
        import xgboost as xgb
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if meta.get("features") not in (None, FEATURES):
            log.warning("ML model was trained with different features - ignoring it. Retrain.")
            return None
        booster = xgb.Booster()
        booster.load_model(str(path))
        log.info("Loaded acceptance model (%s)", meta.get("trained_at", "unknown date"))
        return AcceptanceModel(booster, meta)
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not load ML model (%s) - ranking uses rules only", exc)
        return None


@lru_cache(maxsize=1)
def get_ml_scorer() -> AcceptanceModel | None:
    from app.config import settings
    if not settings.ml_enabled:
        return None
    return load_model(settings.ml_model_path)


def reload_ml_scorer() -> AcceptanceModel | None:
    get_ml_scorer.cache_clear()
    return get_ml_scorer()
