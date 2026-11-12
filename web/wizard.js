// Trailhead setup: one window, one step at a time, with a live remaining-time estimate.
import { Engine } from './engine.js';
import { garmin } from './garmin.js';
import { BUILDS, GarminUsb, buildFor, webUsbSupported } from './mtp.js';

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const DAY_NAMES = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' };
const WATCHES = Object.entries(BUILDS);
const TUNE_SECONDS = Math.max(5, Math.min(600, +new URLSearchParams(location.search).get('tune') || 120));
// h:mm for long races, m:ss under an hour (5 and 10 km)
const fmtMin = (m) => m < 60 ? `${Math.floor(m)}:${String(Math.round((m % 1) * 60) % 60).padStart(2, '0')}`
  : `${Math.floor(m / 60)}:${String(Math.round(m % 60)).padStart(2, '0')}`;
const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10);
const today = () => iso(new Date());

// ---------------------------------------------------------------- saved progress
const saved = JSON.parse(localStorage.getItem('th:setup') || 'null');
const S = saved || {
  step: 0,
  profile: {
    athlete: {}, race: { name: '', date: '', goal_min: null, start_local: '07:00' }, recent: {}, current: {},
    availability: { mon: { primary: 0 }, tue: { primary: 60 }, wed: { primary: 45 }, thu: { primary: 60 }, fri: { primary: 0 },
                    sat: { primary: 150 }, sun: { primary: 90 } },
    strength: { legs: true, upper: false }, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
  },
  garminLogs: [], plan: null,
};
const save = () => localStorage.setItem('th:setup', JSON.stringify(S));

// Plan types. `long`: minutes one day needs for the long run; weeks: allowed time to race (finish) day.
const PLANS = {
  c25k: { label: 'Couch to 5K', sub: 'From no running to 30 minutes non-stop, then a 5 km run. Walk/run, three times a week.', minW: 9, maxW: 20, long: 30 },
  '5k': { label: '5 km', sub: 'Get faster over 5 km: speed, race-pace reps and a weekly long run.', minW: 4, maxW: 40, long: 45, goal: '25:00', race: 'e.g. Riverside 5K' },
  '10k': { label: '10 km', sub: 'A 10 km race: threshold, race-pace reps and long runs up to about 90 minutes.', minW: 4, maxW: 52, long: 60, goal: '50:00', race: 'e.g. City 10K' },
  half: { label: 'Half marathon', sub: 'A half marathon: long runs up to about 2 hours, threshold and race-pace work.', minW: 6, maxW: 60, long: 75, goal: '1:55', race: 'e.g. Harbour Half' },
  marathon: { label: 'Marathon', sub: 'A marathon: long runs up to about 3 hours, marathon-pace work and a 3-week taper.', minW: 6, maxW: 60, long: 90, goal: '4:00', race: 'e.g. Sydney Marathon' },
};
const dist = () => S.profile.race.distance || 'marathon';
const plan = () => PLANS[dist()];
const c25k = () => dist() === 'c25k';
const engine = new Engine();

// ---------------------------------------------------------------- steps

const ALL_STEPS = [
  { id: 'welcome', title: 'Your plan', est: 15 },
  { id: 'garmin', title: 'Garmin Connect', est: 60, race: true },
  { id: 'race', title: 'Your race', est: 30 },
  { id: 'you', title: 'About you', est: 35 },
  { id: 'running', title: 'Running now', est: 40, race: true },
  { id: 'week', title: 'Your week', est: 45 },
  { id: 'build', title: 'Build the plan', est: TUNE_SECONDS + 40 },
  { id: 'watch', title: 'Install on watch', est: 75 },
  { id: 'pair', title: 'Pair the watch', est: 40 },
  { id: 'done', title: 'Done', est: 5 },
];
// Couch to 5K skips the Garmin import and current-running steps, and its plan is built without tuning.
let STEPS = [];
const setSteps = () => {
  STEPS = ALL_STEPS.filter((x) => !(c25k() && x.race)).map((x) =>
    x.id === 'race' && c25k() ? { ...x, title: 'Finish date' } : x.id === 'build' && c25k() ? { ...x, est: 15 } : x);
};
setSteps();
let liveEta = null;   // seconds left in the current step when it knows better (plan building)

