"""Vercel serverless entrypoint.

Vercel's @vercel/python runtime does NOT run ASGI lifespan events,
so we eagerly create tables and seed here at import time.
"""
from app.main import app  # noqa: F401 — Vercel expects `app`

try:
    from app.database import create_db_and_tables
    from app.seed import seed

    create_db_and_tables()
    seed()
except Exception as exc:
    print(f"[warning] Vercel startup DB init warning: {exc}")
