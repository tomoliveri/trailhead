"""Relative aerobic progress from steady, grade-adjusted run sections.

No absolute VDOT inference from estimated HRmax. Compare to the athlete's own
reference runs; races reset that reference. Cached streams stay outside logs.
"""
import datetime as dt
import json
import math
import os
import tempfile
from pathlib import Path
import numpy as np

STREAMS = Path(__file__).resolve().parents[1] / 'data' / 'run_streams'
VERSION = 1


def number(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def from_garmin(details):
    # Garmin details values already use their named units; unit.factor is display
    # metadata, not a multiplier (e.g. sumDistance is metres despite factor=100).
    descriptors = {d['key']: d['metricsIndex'] for d in details.get('metricDescriptors', [])}
    out = []
    for row in details.get('activityDetailMetrics', []):
        values = row.get('metrics') or []
        def get(key):
            i = descriptors.get(key)
            return number(values[i]) if i is not None and i < len(values) else None
        t = get('directTimestamp')
        if t is None:
            t = get('sumElapsedDuration')
        else:
            t /= 1000
        out.append([t, get('sumDistance'), get('directElevation'), get('directHeartRate'),
                    get('directSpeed'), get('directDoubleCadence')])
    valid = [r for r in out if all(v is not None for v in r[:4])]
    if not valid:
        return []
    start = valid[0][0]
    return [[round(r[0] - start, 2), *r[1:]] for r in valid]


def stream_path(log):
    aid = (log.get('garmin') or {}).get('activityId')
    return STREAMS / f'{int(aid)}.json' if aid and str(aid).isdigit() else None


def backfill(g, store, limit=8):
    """Bounded automatic backfill; never overwrite logs or require API in planning."""
    since = (dt.date.today() - dt.timedelta(days=180)).isoformat()
    pending = [lg for lg in store.logs(since) if lg['kind'] in ('run', 'trail')
               and stream_path(lg) and not stream_path(lg).exists()]
    saved = 0
    for lg in pending[:limit]:
        samples = from_garmin(g.get_activity_details(lg['garmin']['activityId'], maxchart=10000, maxpoly=0))
        if not samples:
            continue  # incomplete Garmin upload: retry next sync
        STREAMS.mkdir(parents=True, exist_ok=True)
        path = stream_path(lg)
        fd, tmp = tempfile.mkstemp(dir=STREAMS, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump({'version': VERSION, 'samples': samples}, f, separators=(',', ':'))
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        saved += 1
    if saved:
        store.bump()  # invalidate plan/prediction caches after new traces arrive
    return saved


def cost(grade):
    # Minetti et al. (2002), running energy cost J/kg/m; relative to flat.
    return 155.4*grade**5 - 30.4*grade**4 - 43.3*grade**3 + 46.3*grade**2 + 19.5*grade + 3.6


def half_ratio(samples):
    """Grade-adjusted speed of the second half over the first, by moving time (None if under 20 min moving).

    15-second sections; stops (< 1.2 m/s) are left out so traffic lights don't count as fading."""
    a = np.array([[number(v) if number(v) is not None else np.nan for v in r[:3]] for r in samples if len(r) >= 3], dtype=float)
    a = a[np.all(np.isfinite(a), axis=1)] if len(a) else a
    if len(a) < 60:
        return None, 0.0
    a = a[np.argsort(a[:, 0])]
    t = np.arange(a[0, 0], a[-1, 0], 15)
    d = np.diff(np.interp(t, a[:, 0], a[:, 1]))
    e = np.diff(np.interp(t, a[:, 0], a[:, 2]))
    moving = d / 15 > 1.2
    grade = np.clip(np.where(d > 1, e / np.maximum(d, 1), 0), -.15, .15)
    flat = d * cost(grade) / cost(0)
    mt = np.cumsum(moving * 15.0)
    if mt[-1] < 20 * 60:
        return None, float(mt[-1] / 60)
    h1, h2 = moving & (mt <= mt[-1] / 2), moving & (mt > mt[-1] / 2)
    return float((flat[h2].sum() / h2.sum()) / (flat[h1].sum() / h1.sum())), float(mt[-1] / 60)


_fade_cache = {}


def second_half_fade(logs, planned_min, today=None):
    """The runner's usual slowdown in the second half of runs about this long (0-0.12), for the watch's turn-for-home cue.

    Runs from the last 120 days with a Garmin trace; those lasting at least 60 % of the planned session, else the
    longest five. Defaults to 3 % with fewer than three usable runs. Never assumes a faster return."""
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=120)).isoformat()
    rows = []
    for lg in logs:
        path = stream_path(lg)
        if lg['kind'] not in ('run', 'trail') or lg['date'] < since or not path or not path.exists() \
                or lg.get('run_type') in ('race', 'intervals', 'hills'):
            continue
        key = (str(path), path.stat().st_mtime)
        if key not in _fade_cache:
            try:
                _fade_cache[key] = half_ratio(json.loads(path.read_text()).get('samples', []))
            except (ValueError, OSError):
                _fade_cache[key] = (None, 0.0)
        ratio, minutes = _fade_cache[key]
        if ratio is not None:
            rows.append((minutes, ratio))
    if len(rows) < 3:
        return 0.03
    similar = [r for m, r in rows if m >= .6 * planned_min]
    if len(similar) < 3:
        similar = [r for _, r in sorted(rows)[-5:]]
    return round(float(np.clip(1 - np.median(similar), 0, .12)), 3)


