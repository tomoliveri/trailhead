"""Turn a policy decision into a concrete, Garmin-style workout.

Steps use Garmin's vocabulary (warm up / run / recover / cool down / repeat)
with pace and heart-rate targets, so they can be followed on the watch or
exported as a FIT workout file (fitfile.py).
"""
import math

from . import physiology as phys
from . import extras
from .model import EVENTS

TITLES = {
    'rest': ('Rest day', 'Recovery is where the adaptation happens.'),
    'recovery': ('Recovery walk + mobility', 'Blood flow, not fitness. Keep it gentle.'),
    'easy': ('Easy run', 'Conversational. Aerobic engine and leg conditioning.'),
    'easy_strides': ('Easy run + strides', 'Easy aerobic running, then fast, relaxed strides for economy.'),
    'long': ('Long run', 'The marathon-specific cornerstone: durability and fat use.'),
    'long_mp': ('Long run with marathon-pace finish', 'Race rehearsal on tired legs: pace, fuel and focus.'),
    'threshold': ('Threshold session', 'Comfortably hard. Raises the pace you can hold for a long time.'),
    'vo2': ('VO2 intervals', 'Hard reps that raise your aerobic ceiling.'),
    'hills': ('Hill repeats', 'Strength, power and economy with less pounding than flat speed work.'),
    'mp_run': ('Marathon-pace run', 'Lock in race rhythm at goal effort.'),
    'xt_easy': ('Easy cross-training', 'Aerobic fitness with zero foot strike (easy on tendons and joints).'),
    'xt_intervals': ('Bike intervals', 'Top-end aerobic work without running impact.'),
    'tt5k': ('5 km time trial', 'Checkpoint: re-calibrates every pace in your plan.'),
    'tt10k': ('10 km time trial', 'Checkpoint: re-calibrates your paces and prediction.'),
    'half': ('Half-marathon rehearsal', 'Dress rehearsal: shoes, fuel, pacing, routine.'),
    'race': ('MARATHON', 'Everything has been building to this. Run your race.'),
}

SLOT_HINT = {
    'long': 'Weekend morning', 'long_mp': 'Weekend morning', 'tt5k': 'Morning', 'tt10k': 'Morning', 'half': 'Morning',
}

# Ultra-minimal dose (short blocks get done): once a week, one set of
# hops, then a heavy hinge and heavy calves, two sets each (~13 min). Keep proper rest for the heavy lifts.
STRENGTH_LOWER = {
    'base': [('Pogo hops', 1, '10'), ('Romanian deadlift', 2, '6'), ('Standing calf raise', 2, '10 slow')],
    'build': [('Pogo hops', 1, '10'), ('Romanian deadlift', 2, '5 heavy'), ('Standing calf raise', 2, '8 heavy')],
    'maintain': [('Pogo hops', 1, '10'), ('Romanian deadlift', 2, '4 heavy'), ('Standing calf raise', 2, '8 heavy')],
}
# At home (15 kg kettlebell, a step): single-leg versions make the light bell heavy enough.
HOME_LOWER = [('Pogo hops', 1, '10'), ('Single-leg RDL', 2, '8 / leg (15 kg KB)'),
              ('Standing calf raise', 2, '10 / leg on a step')]
# Away from a gym (travel): the same order, bodyweight or a loaded backpack. Single-leg work and plyos keep most of
# the economy stimulus without a barbell.
TRAVEL_LOWER = [('Pogo hops', 1, '10'), ('Single-leg RDL', 2, '8 / leg (backpack)'),
                ('Standing calf raise', 2, '12 single-leg on a step')]
