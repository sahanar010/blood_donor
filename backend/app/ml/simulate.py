"""Synthetic history of (request, donor) -> accepted?  There is NO real data in this project.

Each donor has a HIDDEN trait ("altruism") that drives behaviour but is never shown to the model.
The model only sees what the live system can observe (response rate, acceptance rate, distance...),
so it must infer willingness from history, exactly as it would in production.

The acceptance rule below is an assumption I wrote to look plausible, so any accuracy measured on this
data says "the pipeline can recover the simulated pattern", NOT "it predicts real donors".
Retrain on real Response rows once you have them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

import numpy as np

from app.enums import Urgency
from app.matching import (DonorFeatures, RequestContext, effective_radius_km, in_preferred_window,
                          passes_travel_policy)
from app.ml.features import feature_matrix

WINDOWS = [(None, None), (time(9), time(17)), (time(6), time(22)), (time(17), time(21)), (time(22), time(6))]
PRIOR_RATE, PRIOR_STRENGTH = 0.6, 5          # mirrors the smoothing in app/models.py
_HOUR_P = np.array([3.0 if 8 <= h <= 20 else 1.0 for h in range(24)])
_HOUR_P /= _HOUR_P.sum()
_URG_BOOST = {Urgency.NORMAL: 0.0, Urgency.URGENT: 0.5, Urgency.EMERGENCY: 1.0}


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@dataclass
class _Donor:
    id: int
    alt: float
    r_wd: float
    r_we: float
    ws: time | None
    we: time | None
    rating: float | None
    resp: float
    acc: float
    count: int
    avg_s: float | None
    days: int | None


@dataclass
class Dataset:
    X: np.ndarray                         # (rows, n_features)
    y: np.ndarray                         # 1 = accepted
    true_p: np.ndarray                    # ground-truth probability (simulation only)
    group: np.ndarray                     # request index per row (rows are contiguous per request)
    feats: list[list[DonorFeatures]]      # per request
    ctxs: list[RequestContext]


def _make_pool(rng: np.random.Generator, n: int) -> list[_Donor]:
    pool = []
    for i in range(n):
        alt = float(rng.normal())
        received = int(rng.integers(0, 41))
        responded = int(rng.binomial(received, _sig(0.9 + 0.9 * alt)))
        accepted = int(rng.binomial(responded, _sig(0.8 + 0.8 * alt)))
        count = int(rng.choice([0, 1, 2, 3, 5, 8, 12], p=[.20, .20, .15, .15, .12, .10, .08]))
        wd = float(rng.choice([5, 10, 15, 20]))
        ws, we = WINDOWS[int(rng.integers(len(WINDOWS)))]
        pool.append(_Donor(
            id=i, alt=alt, r_wd=wd, r_we=wd * float(rng.choice([1.5, 2, 3])), ws=ws, we=we,
            rating=float(np.clip(rng.normal(4.4 + 0.15 * alt, 0.35), 3, 5)) if count else None,
            resp=(responded + PRIOR_RATE * PRIOR_STRENGTH) / (received + PRIOR_STRENGTH),
            acc=(accepted + PRIOR_RATE * PRIOR_STRENGTH) / (responded + PRIOR_STRENGTH),
            count=count,
            avg_s=float(rng.lognormal(5.8 - 0.3 * alt, 0.8)) if responded else None,
            days=int(rng.integers(90, 901)) if count else None,   # only eligible donors reach ranking
        ))
    return pool


def _p_accept(d: _Donor, dist: float, radius: float, ctx: RequestContext) -> float:
    """THE ASSUMED GROUND TRUTH (see module docstring)."""
    when = ctx.required_local
    z = (-0.1 + 1.1 * d.alt
         - 0.12 * dist
         - 0.35 * max(0.0, dist - radius)                      # asked to travel beyond their comfort zone
         + _URG_BOOST[ctx.urgency]
         + (0.5 if in_preferred_window(d.ws, d.we, when.time()) else -0.2)
         + (-0.7 if (when.hour >= 22 or when.hour < 6) else 0.0)
         + (0.2 if when.weekday() >= 5 else 0.0)
         + 0.12 * math.log1p(d.count)
         + (-0.4 if (d.days is not None and d.days < 150) else 0.0)
         + (0.5 * (d.rating - 4.4) if d.rating is not None else 0.0))
    return _sig(z)


def simulate(n_requests: int, seed: int, pool_size: int = 3000, cands: int = 20) -> Dataset:
    """Use different seeds for train / validation / test: each gets its OWN donor pool,
    so evaluation never sees a donor the model trained on."""
    rng = np.random.default_rng(seed)
    pool = _make_pool(rng, pool_size)
    monday = datetime(2026, 10, 5)
    feats_all: list[list[DonorFeatures]] = []
    ctxs: list[RequestContext] = []
    ps: list[float] = []
    groups: list[int] = []

    for g in range(n_requests):
        urg = [Urgency.NORMAL, Urgency.URGENT, Urgency.EMERGENCY][int(rng.choice(3, p=[.5, .3, .2]))]
        when = monday + timedelta(days=int(rng.integers(0, 7)), hours=int(rng.choice(24, p=_HOUR_P)))
        ctx = RequestContext(max_distance_km=float(rng.choice([10, 15, 25])), urgency=urg, required_local=when)
        chosen: set[int] = set()
        fl: list[DonorFeatures] = []
        for _ in range(500):
            if len(fl) >= cands:
                break
            d = pool[int(rng.integers(len(pool)))]
            if d.id in chosen:
                continue
            dist = round(float(rng.uniform(0.3, ctx.max_distance_km)), 2)
            radius = effective_radius_km(d.r_wd, d.r_we, when)
            if not passes_travel_policy(dist, radius, urg):
                continue
            chosen.add(d.id)
            fl.append(DonorFeatures(
                donor_id=d.id, distance_km=dist, travel_radius_km=radius, preferred_start=d.ws,
                preferred_end=d.we, rating_avg=d.rating, response_rate=d.resp, acceptance_rate=d.acc,
                donation_count=d.count, avg_response_seconds=d.avg_s, days_since_last_donation=d.days))
            ps.append(_p_accept(d, dist, radius, ctx))
            groups.append(g)
        feats_all.append(fl)
        ctxs.append(ctx)

    true_p = np.array(ps)
    X = np.vstack([feature_matrix(fl, c) for fl, c in zip(feats_all, ctxs)])
    y = (rng.random(len(true_p)) < true_p).astype(np.int8)
    return Dataset(X=X, y=y, true_p=true_p, group=np.array(groups), feats=feats_all, ctxs=ctxs)
