"""Couch to 5K: a walk/run progression from no running to 30 minutes non-stop, then a 5 km run.

This isn't a simulation like the race plans. People starting from zero need a gentle, predictable ladder, and the
model's fitness estimates don't mean much before someone can run continuously. The plan adapts to what actually
happens instead:

  * the next session is the one after the last one you finished, whatever the date (missed days don't skip ahead),
  * a session you rate 9-10 out of 10 is repeated rather than stepped up,
  * after more than 10 days off you go back a week,
  * three sessions a week on non-consecutive days where possible, with spare days before the finish date used to
    repeat sessions (spread evenly) rather than to rush.
"""
import datetime as dt
import itertools

from . import builder

# (run minutes, walk minutes, reps). Every session starts and ends with 5 minutes of brisk walking.
LADDER = [
    (1, 1.5, 8), (1, 1.5, 8), (1.5, 1.5, 7),
    (1.5, 1.5, 8), (2, 2, 6), (2, 1.5, 7),
    (3, 2, 5), (3, 1.5, 5), (4, 2, 4),
    (5, 2, 4), (5, 1.5, 4), (6, 2, 3),
    (8, 2, 3), (8, 1.5, 3), (10, 2, 2),
    (12, 2, 2), (15, 2, 2), (18, 0, 1),
    (20, 0, 1), (22, 0, 1), (22, 0, 1),
    (25, 0, 1), (25, 0, 1), (28, 0, 1),
    (28, 0, 1), (30, 0, 1),
]
TOTAL = len(LADDER) + 1          # + the 5 km run
WEEKS = 9
RUN_KINDS = ('run', 'trail', 'treadmill')
MIN_SESSION = 12                 # minutes: shorter runs don't count as a finished session
BREAK_DAYS = 10
JOG_S_KM, WALK_S_KM = 450, 600   # for distance estimates only
FEEL = {'type': 'none', 'text': '♥ go by feel: you can still talk in short sentences'}
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def _d(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x)[:10])


def progress(logs, start, today):
    """(sessions finished, last session date, notes) from the runner's logs, replayed in order."""
    level, last, notes = 0, None, []
    days = {}
    for lg in logs:
        if lg.get('source') == 'history' or lg.get('kind') not in RUN_KINDS:
            continue
        if float(lg.get('duration_min') or 0) < MIN_SESSION:
            continue
        d = _d(lg['date'])
        if d < start or d > today:
            continue
        days.setdefault(d, lg)   # one session per day
    for d in sorted(days):
        lg = days[d]
        if last and (d - last).days > BREAK_DAYS and level:
            level = max(0, level - 3)
        if float(lg.get('rpe') or 0) >= 9 and level < len(LADDER):
            notes.append(f'{d.isoformat()}: rated {int(float(lg["rpe"]))}/10, so that session comes round again.')
        else:
            level = min(TOTAL, level + 1)
        last = d
    if last and (today - last).days > BREAK_DAYS and level and level < TOTAL:
        level = max(0, level - 3)
        notes.append('More than 10 days since the last session: picking up a week back, so it feels easy again.')
    return level, last, notes


def pick_days(availability, n=3):
    """The weekdays to train on: n of the free days (30+ min), as evenly spread over the week as possible."""
    free = [i for i, d in enumerate(DAYS) if int((availability.get(d) or {}).get('primary') or 0) >= 30]
    if len(free) <= n:
        return free

    def spread(combo):
        gaps = [(combo[(k + 1) % len(combo)] - combo[k]) % 7 or 7 for k in range(len(combo))]
        return (min(gaps), 5 in combo or 6 in combo, -max(gaps))
    return list(max(itertools.combinations(free, n), key=spread))


def session(index):
    """Steps for ladder session `index` (0-based); the last index is the 5 km run."""
    warm = builder._step('warmup', 5, name='Brisk walk')
    cool = builder._step('cooldown', 5, name='Walk')
    warm['walk'] = cool['walk'] = True
    if index >= len(LADDER):
        run = builder._step('active', meters=5000, name='Run 5 km',
                            note='Your pace, start slower than you think. Walk breaks are allowed.')
        run['hr'] = FEEL
        return [warm, run, cool], None
    r, w, n = LADDER[index]

    def jog(m):
        st = builder._step('active', m, name='Run', note='Easy jog: slow enough to talk')
        st['hr'] = FEEL
        return st

    def stroll(m):
        st = builder._step('recovery', m, name='Walk', note='Brisk walk, let your breathing settle')
        st['walk'] = True
        return st
    main = [builder._repeat(n - 1, [jog(r), stroll(w)]), jog(r)] if n > 1 else [jog(r)]
    for st in (warm, cool):
        st['hr'] = dict(FEEL, text='♥ brisk walk')
    return [warm] + main + [cool], (r, w, n)


def _fmt(m):
    return f'{int(m)}' if float(m).is_integer() else (f'{int(m)}½' if m % 1 == 0.5 else f'{m:g}')