TRAVEL_UPPER = [('Push-up', 2, '8–15'), ('Backpack row', 2, '10–15'), ('Dead bug', 2, '8 / side')]
STRENGTH_UPPER = [('DB row', 2, '8–12'), ('Incline DB press', 2, '8–12'), ('Dead bug', 2, '8 / side')]
# At home (light dumbbells, a kettlebell, mat, chin-up bar): the same pull/press/core pattern.
# Loads are fixed by the kit, so they come from HOME_LOADS, never from gym history.
HOME_UPPER = [('Chin-up', 2, '3–8 (stop 2 short)'), ('Push-up', 2, '8–15'), ('Dead bug', 2, '8 / side')]
HOME_LOADS = {'KB row': 15, 'Reverse fly': 4, 'Lateral raise': 5}
MOBILITY = ['Couch stretch 2×45 s / side', 'Calf wall stretch 2×30 s / side', 'Hip 90/90 2×5 / side',
            'Ankle wall mobility 2×10 / side', 'Foam roll calves, quads, glutes 60 s each']
# Starting loads per exercise (kg); empty = the app suggests a load with 2 reps in reserve.
DEFAULT_LOADS = {}
PER_HAND = {'Reverse fly', 'Bulgarian split squat', 'Single-leg RDL', 'Step-up', 'Farmer carry', 'DB row', 'Incline DB press',
            'Lateral raise', 'Incline DB curl', 'Goblet squat'}


def _pace_target(rng):
    return {'type': 'pace', 'fast': round(rng[0]), 'slow': round(rng[1]),
            'text': f"{phys.fmt_pace(rng[0])}–{phys.fmt_pace(rng[1])} /km"}


def _hr_target(lo, hi):
    return {'type': 'hr', 'low': int(lo), 'high': int(hi), 'text': f"{int(lo)}–{int(hi)} bpm"}


def _step(kind, minutes=None, meters=None, target=None, name=None, note=None):
    st = {'type': kind, 'name': name or kind.replace('_', ' ').title()}
    if minutes is not None:
        st['duration'] = {'type': 'time', 'seconds': int(round(minutes * 60))}
    elif meters is not None:
        st['duration'] = {'type': 'distance', 'meters': int(meters)}
    else:
        st['duration'] = {'type': 'open'}
    if target:
        st['target'] = target
    if note:
        st['note'] = note
    return st


def _repeat(times, steps):
    return {'type': 'repeat', 'times': int(times), 'steps': steps}


def _round_half(x):
    return max(0.5, round(x * 2) / 2)


def estimate_km(steps, paces):
    easy_mid = sum(paces['easy']) / 2
    total = 0.0

    def walk(sts, mult=1):
        nonlocal total
        for s in sts:
            if s['type'] == 'repeat':
                walk(s['steps'], mult * s['times'])
                continue
            d = s.get('duration', {})
            if d.get('type') == 'distance':
                total += mult * d['meters'] / 1000
            elif d.get('type') == 'time':
                t = s.get('target')
                pace = (t['fast'] + t['slow']) / 2 if t and t['type'] == 'pace' else easy_mid
                if s.get('walk'):
                    pace = 600
                total += mult * d['seconds'] / pace
    walk(steps)
    return round(total, 1)


def total_minutes(steps):
    tot = 0.0

    def walk(sts, mult=1):
        nonlocal tot
        for s in sts:
            if s['type'] == 'repeat':
                walk(s['steps'], mult * s['times'])
                continue
            d = s.get('duration', {})
            if d.get('type') == 'time':
                tot += mult * d['seconds'] / 60
    walk(steps)
    return round(tot)


