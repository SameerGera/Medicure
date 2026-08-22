from fastapi import FastAPI

from app.database import create_db_and_tables

app = FastAPI(title="Medicure", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "medicure"}
