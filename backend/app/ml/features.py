"""Single source of truth for model inputs, shared by training (simulation) and serving (live DB rows)."""
from __future__ import annotations

import numpy as np

from app.enums import Urgency
from app.matching import DonorFeatures, RequestContext, in_preferred_window

FEATURES = [
    "distance_km", "travel_radius_km", "distance_over_radius", "in_preferred_window",
    "rating_avg", "response_rate", "acceptance_rate", "donation_count",
    "avg_response_seconds", "days_since_last_donation", "urgency", "hour", "is_weekend",
]
# Keep the model sensible: closer never lowers acceptance; better history never lowers it.
MONOTONE = {"distance_km": -1, "response_rate": 1, "acceptance_rate": 1}

_URGENCY = {Urgency.NORMAL: 0.0, Urgency.URGENT: 1.0, Urgency.EMERGENCY: 2.0}
_NAN = float("nan")  # XGBoost handles missing values natively (new donors, never donated, ...)


def _v(x) -> float:
    return _NAN if x is None else float(x)


def feature_row(f: DonorFeatures, ctx: RequestContext) -> list[float]:
    in_win = in_preferred_window(f.preferred_start, f.preferred_end, ctx.required_local.time())
    return [
        f.distance_km,
        f.travel_radius_km,
        f.distance_km / f.travel_radius_km if f.travel_radius_km > 0 else _NAN,
        1.0 if in_win else 0.0,
        _v(f.rating_avg), _v(f.response_rate), _v(f.acceptance_rate), float(f.donation_count),
        _v(f.avg_response_seconds), _v(f.days_since_last_donation),
        _URGENCY[ctx.urgency], float(ctx.required_local.hour),
        1.0 if ctx.required_local.weekday() >= 5 else 0.0,
    ]


def feature_matrix(feats: list[DonorFeatures], ctx: RequestContext) -> np.ndarray:
    return np.array([feature_row(f, ctx) for f in feats], dtype=np.float32).reshape(-1, len(FEATURES))
