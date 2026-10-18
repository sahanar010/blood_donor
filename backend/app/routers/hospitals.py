from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import matching_service, notifications
from app.config import settings
from app.deps import get_current_hospital, get_db, get_verified_hospital
from app.enums import MatchStatus, RequestStatus
from app.models import BloodRequest, Donation, Hospital, Match
from app.schemas import (BloodRequestCreate, BloodRequestOut, CloseRequestBody, HospitalMatchOut,
                         RecordDonationBody, SendRequestsBody)
from app.views import hospital_match_views

router = APIRouter(prefix="/hospital", tags=["hospital"])


def _own_request(db: Session, hospital: Hospital, request_id: int) -> BloodRequest:
    req = db.get(BloodRequest, request_id)
    if req is None or req.hospital_id != hospital.id:
        raise HTTPException(404, "Request not found")
    return req


def _matches(db: Session, request_id: int) -> list[Match]:
    return db.scalars(select(Match).where(Match.request_id == request_id)
                      .options(joinedload(Match.donor))
                      .order_by(Match.score.desc())).unique().all()


@router.get("/me")
def hospital_me(hospital: Hospital = Depends(get_current_hospital)):
    """Own profile (works before verification so the UI can show the pending state)."""
    return {"name": hospital.name, "address": hospital.address, "latitude": hospital.latitude,
            "longitude": hospital.longitude, "verified": hospital.verified}


@router.post("/requests", response_model=BloodRequestOut, status_code=201)
def create_request(body: BloodRequestCreate, hospital: Hospital = Depends(get_verified_hospital),
                   db: Session = Depends(get_db)):
    when = body.required_time
    if when.tzinfo is None:  # naive input => hospital-local wall-clock time
        when = when.replace(tzinfo=ZoneInfo(settings.local_tz))
        if when < datetime.now(timezone.utc):
            raise HTTPException(422, "required_time must be in the future")
    req = BloodRequest(hospital_id=hospital.id, blood_group=body.blood_group,
                       units_required=body.units_required, urgency=body.urgency,
                       required_time=when, max_distance_km=body.max_distance_km, notes=body.notes)
    db.add(req)
    db.commit()
    return req


@router.get("/requests", response_model=list[BloodRequestOut])
def list_requests(status: RequestStatus | None = None, hospital: Hospital = Depends(get_verified_hospital),
                  db: Session = Depends(get_db)):
    q = select(BloodRequest).where(BloodRequest.hospital_id == hospital.id)
    if status:
        q = q.where(BloodRequest.status == status)
    return db.scalars(q.order_by(BloodRequest.created_at.desc())).all()


@router.get("/requests/{request_id}", response_model=BloodRequestOut)
def get_request(request_id: int, hospital: Hospital = Depends(get_verified_hospital),
                db: Session = Depends(get_db)):
    return _own_request(db, hospital, request_id)


@router.post("/requests/{request_id}/find-donors", response_model=list[HospitalMatchOut])
def find_donors(request_id: int, top_n: int = Query(settings.default_top_n, ge=1, le=20),
                hospital: Hospital = Depends(get_verified_hospital), db: Session = Depends(get_db)):
    """Run the matching engine. Re-running replaces un-sent suggestions and skips donors
    already contacted, so after a decline you get the next-best donors."""
    req = _own_request(db, hospital, request_id)
    if req.status != RequestStatus.OPEN:
        raise HTTPException(409, "Request is not open")
    matching_service.run_matching(db, req, top_n)
    db.commit()
    return hospital_match_views([m for m in _matches(db, req.id) if m.status == MatchStatus.SUGGESTED])


@router.get("/requests/{request_id}/matches", response_model=list[HospitalMatchOut])
def list_matches(request_id: int, hospital: Hospital = Depends(get_verified_hospital),
                 db: Session = Depends(get_db)):
    req = _own_request(db, hospital, request_id)
    return hospital_match_views(_matches(db, req.id))


@router.post("/requests/{request_id}/send-requests", response_model=list[HospitalMatchOut])
def send_requests(request_id: int, body: SendRequestsBody = SendRequestsBody(),
                  hospital: Hospital = Depends(get_verified_hospital), db: Session = Depends(get_db)):
    """Notify the chosen suggested donors (default: all suggested)."""
    req = _own_request(db, hospital, request_id)
    if req.status != RequestStatus.OPEN:
        raise HTTPException(409, "Request is not open")
    targets = [m for m in _matches(db, req.id) if m.status == MatchStatus.SUGGESTED
               and (body.match_ids is None or m.id in body.match_ids)]
    if not targets:
        raise HTTPException(409, "No suggested matches to send. Call find-donors first.")
    now = datetime.now(timezone.utc)
    for m in targets:
        m.status, m.requested_at = MatchStatus.REQUESTED, now
        m.donor.requests_received += 1
    db.commit()
    notifications.donors_new_request(targets)   # live push to each donor
    return hospital_match_views(targets)


@router.post("/matches/{match_id}/record-donation", status_code=201)
def record_donation(match_id: int, body: RecordDonationBody,
                    hospital: Hospital = Depends(get_verified_hospital), db: Session = Depends(get_db)):
    """Hospital records a medically verified donation for an ACCEPTED match."""
    m = db.get(Match, match_id)
    if m is None or m.request.hospital_id != hospital.id:
        raise HTTPException(404, "Match not found")
    if m.status != MatchStatus.ACCEPTED:
        raise HTTPException(409, "Only accepted matches can be completed")

    today = datetime.now(ZoneInfo(settings.local_tz)).date()
    donor, req = m.donor, m.request
    db.add(Donation(donor_id=donor.id, hospital_id=hospital.id, match_id=m.id, donation_date=today,
                    verified_volume_ml=body.verified_volume_ml,
                    experience_rating=body.experience_rating, notes=body.notes))
    donor.last_donation_date = today
    donor.donation_count += 1
    if body.experience_rating is not None:
        total = (donor.rating_avg or 0) * donor.rating_count + body.experience_rating
        donor.rating_count += 1
        donor.rating_avg = round(total / donor.rating_count, 3)

    m.status = MatchStatus.COMPLETED
    req.units_fulfilled += 1
    if req.units_fulfilled >= req.units_required:
        req.status = RequestStatus.FULFILLED
    db.commit()
    notifications.hospital_request_updated(req)
    if req.status == RequestStatus.FULFILLED:
        notifications.donors_request_closed(db, req)
    return {"match_id": m.id, "request_status": req.status, "units_fulfilled": req.units_fulfilled}


@router.post("/requests/{request_id}/close", response_model=BloodRequestOut)
def close_request(request_id: int, body: CloseRequestBody,
                  hospital: Hospital = Depends(get_verified_hospital), db: Session = Depends(get_db)):
    req = _own_request(db, hospital, request_id)
    if req.status != RequestStatus.OPEN:
        raise HTTPException(409, "Request already closed")
    req.status = body.status
    db.commit()
    notifications.hospital_request_updated(req)
    notifications.donors_request_closed(db, req)
    return req