function rail() {
  $('#steps').innerHTML = STEPS.map((s, i) =>
    `<li class="${i === S.step ? 'on' : i < S.step ? 'done' : ''}"><span class="n">${i + 1}</span>${s.title}</li>`).join('');
  const left = STEPS.slice(S.step + 1).reduce((a, s) => a + s.est, 0) + (liveEta ?? STEPS[S.step].est);
  const total = STEPS.reduce((a, s) => a + s.est, 0);
  $('#eta').textContent = left < 60 ? 'under a minute' : `${Math.ceil(left / 60)} min`;
  $('#etabar').style.width = `${Math.round(100 * (1 - left / total))}%`;
}

function footer({ back = true, next = 'Continue', enabled = true, hide = false } = {}) {
  $('#back').style.visibility = back && S.step > 0 ? 'visible' : 'hidden';
  $('#next').textContent = next;
  $('#next').disabled = !enabled;
  $('#next').style.visibility = hide ? 'hidden' : 'visible';
}

function go(i) {
  setSteps();
  S.step = Math.max(0, Math.min(STEPS.length - 1, i));
  liveEta = null;
  save();
  render();
}

$('#back').onclick = () => go(S.step - 1);
$('#next').onclick = async () => {
  const v = VIEWS[STEPS[S.step].id];
  const err = v.validate ? v.validate() : null;
  if (err) return showErr(err);
  if (v.leave) {
    $('#next').disabled = true;
    showErr('');
    let r;
    try { r = await v.leave(); } catch (e) { $('#next').disabled = false; return showErr(e.message); }
    $('#next').disabled = false;
    if (r === false) return;
  }
  go(S.step + 1);
};

function showErr(m) {
  const e = $('#err');
  if (e) e.textContent = m;
}

function render() {
  setSteps();
  S.step = Math.min(S.step, STEPS.length - 1);
  const v = VIEWS[STEPS[S.step].id];
  $('#pane').innerHTML = `<div class="step">${v.html()}</div>`;
  footer(v.footer ? v.footer() : {});
  rail();
  v.mount && v.mount();
}

// bind inputs with data-k="profile.path"
function bind() {
  document.querySelectorAll('[data-k]').forEach((el) => {
    const path = el.dataset.k.split('.');
    const get = () => path.reduce((o, k) => (o || {})[k], S);
    const cur = get();
    if (cur != null) el.value = el.dataset.fmt === 'hm' ? fmtMin(cur)
      : el.dataset.fmt === 'ms' ? `${Math.floor(cur / 60)}:${String(Math.round(cur % 60)).padStart(2, '0')}` : cur;
    el.oninput = () => {
      let val = el.value.trim();
      if (el.dataset.fmt === 'hm') {
        // h:mm:ss, or two parts: mm:ss when the first is 10+ (25:30 for a 5 km), else h:mm (3:45)
        const m = val.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
        val = !m ? null : m[3] ? +m[1] * 60 + +m[2] + +m[3] / 60 : +m[1] >= 10 ? +m[1] + +m[2] / 60 : +m[1] * 60 + +m[2];
      } else if (el.dataset.fmt === 'ms') {
        const m = val.match(/^(\d{1,2}):(\d{2})$/);
        val = m ? +m[1] * 60 + +m[2] : null;
      } else if (el.type === 'number') val = val === '' ? null : +val;
      let o = S;
      path.slice(0, -1).forEach((k) => { o[k] = o[k] || {}; o = o[k]; });
      o[path.at(-1)] = val;
      save();
    };
  });
}

