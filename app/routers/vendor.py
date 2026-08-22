"""Vendor web dashboard.

Serves the vendor UI from app/static/ and provides APIs for the
dashboard to poll orders, trigger demo broadcasts, and manage claims.

All broadcast state is now persisted in the BroadcastReceipt DB table
(no in-memory dict), so this works on Vercel serverless.
"""
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.geo import haversine_km
from app.models import BroadcastReceipt, Order, OrderStatus, Pharmacy
from app.routers.orders import _all_claimed_indices, _total_medicines
from app.services.broadcast import broadcast_to_nearby

router = APIRouter(prefix="/vendor", tags=["vendor"])

STATIC_DIR = Path(__file__).parent.parent / "static"

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


# --- Static / exact-match routes (registered FIRST so they win over path params) ---


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

    count = broadcast_to_nearby(session, order)
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
    status: str | None = None,
    session: Session = Depends(get_session),
):
    """Return orders for this pharmacy. status=active|history|all."""
    if not status:
        status = "active"
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")

    # Query broadcast receipts for this pharmacy from DB.
    receipts = session.exec(
        select(BroadcastReceipt).where(
            BroadcastReceipt.pharmacy_id == pharmacy_id
        )
    ).all()

    out = []
    for receipt in receipts:
        order = session.get(Order, receipt.order_id)
        if order is None:
            continue

        # Compute display state RELATIVE TO THIS pharmacy.
        # Each vendor has an independent view of the same broadcast order.
        my_claimed_entries = []
        if order.claimed_medicines:
            try:
                for e in json.loads(order.claimed_medicines):
                    if e.get("pharmacy_id") == pharmacy_id:
                        my_claimed_entries.append(e)
            except (json.JSONDecodeError, AttributeError):
                pass

        fulfilled = []
        if order.fulfilled_by:
            try:
                fulfilled = json.loads(order.fulfilled_by)
            except (json.JSONDecodeError, AttributeError):
                pass
        i_fulfilled = pharmacy_id in fulfilled
        i_claimed = len(my_claimed_entries) > 0

        if i_claimed and i_fulfilled:
            state = "completed"      # I fulfilled my part -> done for me
        elif i_claimed and not i_fulfilled:
            state = "partial"        # I claimed, can still fulfill
        else:
            # I never claimed anything on this order.
            all_claimed = _all_claimed_indices(order)
            total = _total_medicines(order)
            if len(all_claimed) >= total and total > 0:
                state = "lost"       # everything taken by others
            else:
                state = "pending"    # still medicines available for me

        # Filter based on status query
        # "lost" orders where we never claimed → skip entirely (not our history)
        if state == "lost":
            continue
        if status == "active" and state == "completed":
            continue
        if status == "history" and state != "completed":
            continue

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
            "order_id": order.id,
            "distance_km": receipt.distance_km,
            "received_at": receipt.received_at.timestamp(),
            "estimated_value": order.estimated_value,
            "state": state,
            "claimed_medicines": claimed_medicines,
            "medicines": medicines,
        })
    return out


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

    broadcast_to_nearby(session, order)
    return {"order_id": order.id}
