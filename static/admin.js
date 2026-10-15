let kind = 'visits', page = 0, query = '', requestId = 0;
const $ = id => document.getElementById(id);
const date = value => value ? new Date(value * 1000).toLocaleString() : '—';
const duration = seconds => { const n = Math.max(0, Math.floor(seconds)); return `${Math.floor(n / 60)}m ${n % 60}s`; };
function cell(row, value) { const td = document.createElement('td'); td.textContent = value ?? '—'; row.append(td); }
function details(row, title, values) {
  const td = document.createElement('td'), detail = document.createElement('details'), summary = document.createElement('summary');
  summary.textContent = title; detail.append(summary);
  for (const [name, value] of values) { const p = document.createElement('p'); p.textContent = `${name}: ${value || '—'}`; detail.append(p); }
  td.append(detail); row.append(td);
}
async function load() {
  const current = ++requestId, selected = kind;
  try {
    const response = await fetch(`/admin/api/logs?kind=${kind}&page=${page}&q=${encodeURIComponent(query)}`);
    if (response.status === 401) { location.replace('/admin'); return; }
    if (!response.ok) throw new Error('Could not load logs.');
    const data = await response.json(); if (current !== requestId) return;
    $('error').textContent = ''; $('summary').replaceChildren();
    for (const [key, label] of [['visits','Page visits'],['visitors','Visitor IDs'],['sessions','Open chat sessions'],['matches','Active matches']]) {
      const card = document.createElement('div'), number = document.createElement('strong'), text = document.createElement('span');
      number.textContent = data.summary[key]; text.textContent = label; card.append(number, text); $('summary').append(card);
    }
    const headings = selected === 'visits' ? ['Visited','IP address','Country','Browser / visitor','Chat sessions'] : selected === 'matches' ? ['Matched','Participants','Connected','Time connected','Match length','Ended','Ended by / reason'] : ['Time','Event','IP address','Country','Session / match'];
    const heading = document.createElement('tr');
    headings.forEach(value => { const th = document.createElement('th'); th.textContent = value; heading.append(th); });
    $('head').replaceChildren(heading); $('rows').replaceChildren();
    for (const entry of data.rows) {
      const row = document.createElement('tr');
      if (selected === 'visits') {
        cell(row, date(entry.at)); cell(row, entry.ip); cell(row, entry.country);
        details(row, entry.agent || 'Unknown browser', [['Visitor ID',entry.visitor],['Visit ID',entry.id],['Referrer',entry.referrer]]);
        cell(row, entry.sessions);
      } else if (selected === 'matches') {
        cell(row, date(entry.matched));
        details(row, `${entry.a_ip || 'Unknown'} (${entry.a_country || '—'}) ↔ ${entry.b_ip || 'Unknown'} (${entry.b_country || '—'})`, [['Match ID',entry.id],['A session',entry.a],['A visitor',entry.a_visitor],['B session',entry.b],['B visitor',entry.b_visitor]]);
        cell(row, date(entry.connected));
        cell(row, entry.connected ? duration(entry.connected_seconds + (entry.connected_since ? data.now - entry.connected_since : 0)) : 'Not connected');
        cell(row, duration((entry.ended || data.now) - entry.matched)); cell(row, entry.ended ? date(entry.ended) : 'Active');
        const actor = entry.ended_by === entry.a ? `A (${entry.a_ip})` : entry.ended_by === entry.b ? `B (${entry.b_ip})` : 'Server';
        cell(row, entry.ended ? `${actor} · ${entry.reason}` : '—');
      } else {
        cell(row, date(entry.at)); cell(row, entry.kind); cell(row, entry.ip); cell(row, entry.country);
        details(row, entry.match_id || entry.actor || 'Server', [['Session',entry.actor],['Match',entry.match_id]]);
      }
      $('rows').append(row);
    }
    $('page').textContent = data.total ? `${page * 100 + 1}–${Math.min((page + 1) * 100, data.total)} of ${data.total}` : 'No records';
    $('prev').disabled = page === 0; $('next').disabled = (page + 1) * 100 >= data.total;
  } catch (error) { if (current === requestId) $('error').textContent = error.message; }
}
document.querySelectorAll('[data-kind]').forEach(button => button.onclick = () => {
  kind = button.dataset.kind; page = 0;
  document.querySelectorAll('[data-kind]').forEach(other => other.setAttribute('aria-pressed', String(other === button))); load();
});
$('search').onsubmit = event => { event.preventDefault(); query = $('query').value; page = 0; load(); };
$('prev').onclick = () => { page--; load(); }; $('next').onclick = () => { page++; load(); }; $('refresh').onclick = load;
$('logout').onclick = async () => { const response = await fetch('/admin/logout', {method:'POST'}); if (response.ok) location.replace('/admin'); };
load(); setInterval(() => { if (!document.hidden && !document.querySelector('details[open]')) load(); }, 15000);
