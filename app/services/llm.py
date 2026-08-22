"""Vision LLM prescription parsing (Google Gemini).

`run_inference` reads the raw incoming WhatsApp payload on an Order and
populates:
  - Order.prescription_text : JSON string
      {"medicines":[{"name","quantity","approx_unit_price"}],
       "estimated_value": float}
  - Order.estimated_value   : float (AOV)

Uses the Gemini REST API directly (no extra SDK). If GEMINI_API_KEY is
unset, a lightweight offline fallback runs so the pipeline is still
demoable without credentials.
"""
import base64
import json
import re

import httpx

from app.config import get_settings
from app.models import Order
from sqlmodel import Session

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = (
    "You are a pharmacy prescription parser for a medicine dispatch service. "
    "Given a prescription (image and/or text), extract the medicines and "
    "estimate the Average Order Value (AOV) in INR. "
    "You MUST return ONLY a JSON object (no markdown, no commentary) with "
    "exactly this shape:\n"
    '{"medicines":[{"name":string,"quantity":int,"approx_unit_price":float}],'
    '"estimated_value":float}\n'
    "If you cannot determine a field, use 0. Use the Indian market for price "
    "estimates. estimated_value must equal sum(quantity * approx_unit_price)."
)


def _fallback_parse(body: str) -> dict:
    meds: list[dict] = []
    for match in re.findall(r"([A-Za-z][A-Za-z\s\-]{2,30}?)\s*(\d+)\s*(?:mg|ml|g)?", body or ""):
        name = match[0].strip()
        if len(name) >= 3:
            meds.append({"name": name, "quantity": 1, "approx_unit_price": 0.0})
    return {"medicines": meds, "estimated_value": 0.0, "source": "fallback"}


def _normalize(parsed: object) -> dict:
    """Coerce varied LLM outputs into our canonical shape."""
    if isinstance(parsed, list):
        parsed = {"medicines": parsed}
    if not isinstance(parsed, dict):
        return {"medicines": [], "estimated_value": 0.0}

    raw_meds = parsed.get("medicines") or []
    if not isinstance(raw_meds, list):
        raw_meds = []
    meds: list[dict] = []
    total = 0.0
    for m in raw_meds:
        if not isinstance(m, dict):
            continue
        name = (
            m.get("name")
            or m.get("medicine_name")
            or m.get("medicine")
            or m.get("drug")
            or ""
        )
        qty = int(m.get("quantity") or m.get("qty") or 1 or 0)
        price = float(
            m.get("approx_unit") or m.get("approx_unit_price")
            or m.get("unit_price") or m.get("price") or 0.0
        )
        if not name:
            continue
        meds.append({"name": str(name), "quantity": qty, "approx_unit_price": price})
        total += qty * price

    est = float(parsed.get("estimated_value") or 0.0)
    if est <= 0 and meds:
        est = round(total, 2)
    return {"medicines": meds, "estimated_value": round(est, 2)}


async def _fetch_media(url: str) -> tuple[str, str]:
    settings = get_settings()
    auth = (
        (settings.twilio_account_sid, settings.twilio_auth_token)
        if settings.twilio_account_sid
        else None
    )
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, auth=auth)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "image/jpeg")
        encoded = base64.b64encode(resp.content).decode()
        return content_type, encoded


async def run_inference(session: Session, order: Order) -> None:
    settings = get_settings()
    raw = json.loads(order.raw_message or "{}")
    body: str = raw.get("body", "")
    media: list[str] = raw.get("media", [])

    result: dict | None = None
    if settings.gemini_api_key:
        try:
            parts: list[dict] = []
            for url in media:
                ctype, b64 = await _fetch_media(url)
                parts.append({"inline_data": {"mime_type": ctype, "data": b64}})
            if body:
                parts.append({"text": f"Prescription text (if any): {body}"})
            if not parts:
                parts.append({"text": "Empty prescription."})

            payload = {
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseMimeType": "application/json"},
            }
            url = GEMINI_URL.format(model=settings.gemini_model)
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    url, params={"key": settings.gemini_api_key}, json=payload
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                result = _normalize(json.loads(text))
        except Exception:
            result = None

    if not result or not result.get("medicines"):
        result = _fallback_parse(body)

    order.prescription_text = json.dumps(result, ensure_ascii=False)
    order.estimated_value = float(result.get("estimated_value") or 0.0)
    session.add(order)
    session.commit()
    session.refresh(order)
