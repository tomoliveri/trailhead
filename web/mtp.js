// Minimal MTP (PTP) over WebUSB: enough to copy a Connect IQ app into GARMIN/Apps on a Garmin watch.
// Same operations libmtp uses for a file send: OpenSession, GetStorageIDs, GetObjectHandles/GetObjectInfo (find the
// folder), DeleteObject (old copy), SendObjectInfo + SendObject, CloseSession.

const GARMIN_VENDOR = 0x091e;
const OP = { GetDeviceInfo: 0x1001, OpenSession: 0x1002, CloseSession: 0x1003, GetStorageIDs: 0x1004,
  GetObjectHandles: 0x1007, GetObjectInfo: 0x1008, DeleteObject: 0x100b, SendObjectInfo: 0x100c, SendObject: 0x100d };
const OK = 0x2001, SESSION_OPEN = 0x201e;
const TYPE = { command: 1, data: 2, response: 3 };

export class MtpError extends Error {}

const TIMEOUT_MS = 10000;
function timed(p, what) {
  let t;
  return Promise.race([p, new Promise((_, rej) => { t = setTimeout(() => rej(new MtpError(`The watch stopped answering (${what}). Unplug it, plug it back in and try again.`)), TIMEOUT_MS); })])
    .finally(() => clearTimeout(t));
}

export function webUsbSupported() {
  return typeof navigator !== 'undefined' && 'usb' in navigator && window.isSecureContext;
}

function ptpString(s) {
  if (!s) return new Uint8Array([0]);
  const n = s.length + 1;
  const b = new Uint8Array(1 + n * 2);
  b[0] = n;
  for (let i = 0; i < s.length; i++) { b[1 + i * 2] = s.charCodeAt(i) & 255; b[2 + i * 2] = s.charCodeAt(i) >> 8; }
  return b;
}

function readString(v, off) {
  const n = v.getUint8(off);
  let s = '';
  for (let i = 0; i < n - 1; i++) s += String.fromCharCode(v.getUint16(off + 1 + i * 2, true));
  return [s, off + 1 + n * 2];
}

export class GarminUsb {
  constructor(device) {
    this.dev = device;
    this.tid = 0;
  }

  static async request() {
    if (!webUsbSupported()) throw new MtpError('This browser cannot talk to USB devices. Use Chrome or Edge on a computer.');
    let dev;
    try {
      dev = await navigator.usb.requestDevice({ filters: [{ vendorId: GARMIN_VENDOR }] });
    } catch (e) {
      throw new MtpError('No watch was chosen. Plug the watch in with its cable, then pick it from the list.');
    }
    const g = new GarminUsb(dev);
    await g.open();
    return g;
  }

  static async known() {   // a watch this site was already allowed to use
    if (!webUsbSupported()) return null;
    const list = await navigator.usb.getDevices();
    const d = list.find((x) => x.vendorId === GARMIN_VENDOR);
    if (!d) return null;
    const g = new GarminUsb(d);
    await g.open();
    return g;
  }

  // Watches in Garmin USB mode (product 0x0003, one vendor interface) don't speak MTP.
  get garminMode() {
    const itfs = this.dev.configuration ? this.dev.configuration.interfaces : [];
    const mtp = itfs.some((i) => i.alternates.some((a) => a.interfaceClass === 6 || /mtp/i.test(a.interfaceName || '')));
    // MTP-mode Garmins also use a vendor-class interface and often no product name, so only the product id tells.
    return this.dev.productId === 0x0003 && !mtp;
  }

  async open() {
    const d = this.dev;
    if (!d.opened) await d.open();
    if (!d.configuration) await d.selectConfiguration(1);
    if (this.garminMode) {
      await d.close();
      throw new MtpError('USB_MODE');
    }
    let pick = null;
    for (const itf of d.configuration.interfaces) {
      for (const alt of itf.alternates) {
        const bin = alt.endpoints.find((e) => e.type === 'bulk' && e.direction === 'in');
        const bout = alt.endpoints.find((e) => e.type === 'bulk' && e.direction === 'out');
        if (bin && bout && (alt.interfaceClass === 6 || alt.interfaceClass === 255 || !pick)) {
          pick = { itf: itf.interfaceNumber, alt: alt.alternateSetting, bin, bout, cls: alt.interfaceClass };
          if (alt.interfaceClass === 6) break;
        }
      }
    }
    if (!pick) throw new MtpError('This Garmin does not offer file transfer over USB.');
    try {
      await d.claimInterface(pick.itf);
      if (pick.alt) await d.selectAlternateInterface(pick.itf, pick.alt);
    } catch (e) {
      throw new MtpError('Another app is using the watch. Quit Garmin Express (and Android File Transfer / OpenMTP if open), unplug and replug the watch, then try again.');
    }
    this.ep = pick;
    this.maxPacket = pick.bout.packetSize || 512;
    const r = await this.op(OP.OpenSession, [1]);
    if (r.code === SESSION_OPEN) {
      await this.op(OP.CloseSession);
      await this.op(OP.OpenSession, [1]);
    }
  }

