var state = 'active';
var lastHash = '';

document.getElementById('phname').textContent = PHARMACY_NAME;

function renderStatus(s, el) {
  el.className = 'status ' + s;
  if (s === 'won') el.textContent = 'You won';
  else if (s === 'lost') el.textContent = 'Claimed by other';
  else if (s === 'partial') el.textContent = 'Partially claimed';
  else if (s === 'completed') el.textContent = 'Fulfilled';
  else el.textContent = 'Pending';
}

function renderOrders(orders, activeTab) {
  var c = document.getElementById('orders');
  if (!orders || !orders.length) {
    if (activeTab === 'history') {
      c.innerHTML = '<div class=empty>No fulfilled orders yet.<br>Orders you\'ve completed will appear here.</div>';
    } else {
      c.innerHTML = '<div class=empty>No pending orders yet.<br>Click <b>Demo broadcast to all vendors</b> to start.</div>';
    }
    return;
  }
  var h = '';
  for (var i = 0; i < orders.length; i++) {
    var o = orders[i];
    var cardClass = 'card ' + o.state;

    var badges = '';
    if (o.distance_km != null) badges += '<span class=badge dist>' + o.distance_km + ' km</span>';
    if (o.estimated_value) badges += '<span class=badge val>~' + o.estimated_value + '</span>';
    if (o.state === 'partial') {
      var claimedHere = 0;
      if (o.claimed_medicines) {
        for (var j = 0; j < o.claimed_medicines.length; j++) {
          if (o.claimed_medicines[j].pharmacy_id === PID) claimedHere = o.claimed_medicines[j].medicines.length;
        }
      }
      badges += '<span class=badge partial-badge>' + claimedHere + ' claimed by you</span>';
    }

    var meds = o.medicines || [];
    var ml = '';
    for (var j = 0; j < meds.length; j++) {
      var m = meds[j];
      var isClaimed = false;
      if (o.claimed_medicines) {
        for (var k = 0; k < o.claimed_medicines.length; k++) {
          if (o.claimed_medicines[k].medicines.indexOf(j) >= 0) { isClaimed = true; break; }
        }
      }
      var liClass = isClaimed ? 'claimed-med' : '';
      ml += '<li class=' + liClass + '><input type=checkbox class=med-check data-i=' + j + (isClaimed ? ' disabled checked' : '') + '><span class=med-name>' + m.name + '</span><span class=med-qty>x' + m.quantity + '</span></li>';
    }

    var actions = '';
    if (o.state === 'pending') {
      actions = '<button class=btn onclick="claim(' + o.order_id + ',false)">Claim all</button><button class=btn-sec onclick="claim(' + o.order_id + ',true)">Claim selected</button>';
    } else if (o.state === 'partial') {
      var claimedHere = 0;
      if (o.claimed_medicines) {
        for (var j = 0; j < o.claimed_medicines.length; j++) {
          if (o.claimed_medicines[j].pharmacy_id === PID) claimedHere = o.claimed_medicines[j].medicines.length;
        }
      }
      if (claimedHere > 0) {
        actions = '<button class=btn-fulfill onclick="fulfill(' + o.order_id + ')">Fulfilled</button>';
      } else {
        actions = '<button class=btn onclick="claim(' + o.order_id + ',false)">Claim all</button><button class=btn-sec onclick="claim(' + o.order_id + ',true)">Claim selected</button>';
      }
    } else if (o.state === 'won') {
      actions = '<button class=btn-fulfill onclick="fulfill(' + o.order_id + ')">Fulfilled</button>';
    }

    h += '<div class="' + cardClass + '" id="card-' + o.order_id + '">'
      + '<div class=top><span class=oid>Order #' + o.order_id + '</span>'
      + '<span class=time>' + (o.received_at ? ago(o.received_at) : '') + '</span></div>'
      + '<div class=badges>' + badges + '</div>'
      + '<ul class=meds>' + ml + '</ul>'
      + '<div class=foot><div class=status></div><div class=btn-row>' + actions + '</div></div></div>';
  }
  c.innerHTML = h;
  var statusEls = c.querySelectorAll('.status');
  for (var i = 0; i < statusEls.length; i++) {
    renderStatus(orders[i].state, statusEls[i]);
  }
}

function ago(ts) {
  var d = Math.round(Date.now() / 1000 - ts);
  if (d < 5) return 'just now';
  if (d < 60) return d + 's ago';
  if (d < 3600) return Math.floor(d / 60) + 'm ago';
  return Math.floor(d / 3600) + 'h ago';
}

function poll() {
  fetch('/vendor/' + PID + '/orders?status=' + state)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var h = JSON.stringify(data);
      if (h !== lastHash) {
        lastHash = h;
        renderOrders(data, state);
      }
    });
}

function demoBroadcast() {
  var btn = document.getElementById('demo');
  btn.disabled = true;
  btn.textContent = 'Broadcasting...';
  fetch('/vendor/demo/broadcast')
    .then(function(r) { return r.json(); })
    .then(function(d) {
      lastHash = '';
      poll();
      btn.textContent = 'Sent to ' + d.broadcast_to + ' vendors!';
      setTimeout(function() {
        btn.disabled = false;
        btn.textContent = 'Demo broadcast to all vendors';
      }, 2000);
    });
}

function claim(orderId, partial) {
  var body = { pharmacy_id: PID };
  if (partial) {
    var checks = document.querySelectorAll('#card-' + orderId + ' .med-check:checked:not(:disabled)');
    var idx = [];
    for (var i = 0; i < checks.length; i++) idx.push(parseInt(checks[i].getAttribute('data-i')));
    if (!idx.length) { alert('Select at least one medicine.'); return; }
    body.medicine_indices = idx;
  }
  fetch('/claim/' + orderId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function() { lastHash = ''; poll(); });
}

function fulfill(orderId) {
  fetch('/orders/' + orderId + '/fulfill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pharmacy_id: PID })
  }).then(function() { lastHash = ''; poll(); });
}

function switchTab(t) {
  state = t;
  lastHash = '';
  document.querySelectorAll('.tab').forEach(function(el) {
    el.classList.toggle('active', el.getAttribute('data-tab') === t);
  });
  poll();
}

poll();
setInterval(poll, 3000);
