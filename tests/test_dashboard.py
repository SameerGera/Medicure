from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.database import engine
from app.models import BroadcastReceipt
from app.main import app


def test_dashboard_loads_with_id():
    with TestClient(app) as c:
        r = c.get("/vendor/5")
        assert r.status_code == 200
        assert "const PID=5;" in r.text


def test_health():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"


def test_demo_broadcast_creates_receipts():
    """Demo broadcast should insert BroadcastReceipt rows in the DB."""
    with TestClient(app) as c:
        demo = c.get("/vendor/demo/broadcast").json()
        assert demo["broadcast_to"] >= 1
        oid = demo["order_id"]

    with Session(engine) as s:
        receipts = s.exec(
            select(BroadcastReceipt).where(BroadcastReceipt.order_id == oid)
        ).all()
        assert len(receipts) >= 1
        assert all(r.pharmacy_id is not None for r in receipts)