const VIEWS = {
  welcome: {
    html: () => `
      <h1>Training plan setup</h1>
      <p class="lead">Builds a running plan and puts it on your Garmin. Takes about ${Math.ceil(STEPS.reduce((a, x) => a + x.est, 0) / 60)} minutes. What are you training for?</p>
      <div class="plans" id="plans">${Object.entries(PLANS).map(([k, x]) =>
        `<button class="plan ${S.profile.race.distance === k ? 'sel' : ''}" data-plan="${k}"><b>${x.label}</b><small>${x.sub}</small></button>`).join('')}</div>
      <div class="err" id="err"></div>
      <div class="cards" style="margin-top:18px">
        <div class="card"><b>You’ll need</b><div class="hint" style="margin-top:6px">${c25k() ? 'A start that suits you, three free days a week, and your watch with its charging cable.' : 'Your race date, roughly how much you run now, and your watch with its charging cable.'}</div></div>
        <div class="card"><b>No account</b><div class="hint" style="margin-top:6px">You get a private link to your plan. Your Garmin password isn’t stored.</div></div>
      </div>
      ${saved && saved.step ? '<p class="hint" style="margin-top:14px">Carrying on from last time.</p>' : ''}`,
    footer: () => ({ next: 'Get started' }),
    mount() {
      document.querySelectorAll('#plans .plan').forEach((b) => b.onclick = () => {
        const k = b.dataset.plan;
        if (S.profile.race.distance !== k) {
          S.profile.race.distance = k;
          S.profile.race.goal_min = null;   // a goal for one distance means nothing for another
          if (k === 'c25k') S.profile.race.date = '';
        }
        save(); render();
      });
    },
    validate: () => (!S.profile.race.distance ? 'Pick what you’re training for.' : null),
  },

  garmin: {
    html: () => garmin.connected() ? `
      <h1>Garmin connected</h1>
      <p class="lead">${S.garminLogs.length ? `Got ${S.garminLogs.length} activities from the last 8 weeks.` : 'Connected.'}</p>
      <button class="btn light" id="unlink">Unlink Garmin</button>` : `
      <h1>Connect Garmin <span style="color:var(--mute);font-weight:400">(optional)</span></h1>
      <p class="lead">Pulls in your last 8 weeks of runs so the plan starts from where you actually are.</p>
      <div class="grid">
        <label class="f">Garmin email<input id="ge" type="email" autocomplete="username"></label>
        <label class="f">Password<input id="gp" type="password" autocomplete="current-password"></label>
      </div>
      <div id="mfa" hidden style="margin-top:14px"><label class="f">Code Garmin just sent you<input id="gc" inputmode="numeric" autocomplete="one-time-code"></label></div>
      <div style="margin-top:16px"><button class="btn light" id="gl">Sign in to Garmin</button></div>
      <div class="err" id="err"></div>
      <p class="hint" style="margin-top:18px">Your password is passed to Garmin and not stored. You can skip this and fill things in yourself.</p>`,
    footer: () => ({ next: garmin.connected() ? 'Continue' : 'Skip' }),
    mount() {
      const u = $('#unlink');
      if (u) u.onclick = () => { garmin.forget(); S.garminLogs = []; save(); render(); };
      const b = $('#gl');
      if (!b) return;
      let mfa = null;
      b.onclick = async () => {
        b.disabled = true; showErr('');
        try {
          if (mfa) await garmin.mfa(mfa, $('#gc').value);
          else {
            const r = await garmin.login($('#ge').value, $('#gp').value);
            if (r.mfa) { mfa = r.mfa; $('#mfa').hidden = false; b.textContent = 'Confirm code'; b.disabled = false; return; }
          }
          b.textContent = 'Importing your runs…';
          await importGarmin();
          render();
        } catch (e) { showErr(e.message); b.disabled = false; }
      };
    },
  },

  race: {
    html: () => c25k() ? `
      <h1>When do you want to run 5 km?</h1>
      <p class="lead">Couch to 5K takes about 9 weeks at three sessions a week. A later date leaves room to repeat sessions.</p>
      <div class="grid">
        <label class="f">5 km day <small>optional</small><input type="date" data-k="profile.race.date" min="${weeksOut(9)}" max="${weeksOut(20)}"></label>
      </div>
      <p class="hint" style="margin-top:14px">Leave it blank for 9 weeks from today (${weeksOut(9)}).</p>
      <div class="err" id="err"></div>` : `
      <h1>Your ${esc(plan().label === 'Marathon' ? 'race' : plan().label + ' race')}</h1>
      <p class="lead">The plan runs from today to race day.</p>
      <div class="grid">
        <label class="f">Race name<input data-k="profile.race.name" placeholder="${esc(plan().race)}"></label>
        <label class="f">Race date<input type="date" data-k="profile.race.date" min="${today()}"></label>
        <label class="f">Goal time <small>${plan().goal.split(':')[0].length > 1 ? 'mm:ss' : 'h:mm'}, optional</small><input data-k="profile.race.goal_min" data-fmt="hm" placeholder="${plan().goal}"></label>
        <label class="f">Start time<input type="time" data-k="profile.race.start_local"></label>
      </div>
      <p class="hint" style="margin-top:14px">Leave the goal blank and it’ll pick one from your current fitness.</p>
      <div class="err" id="err"></div>`,
    mount: bind,
    validate() {
      const d = S.profile.race.date, p = plan();
      if (!d) return c25k() ? null : 'Pick the race date.';
      const weeks = (new Date(d) - new Date(today())) / 6048e5;
      if (c25k() && (weeks < p.minW - 0.01 || weeks > p.maxW + 0.01)) return `Pick a day ${p.minW} to ${p.maxW} weeks from now, or leave it blank.`;
      if (weeks < p.minW) return `A ${p.label.toLowerCase()} plan needs at least ${p.minW} weeks before the race.`;
      if (weeks > p.maxW) return `Pick a race within the next ${p.maxW} weeks.`;
      const g = S.profile.race.goal_min;
      if (g && dist() === 'marathon' && g < 120) return 'Marathon goals are in h:mm, e.g. 3:45.';
      return null;
    },
  },

  you: {
    html: () => `
      <h1>About you</h1>
      <p class="lead">For heart rate zones. Leave the heart rates blank if you don’t know them.</p>
      <div class="grid three">
        <label class="f">First name<input data-k="profile.athlete.name"></label>
        <label class="f">Age<input type="number" min="14" max="90" data-k="profile.athlete.age"></label>
        <label class="f">Sex<select data-k="profile.athlete.sex"><option value="X">Prefer not to say</option><option value="F">Female</option><option value="M">Male</option></select></label>
        <label class="f">Weight (kg)<input type="number" step="0.1" data-k="profile.athlete.weight_kg"></label>
        <label class="f">Max heart rate<input type="number" data-k="profile.athlete.hr_max" placeholder="auto"></label>
        <label class="f">Resting heart rate<input type="number" data-k="profile.athlete.hr_rest" placeholder="auto"></label>
      </div>
      <div class="err" id="err"></div>`,
    mount: bind,
    validate: () => (!S.profile.athlete.age ? 'Enter your age.' : null),
  },

  running: {
    html: () => `
      <h1>Your running now</h1>
      <p class="lead">${S.garminLogs.length ? 'Filled in from Garmin. Change anything that’s off.' : 'Roughly, from a normal week.'}</p>
      <div class="grid three">
        <label class="f">Runs per week<input type="number" min="0" max="14" data-k="profile.current.runs_per_week"></label>
        <label class="f">Usual run (min)<input type="number" min="0" data-k="profile.current.easy_min"></label>
        <label class="f">Longest recent run (min)<input type="number" min="0" data-k="profile.current.long_min"></label>
      </div>
      <h3>Recent race or time trial <span style="text-transform:none;letter-spacing:0;font-weight:400"></span></h3>
      <div class="grid three">
        <label class="f">Distance<select data-k="profile.recent.race_km"><option value="">None</option><option value="5">5 km</option><option value="10">10 km</option><option value="21.0975">Half marathon</option><option value="42.195">Marathon</option></select></label>
        <label class="f">Time<input data-k="profile.recent.race_min" data-fmt="hm" placeholder="mm:ss or h:mm:ss"></label>
        <label class="f">Date<input type="date" data-k="profile.recent.date" max="${today()}"></label>
      </div>
      <label class="f" style="margin-top:14px;max-width:260px">Or your easy pace (min/km)<input data-k="profile.current.easy_pace_s" data-fmt="ms" placeholder="6:30"></label>
      <div class="err" id="err"></div>`,
    mount: bind,
    validate() {
      const r = S.profile.recent;
      if (r.race_km) r.race_km = +r.race_km;
      if (r.race_km && !r.race_min) return 'Enter the race time, or set distance to None.';
      if (S.profile.current.runs_per_week == null) return 'How many runs a week (0 is fine)?';
      return null;
    },
  },

  week: {
    html: () => {
      const opts = [0, 30, 45, 60, 75, 90, 120, 150, 180, 240];
      return `
      <h1>Your week</h1>
      <p class="lead">${c25k() ? 'Most time you’ve got each day. Sessions are about 30 minutes, three days a week, with rest days between where possible.' : 'Most time you’ve got each day. Days set to Off stay free.'}</p>
      <div class="week">${DAYS.map((d) => `<div class="row"><span>${DAY_NAMES[d]}</span><div class="seg" data-day="${d}">${opts.map((m) =>
        `<button data-m="${m}" class="${(S.profile.availability[d]?.primary || 0) === m ? 'sel' : ''}">${m ? m + "'" : 'Off'}</button>`).join('')}</div></div>`).join('')}</div>
      ${c25k() ? '' : `<h3>Strength</h3>
      <div class="seg" id="str">${[['legs', 'Legs, ~13 min weekly'], ['both', 'Legs + upper body'], ['none', 'No strength']].map(([k, l]) =>
        `<button data-s="${k}" class="${strengthKey() === k ? 'sel' : ''}">${l}</button>`).join('')}</div>`}
      <div class="err" id="err"></div>`;
    },
    mount() {
      document.querySelectorAll('.seg[data-day] button').forEach((b) => b.onclick = () => {
        const d = b.parentElement.dataset.day, m = +b.dataset.m;
        S.profile.availability[d] = { primary: m, total: m ? m + (S.profile.strength.legs ? 20 : 0) : 0 };
        save(); render();
      });
      document.querySelectorAll('#str button').forEach((b) => b.onclick = () => {
        const k = b.dataset.s;
        S.profile.strength = { legs: k !== 'none', upper: k === 'both' };
        DAYS.forEach((d) => { const a = S.profile.availability[d]; if (a.primary) a.total = a.primary + (k === 'none' ? 0 : 20); });
        save(); render();
      });
    },
    validate() {
      const p = plan();
      if (c25k()) {
        if (DAYS.filter((d) => S.profile.availability[d].primary >= 30).length < 3) return 'Pick at least 3 days with 30 minutes or more.';
        return null;
      }
      const n = DAYS.filter((d) => S.profile.availability[d].primary > 0).length;
      if (n < 3) return 'Pick at least 3 training days.';
      if (!DAYS.some((d) => S.profile.availability[d].primary >= p.long)) return `One day needs ${p.long} minutes or more for the long run.`;
      return null;
    },
  },

  build: {
    html: () => S.plan ? doneBuild() : `
      <h1>Making your plan</h1>
      <p class="lead">${c25k() ? 'Lays out your sessions. Runs on this computer and takes a few seconds.' : 'Tests lots of versions of the plan against your race and keeps the best one. Runs on this computer, so leave the tab open.'}</p>
      <div class="progress"><i id="pg"></i></div>
      <div class="hint" id="pgt">Starting…</div>
      <div class="log" id="log"></div>
      <div class="err" id="err"></div>`,
    footer: () => ({ enabled: !!S.plan, back: !S.plan || true }),
    mount() { if (!S.plan) buildPlan(); },
  },

  watch: {
    html: () => `
      <h1>Put it on your watch</h1>
      <p class="lead">Plug your watch into this computer with its charging cable, then press <b>${webUsbSupported() ? 'Install' : 'Download'}</b>.</p>
      ${webUsbSupported() ? '' : `
      <p class="note">This browser can’t copy to a watch directly. Download the app and copy it to the watch’s GARMIN › Apps folder
        (File Explorer on Windows, <a href="https://openmtp.ganeshrvel.com" target="_blank" rel="noopener">OpenMTP</a> on a Mac).</p>
      <label class="f" style="max-width:280px;margin-top:10px">Your watch<select id="model">${WATCHES.map(([id, name]) => `<option value="${id}">${name}</option>`).join('')}</select></label>`}
      <div id="ustate" ${S.installed ? '' : 'hidden'}>
        <div class="progress"><i id="upg" style="width:${S.installed ? 100 : 0}%"></i></div>
        <div class="hint" id="utext">${S.installed ? 'Installed. Unplug the watch and it’ll finish installing.' : ''}</div>
      </div>
      <div class="err" id="err"></div>
      <h3>Works on</h3>
      <p class="hint" style="columns:3;max-width:620px;line-height:1.7">${WATCHES.map(([, n]) => esc(n)).join('<br>')}</p>`,
    footer: () => ({ next: S.installed ? 'Continue' : webUsbSupported() ? 'Install' : 'Download' }),
    async leave() {
      if (S.installed) return true;
      const st = (f, t) => { $('#ustate').hidden = false; $('#upg').style.width = `${Math.round(f * 100)}%`; $('#utext').textContent = t; };
      if (!webUsbSupported()) {
        const a = document.createElement('a');
        a.href = `watch/${$('#model').value}/TrailheadCoach.prg`; a.download = 'TrailheadCoach.prg'; a.click();
        S.installed = 'download'; save();
        st(1, 'Downloaded. Copy TrailheadCoach.prg to GARMIN › Apps on the watch, then unplug it.');
        footer({ next: 'Continue' });
        return false;
      }
      let w;
      try {
        st(0.03, 'Waiting for you to pick the watch…');
        w = await GarminUsb.request();
        st(0.1, 'Reading the watch');
        const info = await w.deviceInfo();
        const model = info.model || w.dev.productName || 'this watch';
        const build = buildFor(model);
        if (!build) throw new Error(`Trailhead Coach doesn’t run on the ${model} yet. It works on the watches listed below.`);
        st(0.15, `Found ${model}`);
        const prg = new Uint8Array(await (await fetch(`watch/${build}/TrailheadCoach.prg`)).arrayBuffer());
        await w.installApp('TrailheadCoach.prg', prg, st);
        S.installed = build; save();
        st(1, 'Installed. Unplug the watch and it’ll finish installing.');
        footer({ next: 'Continue' });
      } catch (e) {
        $('#ustate').hidden = true;
        throw new Error(e.message === 'USB_MODE'
          ? 'Your watch is in Garmin USB mode. On the watch go to Settings › System › USB Mode › MTP, then unplug it, plug it back in and press Install again.'
          : e.message);
      } finally { if (w) await w.close(); }
      return false;
    },
  },

  pair: {
    html: () => `
      <h1>Pair your watch</h1>
      <p class="lead">Open <b>Trailhead Coach</b> on the watch and type in the code it shows.</p>
      <div style="display:flex;gap:28px;align-items:center;flex-wrap:wrap">
        <div class="watch">PAIR<br>ABCD-1234</div>
        <label class="f" style="min-width:240px">Code on the watch<input id="code" class="code" maxlength="9" placeholder="XXXX-XXXX" autocomplete="off"></label>
      </div>
      <p class="hint" style="margin-top:16px">The watch syncs through the Garmin Connect app on your phone.</p>
      <div class="err" id="err"></div>`,
    footer: () => ({ next: 'Pair' }),
    async leave() {
      const code = $('#code').value.toUpperCase().replace(/[^A-Z0-9]/g, '');
      if (code.length !== 8) {
        if (!code) return;   // skip
        throw new Error('The code has 8 letters and numbers.');
      }
      const r = await fetch(`/api/plans/${S.plan.slug}/pair`, { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Plan-Key': S.plan.key }, body: JSON.stringify({ code }) });
      if (!r.ok) throw new Error((await r.json()).error || 'Pairing failed.');
      S.paired = code; save();
    },
  },

  done: {
    html: () => {
      const url = `${location.origin}/p/${S.plan.slug}#k=${S.plan.key}`;
      return `
      <h1>All set</h1>
      <p class="lead">Save this link. It’s the only way back to your plan.</p>
      <div class="card" style="display:flex;gap:10px;align-items:center"><input readonly value="${esc(url)}" id="url" style="flex:1"><button class="btn light" id="copy">Copy</button></div>
      <p class="hint" style="margin-top:14px">Open it every few days so the plan catches up with your runs and the watch stays up to date.</p>`;
    },
    footer: () => ({ next: 'Open my plan' }),
    mount() { $('#copy').onclick = () => { navigator.clipboard.writeText($('#url').value); $('#copy').textContent = 'Copied'; }; },
    leave() { location.href = `/p/${S.plan.slug}#k=${S.plan.key}`; return new Promise(() => {}); },
  },
};

function weeksOut(w) {
  return iso(new Date(Date.now() + w * 6048e5));
}

function strengthKey() {
  const s = S.profile.strength;
  return !s.legs ? 'none' : s.upper ? 'both' : 'legs';
}

// ---------------------------------------------------------------- Garmin import -> prefill

async function importGarmin() {
  const acts = await garmin.recent(56);
  S.garminLogs = await engine.call('garmin_logs', { activities: acts });
  const runs = S.garminLogs.filter((l) => ['run', 'trail', 'treadmill'].includes(l.kind) && l.duration_min > 5);
  const med = (a) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : null; };
  const cur = S.profile.current;
  if (runs.length) {
    cur.runs_per_week = Math.round(runs.length / 8 * 10) / 10;
    cur.easy_min = Math.round(med(runs.map((r) => r.duration_min)));
    cur.long_min = Math.round(Math.max(...runs.map((r) => r.duration_min)));
    const paced = runs.filter((r) => r.distance_km > 1).map((r) => r.duration_min * 60 / r.distance_km);
    if (paced.length) cur.easy_pace_s = Math.round(med(paced));
    const hrs = runs.map((r) => r.max_hr).filter(Boolean);
    if (hrs.length && !S.profile.athlete.hr_max) S.profile.athlete.hr_max = Math.round(Math.max(...hrs));
  }
  try {
    const p = await garmin.call('profile');
    const u = p && (p.userData || p);
    if (u) {
      if (u.weight && !S.profile.athlete.weight_kg) S.profile.athlete.weight_kg = Math.round(u.weight / 100) / 10;
      if (u.birthDate && !S.profile.athlete.age) S.profile.athlete.age = Math.floor((Date.now() - new Date(u.birthDate)) / 315576e5);
      if (u.gender && !S.profile.athlete.sex) S.profile.athlete.sex = u.gender === 'FEMALE' ? 'F' : u.gender === 'MALE' ? 'M' : 'X';
    }
  } catch (e) { /* profile is a nice-to-have */ }
  try {
    const st = await garmin.call('stats', { cdate: today() });
    if (st && st.restingHeartRate && !S.profile.athlete.hr_rest) S.profile.athlete.hr_rest = st.restingHeartRate;
  } catch (e) { /* optional */ }
  save();
}

// ---------------------------------------------------------------- build

async function buildPlan() {
  const log = (t) => $('#log') && $('#log').insertAdjacentHTML('beforeend', `<div>${esc(t)}</div>`);
  const prog = (f, t) => { if ($('#pg')) $('#pg').style.width = `${Math.round(f * 100)}%`; if (t && $('#pgt')) $('#pgt').textContent = t; };
  try {
    liveEta = c25k() ? 15 : TUNE_SECONDS + 40; rail();
    prog(0.02, 'Loading (about 15 MB, first time only)…');
    const t0 = performance.now();
    await engine.boot(1);
    log('Loaded.');
    const state = await engine.call('new_state', { profile: S.profile, today: today() });
    if (S.garminLogs.length && !c25k()) {
      const merged = await engine.call('merge_into', { state, logs: S.garminLogs });
      Object.assign(state, merged.state);
      log(`Using ${merged.added} Garmin activities.`);
    }
    if (!c25k()) {
      const tr = await fetch('py/precooked.json', { cache: 'no-cache' });
      const table = tr.ok ? await tr.json() : { rows: [] };
      const near = await engine.call('nearest_precooked', { state, table: table.rows, today: today() });
      const P = await engine.call('PARAMS_get');
      const start = near ? P.names.map((n, j) => near.params[n] ?? P.default[j]) : P.default;
      log(near ? `Starting from a similar runner’s plan.` : 'Starting from the default plan.');
      prog(0.08, 'Working…');
      const r = await engine.tune(state, start, TUNE_SECONDS, ({ frac, gen, best, eta }) => {
        liveEta = Math.round(eta); rail();
        prog(0.1 + 0.8 * frac, `Testing plans · best so far ${fmtMin(best.mean)}`);
      }, today());
      engine.stopExtra();
      state.policy = r.params;
      log(r.refined ? `Improved from ${fmtMin(r.evidence.start_mean)} to ${fmtMin(r.evidence.mean)}.` : 'Kept the starting plan.');
    }
    prog(0.93, 'Nearly done…');
    const out = await engine.call('refresh', { state, today: today() });
    const res = await fetch('/api/plans', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ state, bundle: out.bundle, tz: S.profile.tz }) });
    if (!res.ok) throw new Error(res.status >= 500 ? 'Could not save the plan (server problem). Try again in a minute.'
      : 'Could not save the plan. Check your connection and try again.');
    const { slug, key } = await res.json();
    const plans = JSON.parse(localStorage.getItem('th:plans') || '[]');
    plans.push({ slug, key, name: state.program.race.name, created: today() });
    localStorage.setItem('th:plans', JSON.stringify(plans));
    localStorage.setItem(`th:key:${slug}`, key);
    S.plan = { slug, key, prediction: out.prediction, progress: out.progress || null, first: out.days.slice(0, 7),
      goal: state.program.race.goal_a_min ?? null };
    liveEta = null; save(); render();
  } catch (e) {
    console.error(e);
    showErr(`Couldn’t make the plan: ${e.message}`);
    footer({ next: 'Try again' });
    $('#next').onclick = () => { $('#next').onclick = null; location.reload(); };
  }
}

