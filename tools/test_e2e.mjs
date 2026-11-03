// End-to-end: wizard -> plan saved -> watch pairing + sync + upload -> plan page merges it.
// Usage: node tools/test_e2e.mjs [baseUrl]   (screenshots to $OUT, default build/e2e)
import pw, { chromium, firefox } from 'playwright-core';
import fs from 'node:fs';
const BASE = process.argv[2] || 'http://127.0.0.1:13041';
const OUT = process.env.OUT || 'build/e2e';
fs.mkdirSync(OUT, { recursive: true });
const exe = process.env.CHROME || `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;
const browser = process.env.BROWSER === 'firefox'
  ? await pw._bidiFirefox.launch({ executablePath: '/Applications/Firefox.app/Contents/MacOS/firefox', headless: true })
  : await chromium.launch({ executablePath: fs.existsSync(exe) ? exe : undefined, headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 820 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
const shot = async (n) => { await page.waitForTimeout(450); return page.screenshot({ path: `${OUT}/${n}.png` }); };
const next = () => page.click('#next');
const ok = (c, m) => { if (!c) throw new Error('FAIL: ' + m); console.log('ok  ', m); };

await page.goto(BASE + '/setup?tune=' + (process.env.TUNE || 20));
await page.evaluate(() => localStorage.clear());
await page.goto(BASE + '/setup?tune=' + (process.env.TUNE || 20));
await shot('01-welcome');
ok((await page.textContent('h1')).includes('Marathon plan'), 'welcome step renders');
await next();
await shot('02-garmin');
await next();                                   // skip Garmin
await page.fill('[data-k="profile.race.name"]', 'Test City Marathon');
const d = new Date(Date.now() + 20 * 7 * 864e5).toISOString().slice(0, 10);
await page.fill('[data-k="profile.race.date"]', d);
await page.fill('[data-k="profile.race.goal_min"]', '3:59');
await shot('03-race');
await next();
await page.fill('[data-k="profile.athlete.name"]', 'Alex');
await page.fill('[data-k="profile.athlete.age"]', '37');
await page.selectOption('[data-k="profile.athlete.sex"]', 'F');
await page.fill('[data-k="profile.athlete.weight_kg"]', '61');
await next();
await page.fill('[data-k="profile.current.runs_per_week"]', '4');
await page.fill('[data-k="profile.current.easy_min"]', '40');
await page.fill('[data-k="profile.current.long_min"]', '85');
await page.selectOption('[data-k="profile.recent.race_km"]', '10');
await page.fill('[data-k="profile.recent.race_min"]', '49:30');
await shot('05-running');
await next();
await shot('06-week');
await next();
const t0 = Date.now();
await page.waitForSelector('text=Plan ready', { timeout: 240000 }).catch(async (e) => {
  console.log('errors:', errors.join(' | ').slice(0, 2000), '\nerr text:', await page.textContent('#err').catch(() => ''), '\nlog:', await page.textContent('#log').catch(() => ''));
  await shot('07-fail'); throw e;
});
ok(true, `plan built in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
await shot('07-built');
const setup = await page.evaluate(() => JSON.parse(localStorage.getItem('th:setup')));
const { slug, key } = setup.plan;
ok(slug && key, 'plan saved to server with a link + key');
ok(setup.plan.prediction.p50 > 180 && setup.plan.prediction.p50 < 330, `prediction ${setup.plan.prediction.p50.toFixed(1)} min`);
await next();
await shot('08-watch');
// watch side: an unpaired watch is told to pair
const code = 'TEST' + Math.random().toString(36).slice(2, 6).toUpperCase().replace(/[^A-Z0-9]/g, 'Z').padEnd(4, 'Z');
let r = await fetch(BASE + '/api/device/sync', { headers: { Authorization: 'Bearer ' + code } });
ok(r.status === 404 && (await r.json()).pair === code, 'unpaired watch gets 404 + its code');
// no watch in CI: mark the install done and continue from the pairing step
await page.evaluate(() => { const s = JSON.parse(localStorage.getItem('th:setup')); s.installed = 'test'; s.step = 8; localStorage.setItem('th:setup', JSON.stringify(s)); });
await page.reload();
await page.waitForSelector('#code');
await page.fill('#code', code.slice(0, 4) + '-' + code.slice(4));
await shot('09-pair');
await next();
await page.waitForSelector('text=All set');
await shot('10-done');
r = await fetch(BASE + '/api/device/sync', { headers: { Authorization: 'Bearer ' + code } });
const sync = await r.json();
ok(r.status === 200 && sync.today && sync.today.date, `paired watch syncs today's session: ${sync.today && sync.today.t}`);
ok(Array.isArray(sync.wk) && sync.wk.length === 7 && sync.race, 'sync carries week strip and race');
// watch uploads a run
const act = { id: 'watch-' + Math.floor(Date.now() / 1000 - 3600), start: Math.floor(Date.now() / 1000 - 3600), sport: 'run',
  planned: sync.today.k, duration_s: 2700, distance_m: 7400, avg_hr: 146, completed_steps: 3, completed_frac: 1 };
r = await fetch(BASE + '/api/device/activity', { method: 'POST', headers: { Authorization: 'Bearer ' + code, 'Content-Type': 'application/json' }, body: JSON.stringify(act) });
ok(r.status === 201, 'watch upload accepted');
// plan page picks it up
await page.goto(`${BASE}/p/${slug}`);
await page.waitForSelector('.stats', { timeout: 120000 });
await shot('11-plan');
const logged = await page.textContent('.stats .stat:nth-child(4) .big');
ok(+logged >= 1, `plan page merged the watch run (logged ${logged})`);
r = await fetch(`${BASE}/api/plans/${slug}/inbox`, { headers: { 'X-Plan-Key': key } });
ok((await r.json()).items.length === 0, 'inbox acknowledged');
r = await fetch(`${BASE}/api/plans/${slug}`, { method: 'PUT', headers: { 'X-Plan-Key': 'wrong', 'Content-Type': 'application/json' }, body: '{}' });
ok(r.status === 403, 'writes need the plan key');
await page.click('.day.today, .day');
await shot('12-detail');
await page.click('#seasonb');
await page.waitForSelector('#seasonb:text("Next 3 weeks")', { timeout: 60000 });
const n = await page.locator('.day').count();
ok(n > 100, `whole plan to race day: ${n} days`);
// mobile layout
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(BASE + '/');
await shot('13-mobile');
ok(errors.filter((e) => !/favicon/.test(e)).length === 0, 'no page errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
await browser.close();
