// USSD emulator: behaves like the mobile network's USSD gateway, posting to /ussd exactly as
// the aggregator does (sessionId, phoneNumber, serviceCode, text with inputs joined by "*").
(() => {
  const $ = (id) => document.getElementById(id);
  let session = null;
  let inputs = [];

  setInterval(() => { $('clock').textContent = new Date().toTimeString().slice(0, 5); }, 1000);

  async function send() {
    const text = inputs.join('*');
    const body = new URLSearchParams({ sessionId: session, phoneNumber: `+267${$('msisdn').value.replace(/\D/g, '').slice(-8)}`, serviceCode: '*XXX#', text });
    $('display').textContent = 'Please wait…';
    const res = await fetch('/ussd', { method: 'POST', body }).catch(() => null);
    const reply = res ? await res.text() : 'END Network error.';
    const tr = document.createElement('tr');
    [text || '(dial)', reply].forEach((v) => { const td = document.createElement('td'); td.textContent = v; tr.appendChild(td); });
    $('log').prepend(tr);
    const end = reply.startsWith('END');
    $('display').textContent = reply.replace(/^(CON|END) /, '');
    $('replyForm').hidden = end;
    if (end) { session = null; setTimeout(loadSms, 1500); } else { $('reply').value = ''; $('reply').focus(); }
  }

  $('dialBtn').onclick = () => { session = `emu-${Date.now()}`; inputs = []; send(); };
  $('endBtn').onclick = () => { session = null; $('replyForm').hidden = true; $('display').textContent = 'Session ended.'; };
  $('replyForm').onsubmit = (e) => { e.preventDefault(); if (!session) return; inputs.push($('reply').value.trim()); send(); };

  async function loadSms() {
    const m = $('msisdn').value.replace(/\D/g, '').slice(-8);
    const r = await fetch(`/api/ussd/sms?msisdn=${m}`).then((x) => x.json()).catch(() => ({}));
    const box = $('sms');
    if (!r.messages || !r.messages.length) { box.innerHTML = '<p class="muted">No messages yet.</p>'; return; }
    box.innerHTML = '';
    r.messages.forEach((s) => {
      const d = document.createElement('div'); d.className = 'sms';
      d.textContent = s.body;
      const sm = document.createElement('small'); sm.textContent = `${s.created_at.slice(0, 19)} · ${s.status}`;
      d.appendChild(sm); box.appendChild(d);
    });
  }
  setInterval(loadSms, 3000);
  loadSms();
})();
