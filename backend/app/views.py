"""Privacy boundary: the ONLY place that decides what each role may see."""
from app.enums import MatchStatus
from app.models import Match
from app.realtime import hub
from app.schemas import DonorRequestOut, HospitalMatchOut

_CONTACT_VISIBLE = {MatchStatus.ACCEPTED, MatchStatus.COMPLETED}


def hospital_match_view(m: Match, online: bool = False) -> HospitalMatchOut:
    d = m.donor
    revealed = m.status in _CONTACT_VISIBLE
    return HospitalMatchOut(
        match_id=m.id, donor_ref=d.ref, blood_group=d.blood_group,
        distance_km=m.distance_km, score=m.score, reasons=list(m.reasons or []),
        rating_avg=d.rating_avg, response_rate=round(d.response_rate, 3), status=m.status,
        donor_online=online,
        donor_name=d.name if revealed else None,
        donor_phone=d.phone if revealed else None,
    )


def hospital_match_views(matches: list[Match]) -> list[HospitalMatchOut]:
    """Batch version: one presence lookup for the whole list."""
    online = hub.online_user_ids(m.donor.user_id for m in matches)
    return [hospital_match_view(m, online=m.donor.user_id in online) for m in matches]


def donor_request_view(m: Match) -> DonorRequestOut:
    r, h = m.request, m.request.hospital
    return DonorRequestOut(
        match_id=m.id, status=m.status, request_id=r.id, request_status=r.status,
        hospital_name=h.name, hospital_address=h.address, blood_group=r.blood_group,
        units_required=r.units_required, urgency=r.urgency, required_time=r.required_time,
        distance_km=m.distance_km, notes=r.notes, requested_at=m.requested_at,
    )
