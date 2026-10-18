"""DB-facing half of matching: SQL hard filters (PostGIS) -> pure ranking -> persisted matches."""
import logging
from datetime import timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.enums import Availability, MatchStatus
from app.matching import DonorFeatures, RequestContext, effective_radius_km, rank
from app.ml.scorer import get_ml_scorer
from app.models import BloodRequest, Donor, Hospital, Match

log = logging.getLogger(__name__)

# Phase-4 hook: (features, ctx) -> {donor_id: P(accept)}
MlScorer = Callable[[list[DonorFeatures], RequestContext], dict[int, float]]


def to_local(dt):
    return dt.astimezone(ZoneInfo(settings.local_tz))


def fetch_candidates(db: Session, req: BloodRequest, ctx: RequestContext) -> list[DonorFeatures]:
    """HARD filters. A donor failing any of these is never recommended, whatever their score."""
    required_date = ctx.required_local.date()
    cutoff = required_date - timedelta(days=settings.min_donation_interval_days)

    dist_m = func.ST_Distance(Donor.location, Hospital.location)  # geography => metres
    already_contacted = select(Match.donor_id).where(
        Match.request_id == req.id, Match.status != MatchStatus.SUGGESTED)

    stmt = (
        select(Donor, dist_m.label("dist_m"))
        .select_from(Donor)
        .join(Hospital, Hospital.id == req.hospital_id)
        .where(
            Donor.blood_group == req.blood_group,
            Donor.verified.is_(True),
            Donor.availability_status == Availability.AVAILABLE,
            or_(Donor.last_donation_date.is_(None), Donor.last_donation_date <= cutoff),
            func.ST_DWithin(Donor.location, Hospital.location, req.max_distance_km * 1000),
            Donor.id.not_in(already_contacted),
        )
        .order_by(dist_m)
        .limit(settings.max_candidates)
    )

    feats: list[DonorFeatures] = []
    for donor, d_m in db.execute(stmt).all():
        feats.append(DonorFeatures(
            donor_id=donor.id,
            distance_km=d_m / 1000.0,
            travel_radius_km=effective_radius_km(
                donor.travel_radius_weekday_km, donor.travel_radius_weekend_km, ctx.required_local),
            preferred_start=donor.preferred_start,
            preferred_end=donor.preferred_end,
            rating_avg=donor.rating_avg,
            response_rate=donor.response_rate,
            acceptance_rate=donor.acceptance_rate,
            donation_count=donor.donation_count,
            avg_response_seconds=donor.avg_response_seconds,
            days_since_last_donation=(required_date - donor.last_donation_date).days if donor.last_donation_date else None,
        ))
    return feats


def run_matching(db: Session, req: BloodRequest, top_n: int | None = None,
                 ml_scorer: MlScorer | None = None) -> list[Match]:
    """Rank donors for a request and (re)store the top N as SUGGESTED matches.

    Donors already contacted for this request (REQUESTED/ACCEPTED/DECLINED) are skipped,
    so calling this again after a decline naturally yields the next-best donors.
    """
    top_n = top_n or settings.default_top_n
    ctx = RequestContext(max_distance_km=req.max_distance_km, urgency=req.urgency,
                         required_local=to_local(req.required_time))
    feats = fetch_candidates(db, req, ctx)

    ml_scorer = ml_scorer or get_ml_scorer()        # None => rules-only ranking (ML weight redistributed)
    if ml_scorer is not None and feats:
        try:
            probs = ml_scorer(feats, ctx)
        except Exception:  # noqa: BLE001  - never fail a blood request because of the ML layer
            log.exception("ML scoring failed; ranking with rules only")
            probs = {}
        for f in feats:
            f.ml_probability = probs.get(f.donor_id)

    ranked = rank(feats, ctx, settings.weights, top_n)

    db.execute(delete(Match).where(Match.request_id == req.id, Match.status == MatchStatus.SUGGESTED))
    matches = [Match(request_id=req.id, donor_id=s.donor_id, score=s.score, distance_km=s.distance_km,
                     components=s.components, reasons=s.reasons, status=MatchStatus.SUGGESTED)
               for s in ranked]
    db.add_all(matches)
    db.flush()
    return matches
