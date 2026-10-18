"""Shared enums (stdlib only, so the matching engine stays framework-free)."""
import enum


class Role(str, enum.Enum):
    DONOR = "DONOR"
    HOSPITAL = "HOSPITAL"
    ADMIN = "ADMIN"


class BloodGroup(str, enum.Enum):
    A_POS = "A+"
    A_NEG = "A-"
    B_POS = "B+"
    B_NEG = "B-"
    AB_POS = "AB+"
    AB_NEG = "AB-"
    O_POS = "O+"
    O_NEG = "O-"


class Availability(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"


class Urgency(str, enum.Enum):
    NORMAL = "NORMAL"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class RequestStatus(str, enum.Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class MatchStatus(str, enum.Enum):
    SUGGESTED = "SUGGESTED"    # ranked by the engine, donor not contacted yet
    REQUESTED = "REQUESTED"    # hospital sent the request to the donor
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"    # hospital recorded a verified donation
