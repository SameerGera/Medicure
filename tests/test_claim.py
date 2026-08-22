from fastapi.testclient import TestClient
from sqlmodel import Session
from app.database import engine
from app.models import Order, OrderStatus
from app.main import app

def _new_order():
    with Session(engine) as s:
        o = Order(user_id=1, raw_message="{}", status=OrderStatus.PENDING)
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
