"""Vendor web dashboard + broadcast receiver.

This is a single-app prototype: the same FastAPI process both dispatches
orders AND serves the vendor UI. Each pharmacy points its webhook_url at
POST /vendor/{pharmacy_id}/broadcast, which stores the incoming order so
the dashboard can poll and claim it.

The dashboard UI lives in app/static/{vendor.html,vendor.css,vendor.js}.
"""
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.geo import all_active_pharmacies, haversine_km
from app.models import Order, OrderStatus, Pharmacy

router = APIRouter(prefix="/vendor", tags=["vendor"])

STATIC_DIR = Path(__file__).parent.parent / "static"

# In-memory store of received broadcasts, keyed by pharmacy_id (prototype).
RECEIVED: dict[int, list[dict]] = {}

# Diverse prescriptions for simulation (no LLM needed)
PRESCRIPTION_POOL = [
    {
        "medicines": [
            {"name": "Paracetamol 500mg", "quantity": 2, "approx_unit_price": 5.0},
            {"name": "Amoxicillin 250mg", "quantity": 1, "approx_unit_price": 12.0},
        ],
        "estimated_value": 22.0,
    },
    {
        "medicines": [
            {"name": "Metformin 500mg", "quantity": 3, "approx_unit_price": 8.0},
            {"name": "Glimepiride 2mg", "quantity": 1, "approx_unit_price": 15.0},
        ],
        "estimated_value": 39.0,
    },
    {
        "medicines": [
            {"name": "Atorvastatin 20mg", "quantity": 1, "approx_unit_price": 18.0},
            {"name": "Aspirin 75mg", "quantity": 2, "approx_unit_price": 3.0},
            {"name": "Omeprazole 20mg", "quantity": 1, "approx_unit_price": 10.0},
        ],
        "estimated_value": 34.0,
    },
    {
        "medicines": [
            {"name": "Cetirizine 10mg", "quantity": 1, "approx_unit_price": 6.0},
            {"name": "Montelukast 10mg", "quantity": 1, "approx_unit_price": 14.0},
            {"name": "Pantoprazole 40mg", "quantity": 2, "approx_unit_price": 9.0},
        ],
        "estimated_value": 38.0,
    },
    {
        "medicines": [
            {"name": "Dolo 650", "quantity": 4, "approx_unit_price": 4.0},
            {"name": "Azithromycin 500mg", "quantity": 1, "approx_unit_price": 20.0},
            {"name": "Domperidone 10mg", "quantity": 1, "approx_unit_price": 7.0},
        ],
        "estimated_value": 43.0,
    },
    {
        "medicines": [
            {"name": "Losartan 50mg", "quantity": 1, "approx_unit_price": 22.0},
            {"name": "Amlodipine 5mg", "quantity": 1, "approx_unit_price": 11.0},
        ],
        "estimated_value": 33.0,
    },
    {
        "medicines": [
            {"name": "Levocetirizine 5mg", "quantity": 2, "approx_unit_price": 5.0},
            {"name": "Ambroxol 75mg", "quantity": 1, "approx_unit_price": 9.0},
            {"name": "Guaifenesin 100mg", "quantity": 1, "approx_unit_price": 6.0},
        ],
        "estimated_value": 25.0,
    },
    {
        "medicines": [
            {"name": "Ibuprofen 400mg", "quantity": 2, "approx_unit_price": 4.0},
            {"name": "Ranitidine 150mg", "quantity": 1, "approx_unit_price": 7.0},
        ],
        "estimated_value": 15.0,
    },
]


def _random_rx() -> dict:
    return random.choice(PRESCRIPTION_POOL)


def _broadcast_to_all_nearby(session: Session, order: Order, rx: dict) -> int:
    """Broadcast order to all nearby pharmacies via webhook. Returns count."""
    settings = get_settings()
    pharmacies = all_active_pharmacies(session)
    patient_lat = order.location_lat
    patient_long = order.location_long
    count = 0
    for ph in pharmacies:
        if ph.location_lat is None or ph.location_long is None:
            continue
        dist = haversine_km(patient_lat, patient_long, ph.location_lat, ph.location_long)
        if dist > 5.0:
            continue
        if not ph.webhook_url:
            continue
        payload = {
            "order_id": order.id,
            "medicines": rx["medicines"],
            "estimated_value": rx["estimated_value"],
            "patient": {"lat": patient_lat, "long": patient_long},
            "distance_km": round(dist, 1),
            "broadcast_at": datetime.now(timezone.utc).isoformat(),
            "claim_url": f"{settings.public_base_url}/claim/{order.id}",
        }
        RECEIVED.setdefault(ph.id, []).append(payload)
        count += 1
    return count


# --- Static / exact-match routes (registered FIRST so they win over path params) ---

@router.get("/setup")
def setup_all_webhooks(session: Session = Depends(get_session)):
    settings = get_settings()
    count = 0
    for ph in session.exec(select(Pharmacy).where(Pharmacy.is_active == True)):  # noqa: E712
        ph.webhook_url = f"{settings.public_base_url}/vendor/{ph.id}/broadcast"
        session.add(ph)
        count += 1
    session.commit()
    return {"registered": count}


