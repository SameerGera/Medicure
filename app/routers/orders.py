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

    total = _total_medicines(order)
    already_claimed = _all_claimed_indices(order)

    # An order can be claimed as long as there are unclaimed medicines.
    # Status COMPLETED means a pharmacy fulfilled their part, but other
    # pharmacies may still claim the remaining unclaimed medicines.
    if order.status == OrderStatus.COMPLETED and len(already_claimed) >= total:
        raise HTTPException(
            status_code=409,
            detail="Order fully fulfilled.",
        )
    if order.status not in (
        OrderStatus.PENDING,
        OrderStatus.PARTIAL,
        OrderStatus.CLAIMED,
        OrderStatus.COMPLETED,
    ):
        raise HTTPException(status_code=409, detail="Order is not claimable.")

    existing_entries = []
    if order.claimed_medicines:
        try:
            existing_entries = json.loads(order.claimed_medicines)
        except (json.JSONDecodeError, AttributeError):
            existing_entries = []
    my_existing = [e for e in existing_entries if e.get("pharmacy_id") == pharmacy.id]

    requested = body.medicine_indices
    if requested is None:
        # Claim ALL remaining medicines.
        indices = [i for i in range(total) if i not in already_claimed]
    else:
        # Claim only the requested subset.
        indices = [i for i in requested if i not in already_claimed and 0 <= i < total]

    if not indices:
        if my_existing:
            raise HTTPException(
                status_code=400, detail="You have already claimed medicines on this order"
            )
        raise HTTPException(
            status_code=409, detail="Order already claimed by another pharmacy"
        )

    existing_entries.append({"pharmacy_id": pharmacy.id, "medicines": indices})

    all_claimed = _all_claimed_indices(order)
    all_claimed.update(indices)
    if len(all_claimed) >= total:
        new_status = OrderStatus.CLAIMED
    else:
        new_status = OrderStatus.PARTIAL

    # Build WHERE clause that allows claiming on PENDING/PARTIAL/CLAIMED/COMPLETED
    # as long as unclaimed medicines remain (prevents double-claim races).
    stmt = (
        update(Order)
        .where(
            Order.id == order_id,
            Order.status.in_([
                OrderStatus.PENDING,
                OrderStatus.PARTIAL,
                OrderStatus.CLAIMED,
                OrderStatus.COMPLETED,
            ]),
        )
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
    """Mark THIS pharmacy's claimed portion as fulfilled.
    Per-vendor: each pharmacy fulfills independently. The order is only
    globally COMPLETED when all claiming pharmacies have fulfilled."""
    order = session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    # This pharmacy must have claimed something on this order.
    claimed_entries = []
    if order.claimed_medicines:
        try:
            claimed_entries = json.loads(order.claimed_medicines)
        except (json.JSONDecodeError, AttributeError):
            claimed_entries = []
    my_entries = [e for e in claimed_entries if e.get("pharmacy_id") == body.pharmacy_id]
    if not my_entries:
        raise HTTPException(status_code=400, detail="You have not claimed any medicines on this order")

    # Idempotency: check if already fulfilled.
    fulfilled = []
    if order.fulfilled_by:
        try:
            fulfilled = json.loads(order.fulfilled_by)
        except (json.JSONDecodeError, AttributeError):
            fulfilled = []
    if body.pharmacy_id in fulfilled:
        raise HTTPException(status_code=409, detail="Already fulfilled by this pharmacy")

    fulfilled.append(body.pharmacy_id)
    new_fulfilled = json.dumps(fulfilled)

    # Globally completed only when every claiming pharmacy has fulfilled AND
    # all medicines are claimed.
    claiming_pharmacies = {e["pharmacy_id"] for e in claimed_entries}
    all_claimed = _all_claimed_indices(order)
    total = _total_medicines(order)
    globally_done = (
        all(p in fulfilled for p in claiming_pharmacies)
        and len(all_claimed) >= total
    )
    new_status = OrderStatus.COMPLETED if globally_done else order.status

    # Atomic update — prevents lost writes from concurrent fulfill calls.
    old_fulfilled = order.fulfilled_by  # what we read
    stmt = (
        update(Order)
        .where(
            Order.id == order_id,
            Order.fulfilled_by == old_fulfilled,  # optimistic lock
        )
        .values(fulfilled_by=new_fulfilled, status=new_status)
    )
    result = session.exec(stmt)
    session.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=409,
            detail="Concurrent fulfill detected — please retry.",
        )

    return {"status": "fulfilled", "order_id": order.id, "globally_completed": new_status == OrderStatus.COMPLETED}

