"""Vision LLM prescription parsing (Google Gemini + Smart Fallback).

`run_inference` reads the raw incoming WhatsApp / Telegram payload on an Order
and populates:
  - Order.prescription_text : JSON string
      {"medicines":[{"name","quantity","approx_unit_price"}],
       "estimated_value": float}
  - Order.estimated_value   : float (AOV)

Uses the Gemini REST API directly. If GEMINI_API_KEY is unset or fails,
a robust smart offline fallback parser automatically extracts medicines,
quantities, dosages, and Indian market prices.
"""
import base64
import json
import re

import httpx
from sqlmodel import Session

from app.config import get_settings
from app.models import Order

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

STOPWORDS = {
    "i", "want", "need", "please", "send", "get", "me", "give", "buy", "a",
    "an", "the", "some", "strip", "strips", "tablet", "tablets", "tabs",
    "tab", "bottle", "bottles", "pack", "packs", "of", "for", "order", "urgent",
}

COMMON_MEDS = {
    "paracetamol": 5.0, "dolo": 4.0, "dolo 650": 4.0, "amoxicillin": 12.0,
    "metformin": 8.0, "glimepiride": 15.0, "atorvastatin": 18.0, "aspirin": 3.0,
    "omeprazole": 10.0, "pantoprazole": 9.0, "cetirizine": 6.0, "montelukast": 14.0,
    "azithromycin": 20.0, "domperidone": 7.0, "losartan": 22.0, "amlodipine": 11.0,
    "ibuprofen": 4.0, "ranitidine": 7.0, "cough syrup": 45.0, "benadryl": 55.0,
    "crocin": 4.0, "combiflam": 6.0, "allegra": 12.0, "augmentin": 25.0,
    "glycomet": 6.0, "telma": 14.0, "pan d": 11.0, "calpol": 4.0,
}


def _fallback_parse(body: str) -> dict:
    """Smart medicine parser for text messages without LLM."""
    if not body or not str(body).strip():
        return {"medicines": [], "estimated_value": 0.0, "source": "fallback"}

    cleaned = str(body).replace("\n", ", ").replace(";", ", ")
    parts = re.split(r"[,+]|\band\b", cleaned, flags=re.IGNORECASE)
    meds: list[dict] = []
    total = 0.0

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Extract explicit quantity like 'x 4', 'x4', '4x', 'qty 2', or leading '2 '
        qty = 1
        x_match = re.search(r"(?:x\s*|qty\s*|count\s*|\*\s*)(\d+)", part, flags=re.IGNORECASE)
        if x_match:
            try:
                qty = int(x_match.group(1))
            except ValueError:
                qty = 1
        else:
            leading_qty = re.search(r"^(\d+)\s+(?:strips?|packs?|tabs?|tablets?)?\s*([a-zA-Z]+)", part)
            if leading_qty:
                try:
                    num = int(leading_qty.group(1))
                    if 1 <= num <= 50:
                        qty = num
                except ValueError:
                    qty = 1

        # Extract dosage (e.g. '500mg', '650mg', '40mg', '650')
        dosage = ""
        dosage_match = re.search(r"(\d+\s*(?:mg|ml|mcg|g))\b", part, flags=re.IGNORECASE)
        if dosage_match:
            dosage = dosage_match.group(1).replace(" ", "")
        elif "650" in part:
            dosage = "650"

        # Extract words
        tokens = re.findall(r"[a-zA-Z]+", part)
        med_words = [w for w in tokens if w.lower() not in STOPWORDS and len(w) >= 3]
        if not med_words:
            continue

        name = " ".join(med_words).title()
        if dosage and dosage.lower() not in name.lower():
            name = f"{name} {dosage}"

        price = 10.0
        for known_med, known_price in COMMON_MEDS.items():
            if known_med in name.lower():
                price = known_price
                break

        meds.append({"name": name, "quantity": qty, "approx_unit_price": price})
        total += qty * price

    return {"medicines": meds, "estimated_value": round(total, 2), "source": "fallback"}


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
        if settings.twilio_account_sid and "twilio.com" in url
        else None
    )
    async with httpx.AsyncClient(timeout=15.0) as client:
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
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url, params={"key": settings.gemini_api_key.strip()}, json=payload
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
