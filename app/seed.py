"""Seed sample pharmacies around a center point.

Usage:
    python -m app.seed
"""
from sqlmodel import func, select

from app.database import Session, create_db_and_tables, engine
from app.models import Pharmacy

# Demo center: Koramangala, Bangalore. Vendors spread within ~5km.
CENTER_LAT = 12.9352
CENTER_LONG = 77.6245

SAMPLE_PHARMACIES = [
    ("Anand Pharma", 12.9362, 77.6225, "+919900000001", 8.4),
    ("Relief meds", 12.9340, 77.6270, "+919900000002", 6.1),
    ("City Care Pharmacy", 12.9388, 77.6201, "+919900000003", 7.2),
    ("MediQuick", 12.9319, 77.6298, "+919900000004", 4.5),
    ("Sri Venkateshwara", 12.9401, 77.6262, "+919900000005", 9.0),
    ("HealthPoint", 12.9295, 77.6218, "+919900000006", 5.3),
]


def seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        existing = session.exec(select(func.count()).select_from(Pharmacy)).one()
        if existing:
            print(f"Pharmacies already present ({existing}); skipping seed.")
            return
        for name, lat, lng, phone, trust in SAMPLE_PHARMACIES:
            session.add(
                Pharmacy(
                    name=name,
                    location_lat=lat,
                    location_long=lng,
                    phone_number=phone,
                    trust_score=trust,
                    is_active=True,
                )
            )
        session.commit()
        print(f"Seeded {len(SAMPLE_PHARMACIES)} pharmacies.")


if __name__ == "__main__":
    seed()
