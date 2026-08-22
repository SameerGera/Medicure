from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel


class OrderStatus(str, Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    phone_number: str = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    orders: list["Order"] = Relationship(back_populates="user")


class Pharmacy(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    location_lat: float = Field(index=True)
    location_long: float = Field(index=True)
    phone_number: str = Field(index=True)
    trust_score: float = Field(default=5.0)
    is_active: bool = Field(default=True)
    # Endpoint the dispatch backend POSTs order broadcasts to.
    webhook_url: str | None = Field(default=None)

    claimed_orders: list["Order"] = Relationship(back_populates="claimed_by")


class Order(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    status: OrderStatus = Field(default=OrderStatus.PENDING, index=True)
    # Raw LLM-extracted prescription payload (JSON string or free text).
    prescription_text: str | None = Field(default=None)
    # Original incoming WhatsApp payload (body + media URLs) for the
    # inference step. JSON-encoded.
    raw_message: str | None = Field(default=None)
    # Patient location (from a shared WhatsApp location, if provided).
    location_lat: float | None = Field(default=None)
    location_long: float | None = Field(default=None)
    estimated_value: float | None = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    claimed_at: datetime | None = Field(default=None)
    claimed_by_pharmacy_id: int | None = Field(
        default=None, foreign_key="pharmacy.id", index=True
    )
    # Partial-claim tracking. JSON: {"pharmacy_id": int, "medicines": [indices]}
    claimed_medicines: str | None = Field(default=None)
    # Pharmacies that have fulfilled their claimed portion. JSON: [pharmacy_id, ...]
    fulfilled_by: str | None = Field(default=None)

    user: User | None = Relationship(back_populates="orders")
    claimed_by: Pharmacy | None = Relationship(back_populates="claimed_orders")


class BroadcastReceipt(SQLModel, table=True):
    """Tracks which orders were broadcast to which pharmacies.

    Replaces the in-memory RECEIVED dict so broadcasts survive Vercel
    serverless cold starts and cross-instance requests.
    """
    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="order.id", index=True)
    pharmacy_id: int = Field(foreign_key="pharmacy.id", index=True)
    distance_km: float | None = Field(default=None)
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

