"""Glue between real logs and the model: replay -> today's state -> day-by-day plan.

Nothing here is week-based. Every request replays what actually happened, then
asks the policy what the best session is for each coming day given the body's
current state (muscle fatigue, impact load, fitness qualities, readiness).
"""
import copy
import datetime as dt
import json
import os
import statistics

import numpy as np

from . import builder, extras, nutrition
from . import model as M
from . import physiology as phys
from . import run_learning
from .catalog import ACTIVITIES, EXERCISES, MUSCLES, MUSCLE_LABELS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAM = os.path.join(ROOT, 'config', 'program.json')
POLICY = os.path.join(ROOT, 'config', 'policy.json')
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
QUALITY_LABELS = {'aero': 'Aerobic engine', 'thr': 'Threshold', 'vo2': 'VO2 ceiling', 'nm': 'Economy & power',
                  'dur': 'Durability', 'mp': 'Race-specific'}
LEVEL_LABELS = {'A': 'Aerobic engine', 'T': 'Threshold', 'V': 'VO2 ceiling', 'N': 'Economy & power',
                'D': 'Durability', 'M': 'Race-specific'}
RUN_TYPE_DEFAULT_RPE = {'easy': 3, 'recovery': 2, 'long': 4, 'strides': 4, 'tempo': 7, 'intervals': 8, 'hills': 8,
                        'marathon_pace': 6, 'race': 9}


def load_program():
    with open(PROGRAM) as fh:
        program = json.load(fh)
    policy = {}
    if os.path.exists(POLICY):
        with open(POLICY) as fh:
            policy = json.load(fh).get('params', {})
    program['_policy'] = {**{n: float(M.P_DEFAULT[i]) for i, n in enumerate(M.PARAM_NAMES)}, **policy}
    race = dt.date.fromisoformat(program['race']['date'])
    program['_race'] = race
    program['_start'] = dt.date.fromisoformat(program['plan_start'])
    program['_horizon'] = (race - program['_start']).days
    return program


def save_program(program):
    clean = {k: v for k, v in program.items() if not k.startswith('_')}
    tmp = PROGRAM + '.new'
    with open(tmp, 'w') as fh:
        json.dump(clean, fh, indent=2)
    os.replace(tmp, PROGRAM)


def mtimes():
    return tuple(os.path.getmtime(p) if os.path.exists(p) else 0 for p in (PROGRAM, POLICY))


def no_upper(program):
    """Upper-body strength switched off (`strength.upper: false`)."""
    return (program.get('strength') or {}).get('upper') is False


def availability(program):
    av = program['availability']
    nu = no_upper(program)
    return {i: (av[d]['primary'], av[d]['total'], nu) for i, d in enumerate(DAYS)}


def overrides(program):
    """Travel slots, moved days and explicitly selected rest days, shared by every simulation."""
    travel = program.get('travel') or {}
    nu = no_upper(program)
    trip_nu = nu or travel.get('upper') is False   # minimal holiday block: running + legs only
    slots = {d: (float(v[0]), float(v[1]), trip_nu) for d, v in (travel.get('days') or {}).items()}
    slots.update({d: (float(v['primary']), float(v['total']), nu) for d, v in program.get('day_slots', {}).items()})
    slots.update({d: (0.0, 0.0, nu) for d in program.get('rest_days', {})})
    return slots


travel_day = extras.travel_day


def slots_for(program, date):
    """Availability for a date: the weekday default, or the travel day (local start time and timezone)."""
    base = dict(program['availability'][DAYS[date.weekday()]])
    moved = program.get('day_slots', {}).get(date.isoformat())
    if moved:
        base.update({k: v for k, v in moved.items() if k in ('primary', 'total', 'slot', 'slot2')})
    t = travel_day(program, date)
    if t:
        base.update(primary=t['primary'], total=t['total'], slot=t['slot'], slot2='16:00', tz=t['tz'], place=t['stay'].get('place'))
    return base


def weight_ratio(program, on=None):
    ath = program['athlete']
    now_w = float(ath['weight_kg'])
    target = float(ath.get('target_weight_kg') or now_w)
    weeks = max(0.0, ((program['_race'] - (on or dt.date.today())).days) / 7)
    race_w = max(target, now_w - 0.25 * weeks)
    return now_w / race_w


# ----------------------------------------------------------------------------- logs -> stimulus

def _num(x, default=None):
    try:
        return float(x) if x not in (None, '') else default
    except (TypeError, ValueError):
        return default