def strength_block(kind, dtr, loads, timing=None, gym=True, returning=False):
    timing = timing or {}
    if kind == 'strength_lower':
        phase = 'maintain' if dtr <= 56 else 'build' if dtr <= 112 else 'base'
        items = STRENGTH_LOWER[phase] if gym else TRAVEL_LOWER
        title = 'Legs · essentials' + ('' if gym else ' (no gym)')
        why = ('Once a week, about 10 minutes: one set of small, quiet pogo hops, then a heavy hinge and heavy '
               'calves. Warm up with one lighter set before the deadlift. Rest 2 minutes between heavy sets; stop '
               'with 2 good reps left. Skip hops if landings are uncomfortable. No catch-up after a missed week. '
               'This small dose keeps the leg strength that supports economical running late in the race; add the '
               'smallest load increment when both sets feel comfortable.')
    elif kind == 'strength_upper':
        items = STRENGTH_UPPER if gym else TRAVEL_UPPER
        title = 'Upper body · essentials' + ('' if gym else ' (no gym)')
        why = ('Just a pull, a push and core, two sets each. Warm up with an easy set of the pull and push. '
               'Rest 60–90 seconds between sets; stop with 2 good reps left. First two sessions back: one set each. '
               'Use the home version to avoid a separate gym trip.')
        if gym:
            home = _items([(n, 1 if returning else sets, r) for n, sets, r in HOME_UPPER], HOME_LOADS.get)
            sets = sum(i['sets'] for i in home)
            alt = {'title': 'Upper body · essentials (home)' + (' · restart' if returning else ''), 'items': home, 'est_min': int(round(4 + timing.get('min_per_set', 1.9) * sets)),
                   'note': 'Chin-up bar and mat only. Use foot-assisted chin-ups if needed; use incline push-ups if 8 floor reps are too hard.'}
    else:
        mob = int(round(timing.get('mobility_min', 15)))
        return {'kind': 'mobility', 'title': f'Mobility ({mob} min)', 'items': [{'name': m} for m in MOBILITY],
                'why': 'Keeps hips and ankles moving; feels good, low cost.', 'est_min': mob}
    def gym_load(name):
        last = loads.get(name) if gym else None
        if last:
            load = last['load'] + (2.5 if last.get('easy') and not returning else 0)
        else:
            load = DEFAULT_LOADS.get(name) if gym else None
        return _round_half(load * .75) if returning and load else load
    if returning:
        items = [(n, 1, r.replace(' heavy', '')) for n, _, r in items]
        title += ' · restart'
        why = why.replace('two sets each', 'one easy set each').replace('stop with 2 good reps left', 'stop with 3–4 good reps left')
        why = 'One easy working set per exercise today. Rebuild the habit first; stop with 3–4 reps left. ' + why
    out = _items(items, gym_load)
    # duration learned from the runner's own logs: minutes per set (incl. rests and setup) + a short warm-up
    sets = sum(i['sets'] for i in out if i.get('sets'))
    est = int(round(4 + timing.get('min_per_set', 1.9) * sets))
    block = {'kind': kind, 'title': title, 'items': out, 'why': why, 'est_min': est, 'reentry': returning}
    if kind == 'strength_lower' and gym:
        home = _items([(n, 1 if returning else sets, r) for n, sets, r in HOME_LOWER], lambda n: None)
        n_sets = sum(i['sets'] for i in home)
        block['home'] = {'title': 'Legs · essentials (home)' + (' · restart' if returning else ''), 'items': home,
                         'est_min': int(round(4 + timing.get('min_per_set', 1.9) * n_sets)),
                         'note': '15 kg kettlebell and a step. Hold the wall for balance on the single-leg RDL if needed.'}
    if kind == 'strength_upper' and gym:
        block['home'] = alt
    return block


def _items(items, load_for):
    out = []
    for name, sets, reps in items:
        load = load_for(name)
        item = {'name': name, 'sets': sets, 'reps': reps, 'load_kg': load}
        if load is not None and name in PER_HAND and name != 'Goblet squat':
            item['per_hand'] = True
        out.append(item)
    return out


# Heart-rate bands as fractions of heart-rate reserve (Karvonen; %HRR ~ %VO2R, Swain 1997), mapped to the
# Daniels intensities each step targets. Short reps (strides, hill sprints) finish before HR catches up, so they
# are effort-based and carry no HR band.
HR_BANDS = {
    'recovery': (0.50, 0.65, 'Recovery'), 'easy': (0.60, 0.72, 'Easy / Zone 2'), 'long': (0.62, 0.75, 'Long-run aerobic'),
    'marathon': (0.76, 0.84, 'Marathon effort'), 'half': (0.82, 0.87, 'Half-marathon effort'),
    'threshold': (0.84, 0.89, 'Threshold'), 'interval': (0.90, 0.97, 'VO2 — reached late in each rep'),
    'xt_easy': (0.55, 0.70, 'Easy (cycling HR runs ~5-10 lower)'), 'xt_hard': (0.83, 0.92, 'Hard (bike)'),
    'race5k': (0.92, 1.00, '5 km all-out'), 'race10k': (0.88, 0.96, '10 km race'),
}
EASY_FIT = {'recovery', 'easy', 'long', 'xt_easy'}   # watch target = HR for these; quality reps keep pace

