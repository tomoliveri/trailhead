// Run the site's real MTP installer (web/mtp.js) against a plugged-in watch from Node, via node-usb's WebUSB.
// Usage: node tools/test_usb_install.mjs [--info]   (without --info it installs web/watch/<model>/TrailheadCoach.prg)
import fs from 'node:fs';
import { WebUSB } from 'usb';
import { GarminUsb, buildFor } from '../web/mtp.js';
const webusb = new WebUSB({ allowAllDevices: true, deviceTimeout: 15000 });
const dev = (await webusb.getDevices()).find((d) => d.vendorId === 0x091e);
if (!dev) { console.log('no Garmin found'); process.exit(1); }
console.log(`device ${dev.vendorId.toString(16)}:${dev.productId.toString(16)} name=${JSON.stringify(dev.productName)}`);
// node-usb's transferIn/Out take a 1 s timeout by default (extra argument); browsers have none.
const tin = dev.transferIn.bind(dev), tout = dev.transferOut.bind(dev);
dev.transferIn = (ep, len) => tin(ep, len, 15000);
dev.transferOut = (ep, data) => tout(ep, data, 15000);
const w = new GarminUsb(dev);
if (process.env.DEBUG) {
  const op = w.op.bind(w);
  w.op = async (code, params = [], data = null, prog = null) => {
    const t = Date.now();
    try {
      const r = await op(code, params, data, prog);
      console.log(`  op 0x${code.toString(16)} [${params.map((p) => '0x' + (p >>> 0).toString(16)).join(',')}] data=${data ? data.byteLength : '-'} -> 0x${r.code.toString(16)} [${r.params.map((p) => '0x' + p.toString(16)).join(',')}] in=${r.data ? r.data.byteLength : '-'} ${Date.now() - t}ms`);
      return r;
    } catch (e) { console.log(`  op 0x${code.toString(16)} FAILED after ${Date.now() - t}ms: ${e.message}`); throw e; }
  };
}
const t0 = Date.now();
try {
  await w.open();
  const info = await w.deviceInfo();
  const build = buildFor(info.model);
  console.log('model', JSON.stringify(info.model), '-> build', build, 'firmware', info.version);
  if (!process.argv.includes('--info')) {
    const prg = new Uint8Array(fs.readFileSync(`web/watch/${build}/TrailheadCoach.prg`));
    await w.installApp('TrailheadCoach.prg', prg, (f, t) => console.log(`  ${Math.round(f * 100)}% ${t}`));
    console.log(`installed ${prg.byteLength} bytes in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  }
} catch (e) {
  console.log('ERROR', e.message);
} finally {
  await w.close();
}