def stim_from_log(log, program):
    """Model stimulus (N=1) for one logged activity."""
    st = M.empty_stim(1)
    kind = log.get('kind', 'other')
    act = ACTIVITIES.get(kind, ACTIVITIES['other'])
    minutes = _num(log.get('duration_min'), 0.0)
    if minutes <= 0:  # a logged rest/skipped day: no load, counts as a recovery day
        st['low'][:] = 1
        return st
    run_type = log.get('run_type') or ('long' if act.get('is_run') and minutes >= 80 else 'easy')
    rpe = _num(log.get('rpe'))
    if rpe is None:
        rpe = RUN_TYPE_DEFAULT_RPE.get(run_type, act['rpe']) if act.get('is_run') else act['rpe']
    intensity = 0.4 + 0.18 * rpe
    em = minutes * intensity
    is_run = bool(act.get('is_run'))
    speed = 1.0
    dist = _num(log.get('distance_km'))
    if is_run and dist:
        v = dist * 1000 / minutes
        speed = float(np.clip(v / 140.0, 0.8, 1.5))
    st['minutes'][:] = minutes
    st['sys'][:] = em * (0.75 if kind == 'strength' else 1.0) * act.get('load', 1.0)
    st['aero'][:] = em * act['transfer']
    st['impact'][:] = minutes * act['impact'] * speed
    run_min = minutes if is_run else 0.0
    st['run_min'][:] = run_min
    st['longest'][:] = run_min
    work = log.get('work') or {}
    thr = _num(work.get('thr_min'))
    vo2 = _num(work.get('vo2_min'))
    mp = _num(work.get('mp_min'))
    nm = _num(work.get('nm'))
    if is_run:
        if run_type == 'tempo':
            thr = thr if thr is not None else 0.55 * minutes
        elif run_type == 'intervals':
            vo2 = vo2 if vo2 is not None else 0.35 * minutes
            thr = thr if thr is not None else 0.1 * minutes
        elif run_type == 'hills':
            vo2 = vo2 if vo2 is not None else 0.12 * minutes
            nm = nm if nm is not None else 0.6
        elif run_type == 'marathon_pace':
            mp = mp if mp is not None else 0.65 * minutes
            thr = thr if thr is not None else 0.4 * mp
        elif run_type == 'strides':
            nm = nm if nm is not None else 0.3
        elif run_type == 'race':
            d = dist or minutes / 6
            thr = thr if thr is not None else minutes * (0.5 if d <= 10.5 else 0.35)
            vo2 = vo2 if vo2 is not None else minutes * (0.5 if d <= 5.5 else 0.05 if d > 20 else 0.2)
            mp = mp if mp is not None else (minutes * 0.5 if d > 20 else 0)
    elif kind in ('bike', 'elliptical', 'row', 'swim') and rpe >= 7:
        # Hard cross-training only counts as VO2 work when the heart rate got there (>= ~88 % HRmax);
        # below that it is threshold work.
        hr = _num(log.get('avg_hr'))
        top = hr is None or hr >= 0.80 * float(program['athlete']['hr_max'])  # avg incl. recoveries
        vo2 = vo2 if vo2 is not None else (0.25 * minutes * 0.8 if top else 0.0)
        thr = thr if thr is not None else (0.15 * minutes * 0.6 if top else 0.3 * minutes * 0.6)
    st['thr'][:] = thr or 0
    st['vo2'][:] = vo2 or 0
    st['mp'][:] = mp or 0
    long_flag = is_run and (run_type in ('long', 'race') and minutes >= 45 or minutes >= 80)
    st['dur'][:] = 0.3 * run_min + max(0.0, run_min - 50) * (1.0 if long_flag else 0.5)
    st['hard'][:] = float(rpe >= 7 or run_type in ('tempo', 'intervals', 'hills', 'marathon_pace', 'race') or long_flag)
    st['is_long'][:] = float(long_flag)
    st['low'][:] = float(kind in ('walk', 'mobility', 'sauna', 'cold') or rpe <= 2)
    # muscles
    mload = np.zeros(M.NM, np.float32)
    slow = np.zeros(M.NM, np.float32)
    nm_total = nm or 0.0
    if kind == 'strength':
        exercises = log.get('exercises') or []
        lower = upper = 0
        for ex in exercises:
            info = EXERCISES.get(ex.get('name'))
            sets = _num(ex.get('sets'), 3)
            if not info:
                continue
            per = 5.0 * sets * intensity / 1.5
            for m, share in info['m'].items():
                mload[M.MI[m]] += per * share
                slow[M.MI[m]] += per * share * info['ecc']
            nm_total += info['economy'] * sets / 9.0
            if info['economy'] >= 0.5:
                lower += sets
            else:
                upper += sets
            st['impact'] += info.get('impact', 0) * sets
        if not exercises:
            focus = log.get('focus', 'full')
            share = {'lower': M.SH_SL, 'upper': M.SH_SU}.get(focus, (M.SH_SL + M.SH_SU) / 2)
            mload += share * em
            slow += share * em * 1.4
            nm_total += 1.0 if focus == 'lower' else 0.1 if focus == 'upper' else 0.6
            lower = 9 if focus in ('lower', 'full') else 0
            upper = 9 if focus in ('upper', 'full') else 0
        st['sl'][:] = float(lower >= 5)
        st['su'][:] = float(upper >= 5)
        st['low'][:] = 0
    else:
        shares = np.zeros(M.NM, np.float32)
        for m, x in act['muscles'].items():
            shares[M.MI[m]] = x
        ecc = act['ecc'] * (1.2 if long_flag else 1.0) * (1.3 if run_type == 'hills' else 1.0)
        mload += shares * em
        slow += shares * em * ecc
    st['nm'][:] = nm_total
    st['mload'][0] = mload
    st['slow_load'][0] = slow
    return st


