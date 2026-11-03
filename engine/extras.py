"""Per-session extras on top of the training plan: what to listen to, which mental skill to practise, which
shoes, race-morning rehearsals, and dated reminders (nitrate shots, new shoes, packing).

None of this changes training load; it is attached to each planned day after the planner has chosen it.
Sources: Blanchfield 2014 (motivational self-talk, +18 % time to exhaustion); Jones 2014 / Senefeld 2020
(dietary nitrate, ~6–8 mmol 2–3 h before; small gains in recreational runners); Hoogkamer 2018 / Hébert-Losier 2022
(super-shoe economy); race rules on earphones (one ear open / low volume).
"""
import datetime as dt

# Audiobooks, played one after another across the easy, long and recovery sessions, so each book is finished
# before the next one starts. Unabridged lengths (Audible/retailer listings, Oct 2026).
BOOKS = []   # (title, author, minutes, why) - optional audiobook queue
BOOKS_FROM = '2026-10-08'   # listening counted from logs after this date
BOOKS_DONE = 669 - 312      # already listened when the list started: Endure had 5 h 12 min left on 7 Oct 2026
# Share of a session's minutes that are listening time (warm-ups, drills and the audio-off parts excluded).
LISTEN = {'easy': 0.9, 'easy_strides': 0.75, 'recovery': 1.0, 'xt_easy': 0.9, 'long': 0.75, 'long_mp': 0.55}
LOG_LISTEN = {'run', 'treadmill', 'trail', 'walk', 'hike', 'bike', 'elliptical', 'row'}
QUALITY_LOG = {'tempo', 'intervals', 'hills', 'marathon_pace', 'race'}

MUSIC = {
    'quality': ('Music: upbeat, ~170–180 BPM (or 85–90 half-time).',
                'Search "running 175 BPM" in Spotify/Apple Music. Save your favourite for the hardest reps.'),
    'strength': ('Music: your gym playlist.', 'Rest the full time between plyo sets: quality contacts beat quantity.'),
    'xt_hard': ('Music: high-energy, 170+ BPM.', 'Bike intervals are short and sharp.'),
}

SHOE_SWITCH = dt.date(2027, 1, 4)   # fresh race shoes from the first week of January
SUPER = {'long_mp', 'mp_run', 'tt5k', 'tt10k', 'half', 'race', 'threshold'}

SELF_TALK = ('Self-talk', 'Use your four phrases ("I can push through this", "strong and smooth"...) whenever it '
             'starts to hurt. Say them deliberately, not just when it is easy.')


def book_progress(logs, plan_start):
    """Listening minutes already done: logged easy-type sessions since the plan began."""
    total = float(BOOKS_DONE)
    for lg in logs:
        if lg.get('date', '') < plan_start or lg.get('kind') not in LOG_LISTEN:
            continue
        if (lg.get('run_type') or '') in QUALITY_LOG:
            continue
        total += float(lg.get('duration_min') or 0) * 0.85
    return total


def _book_at(minutes):
    left = minutes
    for i, (title, author, length, why) in enumerate(BOOKS):
        if left < length:
            return i, left
        left -= length
    return len(BOOKS), left


def _book_note(idx, into, add):
    if idx >= len(BOOKS):
        return {'kind': 'book', 'title': 'Your pick (or a podcast)',
                'detail': 'Book list finished. Choose something under ~8 h so it lasts about two weeks of runs.'}
    title, author, length, why = BOOKS[idx]
    pct = min(99, int(round(100 * into / length)))
    left = max(0, length - into)
    nxt = f' Next: {BOOKS[idx + 1][0]}.' if idx + 1 < len(BOOKS) and left <= add else ''
    return {'kind': 'book', 'title': f'{title} · {author}',
            'detail': f'{why} About {pct} % in, ~{left // 60} h {left % 60:02d} min left.{nxt}',
            'book': idx, 'pct': pct}


