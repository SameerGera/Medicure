"""Twilio WhatsApp webhook — ingestion endpoint.

Validates Twilio request signatures when credentials are configured,
then delegates to the ingest pipeline.
"""
import httpx
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


async def _get_telegram_file_url(bot_token: str, file_id: str) -> str | None:
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                file_path = data.get("result", {}).get("file_path")
                if file_path:
                    return f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    except Exception:
        pass
    return None


@router.post("/telegram")
async def telegram_webhook(
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    """Telegram Bot webhook for receiving prescriptions from patients."""
    settings = get_settings()
    data = await request.json()
    message = data.get("message") or data.get("edited_message")
    if not message:
        return {"ok": True}

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        return {"ok": True}

    # Store user identity as tg:<chat_id>
    phone = f"tg:{chat_id}"

    body = message.get("text") or message.get("caption") or ""
    media_urls = []

    if message.get("photo") and settings.telegram_bot_token:
        best_photo = message["photo"][-1]
        file_id = best_photo.get("file_id")
        if file_id:
            file_url = await _get_telegram_file_url(settings.telegram_bot_token, file_id)
            if file_url:
                media_urls.append(file_url)

    lat = None
    lon = None
    if message.get("location"):
        lat = message["location"].get("latitude")
        lon = message["location"].get("longitude")

    order = await handle_incoming_message(
        session=session,
        phone=phone,
        body=body,
        media_urls=media_urls,
        lat=lat,
        lon=lon,
    )

    # Acknowledge directly to the user in Telegram
    if settings.telegram_bot_token:
        try:
            send_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    send_url,
                    json={
                        "chat_id": chat_id,
                        "text": f"💊 Received your prescription (Order #{order.id})!\nScanning nearby pharmacies...",
                    },
                )
        except Exception:
            pass

    return {"ok": True, "order_id": order.id}


@router.get("/telegram/setup")
async def setup_telegram_webhook(
    url: str | None = None,
) -> dict:
    """One-click Telegram webhook registration."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=400, detail="TELEGRAM_BOT_TOKEN is not configured")
    webhook_url = url or f"{settings.public_base_url}/webhook/telegram"
    api_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/setWebhook"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(api_url, json={"url": webhook_url})
        return resp.json()

