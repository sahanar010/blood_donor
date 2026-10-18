from datetime import date, datetime, time

from geoalchemy2 import Geography
from sqlalchemy import (Boolean, CheckConstraint, Date, DateTime, Enum, Float, ForeignKey, Index,
                        Integer, String, Text, Time, UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import (Availability, BloodGroup, MatchStatus, RequestStatus, Role, Urgency)


def enum_col(e, length: int = 16):
    """Store enum *values* as plain strings (no native PG enum => painless changes)."""
    return Enum(e, native_enum=False, length=length, validate_strings=True,
                values_callable=lambda x: [i.value for i in x])


# Rate smoothing: a donor with 1 request and 1 reply shouldn't show "100%".
# Blend observed counts with a prior of PRIOR_RATE worth PRIOR_STRENGTH observations.
PRIOR_RATE, PRIOR_STRENGTH = 0.6, 5


def _smoothed(successes: int, trials: int) -> float:
    return (successes + PRIOR_RATE * PRIOR_STRENGTH) / (trials + PRIOR_STRENGTH)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(enum_col(Role))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Donor(Base):
    __tablename__ = "donors"
    __table_args__ = (
        Index("ix_donors_match", "blood_group", "verified", "availability_status"),
        CheckConstraint("travel_radius_weekday_km > 0 AND travel_radius_weekend_km > 0", name="ck_radius_pos"),
        CheckConstraint("rating_avg IS NULL OR (rating_avg >= 0 AND rating_avg <= 5)", name="ck_rating_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    user: Mapped[User] = relationship()

    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(20))
    date_of_birth: Mapped[date] = mapped_column(Date)
    blood_group: Mapped[BloodGroup] = mapped_column(enum_col(BloodGroup, 3))

    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326))  # GiST index auto-created
    area_label: Mapped[str | None] = mapped_column(String(120))

    travel_radius_weekday_km: Mapped[float] = mapped_column(Float, default=10)
    travel_radius_weekend_km: Mapped[float] = mapped_column(Float, default=30)
    availability_status: Mapped[Availability] = mapped_column(enum_col(Availability), default=Availability.AVAILABLE)
    preferred_start: Mapped[time | None] = mapped_column(Time)
    preferred_end: Mapped[time | None] = mapped_column(Time)

    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # set by admin/hospital
    last_donation_date: Mapped[date | None] = mapped_column(Date)
    donation_count: Mapped[int] = mapped_column(Integer, default=0)
    rating_avg: Mapped[float | None] = mapped_column(Float)
    rating_count: Mapped[int] = mapped_column(Integer, default=0)

    requests_received: Mapped[int] = mapped_column(Integer, default=0)
    requests_responded: Mapped[int] = mapped_column(Integer, default=0)
    requests_accepted: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_seconds: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def ref(self) -> str:
        """Pseudonymous reference shown to hospitals before the donor accepts."""
        return f"D-{self.id:06d}"

    @property
    def response_rate(self) -> float:
        return _smoothed(self.requests_responded, self.requests_received)

    @property
    def acceptance_rate(self) -> float:
        return _smoothed(self.requests_accepted, self.requests_responded)


class Hospital(Base):
    __tablename__ = "hospitals"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    user: Mapped[User] = relationship()
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(300))
    phone: Mapped[str] = mapped_column(String(20))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    location = mapped_column(Geography(geometry_type="POINT", srid=4326))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BloodRequest(Base):
    __tablename__ = "blood_requests"
    __table_args__ = (CheckConstraint("units_required > 0", name="ck_units_pos"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[int] = mapped_column(ForeignKey("hospitals.id", ondelete="CASCADE"), index=True)
    hospital: Mapped[Hospital] = relationship()
    blood_group: Mapped[BloodGroup] = mapped_column(enum_col(BloodGroup, 3))
    units_required: Mapped[int] = mapped_column(Integer)
    units_fulfilled: Mapped[int] = mapped_column(Integer, default=0)
    urgency: Mapped[Urgency] = mapped_column(enum_col(Urgency), default=Urgency.NORMAL)
    required_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    max_distance_km: Mapped[float] = mapped_column(Float, default=15)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[RequestStatus] = mapped_column(enum_col(RequestStatus), default=RequestStatus.OPEN, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("request_id", "donor_id", name="uq_match_request_donor"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("blood_requests.id", ondelete="CASCADE"), index=True)
    request: Mapped[BloodRequest] = relationship()
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="CASCADE"), index=True)
    donor: Mapped[Donor] = relationship()
    score: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    components = mapped_column(JSONB, default=dict)
    reasons = mapped_column(JSONB, default=list)
    status: Mapped[MatchStatus] = mapped_column(enum_col(MatchStatus), default=MatchStatus.SUGGESTED, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Response(Base):
    __tablename__ = "responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), unique=True)
    accepted: Mapped[bool] = mapped_column(Boolean)
    response_seconds: Mapped[float] = mapped_column(Float)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Donation(Base):
    __tablename__ = "donations"
    id: Mapped[int] = mapped_column(primary_key=True)
    donor_id: Mapped[int] = mapped_column(ForeignKey("donors.id", ondelete="CASCADE"), index=True)
    hospital_id: Mapped[int | None] = mapped_column(ForeignKey("hospitals.id", ondelete="SET NULL"))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"))
    donation_date: Mapped[date] = mapped_column(Date)
    verified_volume_ml: Mapped[int] = mapped_column(Integer)  # recorded by hospital, never computed by the app
    experience_rating: Mapped[float | None] = mapped_column(Float)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