  container(type, code, params, payloadLen = 0) {
    const len = 12 + params.length * 4;
    const b = new ArrayBuffer(len);
    const v = new DataView(b);
    v.setUint32(0, type === TYPE.data ? 12 + payloadLen : len, true);
    v.setUint16(4, type, true);
    v.setUint16(6, code, true);
    v.setUint32(8, this.tid, true);
    params.forEach((p, i) => v.setUint32(12 + i * 4, p >>> 0, true));
    return new Uint8Array(b);
  }

  async out(bytes) {
    const r = await timed(this.dev.transferOut(this.ep.bout.endpointNumber, bytes), 'sending');
    if (r.status !== 'ok') throw new MtpError('USB write failed (' + r.status + ').');
  }

  async inContainer() {
    let buf = new Uint8Array(0);
    let want = 12;
    while (buf.byteLength < want) {
      const r = await timed(this.dev.transferIn(this.ep.bin.endpointNumber, 1 << 16), 'reading');
      if (r.status === 'stall') {
        await this.dev.clearHalt('in', this.ep.bin.endpointNumber);
        continue;
      }
      if (!r.data || r.data.byteLength === 0) continue;
      const chunk = new Uint8Array(r.data.buffer, r.data.byteOffset, r.data.byteLength);
      const nb = new Uint8Array(buf.byteLength + chunk.byteLength);
      nb.set(buf); nb.set(chunk, buf.byteLength); buf = nb;
      if (buf.byteLength >= 12) want = new DataView(buf.buffer).getUint32(0, true);
    }
    const v = new DataView(buf.buffer, 0, want);
    return { type: v.getUint16(4, true), code: v.getUint16(6, true), body: buf.slice(12, want) };
  }

  // One transaction: command, optional data out, optional data in, response.
  async op(code, params = [], dataOut = null, onProgress = null) {
    this.tid++;
    await this.out(this.container(TYPE.command, code, params));
    if (dataOut) {
      // Header in its own transfer, then the payload (as libmtp does): Garmin's MTP stack doesn't accept
      // a data phase whose header and payload arrive together.
      await this.out(this.container(TYPE.data, code, [], dataOut.byteLength));
      const CHUNK = 32 * this.maxPacket;   // whole packets, so only the very end can be short
      for (let o = 0; o < dataOut.byteLength; o += CHUNK) {
        await this.out(dataOut.subarray(o, Math.min(dataOut.byteLength, o + CHUNK)));
        onProgress && onProgress(Math.min(1, (o + CHUNK) / dataOut.byteLength));
      }
      if (dataOut.byteLength % this.maxPacket === 0) await this.out(new Uint8Array(0));
    }
    let c = await this.inContainer();
    let data = null;
    if (c.type === TYPE.data) {
      data = c.body;
      c = await this.inContainer();
    }
    const v = new DataView(c.body.buffer, c.body.byteOffset, c.body.byteLength);
    const out = [];
    for (let i = 0; i + 4 <= c.body.byteLength; i += 4) out.push(v.getUint32(i, true));
    return { code: c.code, params: out, data };
  }

  async must(code, params, dataOut, what, onProgress) {
    const r = await this.op(code, params, dataOut, onProgress);
    if (r.code !== OK) throw new MtpError(`${what} failed on the watch (0x${r.code.toString(16)}).`);
    return r;
  }

  async deviceInfo() {
    const r = await this.must(OP.GetDeviceInfo, [], null, 'Reading the watch model');
    const v = new DataView(r.data.buffer, r.data.byteOffset, r.data.byteLength);
    let o = 8;
    [, o] = readString(v, o);               // vendor extension description
    o += 2;                                  // functional mode
    for (let k = 0; k < 5; k++) o += 4 + v.getUint32(o, true) * 2;   // supported ops/events/props/formats
    let maker, model, version, serial;
    [maker, o] = readString(v, o);
    [model, o] = readString(v, o);
    [version, o] = readString(v, o);
    [serial] = readString(v, o);
    return { maker, model: model || this.dev.productName || '', version, serial };
  }

  async handles(storage, parent) {
    const r = await this.must(OP.GetObjectHandles, [storage, 0, parent], null, 'Listing files');
    const v = new DataView(r.data.buffer, r.data.byteOffset, r.data.byteLength);
    return Array.from({ length: v.getUint32(0, true) }, (_, i) => v.getUint32(4 + i * 4, true));
  }