TIMING = {
    'long': 'Weekend morning, around your race start time. Rehearse breakfast 3 h before, fuel and toilet routine. '
            'Start earlier on hot days.',
    'easy': 'Whenever suits. Mornings are cooler and get it done.',
    'quality': 'Morning or late afternoon, whichever you feel better for. Finish 3 h+ before bed.',
    'xt': 'Any time. No impact and easy on sleep; keep it 2 h+ before bed.',
    'strength': 'Later on the same day as the run: hours apart limits interference and keeps the next day easy.',
    'event': 'Morning, like race day.',
    'recovery': 'Whenever suits. A lunchtime walk counts.',
}
TIMING_KIND = {'long': 'long', 'long_mp': 'long', 'easy': 'easy', 'easy_strides': 'easy', 'threshold': 'quality', 'vo2': 'quality',
               'hills': 'quality', 'mp_run': 'quality', 'xt_easy': 'xt', 'xt_intervals': 'xt', 'tt5k': 'event', 'tt10k': 'event',
               'half': 'event', 'race': 'event', 'recovery': 'recovery'}


def hr_band(key, hr_max, hr_rest):
    lo, hi, label = HR_BANDS[key]
    r = hr_max - hr_rest
    a, b = round(hr_rest + lo * r), round(hr_rest + hi * r)
    return {'type': 'hr', 'low': a, 'high': b, 'label': label, 'text': f"♥ {a}–{b} bpm · {label}"}


def _band_for(step, kind, sport):
    name = step.get('name', '')
    if sport == 'cycling':
        return 'xt_hard' if name == 'Hard' else 'xt_easy'
    if step['type'] == 'recovery' or step.get('walk') or name == 'Walk':
        return 'recovery'
    if step['type'] in ('warmup', 'cooldown'):
        return 'easy'
    if name in ('Stride', 'Uphill hard'):
        return None
    if name == 'Race':
        return {'tt5k': 'race5k', 'tt10k': 'race10k', 'half': 'half', 'race': 'marathon'}[kind]
    return {'Long run': 'long', 'Steady': 'long', 'Marathon pace': 'marathon', 'Threshold': 'threshold',
            'Hard': 'interval'}.get(name, 'easy')


def assign_hr(steps, kind, sport, hr_max, hr_rest):
    """Give every step an HR range for the session's goal and pick the watch (FIT) target."""
    for s in steps:
        if s['type'] == 'repeat':
            assign_hr(s['steps'], kind, sport, hr_max, hr_rest)
            continue
        key = _band_for(s, kind, sport)
        if s.get('note', '').startswith('HR under'):
            s.pop('note')
        if key is None:
            s['hr'] = {'type': 'none', 'text': '♥ too short for HR — go by feel'}
            continue
        s['hr'] = hr_band(key, hr_max, hr_rest)
        if s.get('walk') or s.get('name') == 'Walk' or (key == 'recovery' and s['type'] != 'cooldown' and 'jog' not in s.get('name', '').lower()):
            s['hr'] = dict(s['hr'], low=int(hr_rest), text=f"♥ under {s['hr']['high']} bpm · let it settle")
        if s.get('target', {}).get('type') == 'hr':
            s.pop('target')   # the goal-based band replaces the older generic HR target
        if key in EASY_FIT or not s.get('target') or s['target'].get('type') != 'pace':
            s['fit_target'] = s['hr']


