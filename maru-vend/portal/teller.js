/* Maru Quick teller portal. Plain JS, no build step. */
(() => {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const app = $('#app');
  const BASE = location.pathname.replace(/\/teller\/?$/, '');
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const P = (thebe) => 'P' + (Number(thebe || 0) / 100).toLocaleString('en-BW', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const time = (d) => (d ? new Date(String(d).replace(' ', 'T')).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) : '');
  const STATE = {
    SUCCEEDED: ['ok', 'Token issued'], FAILED: ['err', 'No token · give cash back'], RESERVED: ['warn', 'Getting token'],
    SUBMITTED: ['warn', 'Getting token'], UNKNOWN: ['warn', 'Confirming · do not sell again'], MANUAL_REVIEW: ['warn', 'Confirming · do not sell again'],
    PAYMENT_PENDING: ['warn', 'Not sold'],
  };
  const tag = (s) => { const [c, t] = STATE[s] || ['', s]; return `<span class="tag ${c}">${esc(t)}</span>`; };
  let me = null;

  async function api(method, path, body) {
    const r = await fetch(BASE + '/teller/api' + path, {
      method, credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let d = {};
    try { d = await r.json(); } catch { /* empty */ }
    if (r.status === 401 && path !== '/login') { me = null; showLogin(); throw new Error(d.message || 'Please sign in.'); }
    if (!r.ok) throw new Error(d.message || 'Something went wrong.');
    return d;
  }
  function toast(m) { const t = $('#toast'); t.textContent = m; t.hidden = false; clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 3500); }
  function form(el, fn) {
    el.addEventListener('submit', async (e) => {
      e.preventDefault();
      const b = el.querySelector('[type=submit]'); const err = el.querySelector('.note.err');
      if (err) err.hidden = true; if (b) b.disabled = true;
      try { await fn(Object.fromEntries(new FormData(el))); } catch (x) { if (err) { err.textContent = x.message; err.hidden = false; } else toast(x.message); }
      finally { if (b) b.disabled = false; }
    });
  }

  // ---------------------------------------------------------------- sign in
  function showLogin() {
    $('#who').hidden = $('#tabs').hidden = true;
    app.innerHTML = `<div class="login-wrap"><form class="card login" id="lf" autocomplete="off">
      <h1>Teller sign in</h1><p class="lead">Use your own username and PIN. Never share them.</p>
      <label for="u">Username</label><input id="u" name="username" autocapitalize="none" required>
      <label for="p">PIN</label><input id="p" name="pin" type="password" inputmode="numeric" maxlength="8" required>
      <div class="note err" role="alert" hidden></div>
      <button class="btn yellow" type="submit">Sign in</button></form></div>`;
    $('#u').focus();
    form($('#lf'), async (d) => { me = await api('POST', '/login', d); start(); });
  }
  function start() {
    $('#who').hidden = $('#tabs').hidden = false;
    $('#whoName').textContent = `${me.name} (${me.role})`;
    $('#whoOutlet').textContent = me.outlet;
    $('#testBanner').hidden = !me.test;
    document.querySelectorAll('.mgr').forEach((a) => { a.hidden = me.role !== 'manager'; });
    if (!location.hash || location.hash === '#/') location.hash = '#/sell'; else route();
  }
  $('#logout').onclick = async () => { await api('POST', '/logout', {}); me = null; location.hash = ''; showLogin(); };

  // ---------------------------------------------------------------- receipt
  function receiptHtml(s) {
    const r = s.receipt || {};
    return `<dl class="kv">
      <dt>Receipt</dt><dd>${esc(s.receipt_no)}</dd><dt>Meter</dt><dd>${esc(s.meter_number)}</dd>
      <dt>Name on meter</dt><dd>${esc(s.customer_name || '—')}</dd><dt>Amount</dt><dd>P${esc(s.amount)}</dd>
      ${r.token ? `<dt>Units</dt><dd>${esc(r.kwh)} kWh</dd><dt>Date</dt><dd>${esc(r.date)}</dd>` : ''}</dl>`;
  }
  function printSlip(s) {
    const r = s.receipt || {};
    const line = (a, b) => `<div class="l"><span>${esc(a)}</span><span>${esc(b ?? '')}</span></div>`;
    $('#slip').innerHTML = `<h3>MARU QUICK</h3><div class="c">Prepaid electricity</div><div class="c">${esc(me.outlet)}</div><hr>
      ${line('Receipt', r.receipt_no)}${line('Date', r.date)}${line('Meter', r.meter_number)}${line('Name', r.customer_name)}${line('Tariff', r.tariff_index)}<hr>
      ${r.key_change_token_1 ? `<div class="c">ENTER KEY CHANGE TOKENS FIRST</div><div class="tok">${esc(r.key_change_token_1)}</div>${r.key_change_token_2 ? `<div class="tok">${esc(r.key_change_token_2)}</div>` : ''}<hr>` : ''}
      <div class="c">TOKEN</div><div class="tok">${esc(r.token)}</div><hr>
      ${line('Amount', 'P' + r.transaction_amount)}${line('Units', r.kwh + ' kWh')}${line('Cost of units', 'P' + r.cost_of_units)}
      ${line('Fixed charge', 'P' + r.fixed_charge)}${line('Levy', 'P' + r.government_levy)}${line('VAT', 'P' + r.vat)}${line('Supplier VAT no.', r.bpc_vat_no)}<hr>
      ${line('Served by', me.name)}${me.test ? '<div class="c">TEST TOKEN - WILL NOT LOAD</div>' : ''}<div class="c">Track your tokens at maruquick.com</div>`;
    window.print();
  }

  // ---------------------------------------------------------------- views
  const views = {};

  views.sell = () => {
    app.innerHTML = `<h1>Sell electricity</h1><p class="lead">Check the meter, read the name back to the customer, take the cash, then sell.</p>
      <div class="grid2"><form class="card" id="sf" novalidate>
        <label for="meter">Meter number</label><input id="meter" class="big" name="meter" inputmode="numeric" maxlength="17" autocomplete="off" required>
        <label for="amount">Amount (Pula) <small>minimum P10</small></label><input id="amount" class="big" name="amount" type="number" inputmode="decimal" min="10" step="1" required>
        <div class="chips">${[20, 50, 100, 200, 500].map((a) => `<button type="button" class="chip" data-a="${a}">P${a}</button>`).join('')}</div>
        <label for="msisdn">Customer's mobile <small>optional, the token is also sent by SMS</small></label><input id="msisdn" name="msisdn" type="tel" inputmode="tel" maxlength="13">
        <div class="note err" role="alert" hidden></div>
        <button class="btn" type="submit">Check meter</button></form>
      <div id="step"><div class="card muted center">The name on the meter appears here.</div></div></div>`;
    $('#meter').focus();
    app.querySelectorAll('[data-a]').forEach((b) => b.onclick = () => { $('#amount').value = b.dataset.a; });
    form($('#sf'), async (d) => {
      const s = await api('POST', '/quote', { meter: d.meter, amount: Number(d.amount), msisdn: d.msisdn, idempotency_key: crypto.randomUUID() });
      $('#sf').querySelectorAll('input,button').forEach((x) => { x.disabled = true; });
      $('#step').innerHTML = `<div class="card"><h2>Confirm with the customer</h2>
        <p class="muted">Name on meter</p><div class="confirm-name">${esc(s.customer_name || 'Name not available')}</div>
        <dl class="kv" style="margin-top:12px"><dt>Meter</dt><dd>${esc(s.meter_number)}</dd><dt>Amount</dt><dd>P${esc(s.amount)}</dd></dl>
        <div class="note err" role="alert" hidden></div>
        <button class="btn yellow" id="sell">Cash received · Sell P${esc(s.amount)}</button>
        <button class="btn ghost" id="cancel">Cancel</button></div>`;
      $('#cancel').onclick = () => views.sell();
      $('#sell').onclick = async () => {
        $('#sell').disabled = true; $('#cancel').hidden = true;
        $('#step').insertAdjacentHTML('beforeend', '<div class="spinner" id="spin"></div>');
        try { result(await api('POST', `/sales/${s.sale_id}/sell`, {})); } catch (x) { $('#spin')?.remove(); const e = $('#step .note.err'); e.textContent = x.message; e.hidden = false; $('#sell').disabled = false; $('#cancel').hidden = false; }
      };
    });
  };

  async function result(s) {
    const done = s.status === 'SUCCEEDED';
    const failed = s.status === 'FAILED' || s.status === 'EXPIRED';
    $('#step').innerHTML = `<div class="card">
      ${done ? '<div class="note ok">Token issued. Print the slip for the customer.</div>' : failed
        ? `<div class="note err">${esc(s.message)} Give the customer their cash back.</div>`
        : `<div class="note warn">${esc(s.message)} Do not sell again; this updates by itself.</div><div class="spinner"></div>`}
      ${done ? `${s.receipt.key_change_token_1 ? `<div class="note warn">Enter the key change tokens first:<br>${esc(s.receipt.key_change_token_1)}${s.receipt.key_change_token_2 ? '<br>' + esc(s.receipt.key_change_token_2) : ''}</div>` : ''}<div class="token">${esc(s.receipt.token)}</div>` : ''}
      ${receiptHtml(s)}
      ${done ? `<button class="btn yellow" id="print">Print slip</button>
        <form id="lc" style="margin-top:18px"><label for="em">Add to the customer's Maru Power account <small>optional</small></label>
          <div class="row"><input id="em" name="email" type="email" placeholder="customer's email"><button class="btn ghost sm" type="submit">Add</button></div>
          <div class="note err" hidden></div><div class="note ok" id="lcOk" hidden></div></form>` : ''}
      <button class="btn ghost" id="next">Next customer</button></div>`;
    $('#next').onclick = () => views.sell();
    if (done) {
      $('#print').onclick = () => printSlip(s);
      form($('#lc'), async (d) => { const r = await api('POST', `/sales/${s.sale_id}/customer`, d); $('#lcOk').textContent = r.message; $('#lcOk').hidden = false; });
    } else if (!failed) {
      setTimeout(async () => { if (location.hash === '#/sell' && $('#step')) result(await api('GET', `/sales/${s.sale_id}`)); }, 4000);
    }
  }

  views.reprint = () => {
    app.innerHTML = `<h1>Reprint a token</h1><p class="lead">Free. Use the receipt number, or the meter number for its latest token.</p>
      <div class="grid2"><form class="card" id="rf"><label for="q">Receipt or meter number</label><input id="q" class="big" name="query" autocomplete="off" required>
        <div class="note err" role="alert" hidden></div><button class="btn" type="submit">Find token</button></form><div id="step"></div></div>`;
    $('#q').focus();
    form($('#rf'), async (d) => {
      const s = await api('POST', '/reprint', d);
      $('#step').innerHTML = `<div class="card"><div class="token">${esc(s.receipt.token)}</div>${receiptHtml(s)}<button class="btn yellow" id="print">Print slip</button></div>`;
      $('#print').onclick = () => printSlip(s);
    });
  };

  function dayView(d, title, lead, showTeller) {
    app.innerHTML = `<h1>${title}</h1><p class="lead">${lead}</p>
      <div class="stats">
        <div class="stat hero"><span>Cash to hand in</span><b>${P(d.cash_thebe)}</b></div>
        <div class="stat"><span>Tokens sold</span><b>${d.count}</b></div>
        <div class="stat"><span>Still confirming</span><b>${P(d.pending_thebe)}</b></div>
        <div class="stat"><span>Failed · cash returned</span><b>${d.failed_count}</b></div>
        ${d.float_available_thebe !== null ? `<div class="stat"><span>Float available</span><b>${P(d.float_available_thebe)}</b></div>` : ''}
      </div>
      <div class="card tw"><table><thead><tr><th>Time</th><th>Receipt</th><th>Meter</th>${showTeller ? '<th>Teller</th>' : ''}<th class="r">Amount</th><th>Status</th></tr></thead><tbody>
      ${d.sales.map((s) => `<tr><td>${time(s.created_at)}</td><td>${esc(s.receipt_no)}</td><td>${esc(s.meter_number)}</td>${showTeller ? `<td>${esc(s.teller || 'online')}</td>` : ''}<td class="r">${P(s.amount_thebe)}</td><td>${tag(s.state)}</td></tr>`).join('') || `<tr><td colspan="6" class="muted center">No sales yet today.</td></tr>`}
      </tbody></table></div>`;
  }
  views.shift = async () => dayView(await api('GET', '/day'), 'My shift', 'Your sales today. Hand in the cash shown, and check it against the slips.', false);
  views.outlet = async () => dayView(await api('GET', '/outlet'), 'Outlet today', `Every sale at ${esc(me.outlet)} today, from all tellers and online.`, true);

  views.tellers = async () => {
    const list = await api('GET', '/tellers');
    app.innerHTML = `<h1>Tellers</h1><p class="lead">People who can sell at ${esc(me.outlet)}.</p>
      <div class="card tw"><table><thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Last sign-in</th><th></th></tr></thead><tbody>
      ${list.map((t) => `<tr><td>${esc(t.name)} ${Number(t.active) ? '' : '<span class="tag err">Off</span>'} ${Number(t.locked) ? '<span class="tag warn">Locked</span>' : ''}</td><td>${esc(t.username)}</td><td>${esc(t.role)}</td><td class="small muted">${esc((t.last_login_at || '—').slice(0, 16))}</td>
        <td class="r"><button class="btn ghost sm" data-pin="${t.id}">New PIN</button> ${Number(t.id) !== Number(me.id) ? `<button class="btn ghost sm" data-act="${t.id}" data-on="${Number(t.active) ? 0 : 1}">${Number(t.active) ? 'Turn off' : 'Turn on'}</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div>
      <form class="card" id="af"><h2>Add a teller</h2>
        <div class="row"><div><label for="an">Full name</label><input id="an" name="name" required></div><div><label for="au">Username</label><input id="au" name="username" autocapitalize="none" required></div></div>
        <div class="row"><div><label for="ap">Starting PIN <small>4 to 8 digits</small></label><input id="ap" name="pin" inputmode="numeric" maxlength="8" required></div>
          <div><label for="ar">Role</label><select id="ar" name="role"><option value="teller">Teller</option><option value="manager">Manager</option></select></div></div>
        <div class="note err" role="alert" hidden></div><button class="btn" type="submit">Add teller</button></form>`;
    form($('#af'), async (d) => { await api('POST', '/tellers', d); toast('Teller added. Ask them to change their PIN.'); views.tellers(); });
    app.querySelectorAll('[data-act]').forEach((b) => b.onclick = async () => { await api('PUT', '/tellers/' + b.dataset.act, { active: b.dataset.on === '1' }); views.tellers(); });
    app.querySelectorAll('[data-pin]').forEach((b) => b.onclick = async () => {
      const pin = prompt('New PIN for this teller (4 to 8 digits):');
      if (!pin) return;
      try { await api('PUT', '/tellers/' + b.dataset.pin, { pin }); toast('PIN changed. Tell the teller in person.'); views.tellers(); } catch (x) { toast(x.message); }
    });
  };

  views.pin = () => {
    app.innerHTML = `<h1>Change my PIN</h1><form class="card" id="pf" style="max-width:420px" autocomplete="off">
      <label for="c">Current PIN</label><input id="c" name="current" type="password" inputmode="numeric" maxlength="8" required>
      <label for="n">New PIN <small>4 to 8 digits, not 1234 or 1111</small></label><input id="n" name="pin" type="password" inputmode="numeric" maxlength="8" required>
      <label for="n2">New PIN again</label><input id="n2" name="pin2" type="password" inputmode="numeric" maxlength="8" required>
      <div class="note err" role="alert" hidden></div><button class="btn" type="submit">Change PIN</button></form>`;
    form($('#pf'), async (d) => {
      if (d.pin !== d.pin2) throw new Error('The new PINs do not match.');
      await api('POST', '/pin', { current: d.current, pin: d.pin }); toast('PIN changed.'); location.hash = '#/sell';
    });
  };

  async function route() {
    if (!me) return;
    const v = (location.hash.match(/^#\/(\w+)/) || [])[1] || 'sell';
    document.querySelectorAll('.tabs a').forEach((a) => { if (a.dataset.v === v) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    app.innerHTML = '<div class="spinner"></div>';
    try { await (views[v] || views.sell)(); } catch (x) { if (me) app.innerHTML = `<div class="note err">${esc(x.message)}</div>`; }
  }
  window.addEventListener('hashchange', route);
  api('GET', '/me').then((m) => { me = m; start(); }).catch(() => { if (!me) showLogin(); });
})();