@router.get("/demo/broadcast")
def demo_broadcast_all(session: Session = Depends(get_session)):
    """Simulate an order and broadcast to ALL nearby pharmacies at once.
    Used for demo: shows fastest-finger-first as multiple vendors race to claim."""
    rx = _random_rx()
    patient_lat = 12.9352 + random.uniform(-0.003, 0.003)
    patient_long = 77.6245 + random.uniform(-0.003, 0.003)
    order = Order(
        user_id=1,
        status=OrderStatus.PENDING,
        raw_message=json.dumps({"body": "Demo broadcast", "media": []}),
        location_lat=patient_lat,
        location_long=patient_long,
        estimated_value=rx["estimated_value"],
        prescription_text=json.dumps(rx),
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    count = _broadcast_to_all_nearby(session, order, rx)
    return {
        "order_id": order.id,
        "broadcast_to": count,
        "medicines": [m["name"] for m in rx["medicines"]],
        "estimated_value": rx["estimated_value"],
    }


@router.get("/{pharmacy_id}")
def dashboard(pharmacy_id: int, session: Session = Depends(get_session)):
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    html = (STATIC_DIR / "vendor.html").read_text(encoding="utf-8")
    bootstrap = (
        f"<script>const PID={pharmacy_id};"
        f"const PHARMACY_NAME={json.dumps(ph.name)};</script>"
    )
    html = html.replace("<!--BOOTSTRAP-->", bootstrap)
    return HTMLResponse(html)


# --- Sub-path routes (registered AFTER the parent catch-all) ---

@router.get("/{pharmacy_id}/orders")
def vendor_orders(
    pharmacy_id: int,
    status: str = "active",
    session: Session = Depends(get_session),
):
    """Return orders for this pharmacy. status=active|history|all."""
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    items = RECEIVED.get(pharmacy_id, [])
    out = []
    for it in items:
        order = session.get(Order, it.get("order_id"))
        if order is None:
            continue

        # Compute display state
        if order.status == OrderStatus.COMPLETED:
            state = "completed"
        elif order.status == OrderStatus.PARTIAL:
            state = "partial"
        elif order.status in (OrderStatus.CLAIMED, OrderStatus.COMPLETED):
            state = "won" if order.claimed_by_pharmacy_id == pharmacy_id else "lost"
        else:
            state = "pending"

        # Filter based on status query
        if status == "active" and state in ("completed", "lost"):
            continue
        if status == "history" and state not in ("completed", "lost"):
            continue

        distance = None
        if (
            order.location_lat is not None
            and order.location_long is not None
            and ph.location_lat is not None
            and ph.location_long is not None
        ):
            distance = round(
                haversine_km(
                    order.location_lat,
                    order.location_long,
                    ph.location_lat,
                    ph.location_long,
                ),
                1,
            )
        claimed_medicines = None
        if order.claimed_medicines:
            try:
                claimed_medicines = json.loads(order.claimed_medicines)
            except (json.JSONDecodeError, AttributeError):
                pass

        # Parse prescription for display
        medicines = []
        try:
            rx = json.loads(order.prescription_text)
            medicines = rx.get("medicines", [])
        except (json.JSONDecodeError, TypeError):
            pass

        out.append({
            **it,
            "state": state,
            "distance_km": distance,
            "claimed_medicines": claimed_medicines,
            "medicines": medicines,
            "estimated_value": order.estimated_value,
        })
    return out


@router.post("/{pharmacy_id}/broadcast")
async def receive_broadcast(
    pharmacy_id: int, payload: dict, session: Session = Depends(get_session)
):
    if session.get(Pharmacy, pharmacy_id) is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    entry = dict(payload)
    entry["received_at"] = time.time()
    RECEIVED.setdefault(pharmacy_id, []).append(entry)
    return {"ok": True}


@router.post("/{pharmacy_id}/register")
def register_webhook(pharmacy_id: int, session: Session = Depends(get_session)):
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    settings = get_settings()
    ph.webhook_url = f"{settings.public_base_url}/vendor/{pharmacy_id}/broadcast"
    session.add(ph)
    session.commit()
    return {"webhook_url": ph.webhook_url}


@router.post("/{pharmacy_id}/simulate")
def simulate_order(pharmacy_id: int, session: Session = Depends(get_session)):
    """Simulate a single order for this pharmacy (fast demo)."""
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    rx = _random_rx()
    order = Order(
        user_id=1,
        status=OrderStatus.PENDING,
        raw_message=json.dumps({"body": "Simulated order", "media": []}),
        location_lat=ph.location_lat + 0.004,
        location_long=ph.location_long,
        estimated_value=rx["estimated_value"],
        prescription_text=json.dumps(rx),
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    settings = get_settings()
    payload = {
        "order_id": order.id,
        "medicines": rx["medicines"],
        "estimated_value": rx["estimated_value"],
        "patient": {"lat": ph.location_lat + 0.004, "long": ph.location_long},
        "broadcast_at": datetime.now(timezone.utc).isoformat(),
        "claim_url": f"{settings.public_base_url}/claim/{order.id}",
    }
    RECEIVED.setdefault(pharmacy_id, []).append(payload)
    return {"order_id": order.id}
