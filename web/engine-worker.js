// One Pyodide + Trailhead engine per worker. Messages: {id, fn, args} -> {id, ok, result | error}.
import { loadPyodide } from './vendor/pyodide/pyodide.mjs';

let ready = null;

// Retry transient network failures (busy server, flaky connection) before giving up.
async function get(url, opts) {
  for (let i = 0; ; i++) {
    try {
      const r = await fetch(url, opts);
      if (r.ok || r.status === 404 || i >= 3) return r;
    } catch (e) {
      if (i >= 3) throw e;
    }
    await new Promise((res) => setTimeout(res, 400 * 2 ** i));
  }
}

async function boot() {
  const py = await loadPyodide({ indexURL: new URL('./vendor/pyodide/', import.meta.url).href });
  const lock = await (await get(new URL('./vendor/pyodide/pyodide-lock.json', import.meta.url))).json();
  await py.loadPackage(new URL('./vendor/pyodide/' + lock.packages.numpy.file_name, import.meta.url).href);
  const man = await (await get(new URL('./py/manifest.json', import.meta.url), { cache: 'no-cache' })).json();
  py.FS.mkdirTree('/th/engine');
  await Promise.all(man.files.map(async (f) => {
    const r = await get(new URL('./py/' + f + '?v=' + man.version, import.meta.url));
    if (r.ok) py.FS.writeFile('/th/' + f, new Uint8Array(await r.arrayBuffer()));
  }));
  py.runPython("import sys; sys.path.insert(0, '/th'); import trailhead");
  const T = py.globals.get('trailhead');
  return (fn, args) => JSON.parse(T.call(fn, JSON.stringify(args ?? null)));
}

self.onmessage = async (e) => {
  const { id, fn, args } = e.data;
  try {
    ready = ready || boot().catch((err) => { ready = null; throw err; });   // a failed start can be retried
    const call = await ready;
    if (fn === '__boot') return self.postMessage({ id, ok: true, result: true });
    self.postMessage({ id, ok: true, result: call(fn, args) });
  } catch (err) {
    self.postMessage({ id, ok: false, error: String(err && err.message || err).slice(-600) });
  }
};
