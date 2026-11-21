// Maru Quick merchant POS: sell BPC tokens for cash against the merchant float, print 58 mm receipts.
(() => {
  const $ = (id) => document.getElementById(id);
  let sale = null;
  let shift = [];
  try { shift = JSON.parse(sessionStorage.getItem('mv.shift')) || []; } catch { shift = []; }

  async function api(method, path, body) {
    const res = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).catch(() => null);
    if (!res) return { ok: false, status: 0, data: { message: 'No connection to the server.' } };
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && path !== '/api/pos/login') signedOut();
    return { ok: res.ok, status: res.status, data };
  }
  const err = (id, m) => { $(id).textContent = m || ''; $(id).hidden = !m; };
  const uuid = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random());

  function signedIn(op) {
    $('login').hidden = true; $('sale').hidden = false; $('who').hidden = false; $('opName').textContent = op;
    renderShift(); $('meter').focus();
  }
  function signedOut() { $('login').hidden = false; $('sale').hidden = true; $('who').hidden = true; }

  fetch('/api/config').then((r) => r.json()).then((c) => { c.operator ? signedIn(c.operator) : signedOut(); });

  $('loginForm').onsubmit = async (e) => {
    e.preventDefault(); err('loginError');
    const r = await api('POST', '/api/pos/login', { operator: $('op').value, pin: $('pin').value });
    $('pin').value = '';
    r.ok ? signedIn(r.data.operator) : err('loginError', r.data.message);
  };
  $('logoutBtn').onclick = async () => { await api('POST', '/api/pos/logout'); signedOut(); };

  function reset() {
    sale = null;
    ['confirmBox', 'waitBox', 'resultBox'].forEach((b) => { $(b).hidden = true; });
    $('saleForm').hidden = false; $('saleForm').reset(); err('saleError'); $('meter').focus();
  }

  $('saleForm').onsubmit = async (e) => {
    e.preventDefault(); err('saleError');
    const meter = $('meter').value.replace(/\D/g, '');
    const amount = Number($('amount').value);
    if (!/^\d{11,13}$/.test(meter)) return err('saleError', 'Meter number must be 11 to 13 digits.');
    if (!(amount >= 10)) return err('saleError', 'Minimum P10.');
    $('checkBtn').disabled = true;
    const r = await api('POST', '/api/pos/confirm', { meter, amount, msisdn: $('msisdn').value, idempotency_key: uuid() });
    $('checkBtn').disabled = false;
    if (!r.ok) return err('saleError', r.data.message);
    sale = r.data;
    $('cName').textContent = sale.customer_name || '—'; $('cMeter').textContent = sale.meter_number; $('cAmount').textContent = `P${sale.amount}`;
    $('sellBtn').textContent = `Cash P${sale.amount} received · Sell token`;
    $('saleForm').hidden = true; $('confirmBox').hidden = false; $('sellBtn').focus();
  };
  $('cancelBtn').onclick = reset;

  $('sellBtn').onclick = async () => {
    err('confirmError');
    $('sellBtn').disabled = true;
    const r = await api('POST', '/api/pos/accept', { sale_id: sale.sale_id });
    $('sellBtn').disabled = false;
    if (!r.ok) return err('confirmError', r.data.message);
    $('confirmBox').hidden = true; $('waitBox').hidden = false;
    poll(Date.now());
  };

  function poll(started) {
    setTimeout(async () => {
      const r = await api('GET', `/api/pos/status/${sale.sale_id}`);
      const s = r.data || {};
      if (s.message) $('waitMsg').textContent = s.message;
      if (s.status === 'SUCCEEDED') return result(s, 'ok');
      if (s.status === 'FAILED') return result(s, 'err');
      if (Date.now() - started > 5 * 60 * 1000) return result(s, 'warn');
      poll(started);
    }, 1200);
  }

  function result(s, kind) {
    $('waitBox').hidden = true; $('resultBox').hidden = false;
    const n = $('resultNote');
    n.className = `note ${kind}`;
    n.textContent = kind === 'ok' ? 'Token issued. Print the receipt for the customer.'
      : kind === 'err' ? `${s.message} Return the cash to the customer.`
        : `Still confirming with BPC. Do NOT sell again. Reprint later with receipt ${s.receipt_no}.`;
    $('tokenCard').hidden = kind !== 'ok';
    if (kind === 'ok') { fillSlip(s, false); $('tokenScreen').textContent = s.receipt.token; $('printBtn').focus(); }
    shift.unshift({ t: new Date().toTimeString().slice(0, 5), r: s.receipt_no, m: s.meter_number, a: s.amount, st: s.status });
    try { sessionStorage.setItem('mv.shift', JSON.stringify(shift.slice(0, 200))); } catch { /* ignore */ }
    renderShift();
  }

  function fillSlip(s, reprint) {
    const rc = s.receipt;
    const set = (id, v) => { $(id).textContent = v ?? ''; };
    set('pVat', rc.bpc_vat_no); set('pDate', rc.date); set('pReceipt', rc.receipt_no); set('pMeter', rc.meter_number);
    set('pName', rc.customer_name); set('pTi', rc.tariff_index); set('pAmount', `P${rc.transaction_amount}`);
    set('pCost', `P${rc.cost_of_units}`); set('pFixed', `P${rc.fixed_charge}`); set('pLevy', `P${rc.government_levy}`);
    set('pVatAmt', `P${rc.vat}`); set('pKwh', `${rc.kwh} kWh`); set('pToken', rc.token);
    const k = [rc.key_change_token_1, rc.key_change_token_2].filter(Boolean);
    $('pKctBox').style.display = k.length ? '' : 'none'; set('pKct', k.join(' / '));
    set('pReprint', reprint ? `REPRINT ${new Date().toLocaleString()}` : '');
  }

  $('printBtn').onclick = () => window.print();
  $('nextBtn').onclick = reset;

  function renderShift() {
    const tb = $('shift'); tb.innerHTML = '';
    let total = 0;
    shift.forEach((x) => {
      const tr = document.createElement('tr');
      [x.t, x.r, x.m, `P${x.a}`, x.st].forEach((v) => { const td = document.createElement('td'); td.textContent = v; tr.appendChild(td); });
      tb.appendChild(tr);
      if (x.st === 'SUCCEEDED') total += Number(x.a);
    });
    $('shiftTotal').textContent = `Cash to bank for tokens sold: P${total.toFixed(2)}`;
  }

  // Tabs and reprint
  const tab = (reprint) => {
    $('paneSale').hidden = reprint; $('paneReprint').hidden = !reprint;
    $('tabSale').setAttribute('aria-selected', String(!reprint)); $('tabReprint').setAttribute('aria-selected', String(reprint));
  };
  $('tabSale').onclick = () => tab(false);
  $('tabReprint').onclick = () => tab(true);
  $('reprintForm').onsubmit = async (e) => {
    e.preventDefault(); err('rpError');
    const v = $('rpValue').value.trim();
    const r = await api('POST', '/api/pos/reprint', /^MV/i.test(v) ? { receipt_no: v.toUpperCase() } : { meter: v });
    if (!r.ok) return err('rpError', r.data.message);
    fillSlip(r.data, true);
    window.print();
  };
})();
