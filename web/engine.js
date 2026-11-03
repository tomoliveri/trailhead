// Worker pool around the Python engine + in-browser plan refinement (cross-entropy search, same objective as the
// server's optimiser). Pure ES module, no dependencies.
export class Engine {
  constructor(n = Math.max(1, Math.min(6, (navigator.hardwareConcurrency || 4) - 1))) {
    this.n = n;
    this.workers = [];
    this.seq = 0;
    this.wait = new Map();
  }

  spawn(i) {
    const w = new Worker(new URL('./engine-worker.js', import.meta.url), { type: 'module' });
    w.onmessage = (e) => {
      const p = this.wait.get(e.data.id);
      if (!p) return;
      this.wait.delete(e.data.id);
      e.data.ok ? p.res(e.data.result) : p.rej(new Error(e.data.error));
    };
    w.onerror = (e) => console.error('engine worker', i, e.message);
    return w;
  }

  ask(i, fn, args) {
    const id = ++this.seq;
    return new Promise((res, rej) => {
      this.wait.set(id, { res, rej });
      this.workers[i].postMessage({ id, fn, args });
    });
  }

  // Start one worker now (for planning); the rest only when tuning needs them.
  async boot(count = 1, onEach) {
    const want = Math.min(count, this.n);
    const starts = [];
    for (let i = this.workers.length; i < want; i++) {
      this.workers.push(this.spawn(i));
      // one retry: the second start reuses whatever downloaded the first time
      starts.push(this.ask(i, '__boot').catch(() => this.ask(i, '__boot')).then(() => onEach && onEach(i)));
    }
    await Promise.all(starts);
  }

  async call(fn, args) {
    await this.boot(1);
    return this.ask(0, fn, args);
  }

  // Refine `start` (param array) on this runner's calendar for `seconds`. onProgress({frac, gen, best, eta}).
  async tune(state, start, seconds, onProgress, today) {
    await this.boot(this.n);
    const P = await this.ask(0, 'PARAMS_get');
    await Promise.all(this.workers.map((_, i) => this.ask(i, 'tune_context', { state, today })));
    const lo = P.lo, hi = P.hi, d = lo.length;
    const span = hi.map((h, j) => h - lo[j]);
    let mu = start.slice();
    let sd = span.map((s) => s * 0.08);
    const pop = 48 * this.n, k = 16, elite = Math.max(8, Math.round(pop / 10));
    const gauss = () => Math.sqrt(-2 * Math.log(1 - Math.random())) * Math.cos(2 * Math.PI * Math.random());
    const t0 = performance.now();
    let gen = 0, best = null;
    while ((performance.now() - t0) / 1000 < seconds) {
      const th = Array.from({ length: pop }, (_, r) => r === 0 ? mu.slice() :
        mu.map((m, j) => Math.min(hi[j], Math.max(lo[j], m + sd[j] * gauss()))));
      const seed = Math.floor(Math.random() * 2 ** 30);
      const per = Math.ceil(pop / this.n);
      const parts = await Promise.all(this.workers.map((_, i) =>
        this.ask(i, 'evaluate', { thetas: th.slice(i * per, (i + 1) * per), k, gen_seed: seed })));
      const obj = parts.flatMap((p) => p.obj), mean = parts.flatMap((p) => p.mean), pa = parts.flatMap((p) => p.hit_a);
      const order = obj.map((o, i) => [o, i]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
      const el = order.slice(0, elite).map((i) => th[i]);
      const m2 = Array.from({ length: d }, (_, j) => el.reduce((s, r) => s + r[j], 0) / el.length);
      const s2 = Array.from({ length: d }, (_, j) => Math.sqrt(el.reduce((s, r) => s + (r[j] - m2[j]) ** 2, 0) / el.length));
      mu = mu.map((m, j) => 0.7 * m2[j] + 0.3 * m);
      sd = sd.map((s, j) => Math.max(0.7 * s2[j] + 0.3 * s, span[j] * 0.005));
      gen++;
      best = { mean: mean[order[0]], pa: pa[order[0]] };
      const el_s = (performance.now() - t0) / 1000;
      onProgress && onProgress({ frac: Math.min(1, el_s / seconds), gen, best, eta: Math.max(0, seconds - el_s) + 8 });
    }
    // Out-of-sample check on fresh runners: keep the refined plan only if it beats the starting point.
    const cands = [mu, start];
    const val = await Promise.all(this.workers.map((_, i) =>
      this.ask(i, 'evaluate', { thetas: cands, k: 64, gen_seed: 900 + i })));
    const avg = (key, c) => val.reduce((s, v) => s + v[key][c], 0) / val.length;
    const win = avg('obj', 0) <= avg('obj', 1) ? 0 : 1;
    return {
      params: Object.fromEntries(P.names.map((n, j) => [n, Math.round(cands[win][j] * 1e4) / 1e4])),
      refined: win === 0, generations: gen,
      evidence: { mean: avg('mean', win), p_goal_a: avg('hit_a', win), start_mean: avg('mean', 1), start_p_goal_a: avg('hit_a', 1) },
    };
  }

  stopExtra() {   // free memory after tuning: keep worker 0 for planning
    this.workers.splice(1).forEach((w) => w.terminate());
  }
}
