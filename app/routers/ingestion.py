from fastapi import APIRouter, Depends, Request, Response

from sqlmodel import Session

from app.database import get_session
from app.services.ingest import handle_incoming_message

router = APIRouter(prefix="/webhook", tags=["ingestion"])


@router.post("/twilio")
async def twilio_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    form = await request.form()
    sender = str(form.get("From", ""))
    phone = sender.replace("whatsapp:", "").replace("sms:", "")

    body = str(form.get("Body", "") or "")
    num_media = int(str(form.get("NumMedia", "0") or "0"))
    media_urls = [
        str(form.get(f"MediaUrl{i}"))
        for i in range(num_media)
        if form.get(f"MediaUrl{i}")
    ]

    lat_raw = form.get("Latitude")
    lon_raw = form.get("Longitude")
    lat = float(str(lat_raw)) if lat_raw else None
    lon = float(str(lon_raw)) if lon_raw else None

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
