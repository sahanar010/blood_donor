from datetime import date, datetime, time, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.enums import Availability, BloodGroup, MatchStatus, RequestStatus, Role, Urgency

PHONE = r"^\+?[0-9]{8,15}$"


# ------------------------------------------------------------------ auth
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: EmailStr
    role: Role


class DonorRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(pattern=PHONE)
    date_of_birth: date
    blood_group: BloodGroup
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    area_label: str | None = Field(default=None, max_length=120)
    travel_radius_weekday_km: float = Field(default=10, gt=0, le=100)
    travel_radius_weekend_km: float = Field(default=30, gt=0, le=200)
    preferred_start: time | None = None
    preferred_end: time | None = None

    @field_validator("date_of_birth")
    @classmethod
    def adult_only(cls, v: date) -> date:
        # Legal-age check for registering/consenting only. Medical eligibility is
        # decided by the hospital/blood bank, not by this app.
        today = date.today()
        age = today.year - v.year - ((today.month, today.day) < (v.month, v.day))
        if age < 18:
            raise ValueError("Donors must be at least 18 to register")
        return v


class HospitalRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=300)
    phone: str = Field(pattern=PHONE)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


# ------------------------------------------------------------------ donor
class DonorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ref: str
    name: str
    phone: str
    blood_group: BloodGroup
    latitude: float
    longitude: float
    area_label: str | None
    travel_radius_weekday_km: float
    travel_radius_weekend_km: float
    availability_status: Availability
    preferred_start: time | None
    preferred_end: time | None
    verified: bool
    last_donation_date: date | None
    donation_count: int
    rating_avg: float | None
    response_rate: float
    acceptance_rate: float
    avg_response_seconds: float | None


class DonorUpdate(BaseModel):
    """PATCH body. Only fields you send are changed; send null to clear preferred times."""
    phone: str | None = Field(default=None, pattern=PHONE)
    area_label: str | None = Field(default=None, max_length=120)
    availability_status: Availability | None = None
    travel_radius_weekday_km: float | None = Field(default=None, gt=0, le=100)
    travel_radius_weekend_km: float | None = Field(default=None, gt=0, le=200)
    preferred_start: time | None = None
    preferred_end: time | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def lat_lon_together(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Send latitude and longitude together")
        return self


class RespondBody(BaseModel):
    accepted: bool


class DonationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    donation_date: date
    verified_volume_ml: int
    experience_rating: float | None
    hospital_id: int | None


# ------------------------------------------------------------------ requests
class BloodRequestCreate(BaseModel):
    blood_group: BloodGroup
    units_required: int = Field(default=1, ge=1, le=10)
    urgency: Urgency = Urgency.NORMAL
    required_time: datetime
    max_distance_km: float = Field(default=15, gt=0, le=200)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("required_time")
    @classmethod
    def not_in_past(cls, v: datetime) -> datetime:
        if v.tzinfo is None:  # naive => assume hospital-local time (done in router)
            return v
        if v < datetime.now(timezone.utc):
            raise ValueError("required_time must be in the future")
        return v


class BloodRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    hospital_id: int
    blood_group: BloodGroup
    units_required: int
    units_fulfilled: int
    urgency: Urgency
    required_time: datetime
    max_distance_km: float
    notes: str | None
    status: RequestStatus
    created_at: datetime


class CloseRequestBody(BaseModel):
    status: RequestStatus

    @field_validator("status")
    @classmethod
    def only_terminal(cls, v):
        if v == RequestStatus.OPEN:
            raise ValueError("Use FULFILLED or CANCELLED")
        return v


# ------------------------------------------------------------------ matches (privacy-aware views)
class HospitalMatchOut(BaseModel):
    """What a hospital may see. Name/phone stay None until the donor ACCEPTS."""
    match_id: int
    donor_ref: str
    blood_group: BloodGroup
    distance_km: float
    score: float
    reasons: list[str]
    rating_avg: float | None
    response_rate: float
    status: MatchStatus
    donor_online: bool = False
    donor_name: str | None = None
    donor_phone: str | None = None


class SendRequestsBody(BaseModel):
    match_ids: list[int] | None = None  # default: all SUGGESTED matches


class DonorRequestOut(BaseModel):
    """What a donor sees for an incoming request."""
    match_id: int
    status: MatchStatus
    request_id: int
    request_status: RequestStatus
    hospital_name: str
    hospital_address: str
    blood_group: BloodGroup
    units_required: int
    urgency: Urgency
    required_time: datetime
    distance_km: float
    notes: str | None
    requested_at: datetime | None


class RecordDonationBody(BaseModel):
    verified_volume_ml: int = Field(gt=0, le=1000)
    experience_rating: float | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=500)


class VerifyBody(BaseModel):
    verified: bool = True
