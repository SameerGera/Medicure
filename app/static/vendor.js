document.getElementById('phname').textContent = PHARMACY_NAME || 'Pharmacy';
var box = document.getElementById('orders');
var simBtn = document.getElementById('sim');
var lastHash = '';

function simulate() {
  simBtn.disabled = true;
  simBtn.textContent = 'Dispatching...';
  fetch('/vendor/' + PID + '/simulate', { method: 'POST' })
    .then(function(r) { if (r.ok) return poll(); })
    .catch(function(e) { console.error(e); })
    .finally(function() {
      simBtn.disabled = false;
      simBtn.textContent = 'Simulate incoming order';
    });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, function(c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

function renderMeds(meds, claimed) {
  var claimedSet = {};
  if (claimed && claimed.medicines) {
    claimed.medicines.forEach(function(i) { claimedSet[i] = true; });
  }
  return meds.map(function(m, i) {
    var checked = claimedSet[i] ? 'checked disabled' : '';
    var cls = claimedSet[i] ? 'claimed-med' : '';
    return '<li class="' + cls + '">'
      + '<input type=checkbox class=med-check data-idx=' + i + ' ' + checked + '>'
      + '<span class=med-name>' + escapeHtml(m.name || 'Medicine') + '</span>'
      + '<span class=med-qty>x' + (m.quantity || 1) + '</span>'
      + '</li>';
  }).join('');
}

function render(list) {
  if (!list.length) {
    box.innerHTML = '<div class="empty">No incoming orders yet.<br>Share this screen - orders appear the moment a patient sends a prescription.</div>';
    return;
  }
  box.innerHTML = list.map(function(o) {
    var meds = renderMeds(o.medicines, o.claimed_medicines);
    var dist = (o.distance_km != null)
      ? '<span class="badge dist">' + o.distance_km + ' km away</span>' : '';
    var val = (o.estimated_value != null)
      ? '<span class="badge val">Rs ' + o.estimated_value + ' est.</span>' : '';
    var badge = '';
    var btnRow = '';
    var status = '';
    if (o.state === 'won') {
      badge = '<span class="status won">YOU WON</span>';
      btnRow = '<div class=btn-row><button class="btn" disabled>Claimed</button></div>';
      status = 'Won by you';
    } else if (o.state === 'lost') {
      badge = '<span class="status lost">Claimed by another</span>';
      btnRow = '<div class=btn-row><button class="btn" disabled>View</button></div>';
      status = 'Lost';
    } else if (o.state === 'partial') {
      badge = '<span class="badge partial-badge">Partially claimed</span>';
      btnRow = '<div class=btn-row>'
        + '<button class="btn" onclick="claim(' + o.order_id + ', null, this)">Claim All Remaining</button>'
        + '</div>';
      status = 'Partial';
    } else {
      btnRow = '<div class=btn-row>'
        + '<button class="btn" onclick="claim(' + o.order_id + ', null, this)">Claim All</button>'
        + '<button class="btn btn-secondary" onclick="claimSelected(' + o.order_id + ', this)">Claim Selected</button>'
        + '</div>';
    }
    return '<div class="card ' + (o.state || '') + '">'
      + '<div class="top"><div class="oid">Order #' + o.order_id + '</div>' + badge + '</div>'
      + '<div class="badges">' + val + dist + '</div>'
      + '<ul class=meds>' + meds + '</ul>'
      + '<div class=foot><span class="status ' + (o.state || '') + '">' + status + '</span>' + btnRow + '</div>'
      + '</div>';
  }).join('');
}

function poll() {
  return fetch('/vendor/' + PID + '/orders')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      var h = JSON.stringify(d);
      if (h !== lastHash) {
        lastHash = h;
        render(d);
      }
    })
    .catch(function(e) { console.error(e); });
}

function claim(id, indices, btn) {
  btn.disabled = true;
  btn.textContent = 'Claiming...';
  var body = { pharmacy_id: PID };
  if (indices !== null) body.medicine_indices = indices;
  fetch('/claim/' + id, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function(r) {
    if (r.ok) { btn.textContent = 'Claimed'; }
    else {
      return r.json().then(function(e) {
        alert(e.detail || 'Claim failed');
        btn.disabled = false;
        btn.textContent = 'Claim Order';
      });
    }
  }).finally(function() { poll(); });
}

function claimSelected(id, btn) {
  var card = btn.closest('.card');
  var checks = card.querySelectorAll('.med-check:not(:checked):not(:disabled)');
  var indices = [];
  checks.forEach(function(c) { indices.push(parseInt(c.dataset.idx)); });
  if (!indices.length) {
    alert('Select at least one medicine to claim.');
    return;
  }
  claim(id, indices, btn);
}

poll();
setInterval(poll, 3000);