def merge_stims(stims):
    out = M.empty_stim(1)
    for st in stims:
        for k, v in st.items():
            if k in ('longest',):
                out[k] = np.maximum(out[k], v)
            elif k in ('hard', 'is_long', 'sl', 'su'):
                out[k] = np.maximum(out[k], v)
            elif k == 'low':
                continue
            else:
                out[k] = out[k] + v
    out['low'][:] = float(all(float(st['low'][0]) > 0 for st in stims)) if stims else 1.0
    return out


# ----------------------------------------------------------------------------- replay

SORENESS_LEVEL = {1: 0.45, 2: 0.75, 3: 1.05}
LOWER_AREAS = {'foot', 'ankle', 'achilles', 'calf', 'shin', 'knee', 'hamstring', 'quad', 'hip', 'glute', 'groin', 'it_band'}


def apply_body_report(s, report):
    """Soreness (0-3 per muscle) and pain flags override the model's estimate."""
    if not report:
        return
    ml = M.muscle_level(s)
    cap = 35.0 + 3.0 * s['m_chronic']
    for m, v in (report.get('soreness') or {}).items():
        v = int(v or 0)
        if m in M.MI and v in SORENESS_LEVEL:
            i = M.MI[m]
            target = SORENESS_LEVEL[v]
            if ml[0, i] < target:
                need = (target * cap[0, i] - 0.4 * s['mf_fast'][0, i]) / 0.6
                s['mf_slow'][0, i] = max(s['mf_slow'][0, i], need)
    pain = report.get('pain') or {}
    if any(int(sev or 0) >= 2 and area in LOWER_AREAS for area, sev in pain.items()):
        s['injured'][:] = np.maximum(s['injured'], 2)
    if report.get('sick'):
        s['sick'][:] = np.maximum(s['sick'], 1)


def baseline_state(program):
    return M.new_state(1, program['baseline'])


HISTORY_DAYS = 366   # logs older than this before plan start are ignored (and rejected on input)


def replay(program, logs, checkins, until):
    """State at the start of `until` (logs before that day applied)."""
    s = baseline_state(program)
    base_lv = {k: v.copy() for k, v in M.levels(s).items()}
    by_day = {}
    for lg in logs:
        by_day.setdefault(lg['date'], []).append(lg)
    start = program['_start']
    first_log = min((dt.date.fromisoformat(d) for d in by_day), default=start)
    day = max(min(start, first_log), start - dt.timedelta(days=HISTORY_DAYS))
    timeline = []
    while day < until:
        key = day.isoformat()
        apply_body_report(s, checkins.get(key))
        todays = by_day.get(key, [])
        st = merge_stims([stim_from_log(lg, program) for lg in todays]) if todays else M.empty_stim(1)
        if not todays:
            st['low'][:] = 1
        for lg in todays:
            anchor_from_race(s, lg, base_lv)
        M.apply(s, st)
        lv = M.levels(s)
        timeline.append(dict(date=key, vdot=round(float(M.vdot_now(s, lv, base_lv)[0]), 2),
                             levels={k: round(float(v[0]), 3) for k, v in lv.items()},
                             atl=round(float(s['atl'][0]), 1), ctl=round(float(s['ctl'][0]), 1),
                             run_min=round(float(st['run_min'][0])), minutes=round(float(st['minutes'][0])),
                             impact=round(float(st['impact'][0]), 1), fer=round(float(s['fer'][0]), 1)))
        day += dt.timedelta(days=1)
    learned = run_learning.analyse(program, logs, until, timeline)
    s['vdot_base'] += learned['correction_vdot']
    program['_run_learning'] = learned
    return s, base_lv, timeline


