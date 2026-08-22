# Medicure

Hyper-local, real-time medicine dispatch network — a "Fastest Finger First"
demand-dispatch marketplace for last-mile medicine access.

A patient sends a prescription over WhatsApp. The backend extracts the
medicines (and an estimated order value) with a Vision LLM, broadcasts the
order to nearby pharmacies (trust-weighted), and the first pharmacy to claim
it wins the sale. The patient is then routed to that pharmacy over WhatsApp
with the distance and a Google Maps link.

## Architecture

```
WhatsApp (Twilio) -> POST /webhook/twilio
        -> extract medicines + AOV (Gemini Vision)
        -> trust-weighted broadcast (5km radius, by trust_score)
        -> vendor dashboard (FastAPI + static HTML/JS) shows orders
        -> POST /claim/{order_id}  (race-safe, first come first served)
        -> patient gets WhatsApp with pharmacy name, distance, Maps URL
```

Stack: **FastAPI** + **SQLModel** (SQLite locally, PostgreSQL in prod) +
**Gemini** (vision) + **Twilio** (WhatsApp) + **httpx** for vendor webhooks.

## Project layout

```
app/
  main.py            FastAPI app, static mount, lifespan (create DB + seed)
  config.py          pydantic-settings env config
  database.py        SQLModel engine + session
  models.py          User, Pharmacy, Order
  geo.py             haversine + 5km radius query (trust-weighted)
  seed.py            seeds sample pharmacies
  routers/
    ingestion.py     POST /webhook/twilio
    orders.py        POST /claim/{id}, GET /orders/{id}
    vendor.py        vendor dashboard + broadcast receiver + /vendor/setup
  services/
    llm.py           Gemini prescription extraction
    broadcast.py     POST order payload to pharmacy webhooks
    ingest.py        ties ingestion -> inference -> broadcast
    notifications.py patient WhatsApp routing (Twilio)
  static/
    vendor.html/.css/.js   the vendor dashboard UI
api/index.py         Vercel serverless entry
tests/               pytest suite
```

## Local setup

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
#   source .venv/bin/activate                       # macOS/Linux
pip install -r requirements.txt
cp .env.example .env        # then fill in real keys
python -m app.seed         # create tables + sample pharmacies
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the interactive API.

## Environment (.env)

| Var | Purpose |
|-----|---------|
| `DATABASE_URL` | `sqlite:///./medicure.db` locally; a `postgresql://` URL in prod |
| `GEMINI_API_KEY` | Google Gemini key (vision prescription parsing) |
| `GEMINI_MODEL` | default `gemini-3.6-flash` |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | Twilio credentials (optional for demo mode) |
| `TWILIO_WHATSAPP_NUMBER` | your Twilio WhatsApp number |
| `PUBLIC_BASE_URL` | public URL (ngrok / deployed domain) used in claim links + webhooks |

> **Secret hygiene:** `.env` is gitignored. Never commit it. The Gemini key is
> only used server-side.

## Exposing the webhook (ngrok)

Twilio must reach your server. In dev, use ngrok:

```bash
ngrok http 8000
# set PUBLIC_BASE_URL to the https://<id>.ngrok-free.dev URL in .env
```

1. In the Twilio Console, configure the WhatsApp sandbox/webhook to
   `https://<ngrok>/webhook/twilio` (method POST).
2. Start the app and register vendor webhooks: `GET /vendor/setup`
   (points every pharmacy's `webhook_url` at this server).
3. Open the vendor dashboard: `http://localhost:8000/vendor/5` (pharmacy id 5).

Send a WhatsApp to your Twilio number with medicine text (or a prescription
image + a shared location). Watch it appear on the vendor dashboard and tap
**Claim Order**.

> If `TWILIO_*` are left blank, patient messages are logged in demo mode
> instead of sent — the rest of the pipeline still works end-to-end.

## Data models

- **User**: id, phone_number, created_at
- **Pharmacy**: id, name, location_lat, location_long, phone_number,
  trust_score (default 5.0), is_active, webhook_url
- **Order**: id, user_id, status (pending/claimed/completed/failed),
  prescription_text (raw LLM JSON), raw_message, location_lat/long,
  estimated_value, created_at, claimed_at, claimed_by_pharmacy_id

(`webhook_url` and `location_lat/long` are added to support the broadcast +
patient-location flow.)

## Tests

```bash
pip install pytest
pytest
```

Covers geo radius/trust-sort, race-safe claims, and the vendor dashboard.

## Deployment

The app is a standard ASGI app (`uvicorn app.main:app`), so it runs on any
Python host. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

### Render / Railway / Fly.io / Hugging Face Spaces
- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Set the same env vars as above. Use a PostgreSQL `DATABASE_URL`.
- The app creates tables and seeds sample pharmacies on startup.

### Vercel (experimental)
- `vercel.json` + `api/index.py` expose the ASGI app as a serverless function.
- **Limitations:** the in-memory broadcast store and `asyncio` background
  tasks do not persist across serverless invocations. For a live multi-vendor
  demo, Render/Railway/Fly are recommended; Vercel works for a single-instance
  demo or as a static+function prototype.

## Notes / limitations (prototype)
- Broadcast uses an in-memory store per process (fine for a single instance).
- Vendor identity in `/claim` is the `pharmacy_id` from the dashboard (no auth
  yet) — add auth before any real use.
- `trust_score` is static seed data; a real system would update it from
  fulfillment history.
