from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > 72:  # bcrypt limit
        raise ValueError("Password must be at most 72 bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    return jwt.encode({"sub": str(user_id), "role": role, "exp": exp}, settings.secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError on invalid/expired tokens."""
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
