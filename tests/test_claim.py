import json
from fastapi.testclient import TestClient
from sqlmodel import Session
from app.database import engine
from app.models import Order, OrderStatus
from app.main import app

SAMPLE_RX = json.dumps({
    "medicines": [
        {"name": "Paracetamol", "quantity": 2, "approx_unit_price": 5.0},
        {"name": "Amoxicillin", "quantity": 1, "approx_unit_price": 12.0},
    ],
    "estimated_value": 22.0,
})

def _new_order():
    with Session(engine) as s:
        o = Order(user_id=1, raw_message="{}", status=OrderStatus.PENDING, prescription_text=SAMPLE_RX)
        s.add(o)
        s.commit()
        s.refresh(o)
        return o.id

def test_first_claim_wins_second_fails():
    oid = _new_order()
    with TestClient(app) as c:
        r1 = c.post(f"/claim/{oid}", json={"pharmacy_id": 5})
        assert r1.status_code == 200
        r2 = c.post(f"/claim/{oid}", json={"pharmacy_id": 1})
        assert r2.status_code == 409

def test_claim_unknown_pharmacy_404():
    oid = _new_order()
    with TestClient(app) as c:
        r = c.post(f"/claim/{oid}", json={"pharmacy_id": 9999})
        assert r.status_code == 404

def test_claim_missing_order_404():
    with TestClient(app) as c:
        r = c.post("/claim/99999999", json={"pharmacy_id": 5})
        assert r.status_code == 404

def test_partial_claim():
    oid = _new_order()
    with TestClient(app) as c:
        r1 = c.post(f"/claim/{oid}", json={"pharmacy_id": 5, "medicine_indices": [0]})
        assert r1.status_code == 200
        data = r1.json()
        assert data["status"] == "partial"
        assert data["medicines_claimed"] == 1
        assert data["medicines_remaining"] == 1
        r2 = c.post(f"/claim/{oid}", json={"pharmacy_id": 1, "medicine_indices": [1]})
        assert r2.status_code == 200
        assert r2.json()["status"] == "claimed"