RACE_KM = {'tt5k': 5.0, 'tt10k': 10.0, 'half': 21.0975, 'race': 42.195}


def goals(program):
    """(A, B) goal finish times in minutes from program.json race.goal_a_min / goal_b_min."""
    r = program.get('race', {})
    return float(r.get('goal_a_min', 240)), float(r.get('goal_b_min', 250))


def goal_label(minutes):
    return f"{int(minutes) // 60}:{int(round(minutes)) % 60:02d}"


def race_effort(lg):
    """(km, min) of the race itself. A watch log of a planned time trial covers the
    whole session (warm-up, cool-down), so use explicit race_km/race_min, else the
    fastest stretch of the planned distance in the Garmin trace."""
    if _num(lg.get('race_km')) and _num(lg.get('race_min')):
        return _num(lg['race_km']), _num(lg['race_min'])
    dist, t = _num(lg.get('distance_km')), _num(lg.get('duration_min'))
    km = RACE_KM.get(lg.get('planned_kind'))
    if km and dist and dist > km * 1.05:
        p = run_learning.stream_path(lg)
        try:
            samples = json.load(open(p))['samples'] if p else []
        except (OSError, ValueError, KeyError):
            samples = []
        best, j, m = None, 0, km * 1000
        for i in range(len(samples)):
            while j < len(samples) and (samples[j][1] or 0) - (samples[i][1] or 0) < m:
                j += 1
            if j >= len(samples):
                break
            d = samples[j][0] - samples[i][0]
            best = d if best is None or d < best else best
        # no trace yet: don't anchor to warm-up + cool-down pace
        return (km, best / 60) if best else (None, None)
    return dist, t


def anchor_from_race(s, lg, base_lv):
    """A time trial / race re-anchors fitness to reality (80 % weight)."""
    if lg.get('run_type') != 'race' or not ACTIVITIES.get(lg.get('kind'), {}).get('is_run'):
        return
    dist, t = race_effort(lg)
    if not dist or not t or dist < 1.5:
        return
    measured = float(phys.vdot_from_race(dist * 1000, t))
    model = float(M.vdot_now(s, None, base_lv)[0])
    s['vdot_base'] += 0.8 * (measured - model)


def hr_vdot_estimates(program, logs, since):
    ath = program['athlete']
    out = []
    for lg in logs:
        if lg['date'] < since or not ACTIVITIES.get(lg['kind'], {}).get('is_run'):
            continue
        if lg.get('run_type') not in (None, 'easy', 'long', 'recovery', 'strides'):
            continue
        dist, t, hr = _num(lg.get('distance_km')), _num(lg.get('duration_min')), _num(lg.get('avg_hr'))
        if not (dist and t and hr) or t < 20:
            continue
        v = phys.vdot_from_hr_run(t * 60 / dist, hr, ath['hr_max'], ath['hr_rest'])
        if v:
            out.append((lg['date'], round(v, 1)))
    return out


def rebase(s, base_lv):
    """Make the current state the new reference point (vdot_base = VDOT now)."""
    lv = M.levels(s)
    s['vdot_base'] = M.vdot_now(s, lv, base_lv).astype(np.float32)
    return {k: v.copy() for k, v in lv.items()}


# ----------------------------------------------------------------------------- readiness

def readiness(checkins, today):
    ci = checkins.get(today.isoformat())
    if not ci:
        return None, []
    past = [v for k, v in checkins.items() if k < today.isoformat()][-30:]
    return _readiness(ci, past)


