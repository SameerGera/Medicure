"""End-to-end pipeline tests.

Verifies: Twilio webhook → Gemini inference (mocked) → BroadcastReceipt creation.
"""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.models import BroadcastReceipt, Order
from app.main import app

GEMINI_JSON = json.dumps(
    {
        "medicines": [{"name": "Paracetamol", "quantity": 2, "approx_unit_price": 5.0}],
        "estimated_value": 10.0,
    }
)


class FakeResp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


async def fake_post(self, url, params=None, json=None, **kw):
    """Mock httpx.AsyncClient.post — returns fake Gemini response."""
    if "generativelanguage" in url:
        return FakeResp(
            {"candidates": [{"content": {"parts": [{"text": GEMINI_JSON}]}}]}
        )
    return FakeResp(status_code=200)


def _noop_validate(*args, **kwargs):
    """Bypass Twilio signature validation in tests."""
    pass


def test_ingest_http_creates_pending_order():
    with (
        patch("httpx.AsyncClient.post", new=fake_post),
        patch("app.routers.ingestion._validate_twilio_signature", _noop_validate),
    ):
        with TestClient(app) as c:
            r = c.post(
                "/webhook/twilio",
                data={
                    "From": "whatsapp:+91981112233",
                    "Body": "Need Paracetamol 500mg x2",
                    "NumMedia": "0",
                    "Latitude": "12.9352",
                    "Longitude": "77.6245",
                },
            )
            assert r.status_code == 200
    with Session(engine) as s:
        orders = s.exec(select(Order)).all()
        assert any(o.raw_message and "Paracetamol" in o.raw_message for o in orders)


def test_pipeline_infers_and_broadcasts_to_db():
    """Full pipeline: Twilio webhook → Gemini inference → DB broadcast receipts."""
    with (
        patch("httpx.AsyncClient.post", new=fake_post),
        patch("app.routers.ingestion._validate_twilio_signature", _noop_validate),
    ):
        with TestClient(app) as c:
            r = c.post(
                "/webhook/twilio",
                data={
                    "From": "whatsapp:+91981112233",
                    "Body": "Need Paracetamol 500mg x2",
                    "NumMedia": "0",
                    "Latitude": "12.9352",
                    "Longitude": "77.6245",
                },
            )
            assert r.status_code == 200

    # Find the most recently created order.
    with Session(engine) as s:
        orders = s.exec(
            select(Order).order_by(Order.id.desc())
        ).all()
        order = orders[0]

        # 1) Inference populated prescription + AOV from the (stubbed) Vision LLM.
        parsed = json.loads(order.prescription_text)
        assert parsed["estimated_value"] == 10.0
        assert parsed["medicines"][0]["name"] == "Paracetamol"

        # 2) Broadcast created DB receipts (not HTTP webhook calls).
        receipts = s.exec(
            select(BroadcastReceipt).where(
                BroadcastReceipt.order_id == order.id
            )
        ).all()
        assert len(receipts) >= 1, f"Expected broadcast receipts, got {receipts}"
        for r in receipts:
            assert r.pharmacy_id is not None
            assert r.distance_km is not None