def run_observation(log, athlete):
    path = stream_path(log)
    samples = (log.get('garmin') or {}).get('run_samples')
    if samples is None and path and path.exists():
        try:
            samples = json.loads(path.read_text()).get('samples', [])
        except (ValueError, OSError):
            return None
    if not samples or log.get('run_type') in ('race', 'tempo', 'intervals', 'hills', 'marathon_pace'):
        return None
    rest, maximum = float(athlete['hr_rest']), float(athlete['hr_max'])
    if maximum <= rest:
        return None
    a = np.array([[number(v) if number(v) is not None else np.nan for v in r]
                  for r in samples if len(r) == 6], dtype=float)
    if len(a) < 20:
        return None
    a = a[np.all(np.isfinite(a[:, :4]), axis=1)]
    a = a[np.argsort(a[:, 0])]
    if len(a) < 20:
        return None
    # Non-overlapping 60-second sections, after five minutes' warm-up. Use
    # three 30-second grades to reduce elevation noise and reject transitions.
    sections = []
    for start in np.arange(a[0, 0] + 300, a[-1, 0] - 60, 60):
        w = a[(a[:, 0] >= start) & (a[:, 0] <= start + 60)]
        if len(w) < 10 or w[-1, 0] - w[0, 0] < 55 or np.max(np.diff(w[:, 0])) > 10:
            continue
        durations = np.diff(w[:, 0]); distances = np.diff(w[:, 1])
        # Ten-second distance differences suppress one-second GPS jitter.
        speed_times = np.arange(w[0, 0], w[-1, 0], 10)
        speeds = np.diff(np.interp(speed_times, w[:, 0], w[:, 1])) / 10
        if np.any(distances < 0) or np.mean((speeds >= 1.5) & (speeds <= 4.5)) < .9:
            continue
        cad = w[:, 5][np.isfinite(w[:, 5]) & (w[:, 5] > 0)]
        if len(cad) < len(w) * .7 or np.mean(cad >= 130) < .9:
            continue  # walking cannot use the running gradient-cost equation
        if np.std(speeds) / np.mean(speeds) > .20:
            continue
        hr = w[w[:, 0] >= start + 30, 3]  # avoid early HR response after transition
        h = float(np.median(hr)); hrr = (h - rest) / (maximum - rest)
        if not .5 <= hrr <= .85 or np.ptp(np.percentile(hr, [10, 90])) > 15:
            continue
        bounds = np.linspace(w[0, 0], w[-1, 0], 4)
        d = np.diff(np.interp(bounds, w[:, 0], w[:, 1]))
        e = np.diff(np.interp(bounds, w[:, 0], w[:, 2]))
        if np.any(d < 20):
            continue
        grades = e/d
        if np.max(np.abs(grades)) > .10 or np.ptp(grades) > .04:
            continue
        gap_speed = float(np.sum(d * cost(grades) / cost(0)) / (w[-1, 0] - w[0, 0]))
        sections.append((gap_speed / hrr, h, gap_speed, float(np.mean(grades))))
    if len(sections) < 5:
        return None
    x = np.array(sections)
    return {'date': log['date'], 'id': log.get('id'), 'sections': len(sections),
            'steady_min': round(len(sections), 1), 'efficiency': float(np.median(x[:, 0])),
            'avg_hr': round(float(np.median(x[:, 1])), 1),
            'grade_adjusted_pace_s_km': round(1000/float(np.median(x[:, 2]))),
            'pace_at_reference_hr_s_km': round(1000/(float(np.median(x[:, 0]))*.65))}


