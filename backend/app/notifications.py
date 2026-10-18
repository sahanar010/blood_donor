"""Turns domain changes into realtime events. Call these AFTER db.commit().

Events (all shaped {"type", "data", "ts"}):
  to DONOR    request.new        a hospital sent you a request           data = DonorRequestOut
  to DONOR    request.closed     the request was fulfilled/cancelled     data = {request_id, status}
  to HOSPITAL match.responded    a donor accepted/declined               data = HospitalMatchOut + request_id
  to HOSPITAL request.updated    status / units changed                  data = {request_id, status, units_*}
Each user only ever receives events addressed to their own user id.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.enums import MatchStatus
from app.models import BloodRequest, Match
from app.realtime import hub
from app.views import donor_request_view, hospital_match_view


def donors_new_request(matches: list[Match]) -> None:
    for m in matches:
        hub.publish(m.donor.user_id, {"type": "request.new",
                                      "data": donor_request_view(m).model_dump(mode="json")})


def hospital_response(m: Match) -> None:
    online = m.donor.user_id in hub.online_user_ids([m.donor.user_id])
    data = hospital_match_view(m, online=online).model_dump(mode="json")
    data["request_id"] = m.request_id
    hub.publish(m.request.hospital.user_id, {"type": "match.responded", "data": data})


def hospital_request_updated(req: BloodRequest) -> None:
    hub.publish(req.hospital.user_id, {"type": "request.updated", "data": {
        "request_id": req.id, "status": req.status.value,
        "units_required": req.units_required, "units_fulfilled": req.units_fulfilled}})


def donors_request_closed(db: Session, req: BloodRequest) -> None:
    """Tell donors who still have a pending request that it is no longer open."""
    pending = db.scalars(select(Match).where(Match.request_id == req.id,
                                             Match.status == MatchStatus.REQUESTED)
                         .options(joinedload(Match.donor))).unique().all()
    for m in pending:
        hub.publish(m.donor.user_id, {"type": "request.closed",
                                      "data": {"request_id": req.id, "status": req.status.value}})