def build(date, cand, sec, dur, vdot, program, dtr, loads, event=None):
    """Concrete workout for one day. `dur` holds scalar session sizes from model.durations."""
    ath = program['athlete']
    hr_max, hr_rest = ath['hr_max'], ath['hr_rest']
    paces = phys.training_paces(vdot)
    easy = _pace_target(paces['easy'])
    easy_hr = _hr_target(hr_rest + 0.55 * (hr_max - hr_rest), phys.hr_cap_for('easy', hr_max, hr_rest))
    long_t = _pace_target(paces['long'])
    kind = event or cand
    title, blurb = TITLES[kind]
    if kind == 'long' and float(dur['L']) < 50:
        title, blurb = 'Longer easy run', 'Your longest run of the week — builds durability one step at a time (≤10 % jumps).'
    steps, fuel, notes = [], [], []
    fuel_plan = None   # watch gel reminders: first_s, every_s (25 g carbs per gel)
    sport = 'running'
    E, L, Qt, Qv, MPw, X = (float(dur[k]) for k in ('E', 'L', 'Qt', 'Qv', 'MPw', 'X'))
    week = max(0.0, (program['_horizon'] - dtr) / 7.0)
    if kind == 'rest':
        sport = None
        notes.append('Optional: easy 20–30 min walk. Sleep 8 h+ tonight.')
    elif kind == 'recovery':
        sport = 'walking'
        steps = [_step('active', 30, target=_hr_target(hr_rest + 20, phys.hr_cap_for('recovery', hr_max, hr_rest)),
                       name='Walk')]
        steps[0]['walk'] = True
    elif kind in ('easy', 'easy_strides'):
        steps = [_step('warmup', 5, name='Walk / easy jog'), _step('active', max(10, round(E) - 5), target=easy,
                                                                    name='Easy run', note=f"HR under {easy_hr['high']}")]
        steps[0]['walk'] = True
        if kind == 'easy_strides':
            steps.append(_repeat(6, [_step('active', 20 / 60, target=_pace_target(paces['repetition']), name='Stride',
                                           note='Fast but relaxed, tall, quick feet'),
                                     _step('recovery', 1, name='Walk back')]))
        steps.append(_step('cooldown', 3, name='Walk'))
    elif kind in ('long', 'long_mp'):
        total = round(L)
        if kind == 'long_mp':
            mp_min = round(total * float(program['_policy'].get('mp_frac', 0.3)) / 5) * 5
            mp_min = max(15, min(mp_min, 90))
            steps = [_step('warmup', 10, target=easy, name='Easy start'),
                     _step('active', max(10, total - 10 - mp_min), target=long_t, name='Steady'),
                     _step('active', mp_min, target=_pace_target(paces['marathon']), name='Marathon pace'),
                     _step('cooldown', 5, name='Walk')]
        else:
            steps = [_step('warmup', 10, target=easy, name='Easy start'),
                     _step('active', max(10, total - 10), target=long_t, name='Long run',
                           note=f"HR under {phys.hr_cap_for('long', hr_max, hr_rest)}"),
                     _step('cooldown', 5, name='Walk')]
        steps[-1]['walk'] = True
        if total >= 70:
            rate = 30 if week < 6 else 45 if week < 12 else 60 if week < 17 else 75
            fuel.append(f"Practise fuelling: ~{rate} g carbs/hour from minute 30 (gel/chews/drink) — gut training "
                        f"(Costa 2017). Race target is 75 g/h from minute 20.")
            fuel_plan = {'first_s': 30 * 60, 'every_s': max(15, round(25 / rate * 60)) * 60}
            fuel.append('Carb-rich dinner the night before; breakfast 2–3 h before.')
        notes.append('Soft surface or treadmill for part of it if calves feel beaten up.')
    elif kind == 'threshold':
        n = max(2, math.ceil(Qt / 10))
        rep = _round_half(Qt / n)
        steps = [_step('warmup', 12, target=easy, name='Warm up'),
                 _repeat(n, [_step('active', rep, target=_pace_target(paces['threshold']), name='Threshold',
                                   note='Comfortably hard — short phrases, not sentences'),
                             _step('recovery', 1.5 if rep >= 6 else 1, name='Easy jog')]),
                 _step('cooldown', 8, target=easy, name='Cool down')]
    elif kind == 'vo2':
        rep = 2 if week < 6 else 3 if week < 13 else 4
        n = max(3, round(Qv / rep))
        steps = [_step('warmup', 15, target=easy, name='Warm up (incl. 3 strides)'),
                 _repeat(n, [_step('active', rep, target=_pace_target(paces['interval']), name='Hard',
                                   note='~3–5 km race effort, controlled'),
                             _step('recovery', rep * 0.8, name='Easy jog / walk')]),
                 _step('cooldown', 8, target=easy, name='Cool down')]
    elif kind == 'hills':
        steps = [_step('warmup', 15, target=easy, name='Warm up'),
                 _repeat(8, [_step('active', 1, name='Uphill hard', note='Strong drive, ~5 km effort; '
                                                                          'treadmill 6–8 % incline works'),
                             _step('recovery', 1.5, name='Jog / walk down')]),
                 _step('cooldown', 10, target=easy, name='Cool down')]
    elif kind == 'mp_run':
        steps = [_step('warmup', 10, target=easy, name='Warm up'),
                 _step('active', round(MPw), target=_pace_target(paces['marathon']), name='Marathon pace'),
                 _step('cooldown', 5, target=easy, name='Cool down')]
    elif kind == 'xt_easy':
        sport = 'cycling'
        steps = [_step('active', round(X), target=easy_hr, name='Bike / elliptical / row',
                       note='Any zero-impact machine. Zone 2, nose-breathing easy.')]
    elif kind == 'xt_intervals':
        sport = 'cycling'
        z5 = _hr_target(0.88 * hr_max, 0.94 * hr_max)   # VO2 intensity; HR climbs into the band by minute 2-3
        steps = [_step('warmup', 10, target=easy_hr, name='Easy spin'),
                 _repeat(5, [_step('active', 4, target=z5, name='Hard', note='RPE 8–9 — hard breathing, can\'t talk'),
                             _step('recovery', 3, name='Easy spin')]),
                 _step('cooldown', 5, name='Easy spin')]
    elif kind in ('tt5k', 'tt10k', 'half', 'race'):
        dist = EVENTS[kind]
        t = float(phys.race_time(dist, vdot))
        pace = t * 60 / (dist / 1000)
        target = {'type': 'pace', 'fast': round(pace - 3), 'slow': round(pace + 3),
                  'text': f"{phys.fmt_pace(pace)} /km (≈ {phys.fmt_hms(t)})"}
        warm = [] if kind == 'race' else [_step('warmup', 15, target=easy, name='Warm up + 4 strides')]
        steps = warm + [_step('active', meters=dist, target=target, name='Race',
                              note='Even pace; first km no faster than target')]
        if kind != 'race':
            steps.append(_step('cooldown', 10, target=easy, name='Cool down'))
        if dist > 20000:
            fuel.append(('75 g carbs/hour (glucose+fructose) from minute 20' if kind == 'race' else
                         '60–75 g carbs/hour (glucose+fructose) from minute 20') + '; drink to thirst (~400–700 ml/h).')
            fuel_plan = {'first_s': 25 * 60, 'every_s': 20 * 60}
        if kind == 'race':
            fuel.insert(0, 'Carb-load ~7 g/kg Friday and ~10 g/kg Saturday, low fibre (Burke 2011; Bussau 2002). '
                           'Breakfast 3 h before. Caffeine ~3 mg/kg 60 min before the start (Guest 2021); optional '
                           '100 mg caffeine gel at 25–30 km. Check what the course provides and carry the rest.')
            mp_hr = hr_band('marathon', hr_max, hr_rest)
            notes.append('First 5 km 5–10 s/km slower than goal pace; settle at 25–30 km, then race.')
            notes.append(f"Keep HR ≤ {mp_hr['high']} until 30 km; expect it to drift up late — that's fine, pace rules after 30 km.")
    workout = {
        'date': date.isoformat(), 'kind': kind, 'title': title, 'blurb': blurb, 'sport': sport, 'steps': steps,
        'fuel': fuel, 'notes': notes, 'fuel_plan': fuel_plan, 'slot_hint': SLOT_HINT.get(kind),
        'paces': {k: [round(v[0]), round(v[1])] for k, v in paces.items()},
        'hr': {'easy_cap': phys.hr_cap_for('easy', hr_max, hr_rest), 'long_cap': phys.hr_cap_for('long', hr_max, hr_rest)},
    }
    if steps:
        workout['minutes'] = total_minutes(steps) if kind not in ('tt5k', 'tt10k', 'half', 'race') else round(
            float(phys.race_time(EVENTS[kind], vdot)) + (0 if kind == 'race' else 25))
        if sport == 'running':
            workout['km'] = estimate_km(steps, paces)
    else:
        workout['minutes'] = 0
    assign_hr(steps, kind, sport, hr_max, hr_rest)
    tk = TIMING_KIND.get(kind, '')
    if tk == 'long' and date.weekday() < 5:
        tk = 'easy'   # a weekday "long" run is a morning-slot run
    workout['timing'] = TIMING.get(tk)
    trip = extras.travel_day(program, date)
    gym = not trip or trip['stay'].get('gym') is True
    workout['secondary'] = strength_block(sec, dtr, loads, program.get('_timing'), gym=gym,
                                         returning=program.get('_strength_reentry', {}).get(sec, 0) > 0) if sec and sec != 'none' else None
    if workout['secondary'] and workout['secondary']['kind'] != 'mobility':
        workout['secondary']['timing'] = TIMING['strength'] if kind not in ('rest', 'recovery') else \
            'Any time today — no run to work around, so pick whenever you feel best (after 10 am is ideal for strength).'
    if workout['secondary'] and workout['secondary']['kind'] != 'mobility':
        workout['minutes'] = workout.get('minutes', 0) + workout['secondary']['est_min']
    if trip:
        travel_notes(workout, trip)
    return workout


