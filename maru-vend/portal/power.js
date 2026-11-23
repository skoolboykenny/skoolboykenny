/* Maru Power customer portal. Plain JS, no build step. */
(() => {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const app = $('#app');
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const P = (thebe) => 'P' + (Number(thebe || 0) / 100).toLocaleString('en-BW', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const tok = (t) => (t ? String(t).replace(/\D/g, '').replace(/(\d{4})(?=\d)/g, '$1 ') : '');
  const date = (d) => (d ? new Date(String(d).replace(' ', 'T')).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) : '');
  const CH = { POS: 'Till', USSD: 'USSD', WEB: 'Web store', APP: 'Maru app' };
  const SITE = { home: 'Homes', business: 'Businesses', other: 'Other sites' };
  const ic = {
    bolt: '<svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
    meter: '<svg viewBox="0 0 24 24"><path d="M12 14l4-4"/><path d="M3.3 19a10 10 0 1 1 17.4 0"/></svg>',
    wallet: '<svg viewBox="0 0 24 24"><rect x="2" y="6" width="20" height="14" rx="2"/><path d="M2 10h20M16 15h2"/></svg>',
    clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    receipt: '<svg viewBox="0 0 24 24"><path d="M4 2v20l3-2 3 2 3-2 3 2 3-2 3 2V2l-3 2-3-2-3 2-3-2-3 2z"/><path d="M8 9h8M8 13h6"/></svg>',
    phone: '<svg viewBox="0 0 24 24"><rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/></svg>',
    home: '<svg viewBox="0 0 24 24"><path d="M3 10l9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/></svg>',
    shop: '<svg viewBox="0 0 24 24"><path d="M3 9l2-5h14l2 5M4 9v11h16V9M3 9h18M9 20v-6h6v6"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
    bulb: '<svg viewBox="0 0 24 24"><path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg>',
    bell: '<svg viewBox="0 0 24 24"><path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12"/></svg>',
    trend: '<svg viewBox="0 0 24 24"><path d="m22 7-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/></svg>',
  };
  let me = null;
  let cfg = { methods: {}, test: true };

  // ---------------------------------------------------------------- api
  async function api(method, path, body) {
    const r = await fetch('/power/api' + path, {
      method, credentials: 'same-origin',
      headers: body ? { 'Content-Type': 'application/json' } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = {};
    try { data = await r.json(); } catch { /* empty */ }
    if (r.status === 401 && path !== '/login') { me = null; go('#/login'); throw new Error(data.message || 'Please sign in.'); }
    if (!r.ok) throw new Error(data.message || 'Something went wrong.');
    return data;
  }
  function toast(msg) {
    const t = $('#toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toast.h); toast.h = setTimeout(() => { t.hidden = true; }, 3500);
  }
  const go = (h) => { if (location.hash !== h) location.hash = h; else route(); };
  const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };

  /** Wire a form: disable while busy, show errors inline. */
  function form(el, fn) {
    el.addEventListener('submit', async (e) => {
      e.preventDefault();
      const btn = el.querySelector('[type=submit]'); const err = el.querySelector('.note.err');
      if (err) err.hidden = true; if (btn) btn.disabled = true;
      try { await fn(Object.fromEntries(new FormData(el))); } catch (x) { if (err) { err.textContent = x.message; err.hidden = false; } else toast(x.message); }
      finally { if (btn) btn.disabled = false; }
    });
  }

  // ---------------------------------------------------------------- views
  const views = {};

  views.login = (arg = '') => {
    chrome(false);
    app.innerHTML = `
      <h1>Welcome to Maru Power</h1>
      <p class="lead">Every meter you own, every token bought for it, at a till, on USSD or online, in one place. All amounts in Pula (BWP).</p>
      <div class="seg" role="tablist"><button aria-pressed="true" data-m="in">Sign in</button><button aria-pressed="false" data-m="up">Create account</button></div>
      <form class="card" id="f" novalidate>
        <div id="upRows" hidden>
          <label>Account type</label>
          <div class="seg" id="types"><button type="button" data-t="household" aria-pressed="true">Household</button><button type="button" data-t="business" aria-pressed="false">Business</button></div>
          <p class="muted small" id="typeHint"></p>
          <div id="bizRows" hidden>
            <label for="cn">Registered company name</label><input id="cn" name="company_name" autocomplete="organization">
            <label for="cr">Company registration number <small>CIPA UIN, e.g. BW00001234567</small></label><input id="cr" name="company_reg" autocomplete="off">
            <label for="vat">VAT number <small>BURS, optional</small></label><input id="vat" name="vat_no" autocomplete="off">
          </div>
          <label for="name" id="nameLbl">Full name</label><input id="name" name="name" autocomplete="name">
        </div>
        <label for="email">Email</label><input id="email" name="email" type="email" autocomplete="email" required>
        <label for="pw">Password <small id="pwHint" hidden>at least 8 characters</small></label><input id="pw" name="password" type="password" autocomplete="current-password" required>
        <div class="note err" role="alert" hidden></div>
        <button class="btn" type="submit" id="go">Sign in</button>
      </form>
      <p class="muted small">Maru Power has its own login. Your Maru Quick Supply Portal account does not sign you in here.</p>`;
    let mode = 'in';
    let type = 'household';
    const setType = (t) => {
      type = t;
      app.querySelectorAll('#types button').forEach((x) => x.setAttribute('aria-pressed', x.dataset.t === t));
      $('#bizRows').hidden = t !== 'business';
      $('#nameLbl').textContent = t === 'business' ? 'Your full name (account administrator)' : 'Full name';
      $('#typeHint').textContent = t === 'business'
        ? 'For companies with one or more sites. All meters, spend per site and VAT receipts in one account.'
        : 'For your home and the homes of family you look after.';
    };
    const setMode = (m) => {
      mode = m;
      app.querySelectorAll('[data-m]').forEach((x) => x.setAttribute('aria-pressed', x.dataset.m === m));
      $('#upRows').hidden = $('#pwHint').hidden = m === 'in';
      $('#go').textContent = m === 'in' ? 'Sign in' : 'Create account';
      $('#pw').autocomplete = m === 'in' ? 'current-password' : 'new-password';
    };
    app.querySelectorAll('[data-m]').forEach((b) => b.onclick = () => setMode(b.dataset.m));
    app.querySelectorAll('#types button').forEach((b) => b.onclick = () => setType(b.dataset.t));
    setType(arg === 'signup-business' ? 'business' : 'household');
    if (arg.startsWith('signup')) setMode('up');
    form($('#f'), async (d) => {
      if (mode === 'up') d.account_type = type;
      await api('POST', mode === 'in' ? '/login' : '/signup', d);
      me = await api('GET', '/me');
      go(mode === 'in' ? '#/' : '#/link');
    });
  };

  views[''] = async () => {
    const d = await api('GET', '/dashboard');
    me = d.user;
    const hour = new Date().getHours();
    const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    const max = Math.max(1, ...d.trend.map((m) => m.kwh));
    app.innerHTML = `
      <section class="card hero"><h1>${greet}, ${esc(me.name.split(' ')[0])}!</h1>${me.account_type === 'business' ? `<p class="small"><b>${esc(me.company_name)}</b> · Business account</p>` : ''}
        <a class="pill" href="#/meters">${ic.meter} ${d.meters.length} <span>${d.meters.length === 1 ? 'meter' : 'meters'}</span></a></section>
      <div class="stats">
        ${stat('Spent this month', P(d.month_thebe), 'All meters, all channels', 'wallet', 'ic-green')}
        ${stat('Units this month', d.month_kwh + ' kWh', 'From issued tokens', 'bolt', 'ic-yellow')}
        ${stat('Meters', d.meters.length, d.meters.length ? groupsSummary(d.meters) : 'None linked yet', 'meter', 'ic-blue')}
        ${stat('In progress', d.in_progress, d.in_progress ? 'Waiting for BPC' : 'Nothing pending', 'clock', 'ic-violet')}
      </div>
      <section class="card"><div class="card-head"><h2>${ic.trend} Usage trends</h2><span class="muted small">kWh bought</span></div>
        <div class="chart" role="img" aria-label="kWh bought per month">${d.trend.map((m) => `
          <div class="bar"><span class="v">${m.kwh ? Math.round(m.kwh) : ''}</span>
            <svg viewBox="0 0 10 100" preserveAspectRatio="none"><rect x="1" width="8" y="${100 - (m.kwh / max) * 100}" height="${(m.kwh / max) * 100}" rx="1.5"/></svg>${esc(m.label)}</div>`).join('')}
        </div></section>
      <section class="card"><div class="card-head"><h2>${ic.receipt} Recent transactions</h2><a href="#/transactions" class="small">See all</a></div>
        ${d.recent.length ? `<div class="list">${d.recent.map(txItem).join('')}</div>` : empty('receipt', 'No transactions yet.', 'Purchases for your meters from any till, USSD or online show here.')}</section>
      <section class="card"><div class="card-head"><h2>${ic.meter} My meters</h2><a class="btn secondary sm" href="#/link">+ Add</a></div>
        ${d.meters.length ? meterGroups(d.meters) : empty('meter', 'No meters added yet', '<a href="#/link">Add your first meter</a>')}</section>
      <section class="card"><h2>${ic.bulb} Quick actions</h2>
        ${qa('ic-blue', 'receipt', 'Link a meter with a till slip', 'Use the receipt number and token from any purchase to add that meter.', '#/link', 'Link meter')}
        ${me.msisdn ? '' : qa('ic-violet', 'phone', 'Verify your phone number', 'We will add every meter whose tokens were sent to your phone by SMS.', '#/profile', 'Verify phone')}
        ${qa('ic-green', 'bolt', 'Buy electricity', 'Buy a token for any of your meters. It is checked and recorded like every other sale.', '#/buy', 'Buy now')}
        ${qa('ic-yellow', 'wallet', 'What do my appliances cost?', 'Estimate the monthly cost of your geyser, stove and more.', '#/calculator', 'Open calculator')}
      </section>`;
    notifyPrompt();
    watchForNew(d.recent);
  };

  const stat = (label, value, sub, icon, cls) => `<div class="stat"><div class="stat-top"><span>${esc(label)}</span><span class="badge-ic ${cls}">${ic[icon]}</span></div><b>${esc(value)}</b><p>${esc(sub)}</p></div>`;
  const qa = (cls, icon, t, p, href, b) => `<div class="qa"><span class="badge-ic ${cls}">${ic[icon]}</span><div><div class="t">${esc(t)}</div><p>${esc(p)}</p><a class="btn secondary sm" href="${href}">${esc(b)}</a></div></div>`;
  const empty = (icon, t, s) => `<div class="empty">${ic[icon]}<p>${esc(t)}</p><p class="small">${s}</p></div>`;
  const groupsSummary = (ms) => Object.entries(ms.reduce((a, m) => ((a[m.site_type] = (a[m.site_type] || 0) + 1), a), {})).map(([k, n]) => `${n} ${k}`).join(', ');
  const stateTag = (t) => t.state === 'SUCCEEDED' ? '<span class="tag ok">Verified</span>' : t.state === 'FAILED' ? '<span class="tag err">Failed · reversed</span>' : '<span class="tag warn">In progress</span>';
  const txItem = (t) => `<a class="item" href="#/tx/${t.id}"><span class="badge-ic ${t.state === 'SUCCEEDED' ? 'ic-green' : 'ic-yellow'}">${ic.bolt}</span>
      <div class="grow"><div class="t">${esc(t.label)}</div><div class="s">${esc(CH[t.channel] || t.channel)} · ${esc(t.outlet)} · ${date(t.created_at)}</div></div>
      <div class="amt">${P(t.amount_thebe)}<small>${t.kwh ? esc(Number(t.kwh).toFixed(1)) + ' kWh' : ''} ${stateTag(t)}</small></div></a>`;
  function meterGroups(ms) {
    const g = {};
    ms.forEach((m) => (g[m.site_type] ||= []).push(m));
    return Object.keys(SITE).filter((k) => g[k]).map((k) => `<div class="group-title">${SITE[k]}</div><div class="list">${g[k].map((m) => `
      <a class="item" href="#/meter/${esc(m.meter_number)}"><span class="badge-ic ${k === 'business' ? 'ic-violet' : 'ic-blue'}">${ic[k === 'business' ? 'shop' : 'home']}</span>
        <div class="grow"><div class="t">${esc(m.label)} ${m.role === 'member' ? '<span class="tag">Shared with you</span>' : ''}</div>
          <div class="s">${esc(m.meter_number)} · ${m.last ? 'last token ' + date(m.last.issued_at) : 'no tokens yet'}</div></div>
        <div class="amt">${P(m.month_thebe)}<small>this month</small></div></a>`).join('')}</div>`).join('');
  }

  views.meters = async () => {
    const ms = await api('GET', '/meters');
    app.innerHTML = `<h1>My meters</h1><p class="lead">Homes and businesses you own or have been given access to.</p>
      <a class="btn" href="#/link">+ Link a meter</a>
      <section class="card">${ms.length ? meterGroups(ms) : empty('meter', 'No meters added yet', 'Link one with a till slip or your phone number.')}</section>`;
  };

  views.meter = async (num) => {
    const m = await api('GET', '/meters/' + encodeURIComponent(num));
    const owner = m.role === 'owner';
    app.innerHTML = `
      <p><a href="#/meters" class="small">← My meters</a></p>
      <h1>${esc(m.label)}</h1><p class="lead">Meter ${esc(m.meter_number)}${m.customer_name ? ' · BPC name: ' + esc(m.customer_name) : ''}</p>
      <div class="stats">
        ${stat('This month', P(m.month_thebe), m.month_kwh + ' kWh', 'wallet', 'ic-green')}
        ${stat('Purchases', m.purchases, 'All time, all channels', 'receipt', 'ic-blue')}
      </div>
      ${m.last ? `<section class="card"><h2>${ic.bolt} Latest token</h2><div class="token">${esc(tok(m.last.token))}</div>
        <p class="muted small">${esc(Number(m.last.kwh).toFixed(1))} kWh · ${P(m.last.amount_thebe)} · receipt ${esc(m.last.receipt_no)} · ${date(m.last.issued_at)}</p>
        <button class="btn secondary" id="copy">Copy token</button></section>` : ''}
      <a class="btn" href="#/buy/${esc(m.meter_number)}">${ic.bolt} Buy for this meter</a>
      <section class="card"><h2>${ic.receipt} Transactions</h2><div class="list" style="margin-top:14px">${m.transactions.length ? m.transactions.map(txItem).join('') : empty('receipt', 'No purchases yet.', '')}</div></section>
      <section class="card"><h2>Settings</h2>
        <form id="ms"><label for="label">Name</label><input id="label" name="label" value="${esc(m.label)}" maxlength="60">
          <label for="site">Type</label><select id="site" name="site_type">${Object.keys(SITE).map((k) => `<option value="${k}" ${k === m.site_type ? 'selected' : ''}>${esc(SITE[k].replace(/s$/, '').replace('Businesse', 'Business').replace('Other site', 'Other'))}</option>`).join('')}</select>
          <div class="note err" hidden></div><button class="btn secondary" type="submit">Save</button></form></section>
      ${owner ? `<section class="card"><h2>People with access</h2><p class="muted small">Family, staff or tenants you add can see this meter, its tokens and buy for it.</p>
        <div class="list">${m.members.map((u) => `<div class="item"><div class="grow"><div class="t">${esc(u.name)} ${u.role === 'owner' ? '<span class="tag ok">Owner</span>' : ''}</div><div class="s">${esc(u.email)}</div></div>
          ${u.role === 'member' ? `<button class="btn secondary sm danger" data-rm="${u.id}">Remove</button>` : ''}</div>`).join('')}</div>
        <form id="share"><label for="em">Add someone by email</label><input id="em" name="email" type="email" required><div class="note err" hidden></div><button class="btn secondary" type="submit">Give access</button></form></section>` : ''}
      <button class="btn secondary danger" id="unlink">${owner ? 'Remove meter from my account' : 'Leave this meter'}</button>`;
    $('#copy')?.addEventListener('click', () => navigator.clipboard?.writeText(m.last.token).then(() => toast('Token copied')));
    form($('#ms'), async (d) => { await api('PUT', '/meters/' + num, d); toast('Saved'); route(); });
    if (owner) {
      form($('#share'), async (d) => { await api('POST', `/meters/${num}/share`, d); toast('Access given'); route(); });
      app.querySelectorAll('[data-rm]').forEach((b) => b.onclick = async () => { await api('DELETE', `/meters/${num}/share/${b.dataset.rm}`); route(); });
    }
    $('#unlink').onclick = async () => {
      if (!confirm(owner ? 'Remove this meter? People you shared it with lose access too.' : 'Leave this meter?')) return;
      await api('DELETE', '/meters/' + num); go('#/meters');
    };
  };

  views.link = () => {
    app.innerHTML = `<h1>Link a meter</h1><p class="lead">Bought electricity at a till, on USSD or online? The slip proves the meter is yours.</p>
      <form class="card" id="f" novalidate>
        <h2>${ic.receipt} With a purchase slip</h2>
        <label for="rn">Receipt number</label><input id="rn" name="receipt_no" autocomplete="off" required placeholder="e.g. MV0000001234">
        <label for="tk">Token <small>all 20 digits</small></label><input id="tk" name="token" inputmode="numeric" autocomplete="off" required placeholder="1234 5678 9012 3456 7890">
        <label for="lb">Name this meter <small>optional</small></label><input id="lb" name="label" maxlength="60" placeholder="e.g. Home, Tuck shop">
        <label for="st">Type</label><select id="st" name="site_type"><option value="home">Home</option><option value="business">Business</option><option value="other">Other</option></select>
        <div class="note err" role="alert" hidden></div>
        <button class="btn" type="submit">Link meter</button>
      </form>
      <section class="card"><h2>${ic.phone} With your phone number</h2>
        <p class="muted">If your tokens were sent to you by SMS, verify that number and we add those meters for you.</p>
        <a class="btn secondary" href="#/profile">${me?.msisdn ? 'Phone verified: ' + esc(me.msisdn) : 'Verify my phone'}</a></section>
      <p class="muted small">Someone else manages the meter? Ask them to add you from the meter's page.</p>`;
    form($('#f'), async (d) => { const m = await api('POST', '/meters/claim', d); toast('Meter linked'); go('#/meter/' + m.meter_number); });
  };

  views.profile = async () => {
    me = await api('GET', '/me');
    app.innerHTML = `<h1>Profile</h1><p class="lead">${esc(me.name)} · ${esc(me.email)}</p>
      <section class="card"><h2>${ic.phone} Mobile number</h2>
        ${me.msisdn ? `<p class="note ok">Verified: ${esc(me.msisdn)}. Tokens you buy here are also sent to this number.</p>` : ''}
        <form id="p1"><label for="ms">${me.msisdn ? 'Change number' : 'Your mobile number'}</label><input id="ms" name="msisdn" type="tel" inputmode="tel" placeholder="71 234 567" required>
          <div class="note err" hidden></div><button class="btn secondary" type="submit">Send code</button></form>
        <form id="p2" hidden><label for="cd">6-digit code</label><input id="cd" name="code" inputmode="numeric" maxlength="6" required>
          <p class="note warn" id="demo" hidden></p><div class="note err" hidden></div><button class="btn" type="submit">Verify</button></form>
        <div id="res"></div></section>`;
    form($('#p1'), async (d) => {
      const r = await api('POST', '/phone', d);
      $('#p2').hidden = false; $('#cd').focus();
      if (r.demo_code) { $('#demo').hidden = false; $('#demo').textContent = 'Test environment code: ' + r.demo_code; }
      toast('Code sent to ' + r.sent_to);
    });
    form($('#p2'), async (d) => {
      const r = await api('POST', '/phone/verify', d);
      $('#p2').hidden = true;
      $('#res').innerHTML = `<p class="note ok">Phone verified. ${r.linked.length ? `Linked ${r.linked.length} meter(s): ${r.linked.map(esc).join(', ')}.` : 'No new meters found for this number.'}</p>
        ${r.owned_by_someone_else.length ? `<p class="note warn">Already managed by another account: ${r.owned_by_someone_else.map(esc).join(', ')}. Ask the owner to share them with you.</p>` : ''}`;
      me = await api('GET', '/me');
    });
  };

  views.buy = async (pre) => {
    const ms = await api('GET', '/meters');
    if (!ms.length) { app.innerHTML = `<h1>Buy electricity</h1>${empty('meter', 'Link a meter first.', '<a href="#/link">Link a meter</a>')}`; return; }
    app.innerHTML = `<h1>Buy electricity</h1><p class="lead">Your token shows here${me?.msisdn ? ' and is sent to ' + esc(me.msisdn) : ''}.</p>
      <form class="card" id="f" novalidate>
        <label>Meter</label><div class="chips" id="mchips">${ms.map((m, i) => `<button type="button" class="chip" data-m="${esc(m.meter_number)}" aria-pressed="${pre ? m.meter_number === pre : i === 0}">${esc(m.label)}</button>`).join('')}</div>
        <label for="amt">Amount (Pula) <small>minimum P10</small></label><input id="amt" name="amount" type="number" inputmode="decimal" min="10" step="1" required placeholder="e.g. 100">
        <div class="chips">${[20, 50, 100, 200, 500].map((a) => `<button type="button" class="chip" data-a="${a}">P${a}</button>`).join('')}</div>
        <div class="note err" role="alert" hidden></div>
        <button class="btn" type="submit">Check meter</button>
      </form><div id="step"></div>`;
    app.querySelectorAll('[data-m]').forEach((b) => b.onclick = () => app.querySelectorAll('[data-m]').forEach((x) => x.setAttribute('aria-pressed', x === b)));
    app.querySelectorAll('[data-a]').forEach((b) => b.onclick = () => { $('#amt').value = b.dataset.a; });
    form($('#f'), async (d) => {
      const meter = $('[data-m][aria-pressed=true]')?.dataset.m;
      const s = await api('POST', '/buy', { meter, amount: Number(d.amount), idempotency_key: crypto.randomUUID() });
      $('#f').hidden = true;
      $('#step').innerHTML = `<section class="card"><h2>Confirm and pay</h2>
        <dl class="kv" style="margin-top:14px"><dt>BPC name</dt><dd>${esc(s.customer_name || '—')}</dd><dt>Meter</dt><dd>${esc(s.meter_number)}</dd><dt>Amount</dt><dd>P${esc(s.amount)}</dd></dl>
        <form id="pay"><label>Pay with</label><select name="method">${Object.entries(cfg.methods).map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join('')}</select>
          <div class="note err" hidden></div><button class="btn" type="submit">Pay P${esc(s.amount)}</button>
          <button class="btn secondary" type="button" id="cancel">Cancel</button></form></section>`;
      $('#cancel').onclick = () => route();
      form($('#pay'), async (p) => {
        const r = await api('POST', `/buy/${s.sale_id}/pay`, p);
        go('#/tx/' + r.sale_id);
      });
    });
  };

  views.transactions = async () => {
    const txs = await api('GET', '/transactions');
    app.innerHTML = `<h1>Transactions</h1><p class="lead">Every purchase for your meters, from every till, USSD session, web store and app.</p>
      <section class="card">${txs.length ? `<div class="list">${txs.map(txItem).join('')}</div>` : empty('receipt', 'No transactions yet.', '')}</section>`;
  };

  views.tx = async (id) => {
    const d = await api('GET', '/transactions/' + Number(id));
    const s = d.sale; const r = s.receipt;
    app.innerHTML = `<p><a href="#/transactions" class="small">← Transactions</a></p>
      <h1>${P(Math.round(Number(s.amount) * 100))}</h1><p class="lead">${esc(CH[s.channel] || s.channel)} · ${esc(s.outlet)} · ${date(s.created_at)}</p>
      <div class="verified ${d.verified ? 'ok' : 'wait'}">${d.verified ? ic.check + ' Payment and token verified' : ic.clock + ' ' + esc(s.message)}</div>
      ${r ? `<section class="card"><h2>${ic.bolt} Token</h2>
        ${r.key_change_token_1 ? `<p class="note warn">Enter these key change tokens first:<br><b>${esc(r.key_change_token_1)}</b>${r.key_change_token_2 ? '<br><b>' + esc(r.key_change_token_2) + '</b>' : ''}</p>` : ''}
        <div class="token">${esc(r.token)}</div><button class="btn secondary" id="copy">Copy token</button></section>` : ''}
      <section class="card"><h2>How this transaction was verified</h2><ul class="checks" style="margin-top:14px">${d.checks.map((c) => `
        <li class="${c.ok ? 'ok' : ''}"><span class="dot">${c.ok ? ic.check : ic.clock}</span><div><div class="t">${esc(c.name)}</div><div class="d">${esc(c.detail)}</div></div></li>`).join('')}</ul></section>
      ${r ? `<section class="card"><h2>${ic.receipt} Receipt</h2><dl class="kv" style="margin-top:14px">
        ${[['Receipt number', r.receipt_no], ['Date', r.date], ['Meter', r.meter_number], ['Customer', r.customer_name], ['Tariff', r.tariff_index], ['Amount', 'P' + r.transaction_amount], ['Units', r.kwh + ' kWh'],
          ['Cost of units', 'P' + r.cost_of_units], ['Fixed charge', 'P' + r.fixed_charge], ['Government levy', 'P' + r.government_levy], ['VAT', 'P' + r.vat], ['BPC VAT no.', r.bpc_vat_no]]
          .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v ?? '—')}</dd>`).join('')}</dl></section>` : ''}
      <section class="card"><h2>History</h2><table style="margin-top:10px"><tbody>${d.timeline.map((e) => `<tr><td class="muted">${date(e.at)}</td><td>${esc(e.cause)}</td></tr>`).join('')}</tbody></table></section>`;
    $('#copy')?.addEventListener('click', () => navigator.clipboard?.writeText(r.token.replace(/\s/g, '')).then(() => toast('Token copied')));
    if (!['SUCCEEDED', 'FAILED', 'EXPIRED'].includes(s.status)) setTimeout(() => { if (location.hash === '#/tx/' + id) route(); }, 3000);
  };

  // ---------------------------------------------------------------- appliance calculator
  const APPLIANCES = {
    'Heating & Cooling': [['🌀', 'Ceiling fan', 75, 8], ['❄️', 'Air conditioner', 1500, 6], ['🔥', 'Heater (2 bar)', 2000, 3]],
    Kitchen: [['🍳', 'Stove (4 plate)', 3000, 1.5], ['🧊', 'Fridge', 150, 10], ['♨️', 'Microwave', 1000, 0.3], ['☕', 'Kettle', 2000, 0.3]],
    Laundry: [['🧺', 'Washing machine', 500, 1], ['👕', 'Iron', 1200, 0.5]],
    Entertainment: [['📺', 'TV', 100, 5], ['📡', 'Decoder', 20, 8], ['🎮', 'Game console', 150, 2]],
    Lighting: [['💡', 'LED bulbs (×6)', 60, 6], ['🔆', 'Security light', 50, 11]],
    'Water Heating': [['🚿', 'Electric geyser (150L)', 2000, 3], ['🔥', 'Instant water heater', 3000, 1]],
    Security: [['📹', 'CCTV system', 40, 24], ['⚡', 'Electric fence', 10, 24]],
    Other: [['💻', 'Laptop', 60, 6], ['📶', 'Wi-Fi router', 10, 24], ['🔌', 'Phone charging', 10, 3]],
  };
  views.calculator = () => {
    const picked = new Map();
    let cat = 'Heating & Cooling';
    const rate = Number(store.get('mp_rate')) || 1.6;
    app.innerHTML = `<h1>Appliance calculator</h1><p class="lead">Find out how much your appliances cost to run.</p>
      <section class="card"><h2>Select your appliances</h2><p class="muted">Tap an appliance to add it to your calculation.</p>
        <div class="seg" id="cats">${Object.keys(APPLIANCES).map((c) => `<button type="button" aria-pressed="${c === cat}">${esc(c)}</button>`).join('')}</div>
        <div class="tiles" id="tiles"></div></section>
      <section class="card"><h2>${ic.bolt} Monthly estimate</h2><div id="est"></div>
        <label for="rate">Price per kWh (Pula) <small>check your latest receipt</small></label><input id="rate" type="number" step="0.01" min="0" value="${rate}"></section>`;
    const draw = () => {
      $('#tiles').innerHTML = APPLIANCES[cat].map(([e, n, w, h]) => `<button type="button" class="tile" data-n="${esc(n)}" aria-pressed="${picked.has(n)}"><div class="e">${e}</div><div class="n">${esc(n)}</div><div class="w">${w}W · ${h}h/day</div></button>`).join('');
      $('#tiles').querySelectorAll('.tile').forEach((t) => t.onclick = () => {
        const a = APPLIANCES[cat].find((x) => x[1] === t.dataset.n);
        picked.has(a[1]) ? picked.delete(a[1]) : picked.set(a[1], { w: a[2], h: a[3] });
        draw();
      });
      const r = Number($('#rate').value) || 0;
      if (!picked.size) { $('#est').innerHTML = '<p class="muted">Select appliances to see your estimated electricity cost.</p>'; return; }
      let total = 0;
      const rows = [...picked].map(([n, a]) => { const kwh = (a.w * a.h * 30) / 1000; total += kwh; return `<tr><td>${esc(n)}</td><td>${kwh.toFixed(0)} kWh</td><td>P${(kwh * r).toFixed(2)}</td></tr>`; });
      $('#est').innerHTML = `<table><tbody>${rows.join('')}</tbody></table><div class="stat" style="margin-top:12px"><span class="muted">About</span><b>P${(total * r).toFixed(2)} / month</b><p>${total.toFixed(0)} kWh at P${r.toFixed(2)}/kWh. Estimates only; hours of use are typical values.</p></div>`;
    };
    $('#cats').querySelectorAll('button').forEach((b) => b.onclick = () => { cat = b.textContent; $('#cats').querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); draw(); });
    $('#rate').oninput = () => { store.set('mp_rate', $('#rate').value); draw(); };
    draw();
  };

  views.help = () => {
    app.innerHTML = `<h1>Help</h1><section class="card">
      <h2>How do my meters get onto my account?</h2><p class="muted">Use any purchase slip (receipt number and token), or verify the phone number your tokens are sent to. A teller can sell to your meter at any Maru till; that sale then appears here automatically.</p>
      <h2>What does "Verified" mean?</h2><p class="muted">The payment was confirmed for the exact amount and used only once, the money was held for BPC, BPC issued the token, and the payment to BPC was recorded. Each step is listed on the transaction.</p>
      <h2>A purchase failed</h2><p class="muted">If BPC does not issue a token, the amount is released and your payment is reversed. The transaction shows this.</p>
      <h2>Lost a token?</h2><p class="muted">Every token for your meters stays here. Open the transaction and copy it again.</p></section>`;
  };

  // ---------------------------------------------------------------- notifications
  function notifyPrompt() {
    if (!('Notification' in window) || Notification.permission !== 'default' || store.get('mp_notify_later')) return;
    const m = $('#modal');
    m.innerHTML = `<div class="card" role="dialog" aria-modal="true" aria-labelledby="nt"><button class="icon-btn x" aria-label="Close">${ic.x}</button>
      <div class="bell">${ic.bell}</div><h2 id="nt" style="justify-content:center">Never miss a token</h2>
      <p class="muted">Maru Power can tell you when a token is bought for one of your meters, wherever it was bought.</p>
      <ul><li>${ic.bolt} A new token for any of your meters</li><li>${ic.check} Payment verified and token issued</li><li>${ic.clock} A purchase waiting on BPC</li></ul>
      <button class="link" id="later">Maybe later</button><button class="btn" id="enable">Enable notifications</button></div>`;
    m.hidden = false;
    const close = () => { m.hidden = true; store.set('mp_notify_later', '1'); };
    m.querySelector('.x').onclick = close; $('#later').onclick = close;
    $('#enable').onclick = async () => { await Notification.requestPermission(); close(); };
  }
  /** While the page is open, check for new purchases on the customer's meters every minute. */
  function watchForNew(recent) {
    clearInterval(watchForNew.h);
    let last = Math.max(0, ...recent.map((t) => t.id));
    watchForNew.h = setInterval(async () => {
      if (!me) return;
      try {
        const txs = await api('GET', '/transactions');
        txs.filter((t) => t.id > last && t.state === 'SUCCEEDED').forEach((t) => {
          const msg = `${t.label}: ${Number(t.kwh).toFixed(1)} kWh, token ${tok(t.token)}`;
          if ('Notification' in window && Notification.permission === 'granted') new Notification('New token bought', { body: msg, icon: '/power/logo.svg' });
          else toast(msg);
        });
        last = Math.max(last, ...txs.map((t) => t.id));
      } catch { /* offline */ }
    }, 60000);
  }

  // ---------------------------------------------------------------- shell
  function chrome(on) {
    $('#topActions').hidden = $('#tabbar').hidden = !on;
    $('#drawer').hidden = true;
  }
  $('#menuBtn').onclick = () => { const d = $('#drawer'); d.hidden = !d.hidden; $('#menuBtn').setAttribute('aria-expanded', !d.hidden); };
  $('#drawer').addEventListener('click', (e) => { if (e.target.closest('a')) $('#drawer').hidden = true; });
  $('#logoutBtn').onclick = async () => { await api('POST', '/logout', {}); me = null; go('#/login'); };

  async function route() {
    const [, name = '', arg] = location.hash.match(/^#\/([a-z]*)\/?(.*)$/) || [];
    if (name === 'login') return views.login(decodeURIComponent(arg || ''));
    if (!me) { try { me = await api('GET', '/me'); } catch { return; } }
    chrome(true);
    document.querySelectorAll('.tabbar a').forEach((a) => { if (a.dataset.tab === name) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
    if (name !== '') clearInterval(watchForNew.h);
    const v = views[name] || views[''];
    app.innerHTML = '<div class="spinner"></div>';
    try { await v(decodeURIComponent(arg || '')); app.focus(); window.scrollTo(0, 0); } catch (e) { if (me) app.innerHTML = `<p class="note err">${esc(e.message)}</p>`; }
  }
  window.addEventListener('hashchange', route);
  api('GET', '/methods').then((c) => { cfg = c; $('#testBanner').hidden = !c.test; }).catch(() => {}).finally(route);
})();