def _workout(day, index, total_slots_note=None):
    steps, spec = session(index)
    if spec is None:
        title, blurb = '5 KM RUN', 'The finish line of Couch to 5K. Run the whole way if you can; walk breaks are fine.'
        kind, minutes, km = 'race', 45, 5.0 + 10 * 60 / WALK_S_KM
    else:
        r, w, n = spec
        if n > 1:
            title = f'Run {_fmt(r)} min / walk {_fmt(w)} min × {n}'
            kind = 'runwalk'
        else:
            title = f'Run {_fmt(r)} minutes non-stop'
            kind = 'easy'
        blurb = 'Easy jogging, slow enough to talk. If a run interval is too much, slow down rather than stop.'
        run_s, walk_s = r * n * 60, w * (n - 1) * 60 + 600
        minutes = round((run_s + walk_s) / 60)
        km = round(run_s / JOG_S_KM + walk_s / WALK_S_KM, 1)
    why = [f'Session {index + 1} of {TOTAL}.']
    if total_slots_note:
        why.append(total_slots_note)
    return {'date': day.isoformat(), 'kind': kind, 'title': title, 'blurb': blurb, 'sport': 'running', 'steps': steps,
            'fuel': [], 'notes': ['Good shoes and a flat, quiet route. Finish each session feeling you could have done a bit more.'],
            'fuel_plan': None, 'slot_hint': None, 'paces': {}, 'hr': {}, 'minutes': minutes, 'km': round(km, 1),
            'timing': 'Whenever suits. Same time each session makes it a habit.', 'secondary': None, 'why': why,
            'c25k': {'session': index + 1, 'of': TOTAL}}


def _rest(day, note):
    return {'date': day.isoformat(), 'kind': 'rest', 'title': 'Rest day', 'blurb': 'Rest days are when your legs adapt.',
            'sport': None, 'steps': [], 'fuel': [], 'notes': [note], 'fuel_plan': None, 'slot_hint': None, 'paces': {},
            'hr': {}, 'minutes': 0, 'secondary': None, 'why': []}


def plan(program, logs, today, n_days=21, full=False):
    """Day-by-day plan from today to the 5 km day. Returns dict(days, weeks, progress)."""
    start, finish = _d(program['plan_start']), _d(program['race']['date'])
    level, last, notes = progress(logs, start, today)
    run_days = set(pick_days(program['availability']))
    done_today = last == today
    days_out = []
    end = finish if full else min(finish, today + dt.timedelta(days=n_days - 1))
    # slots: training days from today (tomorrow if today's session is done) until the day before the 5 km run
    first = today + dt.timedelta(days=1 if done_today else 0)
    slots = [first + dt.timedelta(days=i) for i in range((finish - first).days) if (first + dt.timedelta(days=i)).weekday() in run_days]
    remaining = max(0, len(LADDER) - level)   # training sessions still to do before the 5 km run
    behind = remaining > len(slots)
    plan_idx = {}
    for j, d in enumerate(slots):
        if behind:
            plan_idx[d] = level + j
        else:
            # spare slots repeat sessions near the end (the bigger jumps), never the first ones
            n = len(slots)
            plan_idx[d] = level + remaining - 1 - ((n - 1 - j) * remaining) // n if remaining else len(LADDER) - 1
    day = today
    while day <= end:
        dtr = (finish - day).days
        if day == today and done_today:
            w = _rest(day, f'Session done today ({level} of {TOTAL}). Nice work.')
        elif day == finish:
            if level >= TOTAL:
                w = _rest(day, 'Couch to 5K done. Keep running three times a week, or set up a 5 km plan next.')
            elif behind:
                w = _workout(day, level + len(slots),
                             'A few sessions behind, so the 5 km run waits until you have done them all. Keep going.')
            else:
                w = _workout(day, len(LADDER))
        elif day in plan_idx and level < TOTAL:
            idx = min(plan_idx[day], len(LADDER) - 1 if not behind else TOTAL - 1)
            w = _workout(day, idx)
            if idx == len(LADDER):
                w['title'] = 'Run 5 km'
        else:
            w = _rest(day, 'Optional: an easy 20–30 minute walk.')
        w['dtr'] = dtr
        w['weekday'] = day.strftime('%a')
        days_out.append(w)
        day += dt.timedelta(days=1)
    # repeated sessions: mark the second of two identical consecutive sessions
    seen = None
    for w in days_out:
        s = (w.get('c25k') or {}).get('session')
        if s:
            w['why'][0] = f'Session {s} of {TOTAL}.' + (' Same as last time: repeating builds confidence.' if s == seen else '')
            seen = s
    if notes and days_out:
        days_out[0]['why'] = notes[-1:] + days_out[0]['why']
    weeks = {}
    for w in days_out:
        d = _d(w['date'])
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
        x = weeks.setdefault(wk, dict(week=wk, run_min=0, km=0.0, minutes=0, long=0, hard=0, xt_min=0, strength=0,
                                      kinds=[], focus='Couch to 5K'))
        x['minutes'] += w.get('minutes', 0)
        x['run_min'] += w.get('minutes', 0)
        x['km'] = round(x['km'] + (w.get('km') or 0), 1)
        x['long'] = max(x['long'], w.get('minutes', 0))
        x['kinds'].append(w['kind'])
    nxt = next((w for w in days_out if w.get('c25k')), None)
    return {'days': days_out, 'weeks': list(weeks.values()),
            'progress': {'done': level, 'total': TOTAL, 'finish': finish.isoformat(), 'behind': behind,
                         'next': nxt['date'] if nxt else None, 'next_title': nxt['title'] if nxt else None,
                         'days': [DAYS[i] for i in sorted(run_days)]}}
