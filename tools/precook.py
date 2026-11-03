#!/usr/bin/env python3
"""Precook starting policies over a grid of runner profiles (cross-entropy search, all cores).

The browser starts from the nearest row and refines for a couple of minutes on the runner's real calendar.
    python3 tools/precook.py --seconds 70          # ~1 h for the full grid on 9 cores
Writes web/py/precooked.json (rows: features, params, evidence).
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'web', 'py'))
import trailhead as T  # noqa: E402
from engine import physiology as phys  # noqa: E402

WEEKS = (10, 16, 24, 34)
VDOT = (30, 36, 42, 50)
DAYS = (3, 4, 6)
LAYOUT = {3: ('tue', 'thu', 'sun'), 4: ('tue', 'wed', 'thu', 'sun'), 6: ('mon', 'tue', 'wed', 'thu', 'sat', 'sun')}


def profile(weeks, vdot, days, today):
    av = {d: {'primary': 0} for d in T.DAYS}
    for d in LAYOUT[days]:
        av[d] = {'primary': 150 if d in ('sat', 'sun') else 60, 'total': 180 if d in ('sat', 'sun') else 80}
    ten_k = float(phys.race_time(10000, vdot))
    goal = round(float(phys.race_time(phys.MARATHON_M, vdot + 2)) / 5) * 5
    runs = max(2, days - 1)
    return {'athlete': {'age': 38, 'weight_kg': 70, 'hr_max': 185, 'hr_rest': 55},
            'race': {'name': 'Marathon', 'date': (today + dt.timedelta(weeks=weeks)).isoformat(), 'goal_min': goal},
            'recent': {'race_km': 10, 'race_min': round(ten_k, 1), 'date': (today - dt.timedelta(days=10)).isoformat()},
            'current': {'runs_per_week': runs, 'easy_min': 30 + vdot - 30, 'long_min': 50 + (vdot - 30) * 2, 'weeks_running': 8},
            'availability': av}


_STATE = {}


def _init(state, today):
    _STATE['state'] = state
    T.tune_context(state, today)


def _eval(args):
    return T.evaluate(*args)


def tune(state, today, seconds, pop, k, workers, mu=None, seed=7):
    span = np.array(T.PARAMS['hi']) - np.array(T.PARAMS['lo'])
    lo, hi = np.array(T.PARAMS['lo']), np.array(T.PARAMS['hi'])
    mu = np.array(mu if mu is not None else T.PARAMS['default'], np.float32)
    sd = span * 0.3
    rng = np.random.default_rng(seed)
    n_elite = max(8, pop // 10)
    t0, gen = time.time(), 0
    with ProcessPoolExecutor(workers, mp_context=get_context('fork'), initializer=_init, initargs=(state, today)) as pool:
        while time.time() - t0 < seconds:
            th = np.clip(mu + sd * rng.standard_normal((pop, len(mu))), lo, hi).astype(np.float32)
            th[0] = mu
            gs = int(rng.integers(1 << 30))
            parts = list(pool.map(_eval, [(c.tolist(), k, gs) for c in np.array_split(th, workers * 2) if len(c)]))
            obj = np.concatenate([p['obj'] for p in parts])
            el = th[np.argsort(obj)[:n_elite]]
            mu = 0.7 * el.mean(0) + 0.3 * mu
            sd = np.maximum(0.7 * el.std(0) + 0.3 * sd, span * 0.01)
            gen += 1
        val = [pool.submit(_eval, ([mu.tolist(), T.PARAMS['default']], 128, 900 + j)) for j in range(workers)]
        res = [v.result() for v in val]
    keys = ('obj', 'mean', 'hit_a', 'hit_b', 'inj')
    ev = {key: np.mean([r[key] for r in res], 0).tolist() for key in keys}
    best = mu if ev['obj'][0] <= ev['obj'][1] else np.array(T.PARAMS['default'])
    return best, gen, ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seconds', type=float, default=70)
    ap.add_argument('--pop', type=int, default=512)
    ap.add_argument('--k', type=int, default=24)
    ap.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()
    today = dt.date.today()
    out_path = os.path.join(ROOT, 'web', 'py', 'precooked.json')
    rows = []
    grid = [(w, v, d) for w in WEEKS for v in VDOT for d in DAYS][: a.limit or None]
    for i, (w, v, d) in enumerate(grid):
        st = T.new_state(profile(w, v, d, today), today)
        theta, gen, ev = tune(st, today, a.seconds, a.pop, a.k, a.workers)
        f = T.features(st, today)
        rows.append({'features': f, 'params': {n: round(float(x), 4) for n, x in zip(T.PARAMS['names'], theta)},
                     'evidence': {'generations': gen, 'mean_min': round(ev['mean'][0], 1), 'default_mean_min': round(ev['mean'][1], 1),
                                  'p_goal_a': round(ev['hit_a'][0], 3), 'default_p_goal_a': round(ev['hit_a'][1], 3),
                                  'inj14': round(ev['inj'][0], 3)}})
        print(f"[{i + 1}/{len(grid)}] weeks {w} vdot {v} days {d}: {gen} gens, mean {ev['mean'][0]:.1f} "
              f"(default {ev['mean'][1]:.1f}), P(A) {ev['hit_a'][0]:.0%} (default {ev['hit_a'][1]:.0%})", flush=True)
        json.dump({'generated': dt.datetime.now().isoformat(timespec='seconds'), 'rows': rows}, open(out_path, 'w'), indent=1)


if __name__ == '__main__':
    main()
