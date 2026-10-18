"""Generate a SYNTHETIC dataset (no real people). Run from backend/:

    python -m scripts.seed --donors 10000

Creates: 3 verified demo hospitals + N donors clustered around Chengalpattu / Chennai.
Demo logins:  hospital1@demo.local .. hospital3@demo.local / hospital12345
              donor00001@demo.local ..                      / donor12345
"""
import argparse
import random
from datetime import date, time, timedelta

from faker import Faker
from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.enums import Availability, BloodGroup, Role
from app.geo import point
from app.models import Donor, Hospital, User
from app.security import hash_password

# (lat, lon, label, weight)  -- approximate area centres
CLUSTERS = [
    (12.6819, 79.9888, "Chengalpattu", 0.30),
    (12.7940, 80.0230, "Maraimalai Nagar", 0.15),
    (12.9249, 80.1000, "Tambaram", 0.20),
    (13.0827, 80.2707, "Chennai", 0.25),
    (12.8342, 79.7036, "Kanchipuram", 0.10),
]
# Rough Indian ABO/Rh distribution, for a realistic-looking demo only.
GROUPS = [(BloodGroup.O_POS, .36), (BloodGroup.B_POS, .30), (BloodGroup.A_POS, .20), (BloodGroup.AB_POS, .06),
          (BloodGroup.O_NEG, .02), (BloodGroup.B_NEG, .02), (BloodGroup.A_NEG, .02), (BloodGroup.AB_NEG, .02)]
WINDOWS = [(None, None), (time(9), time(17)), (time(6), time(22)), (time(17), time(21)), (time(22), time(6))]

HOSPITALS = [
    ("Demo General Hospital - Chengalpattu", "Chengalpattu, Tamil Nadu", 12.6819, 79.9888),
    ("Demo City Hospital - Tambaram", "Tambaram, Chennai", 12.9249, 80.1000),
    ("Demo Medical Centre - Chennai", "Chennai Central, Chennai", 13.0827, 80.2707),
]


def binom(rng: random.Random, n: int, p: float) -> int:
    return sum(rng.random() < p for _ in range(n))


def make_donor(i: int, rng: random.Random, fake: Faker, pw_hash: str, today: date) -> Donor:
    lat0, lon0, label, _ = rng.choices(CLUSTERS, weights=[c[3] for c in CLUSTERS])[0]
    lat, lon = rng.gauss(lat0, 0.04), rng.gauss(lon0, 0.04)
    received = rng.randint(0, 40)
    responded = binom(rng, received, rng.betavariate(6, 2))
    accepted = binom(rng, responded, rng.betavariate(5, 2))
    donations = rng.choices([0, 1, 2, 3, 5, 8, 12], weights=[25, 20, 15, 15, 12, 8, 5])[0]

    r = rng.random()  # ~30% donated recently (=> ineligible right now), rest older or never
    if donations == 0:
        last = None
    elif r < 0.30:
        last = today - timedelta(days=rng.randint(5, 89))
    else:
        last = today - timedelta(days=rng.randint(90, 900))

    start, end = rng.choice(WINDOWS)
    weekday_km = rng.choice([5, 10, 15, 20])
    avail = rng.choices([Availability.AVAILABLE, Availability.BUSY, Availability.OFFLINE], [80, 14, 6])[0]
    return Donor(
        user=User(email=f"donor{i:05d}@demo.local", password_hash=pw_hash, role=Role.DONOR),
        name=fake.name(), phone="+91" + str(rng.randint(6_000_000_000, 9_999_999_999)),
        date_of_birth=today - timedelta(days=365 * rng.randint(18, 60) + rng.randint(0, 364)),
        blood_group=rng.choices([g for g, _ in GROUPS], weights=[w for _, w in GROUPS])[0],
        latitude=round(lat, 6), longitude=round(lon, 6), location=point(round(lat, 6), round(lon, 6)),
        area_label=label,
        travel_radius_weekday_km=weekday_km,
        travel_radius_weekend_km=weekday_km * rng.choice([1.5, 2, 3]),
        availability_status=avail, preferred_start=start, preferred_end=end,
        verified=rng.random() < 0.93,
        last_donation_date=last, donation_count=donations,
        rating_avg=round(min(5.0, max(3.0, rng.gauss(4.4, 0.4))), 2) if donations else None,
        rating_count=donations if donations else 0,
        requests_received=received, requests_responded=responded, requests_accepted=accepted,
        avg_response_seconds=round(rng.lognormvariate(5.5, 0.9), 1) if responded else None,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--donors", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    init_db()
    rng, fake = random.Random(args.seed), Faker("en_IN")
    Faker.seed(args.seed)
    today = date.today()

    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Donor)):
            print("Donors already exist - skipping (drop the volume to reseed).")
            return

        h_hash = hash_password("hospital12345")
        for n, (name, addr, lat, lon) in enumerate(HOSPITALS, start=1):
            db.add(Hospital(user=User(email=f"hospital{n}@demo.local", password_hash=h_hash, role=Role.HOSPITAL),
                            name=name, address=addr, phone="+914400000000" if n == 1 else f"+9144000000{n}0",
                            latitude=lat, longitude=lon, location=point(lat, lon), verified=True))
        db.commit()

        d_hash = hash_password("donor12345")  # hash once; 10k bcrypt rounds would take ages
        batch = 1000
        for start in range(1, args.donors + 1, batch):
            db.add_all(make_donor(i, rng, fake, d_hash, today)
                       for i in range(start, min(start + batch, args.donors + 1)))
            db.commit()
            print(f"  inserted {min(start + batch - 1, args.donors)}/{args.donors}")
    print("Done. Open http://localhost:8000/docs")


if __name__ == "__main__":
    main()
