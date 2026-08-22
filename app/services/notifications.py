"""Patient routing notifications (stub for Phase 6).

Phase 6 will send the winning pharmacy details (name, distance, Maps URL)
to the patient over WhatsApp via Twilio. For now this is a no-op so the
claim flow can be wired end-to-end.
"""
from app.models import Order, Pharmacy
from sqlmodel import Session


async def route_patient_to_pharmacy(
    session: Session, order: Order, pharmacy: Pharmacy
) -> None:
    # Phase 6: send WhatsApp message to the patient with pharmacy name,
    # distance, and a Google Maps URL.
    return
