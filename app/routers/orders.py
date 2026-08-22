from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select, update

from app.database import get_session
from app.models import Order, OrderStatus, Pharmacy
from app.services.notifications import route_patient_to_pharmacy

router = APIRouter(tags=["orders"])


class ClaimRequest(BaseModel):
    pharmacy_id: int


@router.post("/claim/{order_id}")
async def claim_order(
    order_id: int,
    body: ClaimRequest,
    session: Session = Depends(get_session),
) -> dict:
    pharmacy = session.get(Pharmacy, body.pharmacy_id)
    if pharmacy is None or not pharmacy.is_active:
        raise HTTPException(status_code=404, detail="Unknown or inactive pharmacy")

    # Race-safe: a single atomic UPDATE only matches a still-PENDING row,
    # so exactly one concurrent claimer succeeds (rowcount == 1).
    stmt = (
        update(Order)
        .where(Order.id == order_id, Order.status == OrderStatus.PENDING)
        .values(
            status=OrderStatus.CLAIMED,
            claimed_by_pharmacy_id=pharmacy.id,
            claimed_at=datetime.now(timezone.utc),
        )
    )
    result = session.exec(stmt)
    session.commit()

    if result.rowcount == 0:
        existing = session.get(Order, order_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Order not found")
        raise HTTPException(
            status_code=409,
            detail=f"Order already claimed by pharmacy {existing.claimed_by_pharmacy_id}",
        )

    order = session.get(Order, order_id)
    # Phase 6: notify the patient that this pharmacy won the order.
    await route_patient_to_pharmacy(session, order, pharmacy)
    return {
        "status": "claimed",
        "order_id": order.id,
        "pharmacy_id": pharmacy.id,
    }


@router.get("/orders/{order_id}")
def get_order(
    order_id: int,
    session: Session = Depends(get_session),
) -> Order:
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order
