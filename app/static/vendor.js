document.getElementById('phname').textContent = PHARMACY_NAME || '';
const box = document.getElementById('orders');
function render(list){
  if(!list.length){ box.innerHTML = '<p class=meta>No orders yet.</p>'; return; }
  box.innerHTML = list.map(o=>{
    const meds = (o.medicines||[]).map(m=>'<li>'+m.name+' x'+(m.quantity||1)+'</li>').join('');
    let badge='';
    let btn='<button onclick="claim('+o.order_id+',this)">Claim Order</button>';
    if(o.state==='won'){ badge='<span class=meta>YOU WON</span>'; btn='<button disabled>Claimed</button>'; }
    if(o.state==='lost'){ badge='<span class=meta>claimed by another</span>'; btn='<button disabled>Claim</button>'; }
    return '<div class="card '+(o.state||'')+'"><div class=row><h3>Order #'+o.order_id+'</h3>'+badge+'</div>'
      +'<div class=meta>Est. value: Rs '+(o.estimated_value||0)+'</div>'
      +'<ul class=meds>'+meds+'</ul>'+btn+'</div>';
  }).join('');
}
async function poll(){
  try{ const r=await fetch('/vendor/'+PID+'/orders'); const d=await r.json(); render(d); }catch(e){ console.error(e); }
}
async function claim(id,btn){
  btn.disabled=true; btn.textContent='Claiming...';
  const r=await fetch('/claim/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({pharmacy_id:PID})});
  if(r.ok){ btn.textContent='Claimed'; } else { const e=await r.json(); alert(e.detail||'claim failed'); btn.disabled=false; btn.textContent='Claim Order'; }
  poll();
}
poll(); setInterval(poll,3000);
