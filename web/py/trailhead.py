"""Trailhead: the planning engine for anyone, run in the browser (Pyodide) or natively (precooking, tests).

Race plans (5 km, 10 km, half marathon, marathon) come from the simulation; Couch to 5K is a walk/run
progression (engine/c25k.py).

Everything specific to the original single-runner app in the shared engine (audiobooks, dated milestones, gym loads, race-specific notes,
phase-dated nutrition) is switched off here. Profiles come from the setup wizard; state is a plain dict the
browser keeps (and mirrors to the server under the plan's link) — never Garmin credentials.
"""
import datetime as dt
import json
import math
import os

import numpy as np

from engine import builder, c25k, device, distances, extras, nutrition, planner, run_learning
from engine import model as M
from engine import physiology as phys

DAYS = planner.DAYS

# --------------------------------------------------------------------------- de-personalise the shared engine

extras.BOOKS = []
extras.MILESTONES = []
builder.DEFAULT_LOADS = {}
builder.TIMING = {
    'long': 'Weekend morning, around your race start time. Rehearse breakfast 3 h before, fuel and toilet routine. '
            'Start earlier on hot days.',
    'easy': 'Whenever suits. Mornings are cooler and get it done.',
    'quality': 'Morning or late afternoon, whichever you feel better for. Finish 3 h+ before bed.',
    'xt': 'Any time. No impact and easy on sleep; keep it 2 h+ before bed.',
    'strength': 'Later on the same day as the run: hours apart limits interference and keeps the next day easy.',
    'event': 'Morning, like race day.',
    'recovery': 'Whenever suits. A lunchtime walk counts.',
}
RACE_TEXT = ()   # (engine phrase, replacement) pairs


def _localise(x, race, start):
    if isinstance(x, str):
        for a, b in RACE_TEXT:
            x = x.replace(a, b.replace('{RACE}', race.upper()).replace('{START}', start))
        return x
    if isinstance(x, list):
        return [_localise(v, race, start) for v in x]
    if isinstance(x, dict):
        return {k: _localise(v, race, start) for k, v in x.items()}
    return x


def _annotate(days, logs, program, today, today_logged=False):
    race = program.get('race', {}).get('name') or 'race day'
    start = program.get('race', {}).get('start_local') or 'race start'
    for w in days:
        w.update(_localise(dict(w), race, start))
        k = w['kind']
        if k in ('threshold', 'vo2', 'hills'):
            w['audio'] = {'kind': 'music', 'title': 'Music: something upbeat (170-180 BPM).',
                          'detail': 'Save your favourite track for the hardest rep.'}
        elif k in ('mp_run', 'tt5k', 'tt10k', 'half', 'race'):
            w['audio'] = {'kind': 'off', 'title': 'No audio',
                          'detail': f'Practise race pace the way you will run it at {race}.'}
        mins = int(w.get('minutes') or 0)
        if k in ('long', 'long_mp') and mins >= 70:
            w['mind'] = {'at_s': max(0, (mins - 25) * 60), 'cue': 'MIND: SELF-TALK',
                         'text': 'Last 25 minutes: short, positive phrases ("strong and smooth") when it gets hard.'}
    return days


extras.annotate = _annotate
nutrition.annotate = lambda days, program, logs: days


class MemStore:
    """The two read methods planner.plan needs, over the browser's logs and check-ins."""

    def __init__(self, logs=(), checkins=None):
        self._logs = sorted((dict(lg) for lg in logs if not lg.get('deleted')), key=lambda lg: (lg['date'], lg.get('time') or ''))
        self._ci = dict(checkins or {})

    def logs(self, since=None):
        return [lg for lg in self._logs if not since or lg['date'] >= since]

    def checkins(self):
        return self._ci


# --------------------------------------------------------------------------- profile -> program

