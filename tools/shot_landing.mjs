import { chromium } from 'playwright-core';
const exe = `${process.env.HOME}/Library/Caches/ms-playwright/chromium-1243/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`;
const b = await chromium.launch({ executablePath: exe, headless: true });
for (const [name, vp] of [['desktop', { width: 1440, height: 900 }], ['mobile', { width: 390, height: 844 }]]) {
  const p = await b.newPage({ viewport: vp, deviceScaleFactor: 1 });
  const errs = []; p.on('pageerror', (e) => errs.push(e.message)); p.on('response', (r) => { if (r.status() >= 400) errs.push(r.status() + ' ' + r.url()); });
  await p.goto(process.argv[2] || 'https://garmin.ttnt.cloud/', { waitUntil: 'networkidle' });
  await p.evaluate(() => document.querySelectorAll('img[loading=lazy]').forEach((i) => i.loading = 'eager'));
  await p.waitForTimeout(1500);
  await p.screenshot({ path: `build/landing-${name}.png`, fullPage: true });
  console.log(name, errs.length ? errs : 'no errors');
}
await b.close();
