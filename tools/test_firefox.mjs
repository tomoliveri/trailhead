// Real Firefox (stock app) via WebDriver BiDi: the engine boots and builds a plan in Firefox.
// Usage: node tools/test_firefox.mjs [baseUrl]
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
const BASE = process.argv[2] || 'https://garmin.ttnt.cloud';
const FF = process.env.FIREFOX || '/Applications/Firefox.app/Contents/MacOS/firefox';
const prof = fs.mkdtempSync(path.join(os.tmpdir(), 'th-ff-'));
const port = 9300 + Math.floor(Math.random() * 500);
const ff = spawn(FF, ['-headless', '-no-remote', '-profile', prof, `--remote-debugging-port=${port}`], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws;
for (let i = 0; i < 60 && !ws; i++) {
  await sleep(500);
  try {
    const s = new WebSocket(`ws://127.0.0.1:${port}/session`);
    await new Promise((res, rej) => { s.onopen = res; s.onerror = rej; });
    ws = s;
  } catch (e) { /* not up yet */ }
}
if (!ws) { ff.kill(); throw new Error('Firefox did not start'); }
let id = 0;
const pending = new Map();
ws.onmessage = (m) => { const j = JSON.parse(m.data); if (j.id && pending.has(j.id)) { pending.get(j.id)(j); pending.delete(j.id); } };
const send = (method, params) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send('session.new', { capabilities: {} });
const tree = await send('browsingContext.getTree', {});
const ctx = tree.result.contexts[0].context;
await send('browsingContext.navigate', { context: ctx, url: BASE + '/', wait: 'complete' });
const run = await send('script.evaluate', { target: { context: ctx }, awaitPromise: true, expression: `(async () => {
  const t0 = performance.now();
  const { Engine } = await import('/engine.js');
  const e = new Engine(2);
  const profile = { athlete: { age: 40 }, race: { name: 'Firefox Marathon', date: new Date(Date.now() + 140 * 864e5).toISOString().slice(0, 10) },
    recent: { race_km: 10, race_min: 50 }, current: { runs_per_week: 4, easy_min: 40, long_min: 80 },
    availability: { mon: { primary: 0 }, tue: { primary: 60 }, wed: { primary: 45 }, thu: { primary: 60 }, fri: { primary: 0 }, sat: { primary: 150 }, sun: { primary: 90 } } };
  const state = await e.call('new_state', { profile });
  const P = await e.call('PARAMS_get');
  const r = await e.tune(state, P.default, 8, null);
  state.policy = r.params;
  const out = await e.call('refresh', { state });
  return JSON.stringify({ secs: Math.round((performance.now() - t0) / 1000), ua: navigator.userAgent.split(' ').pop(), webusb: 'usb' in navigator,
    first: out.days[0].title, p50: Math.round(out.prediction.p50), gens: r.generations, bundle: Object.keys(out.bundle).length });
})()` });
console.log(run.result ? (run.result.result ? run.result.result.value : JSON.stringify(run.result)) : JSON.stringify(run.error || run).slice(0, 600));
ws.close(); ff.kill(); fs.rmSync(prof, { recursive: true, force: true });