def _d(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def estimate_vdot(profile):
    """Fitness (VDOT) from a recent race/time trial, else from comfortable easy pace, else a cautious default."""
    r = profile.get('recent') or {}
    km, mins = r.get('race_km'), r.get('race_min')
    if km and mins:
        return float(phys.vdot_from_race(float(km) * 1000, float(mins)))
    easy = profile.get('current', {}).get('easy_pace_s')   # sec/km on an easy run
    if easy:
        # Easy pace sits ~25-30 % slower than VDOT marathon pace: search the VDOT whose easy band matches.
        best, err = 30.0, 1e9
        for v in np.arange(20.0, 75.0, 0.25):
            p = phys.training_paces(float(v))['easy']
            mid = (p[0] + p[1]) / 2 if isinstance(p, (list, tuple)) else float(p)
            if abs(mid - easy) < err:
                best, err = float(v), abs(mid - easy)
        return best - 1.0   # easy pace overstates fitness slightly when untested
    return 32.0


def down_weeks(start, race, kind='marathon'):
    """A lighter week every fourth week, the last one ending before the taper."""
    mon = start + dt.timedelta(days=(7 - start.weekday()) % 7)
    out, wk = [], mon + dt.timedelta(days=21)
    clear = round(21 * distances.profile(kind)['taper_scale']) + 3
    while wk <= race - dt.timedelta(days=clear):
        out.append(wk.isoformat())
        wk += dt.timedelta(days=28)
    return out


def _goal_label(minutes):
    """h:mm for long races, m:ss under an hour."""
    return planner.goal_label(minutes) if minutes >= 60 else phys.fmt_hms(minutes)


def make_program(profile, today=None):
    today = _d(today or dt.date.today())
    a = profile.get('athlete', {})
    age = int(a.get('age') or 35)
    race = dict(profile['race'])
    kind = distances.key_of({'race': race})
    if kind == 'c25k' and not race.get('date'):
        race['date'] = (today + dt.timedelta(weeks=c25k.WEEKS)).isoformat()
    rdate = _d(race['date'])
    dp = distances.profile(kind)
    goal = float(race.get('goal_min') or 0) or None
    vdot = estimate_vdot(profile)
    if kind == 'c25k':
        goal = None
    elif not goal:   # no goal given: the realistic finish from current fitness, rounded
        r = dp['goal_round']
        goal = math.ceil(float(phys.race_time(dp['km'] * 1000, vdot + 2.0)) / r) * r
    av = {}
    for d in DAYS:
        x = (profile.get('availability') or {}).get(d) or {}
        prim = int(x.get('primary') or 0)
        av[d] = {'primary': prim, 'total': max(prim, int(x.get('total') or prim)),
                 'slot': x.get('slot') or ('08:00' if d in ('sat', 'sun') else '06:30'),
                 'slot2': x.get('slot2') or '17:30'}
    hr_max = float(a.get('hr_max') or round(208 - 0.7 * age))
    hr_rest = float(a.get('hr_rest') or 60)
    weight = float(a.get('weight_kg') or 72)
    program = {
        'about': 'Trailhead plan (garmin.ttnt.cloud).',
        'athlete': {'name': a.get('name') or 'Runner', 'age': age, 'sex': a.get('sex') or 'X',
                    'height_cm': float(a.get('height_cm') or 172), 'weight_kg': weight,
                    'target_weight_kg': weight, 'hr_max': hr_max, 'hr_rest': hr_rest, 'ferritin': 100},
        'race': {'name': race.get('name') or ('Couch to 5K' if kind == 'c25k' else dp['label']), 'date': rdate.isoformat(),
                 'distance': kind, 'start_local': race.get('start_local') or '07:00',
                 **({'goal_a_min': goal, 'goal_b_min': goal + dp['goal_b'],
                     'goal': f"A: {_goal_label(goal)} · B: {_goal_label(goal + dp['goal_b'])}"} if goal else {})},
        'timezone': profile.get('tz') or 'UTC',
        'plan_start': today.isoformat(),
        'availability': av,
        'events': {},
        'reminders': {'evening_preview': '20:00', 'session_lead_min': 20, 'log_nudge': '20:30',
                      'lights_out_lead_min': 30, 'quiet_after': '21:30'},
        'baseline': {'vdot_base': round(vdot, 1), 'fer': 100.0, 'ds_hard': 7, 'ds_long': 7, 'ds_sl': 7, 'ds_su': 7,
                     'vdot_sd': 0.8 if (profile.get('recent') or {}).get('race_min') else 1.6, 'ret_ref': 35},
        'down_weeks': [] if kind == 'c25k' else down_weeks(today, rdate, kind),
        'strength': {'upper': bool((profile.get('strength') or {}).get('upper', False))},
    }
    return program


def history_logs(profile, today=None):
    """Synthetic logs of the last 8 weeks from what the runner told us (replaced by real Garmin activities)."""
    today = _d(today or dt.date.today())
    cur = profile.get('current') or {}
    runs = int(cur.get('runs_per_week') or 0)
    easy = float(cur.get('easy_min') or 30)
    long_ = float(cur.get('long_min') or easy)
    weeks = int(min(8, cur.get('weeks_running') or 8))
    vdot = estimate_vdot(profile)
    pace = phys.training_paces(vdot)['easy']
    pace = (pace[0] + pace[1]) / 2 if isinstance(pace, (list, tuple)) else float(pace)
    logs = []
    # spread runs across the week: long run on Sunday, the rest on alternate days
    slots = {1: [6], 2: [2, 6], 3: [1, 3, 6], 4: [1, 3, 4, 6], 5: [0, 1, 3, 4, 6], 6: [0, 1, 2, 3, 4, 6],
             7: list(range(7))}.get(min(runs, 7), [])
    start = today - dt.timedelta(days=today.weekday() + 7 * weeks)
    for w in range(weeks):
        for i, wd in enumerate(slots):
            d = start + dt.timedelta(days=7 * w + wd)
            if d >= today:
                continue
            mins = long_ if wd == 6 and runs > 1 else easy
            logs.append({'id': f'hist-{d}', 'client_id': f'hist-{d}', 'kind': 'run', 'date': d.isoformat(),
                         'time': '07:00', 'duration_min': mins, 'distance_km': round(mins * 60 / pace, 2),
                         'run_type': 'long' if mins >= 80 else 'easy', 'source': 'history'})
    r = profile.get('recent') or {}
    if r.get('race_km') and r.get('race_min'):
        d = _d(r.get('date') or (today - dt.timedelta(days=14)))
        d = min(d, today - dt.timedelta(days=1))
        logs = [lg for lg in logs if lg['date'] != d.isoformat()]
        logs.append({'id': f'race-{d}', 'client_id': f'race-{d}', 'kind': 'run', 'date': d.isoformat(), 'time': '08:00',
                     'duration_min': float(r['race_min']), 'distance_km': float(r['race_km']), 'run_type': 'race',
                     'race_km': float(r['race_km']), 'race_min': float(r['race_min']), 'rpe': 9, 'source': 'history'})
    return logs


def _program(state, today):
    program = json.loads(json.dumps(state['program']))
    M.configure(distances.key_of(program))
    policy = state.get('policy') or {}
    program['_policy'] = {**{n: float(M.P_DEFAULT[i]) for i, n in enumerate(M.PARAM_NAMES)}, **policy}
    program['_race'] = _d(program['race']['date'])
    program['_start'] = _d(program['plan_start'])
    program['_horizon'] = (program['_race'] - program['_start']).days
    return program


def is_c25k(state):
    return distances.key_of(state.get('program') or {'race': (state.get('profile') or {}).get('race')}) == 'c25k'


def new_state(profile, today=None):
    today = _d(today or dt.date.today())
    program = make_program(profile, today)
    logs = [] if distances.key_of(program) == 'c25k' else history_logs(profile, today)
    return {'v': 1, 'profile': profile, 'program': program,
            'logs': logs, 'checkins': {}, 'policy': None, 'created': today.isoformat()}


# --------------------------------------------------------------------------- optimiser (shared by browser + precook)

PARAMS = {'names': list(M.PARAM_NAMES), 'lo': [float(x) for x in M.P_LO], 'hi': [float(x) for x in M.P_HI],
          'default': [float(x) for x in M.P_DEFAULT]}
SOFT_MIN = 3.0
_CTX = {}


def tune_context(state, today=None):
    """Prepare the simulation inputs once per worker. Returns the goals (minutes)."""
    today = _d(today or dt.date.today())
    program = _program(state, today)
    store = MemStore(state.get('logs', []), state.get('checkins'))
    s, base_lv, _ = planner.replay(program, store.logs(), store.checkins(), today)
    planner.rebase(s, base_lv)
    cal = M.calendar(today, program['_race'], planner.availability(program), program.get('events', {}),
                     program.get('down_weeks', []), overrides=planner.overrides(program))
    _CTX.update(cal=cal, seed=s, wr=planner.weight_ratio(program, today), dist=M.DIST,
                vdot_sd=float(program['baseline'].get('vdot_sd', 1.0)), goals=planner.goals(program))
    return list(_CTX['goals'])


def _soft(t, goal, soft=SOFT_MIN):
    return 1.0 / (1.0 + np.exp(np.clip((t - goal) / soft, -50, 50)))


def evaluate(thetas, k, gen_seed):
    """Score plan versions (rows of thetas) on the same k simulated runners. Returns per-version arrays."""
    M.configure(_CTX['dist'])
    thetas = np.asarray(thetas, np.float32).reshape(-1, len(M.PARAM_NAMES))
    n = thetas.shape[0]
    rng = np.random.default_rng(int(gen_seed))
    athletes = M.sample_population(_CTX['seed'], int(k), rng, vdot_sd=_CTX['vdot_sd'])
    init = {key: (np.tile(v, (n,) + (1,) * (v.ndim - 1)) if isinstance(v, np.ndarray) else v) for key, v in athletes.items()}
    P = M.params_from_matrix(np.repeat(thetas, int(k), axis=0))
    res = M.simulate(P, init, _CTX['cal'], np.random.default_rng(int(gen_seed) + 1), weight_ratio=_CTX['wr'], crn_block=int(k))
    t = res['time'].reshape(n, k)
    ga, gb = _CTX['goals']
    linj = (res['long_injuries'] > 0).reshape(n, k)
    soft = M.D['soft_min']
    mean_t, pa, pb, pinj = t.mean(1), _soft(t, ga, soft).mean(1), _soft(t, gb, soft).mean(1), linj.mean(1)
    obj = -(pa + 0.5 * pb) + 0.25 * pinj + 0.002 * mean_t * (42.195 / M.D['km'])
    return {'obj': obj.tolist(), 'mean': mean_t.tolist(), 'pa': pa.tolist(), 'pb': pb.tolist(), 'inj': pinj.tolist(),
            'hit_a': (t < ga).mean(1).tolist(), 'hit_b': (t < gb).mean(1).tolist()}


# --------------------------------------------------------------------------- precooked starting points

def features(state, today=None):
    today = _d(today or dt.date.today())
    p = state['program']
    weeks = (_d(p['race']['date']) - today).days / 7
    days = sum(1 for d in DAYS if p['availability'][d]['primary'] > 0)
    return {'weeks': weeks, 'vdot': float(p['baseline']['vdot_base']), 'days': days, 'distance': distances.key_of(p)}


def nearest_precooked(state, table, today=None):
    f = features(state, today)
    best, bd = None, 1e9
    for row in table:
        g = row['features']
        if g.get('distance', 'marathon') != f['distance']:
            continue
        dist = ((f['weeks'] - g['weeks']) / 6) ** 2 + ((f['vdot'] - g['vdot']) / 5) ** 2 + ((f['days'] - g['days']) / 1.5) ** 2
        if dist < bd:
            best, bd = row, dist
    return best


# --------------------------------------------------------------------------- plan, prediction, watch bundle

def plan(state, today=None, n_days=21, full=False):
    today = _d(today or dt.date.today())
    program = _program(state, today)
    if is_c25k(state):
        return program, c25k.plan(program, MemStore(state.get('logs', [])).logs(), today, n_days=n_days, full=full)
    store = MemStore(state.get('logs', []), state.get('checkins'))
    res = planner.plan(program, store, today, n_days=n_days, full=full)
    return program, res


def predict(state, today=None, n=400):
    today = _d(today or dt.date.today())
    program = _program(state, today)
    if is_c25k(state):
        return None
    store = MemStore(state.get('logs', []), state.get('checkins'))
    s, base_lv, _ = planner.replay(program, store.logs(), store.checkins(), today)
    planner.rebase(s, base_lv)
    rng = np.random.default_rng(11)
    pop = M.sample_population(s, n, rng, vdot_sd=float(program['baseline'].get('vdot_sd', 1.0)), fer_sd=15.0)
    cal = M.calendar(today, program['_race'], planner.availability(program), program.get('events', {}),
                     program.get('down_weeks', []), overrides=planner.overrides(program))
    P = M.params_from_dict(program['_policy'], n)
    r = M.simulate(P, pop, cal, rng, weight_ratio=planner.weight_ratio(program, today))
    t = r['time'][~r['dns']]
    a, b = planner.goals(program)
    return {'p10': float(np.percentile(t, 10)), 'p50': float(np.percentile(t, 50)), 'p90': float(np.percentile(t, 90)),
            'p_goal_a': float((r['time'] < a).mean()), 'p_goal_b': float((r['time'] < b).mean()),
            'goal_a': a, 'goal_b': b, 'injury_rate': float((r['injuries'] > 0).mean()), 'dns': float(r['dns'].mean())}


def _clean(x):
    """JSON-safe copy (dates, numpy scalars)."""
    return json.loads(json.dumps(x, default=lambda o: o.isoformat() if hasattr(o, 'isoformat') else
                                 (o.item() if hasattr(o, 'item') else str(o))))


def watch_bundle(program, days, pred=None, fade=None, vdot=None):
    """Per-date watch payloads (same shape as /api/device/sync); the server picks today's and fills live bits."""
    out = {}
    by = {d['date']: d for d in days}
    race = program['_race']
    fade = run_learning.second_half_fade([], 0) if fade is None else fade
    for i, w0 in enumerate(days):
        day = _d(w0['date'])
        av = planner.slots_for(program, day)
        tasks = []
        if w0['kind'] != 'rest' and w0.get('steps'):
            tasks.append({'p': 'run', 't': w0['title'][:26], 'at': av['slot'], 'd': False,
                          'want': {'cycling': 'bike', 'walking': 'walk'}.get(w0.get('sport'), 'run')})
        sec = w0.get('secondary')
        if sec and sec.get('items'):
            tasks.append({'p': 'sec', 't': sec['title'][:26], 'at': av.get('slot2', '17:30') if tasks else av['slot'],
                          'd': False, 'want': 'mobility' if sec['kind'] == 'mobility' else 'strength'})
        mon = day - dt.timedelta(days=day.weekday())
        wk = []
        for j in range(7):
            pl = by.get((mon + dt.timedelta(days=j)).isoformat()) or {}
            wk.append({'d': 0, 'k': (pl.get('kind') or 'rest')[:8], 'm': int(pl.get('minutes') or 0)})
        tmr = days[i + 1] if i + 1 < len(days) else None
        mins = int(w0.get('minutes') or 0)
        out[w0['date']] = {
            'tot': program['_horizon'], 'rd': None, 'tasks': tasks, 'wk': wk, 'km_d': 0.0,
            'km_p': round(sum(float((by.get((mon + dt.timedelta(days=j)).isoformat()) or {}).get('km') or 0) for j in range(7)), 1),
            'pred': phys.fmt_hms(pred['p50']) if pred else '',
            'cd': (race - day).days, 'race': (program['race'].get('name') or 'Race')[:12],
            'today': device.compact(w0, fade=fade if mins >= 45 else 0.0),
            'done': False,
            'tmr': {'t': tmr['title'][:28], 'm': int(tmr.get('minutes') or 0), 'k': tmr['kind']} if tmr else None,
            'vdot': vdot, 'hrmax': int(program['athlete']['hr_max']), 'hrrest': int(program['athlete']['hr_rest']), 'cp': None,
            'preview': ({'title': 'Tomorrow', 'sub': tmr['title'][:28],
                         'body': 'Rest day' if tmr['kind'] == 'rest' else f"{tmr.get('minutes')} min at "
                         f"{planner.slots_for(program, _d(tmr['date']))['slot']}", 'act': 0} if tmr else None),
        }
    return _clean(out)


def refresh(state, today=None, n_days=21):
    """Everything the web app shows and the watch needs, in one call (JSON string in, JSON-able dict out)."""
    today = _d(today or dt.date.today())
    program, res = plan(state, today, n_days=n_days)
    days = res['days']
    if is_c25k(state):
        return _clean({'days': days, 'weeks': res['weeks'], 'vdot': None, 'prediction': None, 'paces': {},
                       'progress': res['progress'], 'bundle': watch_bundle(program, days),
                       'generated_for': today.isoformat(), 'race': program['race'], 'athlete': program['athlete']})
    pred = predict(state, today)
    return _clean({'days': days, 'weeks': res['weeks'], 'vdot': res['vdot'], 'prediction': pred,
                   'paces': phys.training_paces(res['vdot']), 'bundle': watch_bundle(program, days, pred, vdot=res['vdot']),
                   'generated_for': today.isoformat(), 'race': program['race'], 'athlete': program['athlete']})


def season(state, today=None):
    today = _d(today or dt.date.today())
    program = _program(state, today)
    n = (program['_race'] - today).days + 1
    _, res = plan(state, today, n_days=n, full=True)
    return _clean({'days': res['days'], 'weeks': res['weeks']})


# --------------------------------------------------------------------------- Garmin activities -> logs

GARMIN_KIND = {'running': 'run', 'trail_running': 'trail', 'treadmill_running': 'treadmill', 'track_running': 'run',
               'street_running': 'run', 'cycling': 'bike', 'indoor_cycling': 'bike', 'road_biking': 'bike',
               'mountain_biking': 'bike', 'virtual_ride': 'bike', 'walking': 'walk', 'hiking': 'hike',
               'elliptical': 'elliptical', 'indoor_rowing': 'row', 'rowing': 'row', 'lap_swimming': 'swim',
               'open_water_swimming': 'swim', 'strength_training': 'strength', 'yoga': 'mobility',
               'pilates': 'mobility'}


def garmin_logs(activities):
    """Garmin Connect activity summaries -> log entries (same fields the engine's logs use)."""
    out = []
    for a in activities or []:
        if not a.get('activityId') or not a.get('startTimeLocal'):
            continue
        tk = (a.get('activityType') or {}).get('typeKey', 'other')
        start = dt.datetime.strptime(a['startTimeLocal'][:19], '%Y-%m-%d %H:%M:%S')
        e = {'id': f"garmin-{a['activityId']}", 'client_id': f"garmin-{a['activityId']}",
             'kind': GARMIN_KIND.get(tk, 'other'), 'date': start.date().isoformat(), 'time': start.strftime('%H:%M'),
             'duration_min': round(float(a.get('duration') or 0) / 60, 1), 'source': 'garmin-connect',
             'title': a.get('activityName')}
        if a.get('distance'):
            e['distance_km'] = round(float(a['distance']) / 1000, 2)
        for src, dst in (('averageHR', 'avg_hr'), ('maxHR', 'max_hr'), ('elevationGain', 'elevation_m')):
            if a.get(src):
                e[dst] = round(float(a[src]), 1)
        out.append(e)
    return out


def merge_logs(state, new):
    """Add logs not already present (by client_id), dropping synthetic history that real activities replace."""
    logs = state.get('logs', [])
    have = {lg.get('client_id') for lg in logs}
    added = [lg for lg in new if lg.get('client_id') not in have]
    if any(lg.get('source') in ('garmin-connect', 'garmin-watch') for lg in added):
        real_days = {lg['date'] for lg in logs + added if lg.get('source') in ('garmin-connect', 'garmin-watch')}
        first_real = min(real_days) if real_days else None
        logs = [lg for lg in logs if not (lg.get('source') == 'history' and lg.get('run_type') != 'race'
                                          and first_real and lg['date'] >= first_real)]
    state['logs'] = logs + added
    return len(added)


def merge_into(state, logs):
    added = merge_logs(state, logs)
    return {'state': state, 'added': added}


def watch_log(state, a, tz_offset_min=0):
    """A Trailhead Coach watch upload -> log (merged with an existing upload of the same session)."""
    zone = dt.timezone(dt.timedelta(minutes=tz_offset_min))
    lg = device.activity_to_log(a, zone, None)
    lg.setdefault('id', lg.get('client_id'))
    for old in state.get('logs', []):
        if old.get('client_id') == lg.get('client_id'):
            for k in ('rpe', 'feel'):
                if lg.get(k) is not None and old.get(k) is None:
                    old[k] = lg[k]
            return 0
    state.setdefault('logs', []).append(lg)
    return 1


def PARAMS_get():
    return PARAMS


def watch_log_state(state, a, tz_offset_min=0):
    watch_log(state, a, tz_offset_min)
    return {'state': state}


def call(fn, payload):
    """Pyodide entry point: JSON in, JSON out (keeps the JS<->Python boundary simple and stable)."""
    args = json.loads(payload or 'null') or {}
    out = globals()[fn](**args)
    return json.dumps(_clean(out))
