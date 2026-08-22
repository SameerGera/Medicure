import asyncio
import json
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.database import engine
from app.models import Order, OrderStatus, Pharmacy
from app.services.ingest import handle_incoming_message
from app.main import app

GEMINI_JSON = json.dumps(
    {
        "medicines": [{"name": "Paracetamol", "quantity": 2, "approx_unit_price": 5.0}],
        "estimated_value": 10.0,
    }
)

CAPTURE = []


class FakeResp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


async def fake_post(self, url, params=None, json=None, **kw):
    # Gemini vision call -> return a structured prescription.
    if "generativelanguage" in url:
        return FakeResp(
            {"candidates": [{"content": {"parts": [{"text": GEMINI_JSON}]}}]}
        )
    # Anything else is a pharmacy webhook -> record it for assertions.
    CAPTURE.append({"url": url, "payload": json})
    return FakeResp(status_code=200)


def test_ingest_http_creates_pending_order():
    CAPTURE.clear()
    with patch("httpx.AsyncClient.post", new=fake_post):
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


def test_pipeline_infers_and_broadcasts():
    CAPTURE.clear()
    with Session(engine) as s:
        ph = s.get(Pharmacy, 5)
        ph.webhook_url = "https://vendor.test/hook"
        s.add(ph)
        s.commit()

    with patch("httpx.AsyncClient.post", new=fake_post):
        async def go():
            o = await handle_incoming_message(
                Session(engine),
                "+91981112233",
                "Need Paracetamol 500mg x2",
                [],
                lat=12.9352,
                lon=77.6245,
            )
            # let the offloaded broadcast task run
            await asyncio.sleep(0.3)
            return o

        order = asyncio.run(go())

    # 1) inference populated prescription + AOV from the (stubbed) Vision LLM
    parsed = json.loads(order.prescription_text)
    assert parsed["estimated_value"] == 10.0
    assert parsed["medicines"][0]["name"] == "Paracetamol"

    # 2) broadcast delivered the order to the registered pharmacy webhook
    assert any("vendor.test/hook" in c["url"] for c in CAPTURE), CAPTURE
    sent = next(c for c in CAPTURE if "vendor.test/hook" in c["url"])
    assert sent["payload"]["medicines"][0]["name"] == "Paracetamol"
    assert "claim_url" in sent["payload"]
