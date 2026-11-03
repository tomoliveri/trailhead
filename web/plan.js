// Plan page: re-plans in the browser from everything logged, then refreshes the watch for the next three weeks.
import { Engine } from './engine.js';
import { garmin } from './garmin.js';

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtMin = (m) => `${Math.floor(m / 60)}:${String(Math.round(m % 60)).padStart(2, '0')}`;
const pace = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
const today = () => iso(new Date());

const slug = location.pathname.split('/')[2];
const frag = new URLSearchParams(location.hash.slice(1));
if (frag.get('k')) {
  localStorage.setItem(`th:key:${slug}`, frag.get('k'));
  history.replaceState(null, '', location.pathname);
}
const key = localStorage.getItem(`th:key:${slug}`);
const engine = new Engine();
let state = null, view = null, season = null, open = null;

const status = (t) => { const s = $('#status'); if (s) s.textContent = t; };

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: { 'Content-Type': 'application/json', ...(key ? { 'X-Plan-Key': key } : {}), ...(opts.headers || {}) } });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || `Request failed (${r.status}).`);
  return j;
}

async function load() {
  const j = await api(`/api/plans/${slug}`);
  state = j.state;
  status('Checking for watch runs…');
  if (key) await pullInbox();
  await replan();
}

async function pullInbox() {
  const { items } = await api(`/api/plans/${slug}/inbox`);
  if (!items.length) return 0;
  const off = -new Date().getTimezoneOffset();
  for (const it of items) {
    const r = await engine.call('watch_log_state', { state, a: it.activity, tz_offset_min: off });
    state = r.state;
  }
  await api(`/api/plans/${slug}/inbox`, { method: 'POST', body: JSON.stringify({ ack: items.map((i) => i.id) }) });
  return items.length;
}

async function replan() {
  status('Updating…');
  view = await engine.call('refresh', { state, today: today() });
  season = null;
  if (key) await api(`/api/plans/${slug}`, { method: 'PUT', body: JSON.stringify({ state, bundle: view.bundle, tz: state.profile.tz }) });
  render();
}

// ---------------------------------------------------------------- rendering

function stepText(s, paces) {
  if (s.type === 'repeat') return `<li>${s.times} × <ol>${s.steps.map((x) => stepText(x, paces)).join('')}</ol></li>`;
  const d = s.duration || {};
  const len = d.type === 'time' ? `${Math.round(d.seconds / 60) || '<1'} min` : d.type === 'distance' ? `${(d.meters / 1000).toFixed(2).replace(/\.?0+$/, '')} km` : 'until lap';
  const t = s.target && s.target.type === 'pace' ? ` @ ${pace(s.target.fast)}–${pace(s.target.slow)} /km` : '';
  const h = s.hr && s.hr.type === 'hr' ? s.hr : s.target && s.target.type === 'hr' ? s.target : null;
  const hr = h ? ` · HR ${h.low}–${h.high}` : '';
  return `<li><b>${esc(s.name || s.type)}</b> ${len}${t}${hr}</li>`;
}

function detail(d) {
  const sec = d.secondary;
  return `<div class="detail">
    ${d.blurb ? `<p>${esc(d.blurb)}</p>` : ''}
    ${d.steps && d.steps.length ? `<ol>${d.steps.map((s) => stepText(s)).join('')}</ol>` : ''}
    ${(d.why || []).length ? `<p class="hint">${d.why.map(esc).join(' ')}</p>` : ''}
    ${(d.notes || []).length ? `<p class="hint">${d.notes.map(esc).join(' ')}</p>` : ''}
    ${(d.fuel || []).length ? `<p class="hint"><b>Fuel:</b> ${d.fuel.map(esc).join(' ')}</p>` : ''}
    ${sec ? `<p><b>${esc(sec.title)}</b></p><ol>${(sec.items || []).map((i) => `<li>${esc(i.name)}${i.sets ? ` — ${i.sets} × ${esc(i.reps)}` : ''}</li>`).join('')}</ol><p class="hint">${esc(sec.why || '')}</p>` : ''}
  </div>`;
}

function dayRow(d) {
  const t = d.date === today();
  return `<div class="day ${d.kind === 'rest' ? 'rest' : ''} ${t ? 'today' : ''}" data-date="${d.date}">
    <div class="d">${t ? 'Today' : d.weekday}<b>${d.date.slice(8)}/${d.date.slice(5, 7)}</b></div>
    <div class="t">${esc(d.title)}${d.secondary ? `<small>+ ${esc(d.secondary.title)}</small>` : ''}</div>
    <div class="m">${d.minutes ? d.minutes + ' min' : ''}${d.km ? ` · ${d.km} km` : ''}</div></div>${open === d.date ? detail(d) : ''}`;
}