def analyse(program, logs, until, timeline):
    """Return observed trend and bounded VDOT correction, computed from scratch."""
    cutoff = until.isoformat()
    races = [lg['date'] for lg in logs if lg['date'] < cutoff and lg.get('run_type') == 'race'
             and lg['kind'] in ('run', 'trail', 'treadmill') and (number(lg.get('distance_km')) or 0) >= 1.5
             and (number(lg.get('duration_min')) or 0) > 0]
    anchor = max(races, default=program['plan_start'])
    observations = []
    recorded_runs = 0
    for lg in logs:
        if lg['kind'] not in ('run', 'trail', 'treadmill') or not anchor <= lg['date'] < cutoff:
            continue
        recorded_runs += 1
        obs = run_observation(lg, program['athlete'])
        if obs:
            observations.append(obs)
    observations.sort(key=lambda o: o['date'])
    result = {'method': 'steady-grade-adjusted-heart-rate', 'reference_hr': round(
              float(program['athlete']['hr_rest']) + .65*(float(program['athlete']['hr_max'])-float(program['athlete']['hr_rest']))),
              'recorded_runs': recorded_runs, 'runs': observations, 'eligible_runs': len(observations), 'correction_vdot': 0.0,
              'status': 'insufficient_data', 'message': 'Learning: need at least six qualifying runs across two weeks; walking, warm-up and unstable sections are excluded.'}
    # Each day is one vote; many samples from one run do not inflate confidence.
    days = {}
    for o in observations:
        days.setdefault(o['date'], []).append(o)
    if len(days) < 6:
        return result
    dates = sorted(days)
    first = dt.date.fromisoformat(dates[0]); last = dt.date.fromisoformat(dates[-1])
    if (until-last).days > 14:
        result.update(status='stale', message='Run evidence is more than two weeks old; no fitness adjustment.')
        return result
    if (last-first).days < 14:
        return result
    # First three usable days, rather than the first calendar week: run/walk
    # return-to-running can otherwise leave the reference permanently empty.
    reference = dates[:3]
    if (dt.date.fromisoformat(reference[-1])-first).days > 21:
        candidates = [dates[i:i+3] for i in range(len(dates)-5)
                      if (dt.date.fromisoformat(dates[i+2])-dt.date.fromisoformat(dates[i])).days <= 21]
        if not candidates:
            return result
        reference = candidates[0]
    recent = [d for d in dates if dt.date.fromisoformat(d) > last-dt.timedelta(days=7) and d not in reference]
    if len(reference) < 3 or len(recent) < 3 or (last-dt.date.fromisoformat(reference[0])).days < 14:
        return result
    def median(field, selected):
        return float(np.median([np.median([o[field] for o in days[d]]) for d in selected]))
    if abs(median('avg_hr', reference)-median('avg_hr', recent)) > 8:
        result.update(status='unmatched_effort', message='Recent runs differ too much in effort for a reliable fitness comparison.')
        return result
    before, after = median('efficiency', reference), median('efficiency', recent)
    change = after/before-1
    # Robust spread across days; prevent a noisy trend from moving fitness.
    ref_values = np.array([median('efficiency', [d]) for d in reference])
    new_values = np.array([median('efficiency', [d]) for d in recent])
    noise = float(np.sqrt((1.4826*np.median(abs(ref_values-before))/before)**2/len(reference)
                         +(1.4826*np.median(abs(new_values-after))/after)**2/len(recent)))
    result.update(improvement_pct=round(change*100, 1), uncertainty_pct=round(max(.02, 2*noise)*100, 1),
                  reference_dates=reference, recent_dates=recent,
                  reference_pace_s_km=round(1000/(before*.65)), recent_pace_s_km=round(1000/(after*.65)))
    model = {t['date']: t['vdot'] for t in timeline}
    if not all(d in model for d in reference+recent):
        return result
    base = float(np.median([model[d] for d in reference]))
    current = float(np.median([model[d] for d in recent]))
    weight = min(.5, len(recent)/20)  # modest weight; checkpoints remain authoritative
    correction = float(np.clip(base*(1+np.clip(change, -.08, .08))-current, -2, 2))*weight
    if noise > .05:
        correction = 0
        result.update(status='noisy', message='Run comparisons are noisy; trend shown without changing fitness.')
    else:
        result.update(status='learning', message='Comparing steady running at similar effort after adjusting for hills. Fitness receives a small correction; heat, wind and surface can still affect the trend.')
    result['correction_vdot'] = round(correction, 4)
    return result
