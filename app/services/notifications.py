"""Patient routing notifications.

On a successful claim, sends the patient a WhatsApp message with the
winning pharmacy's name, distance, and a Google Maps directions URL.

Sending is best-effort: if Twilio credentials are absent, the message is
logged (demo mode) instead of raising, so the claim still succeeds.
"""
from app.config import get_settings
from app.geo import haversine_km
from app.models import Order, Pharmacy, User
from sqlmodel import Session


def _maps_url(pharmacy: Pharmacy) -> str:
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&destination={pharmacy.location_lat},{pharmacy.location_long}"
    )


async def route_patient_to_pharmacy(
    session: Session, order: Order, pharmacy: Pharmacy
) -> None:
    user = session.get(User, order.user_id)
    if user is None:
        return

    distance: float | None = None
    if (
        order.location_lat is not None
        and order.location_long is not None
        and pharmacy.location_lat is not None
        and pharmacy.location_long is not None
    ):
        distance = haversine_km(
            order.location_lat,
            order.location_long,
            pharmacy.location_lat,
            pharmacy.location_long,
        )

    text = (
        f"Your medicines are confirmed!\n"
        f"Pharmacy: {pharmacy.name}\n"
        + (f"Distance: {distance:.1f} km\n" if distance is not None else "")
        + f"Directions: {_maps_url(pharmacy)}\n"
        f"Show order #{order.id} at the counter. Thank you for using Medicure."
    )

    await _send_whatsapp(user.phone_number, text)


async def _send_whatsapp(to_phone: str, body: str) -> None:
    settings = get_settings()
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        print(f"[notify:demo] -> {to_phone}: {body}")
        return
    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            to=f"whatsapp:{to_phone}",
            from_=settings.twilio_whatsapp_number,
            body=body,
        )
    except Exception as exc:
        # Never let a send failure break the claim.
        print(f"[notify:error] failed to message {to_phone}: {exc}")
