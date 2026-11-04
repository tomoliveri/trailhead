"""Garmin watch support: compact plan for the watch, due-notification logic,
and turning a recorded watch activity into a log entry.

Payloads stay small (background responses are limited to ~8 KB on the watch)
and use short keys that the Monkey C code reads directly.
"""
import datetime as dt

INTENSITY = {'warmup': 2, 'active': 0, 'recovery': 4, 'cooldown': 3, 'rest': 1}
SPORT = {'running': 'run', 'cycling': 'bike', 'walking': 'walk', None: 'run'}
PLAN_TO_LOG = {
    'easy': ('run', 'easy'), 'easy_strides': ('run', 'strides'), 'long': ('run', 'long'), 'long_mp': ('run', 'long'),
    'threshold': ('run', 'tempo'), 'vo2': ('run', 'intervals'), 'hills': ('run', 'hills'), 'mp_run': ('run', 'marathon_pace'),
    'xt_easy': ('bike', None), 'xt_intervals': ('bike', None), 'recovery': ('walk', None), 'tt5k': ('run', 'race'),
    'tt10k': ('run', 'race'), 'half': ('run', 'race'), 'race': ('run', 'race'), 'rest': ('walk', None),
    'runwalk': ('run', 'easy'),
}
WATCH_SPORT = {'mobility': 'mobility', 'run': 'run', 'treadmill': 'treadmill', 'trail': 'trail', 'bike': 'bike', 'walk': 'walk',
               'elliptical': 'elliptical', 'row': 'row', 'strength': 'strength', 'rest': 'rest', 'other': 'other'}


def flat_steps(steps, limit=48):
    """Expand repeats into a linear list the watch can step through."""
    out = []

    def add(sts, rep=None):
        for s in sts:
            if s['type'] == 'repeat':
                for i in range(s['times']):
                    add(s['steps'], (i + 1, s['times']))
                continue
            d = s.get('duration', {})
            item = {'n': s.get('name', '')[:18], 'i': INTENSITY.get(s['type'], 0)}
            if rep:
                item['r'] = f'{rep[0]}/{rep[1]}'
            if d.get('type') == 'time':
                item['dt'], item['v'] = 0, int(d['seconds'])
            elif d.get('type') == 'distance':
                item['dt'], item['v'] = 1, int(d['meters'])
            else:
                item['dt'], item['v'] = 2, 0
            t = s.get('target')
            if t and t.get('type') == 'pace':
                item['pf'], item['ps'] = int(t['fast']), int(t['slow'])
            hr = s.get('hr') or {}
            if hr.get('type') == 'hr':
                item['hl'], item['hh'] = int(hr['low']), int(hr['high'])
            out.append(item)
    add(steps)
    return out[:limit]


EX_CUES = {
    'Romanian deadlift': 'Hinge hips, flat back, hamstrings',
    'Bulgarian split squat': 'Tall torso, knee tracks toe',
    'Nordic curl': 'Hips straight, slow eccentric',
    'Single-leg RDL': 'Level hips, hinge from glute',
    'Standing calf raise': '2s up, pause top, 3s down',
    'Bent-knee calf raise': 'Knee bent 45 deg, soleus focus',
    'Tibialis raise': 'Heels planted, pull toes high',
    'Pogo hops': 'Stiff ankles, quick contact',
    'Skipping (A-skips)': 'Tall posture, knee + toe up',
    'Drop jump': 'Instant rebound, stiff ankle',
    'Single-leg hops': 'Springy ankle, quiet landing',
    'Copenhagen plank': 'Top leg on bench, hips high',
    'DB row': 'Pull elbow to hip, flat back',
    'Lat pulldown': 'Chest tall, elbows to ribs',
    'Face pull': 'Pull to forehead, rotate out',
    'Incline DB press': 'Elbows 45 deg, full stretch',
    'Lateral raise': 'Soft elbows, control down',
    'Pallof press': 'Brace core, resist rotation',
    'Dead bug': 'Low back glued to floor',
    'Side plank': 'Stack hips & shoulders straight',
    'KB row': 'Brace on bench, elbow to hip',
    'Chin-up': 'Full hang to chin over bar',
    'Reverse fly': 'Hinge forward, squeeze upper back',
    'Push-up': 'Plank body, chest to floor',
    'Shoulder-tap plank': 'Wide feet, zero hip sway',
    'Plank': 'Glutes & abs braced tight',
    'Backpack row': 'Hinge 45 deg, pull to ribs',
}