def _readiness(ci, past):
    def base(field):
        vals = [_num(p.get(field)) for p in past if _num(p.get(field))]
        return statistics.median(vals) if len(vals) >= 3 else None

    score = 0.8
    why = []
    # Eight Sleep and Garmin measure HRV differently; compare each only with its own baseline.
    if _num(ci.get('hrv_ms')) is None and _num(ci.get('garmin_hrv_ms')) is not None:
        ci = dict(ci, hrv_ms=ci.get('garmin_hrv_ms'), rhr=ci.get('garmin_rhr'))
        past = [dict(p, hrv_ms=p.get('garmin_hrv_ms'), rhr=p.get('garmin_rhr')) for p in past]
    sleep = _num(ci.get('sleep_h'))
    if sleep is None:
        sleep = _num(ci.get('garmin_sleep_h'))
    if sleep is not None:
        score += float(np.clip((sleep - 7.5) * 0.06, -0.25, 0.06))
        if sleep < 6:
            why.append(f'short sleep ({sleep:g} h)')
    hrv, hrv_b = _num(ci.get('hrv_ms')), base('hrv_ms')
    if hrv and hrv_b:
        r = hrv / hrv_b
        score += float(np.clip((r - 1) * 1.2, -0.35, 0.1))
        if r < 0.85:
            why.append(f'HRV {hrv:g} vs usual {hrv_b:g}')
    rhr, rhr_b = _num(ci.get('rhr')), base('rhr')
    if rhr and rhr_b:
        diff = rhr - rhr_b
        score -= float(np.clip(diff * 0.03, -0.05, 0.3))
        if diff >= 5:
            why.append(f'resting HR +{diff:g}')
    status = (ci.get('hrv_status') or '').lower()
    if status in ('low', 'poor'):
        score -= 0.25
        why.append('Garmin HRV status low')
    elif status == 'unbalanced':
        score -= 0.1
    bb = _num(ci.get('body_battery'))
    if bb is not None:
        score += float(np.clip((bb - 60) / 200, -0.2, 0.1))
    tr = _num(ci.get('training_readiness'))
    if tr is not None:
        score += float(np.clip((tr - 50) / 250, -0.2, 0.1))
        if tr < 30:
            why.append(f'Garmin readiness {tr:g}')
    mood = _num(ci.get('energy'))
    if mood is not None:
        score += (mood - 3) * 0.05
    stress = _num(ci.get('stress'))
    if stress is not None:
        score -= (stress - 3) * 0.04
    if ci.get('sick'):
        score = 0.1
        why.append('feeling unwell')
    return float(np.clip(score, 0, 1)), why


# ----------------------------------------------------------------------------- planning

def strength_loads(logs):
    loads = {}
    for lg in logs:
        if lg['kind'] != 'strength':
            continue
        for ex in lg.get('exercises') or []:
            load = _num(ex.get('load_kg'))
            if ex.get('name') and load:
                loads[ex['name']] = {'load': load, 'easy': (_num(ex.get('rpe')) or _num(lg.get('rpe')) or 8) <= 7,
                                     'date': lg['date']}
    return loads


def learned_timing(logs):
    """Session-length estimates from the runner's own strength/mobility logs (median of the last 6)."""
    per_set, mob = [], []
    for lg in logs:
        dur = _num(lg.get('duration_min'))
        if not dur:
            continue
        if lg['kind'] == 'strength':
            sets = sum(int(_num(e.get('sets'), 0)) for e in lg.get('exercises') or [])
            if sets >= 6:
                per_set.append(max(1.0, min(4.0, (dur - 4) / sets)))
        elif lg['kind'] == 'mobility':
            mob.append(dur)
    return {'min_per_set': statistics.median(per_set[-6:]) if per_set else 1.9,
            'mobility_min': statistics.median(mob[-6:]) if mob else 15}


