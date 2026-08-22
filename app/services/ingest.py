"""Handle incoming WhatsApp messages (Twilio webhook pipeline).

Flow: upsert user → create order → Gemini inference → broadcast to pharmacies.
"""
import json

from sqlmodel import Session, select

from app.models import Order, OrderStatus, User
from app.services.broadcast import broadcast_to_nearby
from app.services.llm import run_inference


async def handle_incoming_message(
    session: Session,
    phone: str,
    body: str,
    media_urls: list[str],
    lat: float | None = None,
    lon: float | None = None,
) -> Order:
    # 1. Upsert user by phone number.
    user = session.exec(select(User).where(User.phone_number == phone)).first()
    if user is None:
        user = User(phone_number=phone)
        session.add(user)
        session.commit()
        session.refresh(user)

    # 2. Create the order.
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

    # 3. Extract medicines + AOV via the Vision LLM.
    await run_inference(session, order)
    session.refresh(order)

    # 4. If no medicines were found, mark as FAILED and do not broadcast.
    med_count = 0
    try:
        parsed = json.loads(order.prescription_text or "{}")
        med_count = len(parsed.get("medicines", []))
    except (json.JSONDecodeError, AttributeError):
        pass

    if med_count == 0:
        order.status = OrderStatus.FAILED
        session.add(order)
        session.commit()
        session.refresh(order)
        return order

    # 5. Broadcast to nearby pharmacies (direct DB insert).
    broadcast_to_nearby(session, order)

    return order

