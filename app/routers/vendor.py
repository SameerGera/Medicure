"""Vendor web dashboard + broadcast receiver.

This is a single-app prototype: the same FastAPI process both dispatches
orders AND serves the vendor UI. Each pharmacy points its webhook_url at
POST /vendor/{pharmacy_id}/broadcast, which stores the incoming order so
the dashboard can poll and claim it.

The dashboard UI lives in app/static/{vendor.html,vendor.css,vendor.js}.
"""
import json
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models import Order, OrderStatus, Pharmacy

router = APIRouter(prefix="/vendor", tags=["vendor"])

STATIC_DIR = Path(__file__).parent.parent / "static"

# In-memory store of received broadcasts, keyed by pharmacy_id (prototype).
RECEIVED: dict[int, list[dict]] = {}


@router.get("/setup")
def setup_all_webhooks(session: Session = Depends(get_session)):
    """Point every active pharmacy's webhook_url at this dashboard."""
    settings = get_settings()
    count = 0
    for ph in session.exec(select(Pharmacy).where(Pharmacy.is_active == True)):  # noqa: E712
        ph.webhook_url = f"{settings.public_base_url}/vendor/{ph.id}/broadcast"
        session.add(ph)
        count += 1
    session.commit()
    return {"registered": count}


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


@router.get("/{pharmacy_id}/orders")
def vendor_orders(pharmacy_id: int, session: Session = Depends(get_session)):
    if session.get(Pharmacy, pharmacy_id) is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    items = RECEIVED.get(pharmacy_id, [])
    out = []
    for it in items:
        order = session.get(Order, it.get("order_id"))
        state = "pending"
        if order and order.status != OrderStatus.PENDING:
            state = "won" if order.claimed_by_pharmacy_id == pharmacy_id else "lost"
        out.append({**it, "state": state})
    return out


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
