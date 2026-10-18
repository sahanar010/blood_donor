"""Explainable donor-ranking engine.

Pure Python: no database or web-framework imports, so it is trivial to unit test.

Pipeline (hard rules first, then a configurable weighted score):

  1. HARD FILTERS (done in SQL by matching_service): blood group, verified,
     status AVAILABLE, minimum donation interval, within the hospital's max distance.
  2. TRAVEL POLICY (here): normal requests respect the donor's own travel radius,
     urgent ones allow 1.5x, emergencies allow anything within the max distance.
  3. SOFT SCORE (here): weighted blend of distance, availability, reliability,
     travel compatibility, ML acceptance probability (optional) and rating.
     If no ML probability is supplied, its weight is redistributed.

Every result carries human-readable `reasons`. Weights never override step 1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, time

from app.enums import Urgency

NEUTRAL = 0.5  # used when a donor has no history for a signal (new donor)


@dataclass(frozen=True)
class Weights:
    distance: float = 0.30
    availability: float = 0.20
    reliability: float = 0.20
    travel: float = 0.10
    ml: float = 0.10
    rating: float = 0.10


@dataclass
class DonorFeatures:
    donor_id: int
    distance_km: float
    travel_radius_km: float                 # already weekday/weekend-adjusted
    preferred_start: time | None = None
    preferred_end: time | None = None
    rating_avg: float | None = None         # 0-5
    response_rate: float | None = None      # 0-1
    acceptance_rate: float | None = None    # 0-1
    donation_count: int = 0
    avg_response_seconds: float | None = None
    days_since_last_donation: int | None = None   # None = never donated
    ml_probability: float | None = None     # 0-1, filled by the ML hook (phase 4)


@dataclass
class RequestContext:
    max_distance_km: float
    urgency: Urgency
    required_local: datetime                # hospital-local wall-clock time


@dataclass
class ScoredMatch:
    donor_id: int
    score: float
    distance_km: float
    components: dict[str, float]
    reasons: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- helpers

def effective_radius_km(weekday_km: float, weekend_km: float, when: datetime) -> float:
    """Weekend radius on Saturday/Sunday, weekday radius otherwise."""
    return weekend_km if when.weekday() >= 5 else weekday_km


def in_preferred_window(start: time | None, end: time | None, at: time) -> bool:
    """No stated preference = always OK. Handles windows that wrap past midnight."""
    if start is None or end is None:
        return True
    if start <= end:
        return start <= at <= end
    return at >= start or at <= end


_TRAVEL_FACTOR = {Urgency.NORMAL: 1.0, Urgency.URGENT: 1.5, Urgency.EMERGENCY: math.inf}


def passes_travel_policy(distance_km: float, radius_km: float, urgency: Urgency) -> bool:
    return distance_km <= radius_km * _TRAVEL_FACTOR[urgency]


def distance_score(distance_km: float, max_distance_km: float) -> float:
    if max_distance_km <= 0:
        return 0.0
    return max(0.0, 1.0 - distance_km / max_distance_km)


def travel_score(distance_km: float, radius_km: float) -> float:
    """1.0 inside the donor's radius, decaying linearly to 0 at twice the radius."""
    if distance_km <= radius_km:
        return 1.0
    if radius_km <= 0:
        return 0.0
    return max(0.0, 1.0 - (distance_km - radius_km) / radius_km)


def availability_score(in_window: bool, urgency: Urgency) -> float:
    # Donor status is already AVAILABLE (hard filter); this reflects preferred hours.
    if in_window:
        return 1.0
    return 0.8 if urgency == Urgency.EMERGENCY else 0.5


def reliability_score(response_rate: float | None, acceptance_rate: float | None) -> float:
    r = NEUTRAL if response_rate is None else response_rate
    a = NEUTRAL if acceptance_rate is None else acceptance_rate
    return 0.5 * r + 0.5 * a


def rating_score(rating_avg: float | None) -> float:
    return NEUTRAL if rating_avg is None else max(0.0, min(1.0, rating_avg / 5.0))


# ---------------------------------------------------------------- scoring

def score_donor(f: DonorFeatures, ctx: RequestContext, w: Weights = Weights()) -> ScoredMatch | None:
    """Return a ScoredMatch, or None if the donor fails the travel policy."""
    if not passes_travel_policy(f.distance_km, f.travel_radius_km, ctx.urgency):
        return None

    in_window = in_preferred_window(f.preferred_start, f.preferred_end, ctx.required_local.time())
    comps = {
        "distance": distance_score(f.distance_km, ctx.max_distance_km),
        "availability": availability_score(in_window, ctx.urgency),
        "reliability": reliability_score(f.response_rate, f.acceptance_rate),
        "travel": travel_score(f.distance_km, f.travel_radius_km),
        "rating": rating_score(f.rating_avg),
    }
    weights = {
        "distance": w.distance, "availability": w.availability,
        "reliability": w.reliability, "travel": w.travel, "rating": w.rating,
    }
    if f.ml_probability is not None:
        comps["ml"] = max(0.0, min(1.0, f.ml_probability))
        weights["ml"] = w.ml

    total_w = sum(weights.values())
    score = 100.0 * sum(weights[k] * comps[k] for k in weights) / total_w
    return ScoredMatch(
        donor_id=f.donor_id,
        score=round(score, 1),
        distance_km=round(f.distance_km, 2),
        components={k: round(v, 3) for k, v in comps.items()},
        reasons=build_reasons(f, in_window),
    )


def build_reasons(f: DonorFeatures, in_window: bool) -> list[str]:
    reasons = [f"{f.distance_km:.1f} km away", "Available"]
    if f.preferred_start is not None and in_window:
        reasons.append("Within preferred donation hours")
    if f.distance_km <= f.travel_radius_km:
        reasons.append(f"Within travel preference ({f.travel_radius_km:g} km)")
    else:
        reasons.append(f"Beyond usual travel radius ({f.travel_radius_km:g} km) - urgent/emergency allowance")
    if f.rating_avg is not None:
        reasons.append(f"{f.rating_avg:.1f}★ experience rating")
    if f.response_rate is not None and f.response_rate >= 0.85:
        reasons.append(f"High response rate ({f.response_rate:.0%})")
    if f.acceptance_rate is not None and f.acceptance_rate >= 0.80:
        reasons.append(f"{f.acceptance_rate:.0%} historical acceptance")
    if f.avg_response_seconds is not None and f.avg_response_seconds <= 600:
        reasons.append(f"Usually replies in ~{max(1, round(f.avg_response_seconds / 60))} min")
    if f.donation_count >= 3:
        reasons.append(f"{f.donation_count} previous donations")
    if f.ml_probability is not None:
        reasons.append(f"Predicted acceptance {f.ml_probability:.0%}")
    return reasons


def rank(candidates: list[DonorFeatures], ctx: RequestContext,
         w: Weights = Weights(), top_n: int = 3) -> list[ScoredMatch]:
    scored = [s for c in candidates if (s := score_donor(c, ctx, w)) is not None]
    scored.sort(key=lambda s: (-s.score, s.distance_km, s.donor_id))  # deterministic
    return scored[:top_n]