def _mind(w, minutes):
    """Mental skill to practise in this session (and the watch prompt time, seconds from the start)."""
    k = w['kind']
    if k in ('long', 'long_mp') and minutes >= 60:
        off = max(20, min(30, round(minutes * 0.25)))
        text = (f'Last {off} min: audio off. {SELF_TALK[1]} Then chunk it: run to the next landmark, then the next.')
        if k == 'long_mp':
            text = ('Marathon-pace section: audio off, as on race day. Chunk it into 5 min blocks; each block, check '
                    'shoulders, jaw and hands are loose. ' + SELF_TALK[1])
        return {'skill': 'Self-talk + chunking', 'text': text, 'at_s': max(0, (minutes - off) * 60), 'cue': 'MIND: SELF-TALK'}
    if k in ('threshold', 'vo2', 'hills', 'xt_intervals'):
        return {'skill': 'Cue words', 'text': 'Pick one cue word for the hard reps ("smooth", "tall", "quick"). Say it '
                'at the start of every rep and again halfway through, when it starts to bite.', 'at_s': None, 'cue': None}
    if k == 'mp_run':
        return {'skill': 'Pacing discipline', 'text': 'Audio off. First km no faster than the band, then lock in. '
                'Every 5 min: relax shoulders, hands and face. This is race rhythm, not a race.', 'at_s': 600,
                'cue': 'MIND: RELAX'}
    if k in ('tt5k', 'tt10k', 'half'):
        return {'skill': 'Race rehearsal', 'text': 'No audio, as on race day. Even pacing, self-talk in the last third, and '
                'note what your mind does when it hurts.', 'at_s': None, 'cue': None}
    if k == 'rest':
        return {'skill': 'Visualisation (5 min)', 'text': 'Eyes closed: Shinjuku start, the downhill first 5 km held back, '
                'the course in sections. See '
                'yourself relaxed when it gets hard.', 'at_s': None, 'cue': None}
    if k in ('easy', 'easy_strides') and minutes >= 30:
        return {'skill': 'Form check', 'text': 'Halfway: tall, relaxed shoulders, quick light feet. 30 seconds, then '
                'back to the book.', 'at_s': round(minutes * 30), 'cue': 'FORM CHECK'}
    return None


def annotate(days, logs, program, today, today_logged=False):
    """Attach audio / mind / shoes / rehearsal notes to every planned day (in place)."""
    listened = book_progress(logs, BOOKS_FROM)
    race = program['_race']
    for w in days:
        d = dt.date.fromisoformat(w['date'])
        k = w['kind']
        minutes = int(w.get('minutes') or 0)
        sec = w.get('secondary')
        if sec and sec['kind'] != 'mobility':
            minutes -= int(sec.get('est_min') or 0)
        extras = {}
        if k in LISTEN:
            add = minutes * LISTEN[k]
            idx, into = _book_at(listened)
            extras['audio'] = _book_note(idx, int(into), add)
            if k == 'easy_strides':
                extras['audio']['detail'] += ' Pause it for the strides.'
            if not (today_logged and w['date'] == today.isoformat()):
                listened += add   # a logged session today is already counted from the logs
        elif k in ('threshold', 'vo2', 'hills'):
            extras['audio'] = dict(zip(('title', 'detail'), MUSIC['quality']), kind='music')
        elif k == 'xt_intervals':
            extras['audio'] = dict(zip(('title', 'detail'), MUSIC['xt_hard']), kind='music')
        elif k in ('mp_run', 'tt5k', 'tt10k', 'half', 'race'):
            extras['audio'] = {'kind': 'off', 'title': 'No audio',
                               'detail': 'Many races discourage earphones (one ear open or low volume if you use them), '
                                         'so race-pace work is practised without.'}
        if sec and sec['kind'] != 'mobility':
            sec['audio'] = dict(zip(('title', 'detail'), MUSIC['strength']), kind='music')
        mind = _mind(w, minutes)
        if mind:
            extras['mind'] = mind
        if k in SUPER and k != 'threshold' or (k == 'threshold' and d >= SHOE_SWITCH):
            extras['shoes'] = ('Race shoes. Practise in them so race day feels normal.'
                               if d < SHOE_SWITCH else 'Race shoes: the new pair. Aim for ~60–100 km in them before race day.')
        if k in ('long', 'long_mp') and d.weekday() >= 5 and dt.date(2027, 1, 9) <= d <= race - dt.timedelta(days=14):
            extras['rehearsal'] = ('Race-morning rehearsal: start at 09:10 (race start). Race breakfast at 06:10, '
                                   'caffeine at 08:10, the same gels, kit and shoes.')
            w['slot_hint'] = 'Start 09:10 (race rehearsal)'
        w.update(extras)
    return days


# ------------------------------------------------------------------------- travel

def travel_day(program, date):
    """Where the runner is on a date when travelling: the stay, the day's note and local start time, or None at home."""
    tr = program.get('travel') or {}
    iso = date.isoformat() if hasattr(date, 'isoformat') else str(date)
    day = (tr.get('days') or {}).get(iso)
    if not day:
        return None
    stay = next((s for s in tr.get('stays', []) if s['from'] <= iso <= s['to']), {})
    return dict(stay=stay, primary=day[0], total=day[1], slot=day[2], note=day[3], tz=tr.get('tz'), trip=tr.get('name'),
                general=tr.get('note'))


# ------------------------------------------------------------------------- dated reminders

MILESTONES = []   # (date, kind, title, text) - optional dated reminders


def milestones(today, window=3):
    """Reminders due now: from their date until `window` days after."""
    out = []
    for date, kind, title, text in MILESTONES:
        d = dt.date.fromisoformat(date)
        if d <= today <= d + dt.timedelta(days=window):
            out.append({'date': date, 'kind': kind, 'title': title, 'text': text})
    return out


def upcoming(today, n=4):
    return [{'date': d, 'kind': k, 'title': t, 'text': x} for d, k, t, x in MILESTONES if d >= today.isoformat()][:n]