def explain(s, info, prim, sec, ctx, cs, P, ready_why, program):
    """Human reasons for today's pick."""
    why = []
    ml = info['muscle_level'][0]
    lv = info['levels']
    c = M.CANDS[prim]
    tired = sorted(((float(ml[i]), MUSCLES[i]) for i in range(M.NM) if ml[i] > 0.55), reverse=True)
    if ready_why:
        why.append('Readiness is down (' + ', '.join(ready_why) + ') — keeping it gentle.')
    if tired:
        names = ', '.join(f"{MUSCLE_LABELS[m].lower()} {int(v * 100)}%" for v, m in tired[:3])
        why.append(f'Still recovering: {names} fatigued.')
    ok = info['ok'][0]
    if not ok[M.RUNNING].any() and s['injured'][0] > 0:
        why.append('Pain flagged — no running until it settles. Cross-training keeps the engine going.')
    elif not ok[M.RUNNING].any() and M.RUNNING[prim] == 0 and float(ml[M.RUN_MUSCLES].max()) > P['max_level'][0]:
        why.append('Running legs need a break, so fitness comes from zero-impact work today.')
    cap = float(M.weekly_cap(s, P, ctx['day_from_start'])[0])
    used = float(M.impact_weeks(s)[0][0])
    if used > 0.8 * cap:
        why.append(f'Running impact budget {int(used / cap * 100)}% used this week (tendon and bone protection).')
    if c in ('threshold', 'vo2', 'hills', 'mp_run', 'xt_intervals') and s['ds_hard'][0] >= 2:
        why.append(f"{int(s['ds_hard'][0])} easy days since the last hard session — you're primed for quality.")
    if not M.HARD[prim] and s['ds_hard'][0] < 1 and c not in ('rest',):
        why.append('Hard session yesterday — hard days hard, easy days easy.')
    val = {k: float(cs[k][0, prim]) for k in QUALITY_LABELS}
    builds = [QUALITY_LABELS[k] for k, v in sorted(val.items(), key=lambda kv: -kv[1]) if v > 0.5][:2]
    if builds and c not in ('rest', 'recovery'):
        why.append('Builds: ' + ' + '.join(builds) + '.')
    if c in ('threshold', 'vo2', 'hills') and ctx['dtr'] > 90:
        why.append('Your base is ready for quality; these gains compound under the long runs to come.')
    if c in ('long_mp', 'mp_run'):
        why.append('Race-specific work is most valuable late: it fades within ~3 weeks, so it is timed close to race day.')
    if c == 'long' and float(info['levels']['D'][0]) < 0.5 and M.DIST in ('marathon', 'half'):
        why.append(f"Durability is your biggest lever for the {M.D['short']} distance.")
    if sec == 'strength_lower':
        why.append('Legs strength stacked on the same day keeps tomorrow fresh (hard days hard).')
    if ctx['dtr'] <= float(P['taper_days'][0]) * M.D['taper_scale'] and ctx['dtr'] > 0:
        why.append('Taper: volume down, intensity kept — you arrive fresh (Bosquet 2007).')
    return why[:5]


def _snap(i, arr):
    return {k: float(v[0]) for k, v in arr.items()}


