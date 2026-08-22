import json

from sqlmodel import select

from app.geo import all_active_pharmacies, find_nearby_pharmacies
from app.models import Order, OrderStatus, Pharmacy, User
from app.services.broadcast import broadcast_order
from app.services.llm import run_inference
from sqlmodel import Session


async def handle_incoming_message(
    session: Session,
    phone: str,
    body: str,
    media_urls: list[str],
    lat: float | None = None,
    lon: float | None = None,
) -> Order:
    user = session.exec(select(User).where(User.phone_number == phone)).first()
    if user is None:
        user = User(phone_number=phone)
        session.add(user)
        session.commit()
        session.refresh(user)

    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        raw_message=json.dumps({"body": body, "media": media_urls}),
        location_lat=lat,
        location_long=lon,
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    # Phase 3: extract medicines + AOV via the Vision LLM.
    await run_inference(session, order)
    session.refresh(order)

    # Phase 4: trust-weighted broadcast to nearby pharmacies.
    if lat is not None and lon is not None:
        nearby = find_nearby_pharmacies(session, lat, lon)
    else:
        nearby = all_active_pharmacies(session)
    await broadcast_order(order, nearby)
    session.refresh(order)
    return order
