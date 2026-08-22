"""Geospatial helpers for the trust-weighted broadcast."""
from math import asin, cos, radians, sin, sqrt

from sqlmodel import select

from app.models import Pharmacy

EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def find_nearby_pharmacies(
    session,
    lat: float,
    lon: float,
    radius_km: float = 5.0,
) -> list[Pharmacy]:
    """Active pharmacies within `radius_km`, trust-weighted (high first)."""
    pharmacies = session.exec(
        select(Pharmacy).where(Pharmacy.is_active == True)  # noqa: E712
    ).all()
    scored = [
        (haversine_km(lat, lon, p.location_lat, p.location_long), p)
        for p in pharmacies
        if p.location_lat is not None and p.location_long is not None
    ]
    nearby = [p for dist, p in scored if dist <= radius_km]
    nearby.sort(key=lambda p: p.trust_score, reverse=True)
    return nearby


def all_active_pharmacies(session) -> list[Pharmacy]:
    """Fallback when patient location is unknown: trust-weighted."""
    pharmacies = session.exec(
        select(Pharmacy).where(Pharmacy.is_active == True)  # noqa: E712
    ).all()
    pharmacies.sort(key=lambda p: p.trust_score, reverse=True)
    return pharmacies