function render() {
  const p = view.prediction, race = view.race;
  const days = Math.round((new Date(race.date) - new Date(today())) / 864e5);
  document.title = `Trailhead · ${race.name}`;
  $('#tt').textContent = race.name;
  $('#sub').textContent = `· ${days} days to go`;
  const logs = (state.logs || []).filter((l) => l.source !== 'history');
  $('#pane').innerHTML = `
    <div class="stats">
      <div class="stat"><small>Likely finish</small><div class="big">${fmtMin(p.p50)}</div></div>
      <div class="stat"><small>Chance of ${fmtMin(p.goal_a)}</small><div class="big">${Math.round(p.p_goal_a * 100)}%</div></div>
      <div class="stat"><small>Fitness (VDOT)</small><div class="big">${view.vdot}</div></div>
      <div class="stat"><small>Logged</small><div class="big">${logs.length}</div></div>
    </div>
    <div class="toolbar">
      ${key ? '<button class="btn" id="log">Log a session</button>' : ''}
      ${key && garmin.connected() ? '<button class="btn light" id="gsync">Sync Garmin</button>' : ''}
      ${key && !garmin.connected() ? '<button class="btn light" id="glink">Connect Garmin</button>' : ''}
      ${key ? '<button class="btn light" id="tune">Re-tune (2 min)</button>' : ''}
      ${key ? '<button class="btn light" id="pairb">Pair a watch</button>' : ''}
      <button class="btn light" id="seasonb">${season ? 'Next 3 weeks' : 'Whole plan'}</button>
    </div>
    ${key ? '' : '<p class="note">View only. Open your private link to make changes.</p>'}
    <div class="days" id="days">${(season ? season.days : view.days).map(dayRow).join('')}</div>
    <h3>Paces from your current fitness</h3>
    <p class="hint">${Object.entries(view.paces).map(([k, v]) => `${k} ${pace(v[0])}–${pace(v[1])}`).join(' · ')} /km</p>`;
  $('#days').onclick = (e) => {
    const row = e.target.closest('.day');
    if (!row) return;
    open = open === row.dataset.date ? null : row.dataset.date;
    render();
  };
  $('#seasonb').onclick = async () => {
    if (season) { season = null; return render(); }
    $('#seasonb').textContent = 'Planning to race day…';
    season = await engine.call('season', { state, today: today() });
    render();
  };
  const b = (id, fn) => { const el = $('#' + id); if (el) el.onclick = fn; };
  b('log', logDialog);
  b('tune', retune);
  b('pairb', pairDialog);
  b('glink', garminDialog);
  b('gsync', async () => {
    $('#gsync').textContent = 'Syncing…';
    try {
      const acts = await garmin.recent(21);
      const logsNew = await engine.call('garmin_logs', { activities: acts });
      const r = await engine.call('merge_into', { state, logs: logsNew });
      state = r.state;
      await replan();
    } catch (e) { alert(e.message); render(); }
  });
}

// ---------------------------------------------------------------- dialogs

function dialog(html, onSubmit) {
  const d = $('#dlg');
  d.innerHTML = `<form method="dialog">${html}<div class="err" id="derr"></div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px"><button class="btn ghost" value="cancel">Cancel</button><button class="btn" value="ok" id="dok">Save</button></div></form>`;
  d.showModal();
  $('#dok').onclick = async (e) => {
    e.preventDefault();
    try { $('#dok').disabled = true; await onSubmit(); d.close(); } catch (err) { $('#derr').textContent = err.message; $('#dok').disabled = false; }
  };
}

function logDialog() {
  dialog(`<h2 style="margin-top:0">Log a session</h2>
    <div class="grid">
      <label class="f">What<select id="lk"><option value="run">Run</option><option value="trail">Trail run</option><option value="bike">Bike</option>
        <option value="elliptical">Elliptical</option><option value="swim">Swim</option><option value="walk">Walk</option><option value="strength">Strength</option><option value="rest">Rest day</option></select></label>
      <label class="f">Date<input type="date" id="ld" value="${today()}" max="${today()}"></label>
      <label class="f">Minutes<input type="number" id="lm" min="0"></label>
      <label class="f">Distance (km)<input type="number" step="0.01" id="lx"></label>
      <label class="f">Effort 1–10<input type="number" id="lr" min="1" max="10"></label>
    </div>`, async () => {
    const kind = $('#lk').value;
    const lg = { kind, date: $('#ld').value, time: '12:00', duration_min: kind === 'rest' ? 0 : +$('#lm').value || 0, source: 'manual' };
    if (kind !== 'rest' && !lg.duration_min) throw new Error('How many minutes?');
    if (+$('#lx').value) lg.distance_km = +$('#lx').value;
    if (+$('#lr').value) lg.rpe = +$('#lr').value;
    if (kind === 'strength') lg.focus = 'lower';
    lg.client_id = lg.id = `manual-${Date.now()}`;
    state.logs.push(lg);
    await replan();
  });
}

function pairDialog() {
  dialog(`<h2 style="margin-top:0">Pair a watch</h2><p class="hint">Type in the code Trailhead Coach shows on the watch.</p>
    <input id="pc" class="code" maxlength="9" placeholder="XXXX-XXXX">`, async () => {
    await api(`/api/plans/${slug}/pair`, { method: 'POST', body: JSON.stringify({ code: $('#pc').value }) });
  });
}

function garminDialog() {
  let mfa = null;
  dialog(`<h2 style="margin-top:0">Connect Garmin</h2><p class="hint">Your password is passed to Garmin and not stored.</p>
    <div class="grid"><label class="f">Email<input id="ge" type="email"></label><label class="f">Password<input id="gp" type="password"></label></div>
    <label class="f" id="gcw" hidden style="margin-top:10px">Code from Garmin<input id="gc"></label>`, async () => {
    if (mfa) await garmin.mfa(mfa, $('#gc').value);
    else {
      const r = await garmin.login($('#ge').value, $('#gp').value);
      if (r.mfa) { mfa = r.mfa; $('#gcw').hidden = false; throw new Error('Enter the code Garmin just sent you.'); }
    }
    render();
  });
}

async function retune() {
  const btn = $('#tune');
  try {
    const P = await engine.call('PARAMS_get');
    const start = P.names.map((n, j) => (state.policy || {})[n] ?? P.default[j]);
    const r = await engine.tune(state, start, 120, ({ frac }) => { btn.textContent = `Re-tuning… ${Math.round(frac * 100)}%`; }, today());
    engine.stopExtra();
    state.policy = r.params;
    await replan();
  } catch (e) { alert(e.message); render(); }
}

load().catch((e) => {
  $('#pane').innerHTML = `<h1>Couldn’t load that plan</h1><p class="lead">${esc(e.message)}</p><p><a href="/setup">Set up a new plan</a></p>`;
});
