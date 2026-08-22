"""Broadcast an order to nearby pharmacies via their webhook URLs."""
import json
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.models import Order, Pharmacy

BROADCAST_TIMEOUT = 5.0


async def broadcast_order(order: Order, pharmacies: list[Pharmacy]) -> list[dict]:
    """POST the order payload to each pharmacy's registered webhook.

    Returns a delivery report per pharmacy (status code or error).
    """
    settings = get_settings()
    try:
        parsed = json.loads(order.prescription_text or "{}")
    except json.JSONDecodeError:
        parsed = {}
    medicines = parsed.get("medicines", [])

    payload = {
        "order_id": order.id,
        "medicines": medicines,
        "estimated_value": order.estimated_value,
        "patient": {"lat": order.location_lat, "long": order.location_long},
        "broadcast_at": datetime.now(timezone.utc).isoformat(),
        "claim_url": f"{settings.public_base_url}/claim/{order.id}",
    }

    report: list[dict] = []
    async with httpx.AsyncClient(timeout=BROADCAST_TIMEOUT) as client:
        for pharmacy in pharmacies:
            if not pharmacy.webhook_url:
                report.append(
                    {"pharmacy_id": pharmacy.id, "status": "skipped_no_webhook"}
                )
                continue
            try:
                resp = await client.post(pharmacy.webhook_url, json=payload)
                report.append(
                    {"pharmacy_id": pharmacy.id, "status": resp.status_code}
                )
            except Exception as exc:  # network/timeout errors are non-fatal
                report.append({"pharmacy_id": pharmacy.id, "error": str(exc)})
    return report
