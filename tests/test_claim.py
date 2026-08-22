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


def test_per_vendor_state_is_independent():
    """A vendor's fulfilled order must not appear as 'completed' for another
    vendor who never interacted. Each vendor has an independent view."""
    with TestClient(app) as c:
        # Demo broadcast creates the order and BroadcastReceipt rows in DB.
        demo = c.get("/vendor/demo/broadcast").json()
        oid = demo["order_id"]
        total_meds = len(demo["medicines"])
        # Vendor 1 partially claims medicine[0] and fulfills.
        c.post(f"/claim/{oid}", json={"pharmacy_id": 1, "medicine_indices": [0]})
        f1 = c.post(f"/orders/{oid}/fulfill", json={"pharmacy_id": 1})
        assert f1.status_code == 200

        # Vendor 1 sees it as completed -> removed from active, in history.
        v1_active = c.get(f"/vendor/1/orders?status=active").json()
        assert all(o["order_id"] != oid for o in v1_active)
        v1_hist = c.get(f"/vendor/1/orders?status=history").json()
        assert any(o["order_id"] == oid and o["state"] == "completed" for o in v1_hist)

        # Vendor 2 (never claimed) must NOT see it as completed.
        v2_active = c.get(f"/vendor/2/orders?status=active").json()
        o2 = [o for o in v2_active if o["order_id"] == oid]
        assert len(o2) == 1
        assert o2[0]["state"] != "completed"
        # Vendor 2 claims ALL remaining medicines (indices 1..N-1).
        remaining = list(range(1, total_meds))
        r2 = c.post(f"/claim/{oid}", json={"pharmacy_id": 2, "medicine_indices": remaining})
        assert r2.status_code == 200
        assert r2.json()["medicines_remaining"] == 0


def test_fulfill_idempotency():
    """Double-fulfilling should return 409."""
    oid = _new_order()
    with TestClient(app) as c:
        c.post(f"/claim/{oid}", json={"pharmacy_id": 5})
        r1 = c.post(f"/orders/{oid}/fulfill", json={"pharmacy_id": 5})
        assert r1.status_code == 200
        r2 = c.post(f"/orders/{oid}/fulfill", json={"pharmacy_id": 5})
        assert r2.status_code == 409
