from fastapi import FastAPI

from app.database import create_db_and_tables
from app.routers import ingestion, orders

app = FastAPI(title="Medicure", version="0.1.0")

app.include_router(ingestion.router)
app.include_router(orders.router)


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "medicure"}
