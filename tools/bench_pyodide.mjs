// Run the bundled engine under Pyodide in Node: correctness smoke + simulation throughput.
import { loadPyodide } from 'pyodide';
import fs from 'node:fs';
import path from 'node:path';
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', 'web', 'py');
const py = await loadPyodide({ indexURL: path.resolve(root, '..', 'vendor', 'pyodide') + '/' });
await py.loadPackage(path.resolve(root, '..', 'vendor', 'pyodide', fs.readdirSync(path.resolve(root, '..', 'vendor', 'pyodide')).find(f => f.startsWith('numpy'))));
const man = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json')));
py.FS.mkdirTree('/th/engine');
for (const f of man.files) if (fs.existsSync(path.join(root, f))) py.FS.writeFile('/th/' + f, fs.readFileSync(path.join(root, f)));
py.runPython("import sys; sys.path.insert(0, '/th')");
let t = performance.now();
py.runPython('import trailhead as T');
console.log('import', ((performance.now() - t) / 1000).toFixed(2), 's');
const prof = JSON.parse(process.argv[2] || 'null') || {
  athlete: { age: 40, sex: 'F', weight_kg: 62, hr_max: 182, hr_rest: 55 },
  race: { name: 'Gold Coast Marathon', date: '2027-07-04', goal_min: 240 },
  recent: { race_km: 10, race_min: 52, date: '2026-10-25' },
  current: { runs_per_week: 4, easy_min: 40, long_min: 80, weeks_running: 8 },
  availability: { mon: { primary: 0 }, tue: { primary: 60, total: 80 }, wed: { primary: 45 }, thu: { primary: 60, total: 80 },
                  fri: { primary: 0 }, sat: { primary: 150 }, sun: { primary: 120 } }, tz: 'Australia/Brisbane' };
const call = (fn, args) => JSON.parse(py.globals.get('T').call(fn, JSON.stringify(args)));
const st = call('new_state', { profile: prof, today: '2026-11-03' });
t = performance.now(); const r = call('refresh', { state: st, today: '2026-11-03' });
console.log('refresh', ((performance.now() - t) / 1000).toFixed(2), 's', r.days.slice(0, 4).map(d => d.title).join(' / '), 'p50', r.prediction.p50.toFixed(1));
call('tune_context', { state: st, today: '2026-11-03' });
const P = call('PARAMS_get', null);
const th = Array.from({ length: 16 }, () => P.default);
for (const [n, k] of [[16, 16], [64, 16]]) {
  const rows = Array.from({ length: n }, () => P.default);
  t = performance.now(); const e = call('evaluate', { thetas: rows, k, gen_seed: 5 });
  const dtm = (performance.now() - t) / 1000;
  console.log(`evaluate ${n}x${k}: ${dtm.toFixed(2)} s -> ${(dtm / (n * k) * 1000).toFixed(2)} ms/sim, obj ${e.obj[0].toFixed(3)}`);
}
t = performance.now(); const s = call('season', { state: st, today: '2026-11-03' });
console.log('season', s.days.length, 'days', ((performance.now() - t) / 1000).toFixed(2), 's');
