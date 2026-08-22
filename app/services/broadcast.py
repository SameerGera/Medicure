"""Broadcast an order to nearby pharmacies.

Primary path: direct DB inserts (BroadcastReceipt rows).
This works on Vercel serverless where the old HTTP-webhook approach
failed because each request runs on a potentially different instance.
"""
from app.geo import all_active_pharmacies, find_nearby_pharmacies, haversine_km
from app.models import BroadcastReceipt, Order, Pharmacy
from sqlmodel import Session


def broadcast_to_nearby(session: Session, order: Order) -> int:
    """Insert BroadcastReceipt rows for all pharmacies within 5 km.

    Returns the number of pharmacies notified.
    """
    if order.location_lat is not None and order.location_long is not None:
        pharmacies = find_nearby_pharmacies(
            session, order.location_lat, order.location_long
        )
    else:
        pharmacies = all_active_pharmacies(session)

    count = 0
    for ph in pharmacies:
        dist = None
        if (
            order.location_lat is not None
            and order.location_long is not None
            and ph.location_lat is not None
            and ph.location_long is not None
        ):
            dist = round(
                haversine_km(
                    order.location_lat,
                    order.location_long,
                    ph.location_lat,
                    ph.location_long,
                ),
                1,
            )
        session.add(
            BroadcastReceipt(
                order_id=order.id,
                pharmacy_id=ph.id,
                distance_km=dist,
            )
        )
        count += 1
    session.commit()
    return count
