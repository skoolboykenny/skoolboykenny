// Maru Quick web store and Maru app (same page; the channel comes from the URL).
(() => {
  const CH = location.pathname.startsWith('/app') ? 'app' : 'web';
  const $ = (id) => document.getElementById(id);
  const steps = ['stepEntry', 'stepConfirm', 'stepWait', 'stepDone', 'stepReprint'];
  let sale = null;
  let pollTimer = null;

  if (CH === 'app') $('channelName').textContent = 'Maru app · open 24 hours';

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  function show(step) {
    steps.forEach((s) => { $(s).hidden = s !== step; });
    const reprint = step === 'stepReprint';
    $('tabBuy').setAttribute('aria-selected', String(!reprint));
    $('tabReprint').setAttribute('aria-selected', String(reprint));
    window.scrollTo(0, 0);
  }
  function err(id, msg) { $(id).textContent = msg || ''; $(id).hidden = !msg; }

  async function api(method, path, body) {
    const res = await fetch(`/api/${CH}${path}`, {
      method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    if (!res) return { ok: false, data: { message: 'No connection. Check your internet and try again.' } };
    const data = await res.json().catch(() => ({}));
    return { ok: res.ok, data };
  }
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random().toString(16).slice(2));

  // ---- config, saved meters, quick amounts
  fetch('/api/config').then((r) => r.json()).then((c) => {
    $('testBanner').hidden = !c.testPayments;
    const m = $('methods');
    Object.entries(c.methods).forEach(([k, label], i) => {
      const l = document.createElement('label');
      l.className = 'method';
      l.innerHTML = `<input type="radio" name="method" value="${k}" ${i === 0 ? 'checked' : ''}> <span></span>`;
      l.querySelector('span').textContent = label;
      m.appendChild(l);
    });
  });
  [20, 50, 100, 200, 500].forEach((v) => {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'chip'; b.textContent = `P${v}`;
    b.onclick = () => { $('amount').value = v; document.querySelectorAll('#quickAmounts .chip').forEach((c) => c.setAttribute('aria-pressed', String(c === b))); };
    $('quickAmounts').appendChild(b);
  });
  function renderSaved() {
    const box = $('savedMeters'); box.innerHTML = '';
    store.get('mv.meters', []).forEach((mt) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'chip'; b.textContent = `${mt.meter} · ${mt.name}`;
      b.onclick = () => { $('meter').value = mt.meter; };
      box.appendChild(b);
    });
  }
  renderSaved();
  $('msisdn').value = store.get('mv.msisdn', '');

  // ---- step 1: confirm meter with BPC
  $('entryForm').onsubmit = async (e) => {
    e.preventDefault();
    err('entryError');
    const meter = $('meter').value.replace(/\D/g, '');
    const amount = Number($('amount').value);
    if (!/^\d{11,13}$/.test(meter)) return err('entryError', 'Enter your 11 to 13 digit meter number.');
    if (!(amount >= 10)) return err('entryError', 'The minimum amount is P10.');
    $('checkBtn').disabled = true; $('checkBtn').textContent = 'Checking with BPC…';
    const r = await api('POST', '/confirm', { meter, amount, msisdn: $('msisdn').value, idempotency_key: uuid() });
    $('checkBtn').disabled = false; $('checkBtn').textContent = 'Check meter';
    if (!r.ok) return err('entryError', r.data.message || 'Could not check the meter.');
    sale = r.data;
    store.set('mv.msisdn', $('msisdn').value);
    $('cName').textContent = sale.customer_name || '—';
    $('cMeter').textContent = sale.meter_number;
    $('cAmount').textContent = `P${sale.amount}`;
    $('payBtn').textContent = `Pay P${sale.amount}`;
    show('stepConfirm');
  };
  $('backBtn').onclick = () => show('stepEntry');

  // ---- step 2: accept + pay
  $('payForm').onsubmit = async (e) => {
    e.preventDefault();
    err('payError');
    const method = (document.querySelector('input[name=method]:checked') || {}).value;
    if (!method) return err('payError', 'Choose how to pay.');
    $('payBtn').disabled = true;
    let r = await api('POST', '/accept', { sale_id: sale.sale_id });
    if (r.ok) r = await api('POST', `/pay/${sale.sale_id}`, { method });
    $('payBtn').disabled = false;
    if (!r.ok) return err('payError', r.data.message || 'Payment could not be started.');
    const saved = store.get('mv.meters', []).filter((m) => m.meter !== sale.meter_number);
    saved.unshift({ meter: sale.meter_number, name: sale.customer_name || '' });
    store.set('mv.meters', saved.slice(0, 4));
    renderSaved();
    show('stepWait');
    poll(Date.now());
  };

  // ---- step 3: poll until BPC answers
  function poll(started) {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      const r = await api('GET', `/status/${sale.sale_id}`);
      const s = r.data || {};
      if (s.status === 'SUCCEEDED') return done(s);
      if (s.status === 'FAILED' || s.status === 'EXPIRED') return fail(s.message);
      if (s.message) $('waitMsg').textContent = s.message;
      if (s.status === 'UNKNOWN' || s.status === 'MANUAL_REVIEW') $('waitTitle').textContent = 'Confirming with BPC';
      if (Date.now() - started > 5 * 60 * 1000) return pending();
      poll(started);
    }, 1500);
  }

  function done(s) {
    const rc = s.receipt;
    $('doneOk').hidden = false; $('doneFail').hidden = true; $('donePending').hidden = true;
    $('token').textContent = rc.token;
    const k = [rc.key_change_token_1, rc.key_change_token_2].filter(Boolean);
    $('kctBox').hidden = k.length === 0;
    if (k[0]) $('kct1').textContent = k[0];
    $('kct2').hidden = !k[1]; if (k[1]) $('kct2').textContent = k[1];
    $('smsNote').textContent = $('msisdn').value ? `A copy has been sent by SMS to ${$('msisdn').value}.` : '';
    const rows = [
      ['Receipt number', rc.receipt_no], ['Date', rc.date], ['Meter', rc.meter_number], ['Name', rc.customer_name],
      ['Tariff index', rc.tariff_index], ['Amount paid', `P${rc.transaction_amount}`], ['Units', `${rc.kwh} kWh`],
      ['Cost of units', `P${rc.cost_of_units}`], ['Fixed charge', `P${rc.fixed_charge}`], ['Government levy', `P${rc.government_levy}`],
      ['VAT', `P${rc.vat}`], ['BPC VAT number', rc.bpc_vat_no],
    ];
    const dl = $('receipt'); dl.innerHTML = '';
    rows.forEach(([k2, v]) => { const dt = document.createElement('dt'); dt.textContent = k2; const dd = document.createElement('dd'); dd.textContent = v ?? ''; dl.append(dt, dd); });
    show('stepDone');
  }
  function fail(msg) {
    $('doneOk').hidden = true; $('donePending').hidden = true;
    $('doneFail').hidden = false; $('doneFail').textContent = msg || 'BPC could not issue a token. You have not been charged.';
    show('stepDone');
  }
  function pending() {
    $('doneOk').hidden = true; $('doneFail').hidden = true;
    $('donePending').hidden = false;
    $('donePending').textContent = `Still confirming with BPC. Do not pay again. Your token will be sent by SMS, or use "Get my token again" with receipt ${sale.receipt_no}.`;
    show('stepDone');
  }

  $('copyBtn').onclick = async () => {
    try { await navigator.clipboard.writeText($('token').textContent.replace(/\s/g, '')); $('copyBtn').textContent = 'Copied'; } catch { /* ignore */ }
    setTimeout(() => { $('copyBtn').textContent = 'Copy token'; }, 2000);
  };
  $('againBtn').onclick = () => { sale = null; $('amount').value = ''; show('stepEntry'); };

  // ---- reprint
  $('tabBuy').onclick = () => show('stepEntry');
  $('tabReprint').onclick = () => show('stepReprint');
  $('reprintForm').onsubmit = async (e) => {
    e.preventDefault();
    err('rpError');
    const v = $('rpValue').value.trim();
    const body = /^MV/i.test(v) ? { receipt_no: v.toUpperCase() } : { meter: v };
    const r = await api('POST', '/reprint', body);
    if (!r.ok) return err('rpError', r.data.message || 'No token found.');
    sale = { sale_id: r.data.sale_id, receipt_no: r.data.receipt_no };
    done(r.data);
  };

  if ('serviceWorker' in navigator && CH === 'app') navigator.serviceWorker.register('/sw.js').catch(() => {});
})();