  async name(h) {
    const r = await this.must(OP.GetObjectInfo, [h], null, 'Reading a file entry');
    const v = new DataView(r.data.buffer, r.data.byteOffset, r.data.byteLength);
    return readString(v, 52)[0];
  }

  async find(storage, parent, wanted) {
    for (const h of await this.handles(storage, parent)) {
      if ((await this.name(h)).toLowerCase() === wanted.toLowerCase()) return h;
    }
    return null;
  }

  // Copy `bytes` to GARMIN/Apps/<filename>, replacing an older copy. onStep(fraction, text) reports progress.
  async installApp(filename, bytes, onStep = () => {}) {
    onStep(0.2, 'Finding the Apps folder');
    const sr = await this.must(OP.GetStorageIDs, [], null, 'Reading storage');
    const sv = new DataView(sr.data.buffer, sr.data.byteOffset, sr.data.byteLength);
    const storages = Array.from({ length: sv.getUint32(0, true) }, (_, i) => sv.getUint32(4 + i * 4, true));
    let storage = null, apps = null;
    for (const s of storages) {
      const garmin = await this.find(s, 0xffffffff, 'GARMIN');
      if (garmin == null) continue;
      apps = await this.find(s, garmin, 'Apps');
      if (apps != null) { storage = s; break; }
    }
    if (apps == null) throw new MtpError('GARMIN/Apps was not found on the watch.');
    const old = await this.find(storage, apps, filename);
    if (old != null) {
      onStep(0.3, 'Removing the old version');
      await this.must(OP.DeleteObject, [old, 0], null, 'Removing the old app');
    }
    onStep(0.35, 'Copying');
    const name = ptpString(filename);
    const info = new Uint8Array(52 + name.byteLength + 3);
    const iv = new DataView(info.buffer);
    iv.setUint32(0, storage, true);
    iv.setUint16(4, 0x3000, true);          // undefined object format (a .prg)
    iv.setUint32(8, bytes.byteLength, true);
    iv.setUint32(38, apps, true);
    info.set(name, 52);                     // filename; capture/modification dates and keywords stay empty
    await this.must(OP.SendObjectInfo, [storage, apps], info, 'Preparing the copy');
    await this.must(OP.SendObject, [], bytes, 'Copying the app', (f) => onStep(0.35 + 0.55 * f, `Copying ${Math.round(f * 100)}%`));
    onStep(0.95, 'Checking');
    if ((await this.find(storage, apps, filename)) == null) throw new MtpError('The copy did not appear on the watch.');
  }

  async close() {
    try { await this.op(OP.CloseSession); } catch (e) { /* already gone */ }
    try { await this.dev.releaseInterface(this.ep.itf); } catch (e) { /* ignore */ }
    try { await this.dev.close(); } catch (e) { /* ignore */ }
  }
}

// Which build fits the plugged-in watch.
// Model names as the watch reports them over USB ("Forerunner 255S Music", "vívoactive 5", "fēnix 7").
export const BUILDS = {
  fr165: 'Forerunner 165', fr165m: 'Forerunner 165 Music', fr170: 'Forerunner 170', fr170m: 'Forerunner 170 Music',
  fr255: 'Forerunner 255', fr255m: 'Forerunner 255 Music', fr255s: 'Forerunner 255S', fr255sm: 'Forerunner 255S Music',
  fr265: 'Forerunner 265', fr265s: 'Forerunner 265S', fr955: 'Forerunner 955', fr965: 'Forerunner 965',
  fr970: 'Forerunner 970', vivoactive5: 'vívoactive 5', vivoactive6: 'vívoactive 6', venu3: 'Venu 3', venu3s: 'Venu 3S',
  fenix7: 'fēnix 7',
};

export function buildFor(model) {
  const m = (model || '').normalize('NFD').replace(/[\u0300-\u036f®™]/g, '').toLowerCase().replace(/\s+/g, ' ').trim();
  let r = m.match(/forerunner (\d{3})(s)?( music)?\b/);
  if (r) { const id = `fr${r[1]}${r[2] ? 's' : ''}${r[3] ? 'm' : ''}`; return BUILDS[id] ? id : null; }
  r = m.match(/vivoactive (\d)\b/);
  if (r) return BUILDS[`vivoactive${r[1]}`] ? `vivoactive${r[1]}` : null;
  r = m.match(/venu (\d)(s)?\b/);
  if (r) { const id = `venu${r[1]}${r[2] ? 's' : ''}`; return BUILDS[id] ? id : null; }
  if (/^fenix 7$/.test(m)) return 'fenix7';
  return null;
}
