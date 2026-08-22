"""Vendor web dashboard + broadcast receiver.

This is a single-app prototype: the same FastAPI process both dispatches
orders AND serves the vendor UI. Each pharmacy points its webhook_url at
POST /vendor/{pharmacy_id}/broadcast, which stores the incoming order so
the dashboard can poll and claim it.
"""
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_session
from app.models import Order, OrderStatus, Pharmacy

router = APIRouter(prefix="/vendor", tags=["vendor"])

# In-memory store of received broadcasts, keyed by pharmacy_id (prototype).
RECEIVED: dict[int, list[dict]] = {}


@router.get("/setup")
def setup_all_webhooks(session: Session = Depends(get_session)):
    """Point every active pharmacy's webhook_url at this dashboard."""
    settings = get_settings()
    count = 0
    for ph in session.exec(select(Pharmacy).where(Pharmacy.is_active == True)):  # noqa: E712
        ph.webhook_url = f"{settings.public_base_url}/vendor/{ph.id}/broadcast"
        session.add(ph)
        count += 1
    session.commit()
    return {"registered": count}


@router.post("/{pharmacy_id}/broadcast")
async def receive_broadcast(
    pharmacy_id: int, payload: dict, session: Session = Depends(get_session)
):
    if session.get(Pharmacy, pharmacy_id) is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    entry = dict(payload)
    entry["received_at"] = time.time()
    RECEIVED.setdefault(pharmacy_id, []).append(entry)
    return {"ok": True}


@router.get("/{pharmacy_id}/orders")
def vendor_orders(pharmacy_id: int, session: Session = Depends(get_session)):
    if session.get(Pharmacy, pharmacy_id) is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    items = RECEIVED.get(pharmacy_id, [])
    out = []
    for it in items:
        order = session.get(Order, it.get("order_id"))
        state = "pending"
        if order and order.status != OrderStatus.PENDING:
            state = "won" if order.claimed_by_pharmacy_id == pharmacy_id else "lost"
        out.append({**it, "state": state})
    return out


@router.post("/{pharmacy_id}/register")
def register_webhook(pharmacy_id: int, session: Session = Depends(get_session)):
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    settings = get_settings()
    ph.webhook_url = f"{settings.public_base_url}/vendor/{pharmacy_id}/broadcast"
    session.add(ph)
    session.commit()
    return {"webhook_url": ph.webhook_url}


@router.get("/{pharmacy_id}")
def dashboard(pharmacy_id: int, session: Session = Depends(get_session)):
    ph = session.get(Pharmacy, pharmacy_id)
    if ph is None:
        raise HTTPException(status_code=404, detail="pharmacy not found")
    html = DASHBOARD_HTML.format(pharmacy_id=pharmacy_id, pharmacy_name=ph.name)
    return HTMLResponse(html)


DASHBOARD_HTML = """<!doctype html>
<html lang=en>
<head>
<meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Medicure Vendor</title>
<style>
  body{{font-family:system-ui,Arial,sans-serif;margin:0;background:#0f172a;color:#e2e8f0}}
  header{{padding:16px;background:#16a34a;color:#fff;font-weight:700;font-size:18px}}
  #wrap{{padding:16px;max-width:560px;margin:0 auto}}
  .card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:14px;margin-bottom:12px}}
  .card.won{{border-color:#16a34a}}
  .card.lost{{opacity:.5}}
  .meds{{margin:8px 0;font-size:14px}}
  .row{{display:flex;justify-content:space-between;align-items:center}}
  button{{background:#16a34a;color:#fff;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}}
  button:disabled{{background:#475569;cursor:not-allowed}}
  .meta{{font-size:12px;color:#94a3b8}}
  h3{{margin:0}}
</style>
</head>
<body>
<header>Medicure Vendor &middot; {pharmacy_name}</header>
<div id=wrap><p class=meta>Live incoming orders (auto-refresh):</p><div id=orders></div></div>
<script>
const PID = {pharmacy_id};
const box = document.getElementById('orders');
function render(list){{
  if(!list.length){{ box.innerHTML = '<p class=meta>No orders yet.</p>'; return; }}
  box.innerHTML = list.map(o=>{{
    const meds = (o.medicines||[]).map(m=>'<li>'+m.name+' x'+(m.quantity||1)+'</li>').join('');
    let badge = '';
    let btn = '<button onclick="claim('+o.order_id+',this)">Claim Order</button>';
    if(o.state==='won'){{ badge='<span class=meta>YOU WON</span>'; btn='<button disabled>Claimed</button>'; }}
    if(o.state==='lost'){{ badge='<span class=meta>claimed by another</span>'; btn='<button disabled>Claim</button>'; }}
    return '<div class="card '+(o.state||'')+'"><div class=row><h3>Order #'+o.order_id+'</h3>'+badge+'</div>'
      +'<div class=meta>Est. value: Rs '+(o.estimated_value||0)+'</div>'
      +'<ul class=meds>'+meds+'</ul>'+btn+'</div>';
  }}).join('');
}}
async function poll(){{
  try{{ const r = await fetch('/vendor/'+PID+'/orders'); const d = await r.json(); render(d); }}
  catch(e){{ console.error(e); }}
}}
async function claim(id, btn){{
  btn.disabled = true; btn.textContent = 'Claiming...';
  const r = await fetch('/claim/'+id, {{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{pharmacy_id:PID}})}});
  if(r.ok){{ btn.textContent='Claimed'; }} else {{ const e=await r.json(); alert(e.detail||'claim failed'); btn.disabled=false; btn.textContent='Claim Order'; }}
  poll();
}}
poll(); setInterval(poll, 3000);
</script>
</body>
</html>"""