def plan(program, store, today, n_days=14, full=True):
    logs = store.logs()
    checkins = store.checkins()
    P = M.params_from_dict(program['_policy'], 1)
    s, base_lv, timeline = replay(program, logs, checkins, today)
    # Absolute HR-derived VDOT remains display-only. Relative steady-section
    # evidence, corrected for gradient, is applied conservatively during replay.
    ests = hr_vdot_estimates(program, logs, (today - dt.timedelta(days=21)).isoformat())
    base_lv = rebase(s, base_lv)
    vdot_today = float(s['vdot_base'][0])
    loads = strength_loads(logs)
    program['_timing'] = learned_timing(logs)
    # Restart with one set for the first two sessions of each type after a gap.
    recent = [lg for lg in logs if lg['kind'] == 'strength'
              and (today - dt.timedelta(days=14)).isoformat() <= lg['date'] < today.isoformat()]
    program['_strength_reentry'] = {f'strength_{focus}': max(0, 2 - sum(lg.get('focus') == focus for lg in recent))
                                    for focus in ('lower', 'upper')}
    todays_logs = [lg for lg in logs if lg['date'] == today.isoformat()]
    ci_today = checkins.get(today.isoformat())
    apply_body_report(s, ci_today)
    ready, ready_why = readiness(checkins, today)
    cal = M.calendar(today, program['_race'], availability(program), program.get('events', {}), program.get('down_weeks', []),
                     overrides=overrides(program))
    days, weeks = [], {}
    sim = M.clone_state(s)
    muscles_today = {m: round(float(x), 2) for m, x in zip(MUSCLES, M.muscle_level(s)[0])}
    for i, ctx in enumerate(cal):
        c = dict(ctx)
        c['avail'] = np.array([ctx['avail']], np.float32)
        c['avail_total'] = np.array([ctx['avail_total']], np.float32)
        rd = np.array([ready], np.float32) if (i == 0 and ready is not None) else None
        v = float(M.vdot_now(sim, None, base_lv)[0])
        if ctx['event'] or ctx['dtr'] == 0:
            ev = 'race' if ctx['dtr'] == 0 else ctx['event']
            st = M.event_stim(ev, np.array([v], np.float32), 1) if ev != 'race' else None
            prim_name, sec_name, dur = ev, 'none', None
            why = ['Checkpoint: your result re-calibrates all paces and the finish prediction.'] if ev != 'race' else \
                ['Race day. Trust the work.']
            workout = builder.build(ctx['date'], 'rest', None, {k: 0 for k in ('E', 'L', 'Qt', 'Qv', 'MPw', 'X')}, v,
                                    program, ctx['dtr'], loads, event=ev)
        else:
            prim, sec, dur, cs, info = M.choose(sim, P, c, readiness=rd)
            p, sc = int(prim[0]), int(sec[0])
            prim_name, sec_name = M.CANDS[p], M.SECONDARY[sc]
            st = M.stim_from_choice(prim, sec, cs, 1)
            why = explain(sim, info, p, M.SECONDARY[sc], ctx, cs, P, ready_why if i == 0 else [], program) \
                if i < n_days else []
            if ctx['date'].isoformat() in program.get('rest_days', {}):
                why = [program['rest_days'][ctx['date'].isoformat()]]
            elif program.get('day_slots', {}).get(ctx['date'].isoformat(), {}).get('note'):
                why = [program['day_slots'][ctx['date'].isoformat()]['note']] + why
            workout = builder.build(ctx['date'], prim_name, sec_name,
                                    {k: float(np.asarray(dur[k]).reshape(-1)[0]) for k in ('E', 'L', 'Qt', 'Qv', 'MPw', 'X')},
                                    v, program, ctx['dtr'], loads)
            if program['_strength_reentry'].get(sec_name, 0) > 0:
                program['_strength_reentry'][sec_name] -= 1
                # Do not credit the full essentials stimulus for a single-set restart.
                for key, amount in (('minutes', M.SEC_MIN[sc]), ('sys', M.SEC_SYS[sc]), ('nm', M.SEC_NM[sc])):
                    st[key] -= amount * .5
                sl = M.SEC_SHARE[sc] * M.SEC_EM[sc] * .5
                st['mload'] -= sl
                st['slow_load'] -= sl * M.SEC_ECC[sc]
        if i < n_days:
            workout['why'] = why
            workout['dtr'] = ctx['dtr']
            workout['weekday'] = ctx['date'].strftime('%a')
            days.append(workout)
        wk = (ctx['date'] - ctx['date'].weekday() * dt.timedelta(days=1)).isoformat()
        w = weeks.setdefault(wk, dict(week=wk, run_min=0, km=0.0, minutes=0, long=0, hard=0, xt_min=0, strength=0,
                                      kinds=[]))
        sec = workout.get('secondary')
        main_min = workout.get('minutes', 0) - (sec['est_min'] if sec and sec['kind'] != 'mobility' else 0)   # builder adds gym time
        w['run_min'] += main_min if workout.get('sport') == 'running' else 0
        w['km'] += workout.get('km', 0) or 0
        w['minutes'] += workout.get('minutes', 0)
        if workout['kind'] in ('long', 'long_mp', 'half', 'race'):
            w['long'] = max(w['long'], main_min)
        w['hard'] += int(workout['kind'] in ('long', 'long_mp', 'threshold', 'vo2', 'hills', 'mp_run', 'xt_intervals',
                                             'tt5k', 'tt10k', 'half'))
        w['xt_min'] += main_min if workout.get('sport') == 'cycling' else 0
        w['strength'] += int(bool(workout.get('secondary')) and workout['secondary']['kind'] != 'mobility')
        w['kinds'].append(workout['kind'])
        if not full and i >= n_days:
            break
        if i == 0 and todays_logs:
            st = merge_stims([stim_from_log(lg, program) for lg in todays_logs])
        if st is not None:
            M.apply(sim, st)
    for w in weeks.values():
        w['km'] = round(w['km'], 1)
        w['focus'] = _focus(w['kinds'])
    extras.annotate(days, logs, program, today, today_logged=bool(todays_logs))
    nutrition.annotate(days, program, logs)
    return dict(days=days, weeks=list(weeks.values()), timeline=timeline, vdot=round(vdot_today, 1),
                base_levels={k: round(float(v[0]), 3) for k, v in base_lv.items()}, muscles=muscles_today,
                readiness=ready, readiness_why=ready_why, hr_vdot=ests, run_learning=program.get('_run_learning'), state=s, today_logs=todays_logs)


def _focus(kinds):
    if 'race' in kinds:
        return 'Race'
    counts = {k: kinds.count(k) for k in set(kinds)}
    if counts.get('long_mp', 0) + counts.get('mp_run', 0) >= 1:
        return 'Race-specific'
    if counts.get('threshold', 0) + counts.get('vo2', 0) >= 1:
        return 'Threshold & VO2'
    if counts.get('hills', 0) >= 1:
        return 'Strength & hills'
    return 'Aerobic base'


