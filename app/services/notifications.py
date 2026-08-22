"""Patient routing notifications.

On a successful claim, sends the patient a WhatsApp message with the
winning pharmacy's name, phone number, distance, and Google Maps URL.

Sending is best-effort: if Twilio credentials are absent, the message is
logged (demo mode) instead of raising, so the claim still succeeds.
"""
import json

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

    # Build the claimed-medicines summary for the patient.
    med_summary = ""
    try:
        parsed = json.loads(order.prescription_text or "{}")
        meds = parsed.get("medicines", [])
        if meds:
            lines = []
            for i, m in enumerate(meds):
                lines.append(f"  {i+1}. {m.get('name', 'Medicine')} x{m.get('quantity', 1)}")
            med_summary = "\n".join(lines)
    except (json.JSONDecodeError, AttributeError):
        pass

    text = (
        f"Your medicines are confirmed!\n"
        f"\n"
        f"Pharmacy: {pharmacy.name}\n"
        f"Phone: {pharmacy.phone_number}\n"
    )
    if distance is not None:
        text += f"Distance: {distance:.1f} km\n"
    text += (
        f"Location: {_maps_url(pharmacy)}\n"
        f"\n"
    )
    if med_summary:
        text += f"Medicines:\n{med_summary}\n\n"
    text += (
        f"Show order #{order.id} at the counter.\n"
        f"Thank you for using Medicure."
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
        print(f"[notify:error] failed to message {to_phone}: {exc}")
