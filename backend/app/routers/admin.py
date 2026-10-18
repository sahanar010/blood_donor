from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db, require_role
from app.enums import Role
from app.ml.scorer import get_ml_scorer, reload_ml_scorer
from app.models import Donor, Hospital
from app.schemas import VerifyBody

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_role(Role.ADMIN))])


@router.get("/pending")
def pending(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    hospitals = db.scalars(select(Hospital).where(Hospital.verified.is_(False)).limit(limit)).all()
    donors = db.scalars(select(Donor).where(Donor.verified.is_(False)).limit(limit)).all()
    return {
        "hospitals": [{"id": h.id, "name": h.name, "address": h.address, "phone": h.phone} for h in hospitals],
        "donors": [{"id": d.id, "ref": d.ref, "blood_group": d.blood_group, "area": d.area_label} for d in donors],
    }


@router.post("/hospitals/{hospital_id}/verify")
def verify_hospital(hospital_id: int, body: VerifyBody = VerifyBody(), db: Session = Depends(get_db)):
    h = db.get(Hospital, hospital_id)
    if not h:
        raise HTTPException(404, "Hospital not found")
    h.verified = body.verified
    db.commit()
    return {"id": h.id, "verified": h.verified}


@router.post("/donors/{donor_id}/verify")
def verify_donor(donor_id: int, body: VerifyBody = VerifyBody(), db: Session = Depends(get_db)):
    d = db.get(Donor, donor_id)
    if not d:
        raise HTTPException(404, "Donor not found")
    d.verified = body.verified
    db.commit()
    return {"id": d.id, "ref": d.ref, "verified": d.verified}


def _ml_info(model):
    if model is None:
        return {"loaded": False, "detail": "No model loaded. Train one with: python -m app.ml.train"}
    m = model.meta
    return {"loaded": True, "trained_at": m.get("trained_at"), "data_source": m.get("data_source"),
            "test_metrics": m.get("test_metrics"), "feature_gain": m.get("feature_gain")}


@router.get("/ml/status")
def ml_status():
    return _ml_info(get_ml_scorer())


@router.post("/ml/reload")
def ml_reload():
    """Pick up a freshly trained model without restarting the API."""
    return _ml_info(reload_ml_scorer())
