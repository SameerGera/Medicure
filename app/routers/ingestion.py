"""Twilio WhatsApp webhook — ingestion endpoint.

Validates Twilio request signatures when credentials are configured,
then delegates to the ingest pipeline.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlmodel import Session

from app.config import get_settings
from app.database import get_session
from app.services.ingest import handle_incoming_message

router = APIRouter(prefix="/webhook", tags=["ingestion"])


def _validate_twilio_signature(request: Request, form_data: dict) -> None:
    """Verify X-Twilio-Signature header. Skips in demo mode (no creds)."""
    settings = get_settings()
    if not (settings.twilio_account_sid and settings.twilio_auth_token):
        return  # Demo mode — no validation possible

    try:
        from twilio.request_validator import RequestValidator
    except ImportError:
        return  # Twilio SDK not installed — skip

    validator = RequestValidator(settings.twilio_auth_token)
    signature = request.headers.get("X-Twilio-Signature", "")

    # Reconstruct the full URL Twilio signed against.
    url = str(request.url)
    # Vercel may terminate TLS at the edge — Twilio signs the https:// URL.
    if request.headers.get("x-forwarded-proto") == "https" and url.startswith("http://"):
        url = "https://" + url[7:]

    if not validator.validate(url, form_data, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


@router.post("/twilio")
async def twilio_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    form = await request.form()
    # Convert to a plain dict for Twilio signature validation.
    form_dict = {k: str(v) for k, v in form.items()}

    _validate_twilio_signature(request, form_dict)

    sender = form_dict.get("From", "")
    phone = sender.replace("whatsapp:", "").replace("sms:", "")

    body = form_dict.get("Body", "")
    num_media = int(form_dict.get("NumMedia", "0"))
    media_urls = [
        form_dict[f"MediaUrl{i}"]
        for i in range(num_media)
        if form_dict.get(f"MediaUrl{i}")
    ]

    lat_raw = form_dict.get("Latitude")
    lon_raw = form_dict.get("Longitude")
    lat = float(lat_raw) if lat_raw else None
    lon = float(lon_raw) if lon_raw else None

    order = await handle_incoming_message(
        session=session,
        phone=phone,
        body=body,
        media_urls=media_urls,
        lat=lat,
        lon=lon,
    )

    # Twilio expects a TwiML response. We acknowledge now; the patient
    # gets the routing message (Phase 6) once a pharmacy claims.
    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        "<Message>Received your request (order #"
        f"{order.id}). Finding nearby pharmacies...</Message>"
        "</Response>"
    )
    return Response(content=twiml, media_type="application/xml")
