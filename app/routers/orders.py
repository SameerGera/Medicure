import json
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
    medicine_indices: list[int] | None = None


def _total_medicines(order: Order) -> int:
    try:
        return len(json.loads(order.prescription_text or "{}").get("medicines", []))
    except (json.JSONDecodeError, AttributeError):
        return 0


def _all_claimed_indices(order: Order) -> set[int]:
    claimed = set()
    if order.claimed_medicines:
        try:
            for entry in json.loads(order.claimed_medicines):
                claimed.update(entry.get("medicines", []))
        except (json.JSONDecodeError, AttributeError):
            pass
    return claimed


@router.post("/claim/{order_id}")
async def claim_order(
    order_id: int,
    body: ClaimRequest,
    session: Session = Depends(get_session),
) -> dict:
    pharmacy = session.get(Pharmacy, body.pharmacy_id)
    if pharmacy is None or not pharmacy.is_active:
        raise HTTPException(status_code=404, detail="Unknown or inactive pharmacy")

    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in (OrderStatus.PENDING, OrderStatus.PARTIAL):
        raise HTTPException(
            status_code=409,
            detail=f"Order already claimed by pharmacy {order.claimed_by_pharmacy_id}",
        )

    total = _total_medicines(order)
    requested = body.medicine_indices

    if requested is None:
        # Claim ALL remaining medicines.
        indices = list(range(total))
    else:
        # Claim only the requested subset.
        already = _all_claimed_indices(order)
        indices = [i for i in requested if i not in already and 0 <= i < total]

    if not indices:
        raise HTTPException(status_code=400, detail="No available medicines to claim")

    existing_entries = []
    if order.claimed_medicines:
        try:
            existing_entries = json.loads(order.claimed_medicines)
        except (json.JSONDecodeError, AttributeError):
            existing_entries = []

    existing_entries.append({"pharmacy_id": pharmacy.id, "medicines": indices})

    all_claimed = _all_claimed_indices(order)
    all_claimed.update(indices)
    new_status = OrderStatus.CLAIMED if len(all_claimed) >= total else OrderStatus.PARTIAL

    stmt = (
        update(Order)
        .where(Order.id == order_id, Order.status.in_([OrderStatus.PENDING, OrderStatus.PARTIAL]))
        .values(
            status=new_status,
            claimed_by_pharmacy_id=pharmacy.id,
            claimed_at=datetime.now(timezone.utc),
            claimed_medicines=json.dumps(existing_entries),
        )
    )
    result = session.exec(stmt)
    session.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=409,
            detail="Order was claimed by another pharmacy while processing.",
        )

    order = session.get(Order, order_id)
    await route_patient_to_pharmacy(session, order, pharmacy)

    claimed_count = len(all_claimed)
    return {
        "status": new_status.value,
        "order_id": order.id,
        "pharmacy_id": pharmacy.id,
        "medicines_claimed": len(indices),
        "medicines_total": total,
        "medicines_remaining": total - claimed_count,
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


@router.post("/orders/{order_id}/fulfill")
def fulfill_order(
    order_id: int,
    body: ClaimRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Mark an order as fulfilled/completed. Only the claiming pharmacy can fulfill."""
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status not in (OrderStatus.CLAIMED, OrderStatus.PARTIAL):
        raise HTTPException(status_code=400, detail="Order is not in a fulfillable state")
    if order.claimed_by_pharmacy_id != body.pharmacy_id:
        raise HTTPException(status_code=403, detail="Only the claiming pharmacy can fulfill this order")

    order.status = OrderStatus.COMPLETED
    session.add(order)
    session.commit()
    return {"status": "completed", "order_id": order.id}