def predict(program, state, base_lv_unused=None, n=600, seed=11):
    """Finish-time distribution by simulating many plausible versions of you from today."""
    rng = np.random.default_rng(seed)
    today = dt.date.today()
    s = M.clone_state(state)
    pop = M.sample_population(s, n, rng, vdot_sd=float(program['baseline'].get('vdot_sd', 1.0)), fer_sd=15.0)
    cal = M.calendar(today, program['_race'], availability(program), program.get('events', {}), program.get('down_weeks', []),
                     overrides=overrides(program))
    P = M.params_from_dict(program['_policy'], n)
    res = M.simulate(P, pop, cal, rng, weight_ratio=weight_ratio(program, today))
    t = res['time'][~res['dns']]
    if not len(t):
        return None
    return dict(p10=float(np.percentile(t, 10)), p50=float(np.percentile(t, 50)), p90=float(np.percentile(t, 90)),
                p_sub4=float((res['time'] < 240).mean()), p_sub330=float((res['time'] < 210).mean()),
                dns=float(res['dns'].mean()), injury_rate=float((res['injuries'] > 0).mean()),
                p_sub410=float((res['time'] < 250).mean()),
                **_goal_odds(program, res['time']),
                vdot_race=float(np.median(res['vdot'])))


def _goal_odds(program, t):
    a, b = goals(program)
    return dict(goal_a=a, goal_b=b, p_goal_a=float((t < a).mean()), p_goal_b=float((t < b).mean()))


# ----------------------------------------------------------------------------- optimiser support

def current_state(program):
    """Real state today from the database (or the baseline if there is no DB yet)."""
    from .store import Store
    db = os.path.join(ROOT, 'data', 'marathon.db')
    today = dt.date.today()
    if os.path.exists(db):
        st = Store(db)
        s, base_lv, _ = replay(program, st.logs(), st.checkins(), today)
    else:
        s = baseline_state(program)
        base_lv = {k: v.copy() for k, v in M.levels(s).items()}
    rebase(s, base_lv)
    return s


def optimiser_inputs(program):
    today = dt.date.today()
    s = current_state(program)
    cal = M.calendar(today, program['_race'], availability(program), program.get('events', {}), program.get('down_weeks', []),
                     overrides=overrides(program))
    return s, cal, weight_ratio(program, today)


def policy_evidence(program, policy, n=2048, seed=5):
    """What the chosen policy actually does across simulated athletes, week by week."""
    rng = np.random.default_rng(seed)
    s, cal, wr = optimiser_inputs(program)
    pop = M.sample_population(s, n, rng, vdot_sd=float(program['baseline'].get('vdot_sd', 2.5)))
    P = M.params_from_dict(policy, n)
    res = M.simulate(P, pop, cal, rng, weight_ratio=wr, collect=True)
    trace = res['trace']
    weeks = []
    for w0 in range(0, len(trace), 7):
        wk = trace[w0:w0 + 7]
        prim = np.stack([x['prim'] for x in wk])
        sec = np.stack([x['sec'] for x in wk])
        run = np.sum([x['run_min'] for x in wk], 0)
        weeks.append(dict(
            week_start=cal[w0]['date'].isoformat(),
            run_min_median=float(np.median(run)),
            total_min_median=float(np.median(np.sum([x['minutes'] for x in wk], 0))),
            longest_run_median=float(np.median(np.max([x['run_min'] for x in wk], 0))),
            threshold_min=float(np.median(np.sum([x['thr'] for x in wk], 0))),
            vo2_min=float(np.median(np.sum([x['vo2'] for x in wk], 0))),
            mp_min=float(np.median(np.sum([x['mp'] for x in wk], 0))),
            sessions={c: round(float((prim == i).sum(0).mean()), 2) for i, c in enumerate(M.CANDS) if (prim == i).any()},
            strength_lower=round(float((sec == 1).sum(0).mean()), 2),
            strength_upper=round(float((sec == 2).sum(0).mean()), 2),
        ))
    ok = ~res['dns']
    return dict(n=n, p_sub4=float((res['time'] < 240).mean()), p_sub330=float((res['time'] < 210).mean()),
                p_sub410=float((res['time'] < 250).mean()), **_goal_odds(program, res['time']),
                long_injury_rate=float((res['long_injuries'] > 0).mean()),
                finish_p10=float(np.percentile(res['time'][ok], 10)),
                finish_p50=float(np.percentile(res['time'][ok], 50)),
                finish_p90=float(np.percentile(res['time'][ok], 90)), dns_rate=float(res['dns'].mean()),
                any_injury_rate=float((res['injuries'] > 0).mean()), weeks=weeks)
