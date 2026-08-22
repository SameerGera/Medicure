"""Vision LLM prescription parsing.

Placeholder for Phase 3. `run_inference` is called by the ingestion
pipeline with the raw incoming message and is expected to populate
`Order.prescription_text` (JSON list of medicines) and
`Order.estimated_value` (AOV). The real GPT-4o implementation lands in
Phase 3.
"""
from app.models import Order
from sqlmodel import Session


async def run_inference(session: Session, order: Order) -> None:
    # No-op stub until Phase 3 wires up the Vision LLM.
    return
