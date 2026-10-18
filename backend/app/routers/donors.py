from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import notifications
from app.deps import get_current_donor, get_db
from app.enums import MatchStatus, RequestStatus
from app.geo import point
from app.models import BloodRequest, Donation, Donor, Match, Response
from app.schemas import DonationOut, DonorOut, DonorRequestOut, DonorUpdate, RespondBody
from app.views import donor_request_view

router = APIRouter(prefix="/donor", tags=["donor"])


@router.get("/me", response_model=DonorOut)
def get_me(donor: Donor = Depends(get_current_donor)):
    return donor


@router.patch("/me", response_model=DonorOut)
def update_me(body: DonorUpdate, donor: Donor = Depends(get_current_donor), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    lat, lon = data.pop("latitude", None), data.pop("longitude", None)
    for k, v in data.items():
        setattr(donor, k, v)
    if lat is not None and lon is not None:
        donor.latitude, donor.longitude, donor.location = lat, lon, point(lat, lon)
    db.commit()
    return donor


@router.get("/requests", response_model=list[DonorRequestOut])
def my_requests(status: MatchStatus | None = Query(None, description="Default: pending (REQUESTED)"),
                donor: Donor = Depends(get_current_donor), db: Session = Depends(get_db)):
    """Incoming blood requests addressed to this donor. SUGGESTED matches are never shown."""
    wanted = status or MatchStatus.REQUESTED
    if wanted == MatchStatus.SUGGESTED:
        return []
    q = select(Match).where(Match.donor_id == donor.id, Match.status == wanted)
    if wanted == MatchStatus.REQUESTED:  # don't show pending asks whose request has closed
        q = q.where(Match.request.has(BloodRequest.status == RequestStatus.OPEN))
    rows = db.scalars(q.options(joinedload(Match.request).joinedload(BloodRequest.hospital))
                      .order_by(Match.requested_at.desc())).unique().all()
    return [donor_request_view(m) for m in rows]


@router.post("/requests/{match_id}/respond", response_model=DonorRequestOut)
def respond(match_id: int, body: RespondBody,
            donor: Donor = Depends(get_current_donor), db: Session = Depends(get_db)):
    m = db.get(Match, match_id)
    if m is None or m.donor_id != donor.id or m.status == MatchStatus.SUGGESTED:
        raise HTTPException(404, "Request not found")  # SUGGESTED = donor was never contacted
    if m.status != MatchStatus.REQUESTED:
        raise HTTPException(409, f"Already {m.status.value.lower()}")
    if m.request.status != RequestStatus.OPEN:
        raise HTTPException(409, "This request is no longer open")

    now = datetime.now(timezone.utc)
    seconds = max(0.0, (now - m.requested_at).total_seconds())
    m.status = MatchStatus.ACCEPTED if body.accepted else MatchStatus.DECLINED
    m.responded_at = now
    db.add(Response(match_id=m.id, accepted=body.accepted, response_seconds=seconds, responded_at=now))

    donor.requests_responded += 1
    if body.accepted:
        donor.requests_accepted += 1
    n = donor.requests_responded
    donor.avg_response_seconds = seconds if donor.avg_response_seconds is None \
        else donor.avg_response_seconds + (seconds - donor.avg_response_seconds) / n
    db.commit()
    notifications.hospital_response(m)   # live update on the hospital dashboard
    return donor_request_view(m)


@router.get("/donations", response_model=list[DonationOut])
def my_donations(donor: Donor = Depends(get_current_donor), db: Session = Depends(get_db)):
    return db.scalars(select(Donation).where(Donation.donor_id == donor.id)
                      .order_by(Donation.donation_date.desc())).all()