def watch_items(sec):
    items = []
    for it in (sec or {}).get('items', [])[:12]:
        name = it['name']
        e = {'n': name[:24]}
        cue = EX_CUES.get(name)
        if cue:
            e['c'] = cue[:28]
        if it.get('sets'):
            e['s'] = int(it['sets'])
            e['r'] = str(it.get('reps', '')).replace('\u2013', '-').split(' ')[0][:6]
            e['rt'] = 90 if any(k in name for k in ('deadlift', 'split squat', 'Nordic', 'Drop jump')) else 60
            if it.get('load_kg') is not None:
                e['l'] = float(it['load_kg'])
                if it.get('per_hand'):
                    e['h'] = 1
        items.append(e)
    return items


def compact(w, fade=None):
    """Watch payload for one day. `fade`: second-half slowdown (fraction) for the turn-for-home cue on outdoor runs."""
    if not w:
        return None
    hr = None
    for s in w.get('steps', []):
        h = s.get('hr') if s.get('type') == 'active' else None
        if h and h.get('type') == 'hr':
            hr = [h['low'], h['high']]
            break
    sec = w.get('secondary')
    home = (sec or {}).get('home')
    note = None
    if w.get('shoes'):
        note = w['shoes'].split('.')[0][:36]
    elif (w.get('audio') or {}).get('title'):
        note = w['audio']['title'][:36]
    elif w.get('notes'):
        note = w['notes'][0][:36]
    elif w.get('blurb'):
        note = w['blurb'][:36]
    return {
        'date': w['date'], 'k': w['kind'], 't': w['title'][:28], 'm': int(w.get('minutes') or 0),
        'km': w.get('km') or 0, 'sp': SPORT.get(w.get('sport'), 'run') if w.get('sport') else None,
        'hr': hr, 'note': note, 'sec': sec['title'][:28] if sec else None, 'sk': sec['kind'] if sec else None,
        'x': watch_items(sec),
        # at-home alternative (upper body): the watch asks Gym / At home before starting
        'xh': watch_items(home) or None,
        's': flat_steps(w.get('steps', [])),
        'fu': [w['fuel_plan']['first_s'], w['fuel_plan']['every_s']] if w.get('fuel_plan') else None,
        'mc': [int(w['mind']['at_s']), w['mind']['cue'][:16]] if (w.get('mind') or {}).get('cue') else None,
        'th': int(round(fade * 1000)) if fade is not None and w.get('sport') in ('running', 'walking')
        and int(w.get('minutes') or 0) >= 20 and w.get('steps') else None,
    }


def _at(day, hhmm, zone):
    h, m = map(int, hhmm.split(':'))
    return dt.datetime.combine(day, dt.time(h, m), zone)


QUIET_FROM, QUIET_TO = 22, 10   # never buzz the watch from 22:00 until 10:00


def due_notification(res, program, now, zone, mark_sent, window_min=30):
    """The notification the watch should show now (at most one), deduplicated per key.

    The watch only gets the evening preview of tomorrow, and nothing
    between 22:00 and 10:00. Session / strength / log-nudge reminders stay on the phone push."""
    if now.hour >= QUIET_FROM or now.hour < QUIET_TO:
        return None
    day = now.date()
    days = res['days']
    if not days:
        return None
    w0 = days[0]
    rem = program['reminders']
    cands = []
    if len(days) > 1:
        w1 = days[1]
        tomorrow = day + dt.timedelta(days=1)
        slot = program['availability'][('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')[tomorrow.weekday()]]['slot']
        cands.append((_at(day, rem.get('evening_preview', '20:00'), zone), f'watch-preview:{tomorrow}',
                      {'title': 'Tomorrow', 'sub': w1['title'][:28],
                       'body': 'Rest day' if w1['kind'] == 'rest' else f"{w1.get('minutes')} min at {slot}", 'act': 0}))
    for t, key, msg in sorted(cands, key=lambda c: c[0]):
        if t <= now < t + dt.timedelta(minutes=window_min) and mark_sent(key):
            return msg
    return None


