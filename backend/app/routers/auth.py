from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.enums import Role
from app.geo import point
from app.models import Donor, Hospital, User
from app.schemas import DonorOut, DonorRegister, HospitalRegister, Token, UserOut
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def _new_user(db: Session, email: str, password: str, role: Role) -> User:
    email = email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    return user


@router.post("/register/donor", response_model=DonorOut, status_code=201)
def register_donor(body: DonorRegister, db: Session = Depends(get_db)):
    user = _new_user(db, body.email, body.password, Role.DONOR)
    donor = Donor(
        user=user, name=body.name, phone=body.phone, date_of_birth=body.date_of_birth,
        blood_group=body.blood_group, latitude=body.latitude, longitude=body.longitude,
        location=point(body.latitude, body.longitude), area_label=body.area_label,
        travel_radius_weekday_km=body.travel_radius_weekday_km,
        travel_radius_weekend_km=body.travel_radius_weekend_km,
        preferred_start=body.preferred_start, preferred_end=body.preferred_end,
        verified=False,  # must be verified before anyone can be matched
    )
    db.add(donor)
    db.commit()
    return donor


@router.post("/register/hospital", status_code=201)
def register_hospital(body: HospitalRegister, db: Session = Depends(get_db)):
    user = _new_user(db, body.email, body.password, Role.HOSPITAL)
    hospital = Hospital(user=user, name=body.name, address=body.address, phone=body.phone,
                        latitude=body.latitude, longitude=body.longitude,
                        location=point(body.latitude, body.longitude), verified=False)
    db.add(hospital)
    db.commit()
    return {"id": hospital.id, "name": hospital.name, "verified": hospital.verified,
            "detail": "Registered. An admin must verify the hospital before it can create requests."}


@router.post("/login", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == form.username.lower()))
    if not user or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password",
                            headers={"WWW-Authenticate": "Bearer"})
    return Token(access_token=create_access_token(user.id, user.role.value), role=user.role)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
