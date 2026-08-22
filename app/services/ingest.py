import json

from sqlmodel import select

from app.models import Order, OrderStatus, User
from app.services.llm import run_inference
from sqlmodel import Session


async def handle_incoming_message(
    session: Session,
    phone: str,
    body: str,
    media_urls: list[str],
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
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    # Phase 3 implements the actual extraction; for now this is a no-op
    # that leaves the order pending until a pharmacy claims it.
    await run_inference(session, order)
    session.refresh(order)
    return order
