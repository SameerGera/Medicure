from fastapi.testclient import TestClient
from app.main import app

def test_vendor_setup_registers_webhooks():
    with TestClient(app) as c:
        r = c.get("/vendor/setup")
        assert r.status_code == 200
        assert r.json()["registered"] >= 1

def test_dashboard_loads_with_id():
    with TestClient(app) as c:
        r = c.get("/vendor/5")
        assert r.status_code == 200
        assert "const PID=5;" in r.text

def test_health():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"] == "ok"
