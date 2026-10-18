import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.enums import Role
from app.models import Donor, Hospital, User
from app.security import decode_token

oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_db():
    with SessionLocal() as db:
        yield db


def get_current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    err = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token",
                        headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = decode_token(token)
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise err
    if user is None or not user.is_active:
        raise err
    return user


def require_role(*roles: Role):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
        return user
    return checker


def get_current_donor(user: User = Depends(require_role(Role.DONOR)), db: Session = Depends(get_db)) -> Donor:
    donor = db.scalar(select(Donor).where(Donor.user_id == user.id))
    if donor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Donor profile not found")
    return donor


def get_current_hospital(user: User = Depends(require_role(Role.HOSPITAL)), db: Session = Depends(get_db)) -> Hospital:
    hospital = db.scalar(select(Hospital).where(Hospital.user_id == user.id))
    if hospital is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Hospital profile not found")
    return hospital


def get_verified_hospital(hospital: Hospital = Depends(get_current_hospital)) -> Hospital:
    if not hospital.verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Hospital has not been verified by an admin yet")
    return hospital
