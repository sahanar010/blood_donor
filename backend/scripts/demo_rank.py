"""Offline demo of the ranking engine - no database, no Docker needed:

    python -m scripts.demo_rank
"""
import random
from datetime import datetime, time

from app.enums import Urgency
from app.matching import DonorFeatures, RequestContext, rank

rng = random.Random(7)
donors = [
    DonorFeatures(
        donor_id=i, distance_km=round(rng.uniform(0.5, 14), 1),
        travel_radius_km=rng.choice([5, 10, 15, 20]),
        preferred_start=time(9), preferred_end=time(17),
        rating_avg=round(rng.uniform(3.8, 5.0), 1),
        response_rate=round(rng.uniform(0.5, 1.0), 2),
        acceptance_rate=round(rng.uniform(0.5, 1.0), 2),
        donation_count=rng.randint(0, 10), avg_response_seconds=rng.uniform(60, 1800))
    for i in range(1, 51)
]

for urgency in (Urgency.NORMAL, Urgency.EMERGENCY):
    ctx = RequestContext(max_distance_km=15, urgency=urgency, required_local=datetime(2026, 10, 7, 11, 0))
    print(f"\n=== O+ x1, {urgency.value}: top 3 of {len(donors)} donors ===")
    for pos, m in enumerate(rank(donors, ctx, top_n=3), start=1):
        print(f"{pos}. Donor {m.donor_id:>2}  score {m.score}")
        print("   " + " • ".join(m.reasons))