function doneBuild() {
  const p = S.plan.prediction, g = S.plan.progress;
  const fmtDate = (d) => new Date(d + 'T12:00').toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
  return `
    <h1>Plan ready</h1>
    ${g ? `<div class="stats">
      <div class="stat"><small>Sessions</small><div class="big">${g.total}</div></div>
      <div class="stat"><small>First session</small><div class="big" style="font-size:28px;margin-top:20px">${g.next ? fmtDate(g.next) : '–'}</div></div>
      <div class="stat"><small>5 km day</small><div class="big" style="font-size:28px;margin-top:20px">${fmtDate(g.finish)}</div></div>
    </div>` : `<div class="stats">
      <div class="stat"><small>Likely finish</small><div class="big">${fmtMin(p.p50)}</div></div>
      <div class="stat"><small>Goal ${fmtMin(p.goal_a)}</small><div class="big">${Math.round(p.p_goal_a * 100)}%</div></div>
      <div class="stat"><small>Range</small><div class="big" style="font-size:28px;margin-top:20px">${fmtMin(p.p10)}–${fmtMin(p.p90)}</div></div>
    </div>`}
    <h3>Your first week</h3>
    <div class="days">${S.plan.first.map((d) => `<div class="day ${d.kind === 'rest' ? 'rest' : ''}"><div class="d">${d.weekday}<b>${d.date.slice(8)}/${d.date.slice(5, 7)}</b></div>
      <div class="t">${esc(d.title)}${d.secondary ? `<small>+ ${esc(d.secondary.title)}</small>` : ''}</div><div class="m">${d.minutes ? d.minutes + ' min' : ''}</div></div>`).join('')}</div>`;
}

render();
