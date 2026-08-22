from sqlmodel import Session
from app.database import engine
from app.geo import haversine_km, find_nearby_pharmacies

def test_haversine_small_distance():
    d = haversine_km(12.9352, 77.6245, 12.9401, 77.6262)
    assert 0.4 < d < 0.9

def test_nearby_sorted_by_trust():
    with Session(engine) as s:
        near = find_nearby_pharmacies(s, 12.9352, 77.6245, 5.0)
        assert near, "expected nearby pharmacies"
        scores = [p.trust_score for p in near]
        assert scores == sorted(scores, reverse=True)

def test_far_location_excluded():
    with Session(engine) as s:
        assert find_nearby_pharmacies(s, 0.0, 0.0, 5.0) == []