def activity_to_log(a, zone, plan_day):
    """Watch activity summary -> log entry (same shape the PWA posts)."""
    start = dt.datetime.fromtimestamp(int(a['start']), zone)
    kind = WATCH_SPORT.get(a.get('sport'), 'other')
    planned = a.get('planned')
    if kind in ('strength', 'mobility'):
        entry = {'client_id': str(a.get('id') or f"watch-{int(a['start'])}")[:64], 'kind': kind,
                 'date': start.date().isoformat(), 'time': start.strftime('%H:%M'),
                 'duration_min': round(float(a.get('duration_s') or 0) / 60, 1), 'source': 'garmin-watch',
                 'garmin': {k: a.get(k) for k in ('calories', 'device', 'completed_steps') if a.get(k) is not None}}
        for src in ('avg_hr', 'max_hr', 'rpe', 'feel'):
            if a.get(src) not in (None, 0):
                entry[src] = a[src]
        ex = [{'name': e.get('n'), 'sets': e.get('s'), 'reps': e.get('r'), 'load_kg': e.get('l')}
              for e in (a.get('exercises') or []) if e.get('n')]
        if ex:
            entry['exercises'] = ex
        if planned:
            entry['planned_kind'] = planned
            entry['as_planned'] = True
            entry['focus'] = 'lower' if planned == 'strength_lower' else 'upper' if planned == 'strength_upper' else None
        return entry
    entry = {
        'client_id': str(a.get('id') or f"watch-{int(a['start'])}")[:64], 'kind': kind,
        'date': start.date().isoformat(), 'time': start.strftime('%H:%M'),
        'duration_min': round(float(a.get('duration_s') or 0) / 60, 1), 'source': 'garmin-watch',
        'garmin': {k: a.get(k) for k in ('in_range_pct', 'zone_s', 'steps', 'calories', 'device', 'completed_steps')
                   if a.get(k) is not None},
    }
    if a.get('distance_m'):
        entry['distance_km'] = round(float(a['distance_m']) / 1000, 2)
    for src, dst in (('avg_hr', 'avg_hr'), ('max_hr', 'max_hr'), ('cadence', 'cadence'), ('ascent', 'elevation_m'),
                     ('rpe', 'rpe'), ('feel', 'feel')):
        if a.get(src) not in (None, 0):
            entry[dst] = a[src]
    if planned and plan_day and plan_day.get('kind') == planned:
        entry['planned_kind'] = planned
        entry['as_planned'] = True
        run_type = PLAN_TO_LOG.get(planned, (None, None))[1]
        if run_type and kind in ('run', 'treadmill', 'trail'):
            entry['run_type'] = run_type
        entry['work'] = work_from_steps(plan_day, float(a.get('completed_frac') or 1.0))
    return entry


def work_from_steps(w, frac=1.0):
    thr = vo2 = mp = 0.0

    def walk(sts, mult=1):
        nonlocal thr, vo2, mp
        for s in sts:
            if s['type'] == 'repeat':
                walk(s['steps'], mult * s['times'])
                continue
            d = s.get('duration', {})
            m = d['seconds'] / 60 if d.get('type') == 'time' else 0
            if s.get('name') == 'Threshold':
                thr += m * mult
            elif s.get('name') == 'Hard':
                vo2 += m * mult
            elif s.get('name') in ('Marathon pace', 'Race pace'):
                mp += m * mult
    walk(w.get('steps', []))
    out = {k: round(v * frac, 1) for k, v in (('thr_min', thr), ('vo2_min', vo2), ('mp_min', mp)) if v}
    if w.get('kind') == 'easy_strides':
        out['nm'] = 0.3
    if w.get('kind') == 'hills':
        out['nm'] = 0.6
    return out