def travel_notes(w, trip):
    """Away from home: where to run, local start time, heat, and the gym situation."""
    stay = trip['stay']
    w['travel'] = {'trip': trip['trip'], 'place': stay.get('place'), 'note': trip['note'], 'run': stay.get('run'),
                   'gym': stay.get('gym_note'), 'slot': trip['slot'], 'general': trip.get('general')}
    w['slot_hint'] = f"Start {trip['slot']} local time"
    tips = []
    if w['kind'] not in ('rest',) and w.get('sport') == 'running' and stay.get('run'):
        tips.append(f"{stay.get('place')}: {stay['run']}")
    if w.get('sport') in ('running', 'walking') and stay.get('place') != 'Ella':
        tips.append('Heat: run by heart rate (pace will be slower, that\'s fine), 500 ml with electrolytes per hour, '
                    'and finish before the sun is high.')
    if w['kind'] == 'xt_easy':
        w['title'] = 'Easy cross-training: swim or hike'
        w['blurb'] = 'No bike on the trip: an easy pool or sea swim, or a brisk hill walk, at the same easy effort.'
        for s in w['steps']:
            if s.get('name') == 'Bike / elliptical / row':
                s['name'] = 'Swim / brisk hike'
                s['note'] = 'Easy, conversational effort. Swim HR runs ~10 lower: go by feel.'
    sec = w.get('secondary')
    if sec and sec['kind'] != 'mobility':
        sec['timing'] = (stay.get('gym_note') + ' ' if stay.get('gym_note') and stay.get('gym') is not True else '') + \
            ('Use the gym: ' + stay['gym_note'] if stay.get('gym') is True and stay.get('gym_note') else
             'Bodyweight or a loaded backpack, any time today (hotel room or garden).')
    w['notes'] = [trip['note']] + tips + w.get('notes', [])
