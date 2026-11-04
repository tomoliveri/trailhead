"""Vectorised athlete model and day-by-day training policy.

One code path serves two jobs:
  * the optimiser simulates N (10^4–10^6) stochastic athletes x policy variants
    in parallel with numpy (see optimize.py);
  * the app replays the runner's real logs into the same state (N=1) and asks the same
    policy what to do today and for the coming days (see planner.py).

Model (literature-informed, deliberately simple — see docs/SCIENCE.md):
  * Fitness qualities are EWMAs of their specific stimulus with time constants
    taken from residual-training-effect data (Issurin 2008): aerobic engine A,
    threshold T, VO2/top-end V, economy/neuromuscular N, durability D and
    marathon-specific M. Each saturates (diminishing returns).
  * Qualities compound: T and V gains scale with A, M with D, D with A.
  * Systemic load uses session-RPE minutes (Foster 2001) in ATL/CTL form
    (Banister impulse-response); race-day freshness depends on ATL/CTL.
  * Per-muscle fatigue has a fast (metabolic) and slow (structural/eccentric)
    component; muscles whose fatigue is high are not loaded again.
  * Injury hazard rises with running acute:chronic workload (Gabbett 2016),
    with single sessions longer than 110 % of the longest run in the prior 30
    days (Frandsen et al. 2025, BJSM) and with loading fatigued tissue.
  * Running impact drains a ferritin proxy (foot-strike haemolysis, hepcidin);
    low iron blunts adaptation.
The daily policy is a one-step model-predictive rule: pick the session whose
marginal race-day value (retained adaptation + compounding) minus fatigue,
injury, freshness and iron costs is highest, subject to hard safety rules.
"""
import numpy as np

from .catalog import MUSCLES
from . import distances
from . import physiology as phys

F = np.float32
NM = len(MUSCLES)
MI = {m: i for i, m in enumerate(MUSCLES)}

CANDS = ('rest', 'recovery', 'easy', 'easy_strides', 'long', 'long_mp', 'threshold', 'vo2', 'hills', 'mp_run',
         'xt_easy', 'xt_intervals')
C = len(CANDS)
CI = {c: i for i, c in enumerate(CANDS)}
SECONDARY = ('none', 'strength_lower', 'strength_upper', 'mobility')
EVENTS = {'tt5k': 5000.0, 'tt10k': 10000.0, 'half': 21097.5, 'race': 42195.0}

HARD = np.array([c in ('long', 'long_mp', 'threshold', 'vo2', 'hills', 'mp_run', 'xt_intervals') for c in CANDS])
RUNNING = np.array([c in ('easy', 'easy_strides', 'long', 'long_mp', 'threshold', 'vo2', 'hills', 'mp_run') for c in CANDS])
LONG = np.array([c in ('long', 'long_mp') for c in CANDS])
LOW = np.array([c in ('rest', 'recovery') for c in CANDS])

TAU = dict(A=45., T=45., V=35., N=30., D=35., M=21., atl=7., ctl=42., imp_a=7., imp_c=28., mch=28.)
REF = dict(A=45., T=3.0, V=1.8, N=0.35, D=20., M=4.0)
COEF = dict(A=6.0, T=2.0, V=1.5, N=1.2)
DNS_MINUTES = 360.0
EASY_MIN = 30.0    # shortest easy run offered when the weekly budget is nearly used
PEAK_WEEK = 480.0  # 7-day running impact ceiling (~65-70 km/week): sub-4 programmes peak at 55-70 km
DECAY_FAST, DECAY_SLOW = np.exp(-1 / 0.8), np.exp(-1 / 2.5)

# Race distance in force (see distances.py). Module-level because every simulation in a process plans one race;
# configure() switches it (each browser worker and precook process calls it before planning).
D = dict(distances.PROFILES['marathon'])
DIST = 'marathon'
RACE_M = 42195.0


def configure(key):
    """Switch the model to a race distance ('marathon', 'half', '10k', '5k')."""
    global D, DIST, RACE_M, PEAK_WEEK, LR_FULL, DNS_MINUTES
    key = key if key in distances.PROFILES else 'marathon'
    D = dict(distances.PROFILES[key])
    DIST = key
    RACE_M = D['km'] * 1000.0
    EVENTS['race'] = RACE_M
    PEAK_WEEK = D['peak_week']
    LR_FULL = D['lr_full']
    DNS_MINUTES = 8.5 * D['km']   # a DNS scores as a very slow finish (360 min for the marathon)
    return key


def _shares(d):
    v = np.zeros(NM, F)
    for k, x in d.items():
        v[MI[k]] = x
    return v


SH_RUN = _shares({'calves': .32, 'quads': .20, 'hamstrings': .15, 'glutes': .15, 'hip_flexors': .12, 'core': .06})
SH_WALK = _shares({'calves': .35, 'quads': .20, 'hamstrings': .15, 'glutes': .20, 'hip_flexors': .10})
SH_XT = _shares({'quads': .45, 'glutes': .25, 'calves': .11, 'hamstrings': .10, 'hip_flexors': .07, 'arms': .02})
SH_SL = _shares({'hamstrings': .30, 'glutes': .25, 'quads': .25, 'calves': .15, 'core': .05})
SH_SU = _shares({'back': .35, 'chest_shoulders': .25, 'arms': .20, 'core': .20})
SH_MOB = _shares({'core': .5, 'hip_flexors': .5})
CAND_SHARE = np.stack([np.zeros(NM, F), SH_WALK, SH_RUN, SH_RUN, SH_RUN, SH_RUN, SH_RUN, SH_RUN, SH_RUN, SH_RUN,
                       SH_XT, SH_XT])
CAND_ECC = np.array([0, .5, 1.0, 1.05, 1.2, 1.25, 1.1, 1.15, 1.35, 1.15, .35, .4], F)
SEC_SHARE = np.stack([np.zeros(NM, F), SH_SL, SH_SU, SH_MOB])
SEC_ECC = np.array([0, 1.6, .8, .1], F)
RUN_MUSCLES = [MI['calves'], MI['quads'], MI['hamstrings']]
XT_MUSCLES = [MI['quads'], MI['glutes']]
LOWER = [MI['hamstrings'], MI['glutes'], MI['quads'], MI['calves']]
UPPER = [MI['back'], MI['chest_shoulders'], MI['arms']]

# name, low, high, default — the optimiser searches this box.
PARAM_SPEC = [
    ('w_fatigue', 0.0, 4.0, 1.0),       # aversion to loading already-fatigued muscles
    ('w_risk', 0.0, 60.0, 15.0),        # VDOT-points cost per unit injury hazard
    ('w_fresh', 0.0, 6.0, 1.5),         # cost of fatigue still present on race day
    ('w_iron', 0.0, 0.004, 0.001),      # cost per impact unit when ferritin is low
    ('w_compound', 0.0, 3.0, 0.8),      # value of base that enables later training
    ('rest_bias', -0.05, 0.08, 0.005),  # preference for rest when value is marginal
    ('lr_growth', 0.03, 0.10, 0.08),    # long run growth per long run (capped by 10 % rule)
    ('lr_peak', 150.0, 180.0, 165.0),   # longest long run (min); > ~3 h adds damage faster than durability
    ('easy_base', 20.0, 40.0, 25.0),
    ('easy_growth', 0.0, 3.0, 1.5),     # min per week
    ('easy_cap', 40.0, 95.0, 60.0),   # up to a midweek medium-long run
    ('thr_base', 8.0, 20.0, 12.0),      # threshold work minutes
    ('thr_growth', 0.0, 1.0, 0.6),
    ('vo2_base', 6.0, 12.0, 8.0),       # VO2 work minutes
    ('vo2_growth', 0.0, 0.8, 0.4),
    ('mp_frac', 0.15, 0.45, 0.3),       # share of a long run at marathon pace
    ('min_hard_gap', 2.0, 3.5, 2.0),    # days between hard sessions
    ('long_gap', 5.0, 8.0, 6.0),        # days between long runs
    ('max_level', 0.5, 1.2, 0.8),       # max muscle fatigue level to load that muscle
    ('impact_cap0', 120.0, 300.0, 200.0),   # 7-day running impact budget (EM)
    ('impact_cap_growth', 0.0, 25.0, 10.0),  # per week
    ('ramp', 1.1, 1.3, 1.2),            # rolling week <= ramp x previous week (or chronic week after a down week)
    ('xt_dur', 30.0, 75.0, 45.0),
    ('taper_days', 18.0, 24.0, 21.0),  # ~3 weeks: Bosquet 2007; Smyth & Lawlor 2021 (strict 3-wk taper best)
    ('taper_cut', 0.45, 0.65, 0.5),
    ('ready_hard', 0.4, 0.7, 0.55),
    ('strength_value', 0.0, 2.0, 1.0),
    ('w_long', 0.0, 3.0, 1.0),          # value of extending the longest recent run (race-day fade)
]
PARAM_NAMES = [p[0] for p in PARAM_SPEC]
P_LO = np.array([p[1] for p in PARAM_SPEC], F)
P_HI = np.array([p[2] for p in PARAM_SPEC], F)
P_DEFAULT = np.array([p[3] for p in PARAM_SPEC], F)


def params_from_matrix(mat):
    """(N, P) matrix -> dict of (N,) arrays, clipped to the search box."""
    mat = np.clip(np.asarray(mat, F), P_LO, P_HI)
    return {n: mat[:, i] for i, n in enumerate(PARAM_NAMES)}


def params_from_dict(d, n=1):
    vec = np.array([d.get(k, P_DEFAULT[i]) for i, k in enumerate(PARAM_NAMES)], F)
    return params_from_matrix(np.tile(vec, (n, 1)))


# ----------------------------------------------------------------------------- state

STATE_SCALARS = ('aero_e', 'atl', 'ctl', 'thr_e', 'vo2_e', 'nm_e', 'dur_e', 'mp_e', 'imp_a', 'imp_c', 'fer',
                 'ds_hard', 'ds_long', 'ds_sl', 'ds_su', 'ds_low', 'injured', 'sick', 'resp', 'vdot_base', 'reinj',
                 'ret_ref', 'wfrac', 'fade_i')
STATE_DEFAULTS = {'resp': 1.0, 'ret_ref': 35.0, 'wfrac': 1.0}


def new_state(n, seed):
    """Initial state for n athletes from a seed dict (see config/program.json 'baseline')."""
    s = {k: np.full(n, float(seed.get(k, STATE_DEFAULTS.get(k, 0.0))), F) for k in STATE_SCALARS}
    s['mf_fast'] = np.zeros((n, NM), F)
    s['mf_slow'] = np.zeros((n, NM), F)
    s['m_chronic'] = np.tile(np.array([seed.get('m_chronic', {}).get(m, 0.0) for m in MUSCLES], F), (n, 1))
    s['run_hist'] = np.zeros((n, 30), F)
    s['run_hist'][:, 0] = seed.get('longest_run_30d', 0.0)
    s['lr_hist'] = np.zeros((n, 42), F)
    s['lr_hist'][:, 0] = seed.get('longest_run_30d', 0.0)
    s['imp_hist'] = np.zeros((n, 14), F)
    s['imp_hist'][:, :] = seed.get('imp_a', 0.0)
    s['hard_hist'] = np.zeros((n, 7), F)
    s['run7'] = np.zeros((n, 7), F)
    s['run7'][:, :int(seed.get('runs_last_7d', 0))] = 1
    s['day'] = 0
    return s


def clone_state(s, n=None):
    out = {}
    for k, v in s.items():
        if isinstance(v, np.ndarray):
            out[k] = np.repeat(v, n, axis=0) if n and v.shape[0] == 1 else v.copy()
        else:
            out[k] = v
    return out


def levels(s):
    """Adaptation levels 0..1 for each quality."""
    return {
        'A': 1 - np.exp(-s['aero_e'] / REF['A']),
        'T': 1 - np.exp(-s['thr_e'] / REF['T']),
        'V': 1 - np.exp(-s['vo2_e'] / REF['V']),
        'N': 1 - np.exp(-s['nm_e'] / REF['N']),
        'D': 1 - np.exp(-s['dur_e'] / REF['D']),
        'M': 1 - np.exp(-s['mp_e'] / REF['M']),
    }


def muscle_level(s):
    cap = 35.0 + 3.0 * s['m_chronic']
    return (0.4 * s['mf_fast'] + 0.6 * s['mf_slow']) / cap


def vdot_now(s, lv=None, base_levels=None, weight_ratio=1.0):
    lv = lv or levels(s)
    b = base_levels or {k: 0.0 for k in lv}
    gain = (COEF['A'] * (lv['A'] - b['A']) + COEF['T'] * (lv['T'] - b['T']) + COEF['V'] * (lv['V'] - b['V'])
            + COEF['N'] * (lv['N'] - b['N']))
    gain = np.where(gain > 0, gain * s['resp'], gain)
    iron = np.where(s['fer'] < 30, 0.9, np.where(s['fer'] < 45, 0.96, 1.0))
    # Weight loss: the planned loss is reached only partly or not at all by some athletes (wfrac).
    wr = 1 + (weight_ratio - 1) * s['wfrac']
    return (s['vdot_base'] + gain) * iron * (1 + 0.6 * (wr - 1))


LR_FULL = 170.0  # min: a recent long run this long removes the long-run fade penalty
LR_KEEP, LR_TAU = 28.0, 20.0  # a long run counts fully for 28 days, then fades (tau 20 d)


def long_run_deficit(lr):
    """Extra marathon slowdown from a short recent longest run (the 'wall'): ~10 % at 60 min, ~6 % at 90,
    ~3 % at 120, ~1 % at 150, 0 at 170+. Longest runs and weekly volume are the strongest training
    predictors of recreational marathon time (Tanda 2011; Doherty 2020)."""
    return D['lr_amp'] * np.power(np.maximum(0.0, 1 - lr / LR_FULL), 1.6)


def lr_recency(age):
    return np.exp(-np.maximum(0.0, age - LR_KEEP) / LR_TAU)


def lr_effective(s, ahead=0.0):
    """Longest run of the last 6 weeks as it will count `ahead` days from now: runs older than ~4 weeks
    count less, so a peak long run 4.5 weeks out no longer covers race day (the old 42-day max did)."""
    d = s['day']
    age = np.arange(1, 43, dtype=F)            # slot (d - a + 1) % 42 holds the run from a days ago
    idx = (d - age.astype(int) + 1) % 42
    return (s['lr_hist'][:, idx] * lr_recency(age + ahead)[None, :]).max(1)


def race_minutes(s, base_levels, weight_ratio=1.0):
    """Race-day finish time (min) for the configured distance."""
    lv = levels(s)
    vdot = vdot_now(s, lv, base_levels, weight_ratio)
    t = phys.race_time(RACE_M, vdot)
    fade = (1 + D['base_fade'] + D['dur_fade'] * np.power(1 - lv['D'], 1.3) - 0.025 * lv['M']
            + long_run_deficit(lr_effective(s))) * (1 + s['fade_i'])
    # Freshness: a proper taper (ATL/CTL ~0.65) is worth ~2-3 % (Bosquet 2007; Wang 2023; Smyth & Lawlor
    # 2021); arriving untapered (ratio ~1) costs ~2 %, over-resting (< 0.4) costs fitness.
    r = s['atl'] / np.maximum(s['ctl'], 1.0)
    taper = 1 + 0.06 * np.clip(r - 0.65, 0, 0.6) + 0.03 * np.maximum(0, 0.4 - r)
    return t * fade * taper, vdot


marathon_minutes = race_minutes   # older name


# ----------------------------------------------------------------------------- stimuli

def _z(n):
    return np.zeros(n, F)


def empty_stim(n):
    st = {k: _z(n) for k in ('minutes', 'aero', 'sys', 'impact', 'run_min', 'thr', 'vo2', 'nm', 'dur', 'mp', 'hard',
                             'is_long', 'sl', 'su', 'low', 'longest')}
    st['mload'] = np.zeros((n, NM), F)
    st['slow_load'] = np.zeros((n, NM), F)
    return st


def impact_weeks(s):
    """Running impact over the last 6 days (+ today's candidate = a 7-day week) and the 7 days before.
    Slot d % 14 holds yesterday. (Summing 7 past days plus today made an 8-day week, so a long run always
    saw last week's long run in its window and was blocked by the peak-week ceiling.)"""
    d = s['day']
    idx = (d - np.arange(13)) % 14
    h = s['imp_hist'][:, idx]
    return h[:, :6].sum(1), h[:, 6:13].sum(1)


def weekly_cap(s, P, day_from_start):
    """7-day running impact budget: absolute (growing, never above PEAK_WEEK) and relative — at most
    `ramp` x the previous week, or x the chronic week after a down week; 150 return-to-run floor. Weekly
    ratios predict injury weakly (Buist 2008: 10 %/wk no safer than 24 %/wk; Frandsen 2025), so the
    session-spike rule is the strict one and this is a ceiling the optimiser may set between 10-40 %."""
    cap = np.minimum(P['impact_cap0'] + P['impact_cap_growth'] * day_from_start / 7.0, PEAK_WEEK)
    _, prev7 = impact_weeks(s)
    ref = np.maximum(prev7, 7.0 * s['imp_c'])
    return np.minimum(cap, np.maximum(150.0, P['ramp'] * ref))


def durations(s, P, ctx):
    """Session sizes for today given state, policy parameters and calendar context."""
    w = ctx['day_from_start'] / 7.0
    dtr = ctx['dtr']
    # Stepped taper (thirds of taper_days at 1/3, 2/3 and the full cut): ~0.85 / 0.70 / 0.50 of normal volume.
    taper_days = P['taper_days'] * D['taper_scale']
    frac = np.clip(1 - dtr / np.maximum(taper_days, 1), 0, 1)
    tscale = np.where(dtr < taper_days, 1 - P['taper_cut'] * np.ceil(frac * 3) / 3, 1.0)
    if ctx.get('down'):
        tscale = tscale * 0.8      # planned recovery week
    max30 = s['run_hist'].max(1)
    ref = np.where(max30 > 0, np.maximum(max30, np.minimum(s['ret_ref'], 35.0)), s['ret_ref'])
    # Long run grows from the longest run of the last 30 days (never > 110 %); easy runs stay clearly
    # shorter than the long run, so no ordinary day is itself a spike.
    L = np.minimum(np.maximum(max30 * (1 + P['lr_growth']), ref), np.minimum(ref * 1.10, P['lr_peak'] * D['lr_scale']))
    if ctx.get('post_event'):
        L = np.minimum(L, 100.0 * D['lr_scale'])   # recovery week after the half
    E = np.minimum(np.clip(P['easy_base'] + P['easy_growth'] * w, 20, P['easy_cap']), np.maximum(0.8 * L, 20.0))
    # The weekly budget sets run length, not the other way round: after the long run, the rest of the
    # 7-day impact budget is shared by ~3 other runs, so the long run never gets crowded out.
    cap = weekly_cap(s, P, ctx['day_from_start'])
    E = np.minimum(E, np.maximum(20.0, (cap - 1.1 * L) / 3.0))
    L = L * tscale
    E = E * tscale
    Qt = np.clip(P['thr_base'] + P['thr_growth'] * w, 8, 30) * np.sqrt(tscale)
    Qv = np.clip(P['vo2_base'] + P['vo2_growth'] * w, 6, 20) * np.sqrt(tscale)
    MPw = np.clip(15 + 1.5 * w, 15, 60) * D['rp_scale'] * tscale   # race-pace minutes (reps for 5/10 km)
    X = P['xt_dur'] * tscale
    cap = cap * tscale         # down weeks and the taper shrink the weekly budget too, not just run lengths
    return dict(E=E.astype(F), L=L.astype(F), Qt=Qt.astype(F), Qv=Qv.astype(F), MPw=MPw.astype(F), X=X.astype(F),
                max30=max30, ref=ref, tscale=tscale, cap=cap.astype(F))


def candidate_stim(dur, P, n):
    """(N, C) arrays for every stimulus field of every candidate session."""
    E, L, Qt, Qv, MPw, X = dur['E'], dur['L'], dur['Qt'], dur['Qv'], dur['MPw'], dur['X']
    f = P['mp_frac']
    z = _z(n)
    minutes = np.stack([z, z + 30, E, E + 4, L, L, 20 + 1.2 * Qt, 23 + 1.8 * Qv, z + 45, 15 + MPw, X, z + 50], 1)
    em = np.stack([z, z + 18, E, E + 6, 1.1 * L, L * ((1 - f) * 1.1 + f * 1.5), 20 + 2.16 * Qt,
                   23 + 3.44 * Qv, z + 55, 15 + 1.5 * MPw, X, z + 70], 1)
    transfer = np.array([0, .3, 1, 1, 1, 1, 1, 1, 1, 1, .72, .72], F)
    impact_rate = np.array([0, .25, 1, 1.02, 1.05, 1.08, 1.1, 1.15, 1.2, 1.1, .05, .05], F)
    run_min = minutes * RUNNING
    st = {
        'minutes': minutes, 'sys': em, 'aero': em * transfer, 'impact': minutes * impact_rate, 'run_min': run_min,
        'thr': np.stack([z, z, z, z, z, 0.3 * f * L, Qt, 0.2 * Qv, z, D['rp_thr'] * MPw, z, z + 4.8], 1),
        'vo2': np.stack([z, z, z, z, z, z, z, Qv, z + 3, D['rp_vo2'] * MPw, z, z + 9.6], 1),
        'nm': np.stack([z, z, z, z + .3, z, z, z + .05, z + .1, z + .6, z, z, z], 1),
        'mp': np.stack([z, z, z, z, z, np.minimum(f * L, 90.0) + 0.1 * L, z, z, z, MPw, z, z], 1),  # builder caps MP at 90
        'dur': 0.3 * run_min + np.maximum(0, run_min - 50) * LONG + np.maximum(0, run_min - 50) * 0.5 * (~LONG),
        'hard': np.broadcast_to(HARD.astype(F), (n, C)),
        'is_long': np.broadcast_to(LONG.astype(F), (n, C)),
        'low': np.broadcast_to(LOW.astype(F), (n, C)),
    }
    return st


# Short essentials sessions; adaptation is conservatively reduced with volume.
# Legs: ultra-minimal 5-set block once a week (3 Nov 2026), half the old load/fatigue; minimal-dose strength
# keeps much of the effect, so the economy stimulus is cut less than the volume (modelling assumption).
SEC_MIN = np.array([0, 13, 16, 15], F)
SEC_EM = np.array([0, 18, 18, 6], F)
SEC_SYS = np.array([0, 9, 8, 2], F)
SEC_NM = np.array([0, 0.45, 0.05, 0.02], F)


# ----------------------------------------------------------------------------- policy

def spike_rr(r):
    """Injury rate ratio for a run r x the longest run of the last 30 days (Frandsen 2025, BJSM, n=5,205):
    1.64 for 10-30 % longer, 1.52 for 30-100 %, 2.28 for > 100 %."""
    return np.where(r > 2.0, 2.28, np.where(r > 1.3, 1.52, np.where(r > 1.1, 1.64, 1.0))).astype(F)


def choose(s, P, ctx, readiness=None, rng=None, forced=None):
    """Pick today's primary and secondary session for every athlete.

    Returns (primary idx (N,), secondary idx (N,), duration dict, candidate stim, scores).
    """
    n = s['aero_e'].shape[0]
    dur = durations(s, P, ctx)
    dtr = float(ctx['dtr'])
    R = float(ctx['horizon'])
    imp7, _ = impact_weeks(s)
    # Long-run lookahead (rows, own min_hard_gap): is the long run due on one of the next days, and does it fit there?
    gap_row = np.floor(P['min_hard_gap']).astype(int)
    ahead = ctx.get('avail_ahead') or []
    fits_today = ctx['avail'] >= dur['L'] if np.ndim(ctx['avail']) else np.full(n, ctx['avail']) >= dur['L']
    soon = np.zeros(n, bool)
    due_soon = np.zeros(n, bool)
    # Past impact that will still be inside the 7-day window on the long-run day (k days ahead keeps the
    # last 6 - k days; counting the whole current week blocked runs whose impact drops out by then).
    hist = s['imp_hist'][:, (s['day'] - np.arange(6)) % 14]   # slot d % 14 = yesterday
    keep = np.zeros(n, F)
    for k, av in enumerate(ahead[:3], start=1):
        due_k = (av >= dur['L']) & (s['ds_long'] + k >= np.floor(P['long_gap'])) & (dtr - k > D['no_long_days'])
        soon |= due_k & (k <= gap_row)
        due_soon |= due_k
        keep = np.where(due_k, np.maximum(keep, hist[:, :6 - k].sum(1)), keep)
    reserve_on = due_soon & ~fits_today
    # Easy runs shrink to fit today's time and what is left of the 7-day impact budget (and the room kept for
    # a coming long run) instead of being blocked outright: a full-length easy run that no longer fits used
    # to hand the day to the bike, so late in the build weeks fell to 1-3 runs around a 3-hour long run.
    avail = ctx['avail'] if np.ndim(ctx['avail']) else np.full(n, float(ctx['avail']))
    room = dur['cap'] - imp7
    room = np.where(reserve_on, np.minimum(room, PEAK_WEEK - keep - 1.1 * dur['L']), room)
    fit = np.minimum(room / 1.03, avail) - 4.0   # easy + strides is the larger of the two easy candidates
    dur['E'] = np.where(fit >= EASY_MIN, np.minimum(dur['E'], fit), dur['E']).astype(F)
    cs = candidate_stim(dur, P, n)
    lv = levels(s)
    ml = muscle_level(s)

    # --- marginal race-day value (VDOT-equivalent points) of each candidate
    def unit(tau):
        return np.exp(-dtr / tau) / tau

    def compound(tau):
        return (1 - np.exp(-dtr / tau)) / tau * (dtr / max(R, 1.0))

    dA = COEF['A'] * np.exp(-s['aero_e'] / REF['A']) / REF['A']
    dT = COEF['T'] * np.exp(-s['thr_e'] / REF['T']) / REF['T'] * (0.4 + 0.6 * lv['A'])
    dV = COEF['V'] * np.exp(-s['vo2_e'] / REF['V']) / REF['V'] * (0.3 + 0.7 * lv['A'])
    dN = COEF['N'] * np.exp(-s['nm_e'] / REF['N']) / REF['N'] * P['strength_value']
    fade_D = 6.7 * D['dur_val'] * np.power(np.maximum(1 - lv['D'], 1e-3), 0.3)
    dD = fade_D * np.exp(-s['dur_e'] / REF['D']) / REF['D'] * (0.5 + 0.5 * lv['A'])
    dM = 1.1 * np.exp(-s['mp_e'] / REF['M']) / REF['M'] * (0.3 + 0.7 * lv['D'])
    wc = P['w_compound']
    # Extending the longest recent run reduces race-day fade (~0.38 VDOT points per 1 % of marathon time).
    # Far from the race this is the build-up ladder (longest of the last 6 weeks); in the last 5 weeks it is
    # what will still count on race day, so the final long runs land ~3 weeks out instead of 4.5.
    # Shorter races barely fade from a short long run, so the ladder simply runs until the (short) taper.
    if dtr > 35 or DIST != 'marathon':
        lr_now = s['lr_hist'].max(1)
        today_w = 1.0
    else:
        lr_now = lr_effective(s, ahead=dtr)
        today_w = float(lr_recency(dtr))
    d_fade = D['lr_amp'] * 1.6 * np.power(np.maximum(0.0, 1 - lr_now / LR_FULL), 0.6) / LR_FULL
    lr_val = (P['w_long'] * 38.0 * d_fade)[:, None] * np.maximum(0.0, today_w * cs['run_min'] - lr_now[:, None])
    val = (cs['aero'] * (dA * (unit(TAU['A']) + wc * compound(TAU['A'])))[:, None]
           + cs['thr'] * (dT * unit(TAU['T']))[:, None]
           + cs['vo2'] * (dV * unit(TAU['V']))[:, None]
           + cs['nm'] * (dN * unit(TAU['N']))[:, None]
           + cs['dur'] * (dD * (unit(TAU['D']) + wc * compound(TAU['D'])))[:, None]
           + cs['mp'] * (dM * unit(TAU['M']))[:, None]
           + lr_val)

    # --- costs
    load = cs['sys'] * CAND_ECC
    fat_cost = P['w_fatigue'][:, None] * load * ((ml * ml) @ CAND_SHARE.T) / 100.0
    imp_c_new = s['imp_c'][:, None] + (cs['impact'] - s['imp_c'][:, None]) / TAU['imp_c']
    imp_a_new = s['imp_a'][:, None] + (cs['impact'] - s['imp_a'][:, None]) / TAU['imp_a']
    acwr = imp_a_new / np.maximum(imp_c_new, 10.0)
    max30 = dur['max30']
    lr_ratio = cs['run_min'] / dur['ref'][:, None]
    run_mus = ml[:, RUN_MUSCLES].max(1)
    # Tissue that is used to running tolerates more of it (chronic load is protective).
    # Low chronic load (returning from a break) raises per-hour risk up to x1.41.
    tolerance = np.sqrt(20.0 / np.maximum(s['imp_c'], 10.0))[:, None]
    # ~4.5 time-loss injuries per 1000 h at baseline load (recreational 7.7, novice 17.8 incl. minor ones:
    # Videbaek 2015); previous injury roughly doubles risk for weeks after return (Hulme 2017; van der Worp 2015).
    # No acute:chronic ratio term: ACWR is a statistical artefact (Impellizzeri 2020; Lolli 2019) and in
    # Frandsen 2025 weekly ratios did not predict injury; the session spike did (steps below, its RRs).
    prior = np.where(s['reinj'] > 0, 1.8, 1.0)[:, None]
    hazard = 0.0045 * prior * tolerance * cs['run_min'] / 60 * spike_rr(lr_ratio) \
        * np.exp(2.5 * np.maximum(0, run_mus - 0.6)[:, None])
    hazard = hazard + 0.0002 * cs['minutes'] * (~RUNNING) / 60
    risk_cost = P['w_risk'][:, None] * hazard
    fresh_cost = P['w_fresh'][:, None] * cs['sys'] * (np.exp(-dtr / TAU['atl']) / TAU['atl'] * 0.02)
    iron_w = 1 / (1 + np.exp((s['fer'] - 55) / 8))
    iron_cost = (P['w_iron'] * iron_w)[:, None] * cs['impact']
    score = val - fat_cost - risk_cost - fresh_cost - iron_cost
    score[:, CI['rest']] += P['rest_bias']
    score[:, CI['recovery']] += P['rest_bias'] * 0.8

    # --- hard rules (evidence-based guard rails; never optimised away)
    ok = np.ones((n, C), bool)
    ok &= cs['minutes'] <= ctx['avail'][:, None] if np.ndim(ctx['avail']) else cs['minutes'] <= ctx['avail']
    injured = s['injured'] > 0
    ok[injured] &= ~RUNNING
    sick = s['sick'] > 0
    ok[sick] = False
    ok[sick, CI['rest']] = True
    gap_hard = s['ds_hard'] < np.floor(P['min_hard_gap'])
    ok[gap_hard] &= ~HARD
    if ctx.get('post_event') or ctx.get('dte', 99) <= 2:
        ok &= ~HARD[None, :]       # 5 easy days after the half; 2 easy days before any checkpoint
    # hard sessions in the last 6 days (slot d % 7 = yesterday) + today <= 3 per 7 days
    hard7 = s['hard_hist'][:, [(s['day'] - k) % 7 for k in range(6)]].sum(1) >= 3
    ok[hard7] &= ~HARD
    ok[s['ds_long'] < np.floor(P['long_gap'])] &= ~LONG
    ok[:, CI['long_mp']] &= lv['D'] > 0.35
    if not D['long_rp']:
        ok[:, CI['long_mp']] = False   # 5 / 10 km: race pace is short reps, not the end of a long run
    ok[:, CI['mp_run']] &= lv['A'] > 0.35
    no_base = s['imp_c'] < 12
    ok[no_base, CI['threshold']] = False
    ok[no_base, CI['vo2']] = False
    ok[no_base, CI['hills']] = False
    ok[no_base, CI['mp_run']] = False
    ok &= ~(RUNNING[None, :] & (run_mus > P['max_level'])[:, None])
    xt_mus = ml[:, XT_MUSCLES].max(1)
    ok[:, CI['xt_intervals']] &= xt_mus <= P['max_level']
    # Weekly cap (from durations): absolute budget, and a ramp relative to what the tissue is used to
    # (chronic week = 7 x 28-day EWMA) with a return-to-run floor.
    cap = dur['cap']
    # Single-session spike rule applies to every run, not just long ones (Frandsen 2025).
    ok &= ~(RUNNING[None, :] & (cs['run_min'] > (dur['ref'] * 1.10 + 0.5)[:, None]))
    # The long run answers to the session-spike rule (<= 110 % of the recent longest) and the peak-week
    # ceiling, not the weekly ramp: weekly ratios are the weaker evidence, and a greedy day-by-day policy
    # would otherwise spend the week's budget on easy days and let the long run slip for weeks.
    over = (imp7[:, None] + cs['impact']) > cap[:, None]
    over_peak = (imp7[:, None] + cs['impact']) > PEAK_WEEK
    ok &= ~(RUNNING[None, :] & np.where(LONG[None, :], over_peak, over))
    # Long-run lookahead: when the long run is due on one of the next days and will fit there, other hard
    # sessions stay off the days just before it, and other runs leave room for it in the peak-week budget
    # (otherwise easy days use up the week and the long run is blocked).
    ok[soon & ~fits_today] &= ~(HARD & ~LONG)
    reserve = (keep[:, None] + cs['impact'] + 1.1 * dur['L'][:, None]) > PEAK_WEEK
    ok &= ~((RUNNING & ~LONG)[None, :] & reserve_on[:, None] & reserve)
    # Specificity guard: keep running frequency up (3 runs per 6 days for the first 8 weeks, then 4) so
    # cross-training supplements running rather than replacing it. Enforced only when a run is actually allowed today and there's a gap since the last run.
    runs7 = s['run7'].sum(1) - s['run7'][:, (s['day'] + 1) % 7]  # runs in the last 6 days
    target = 3.0 if ctx['day_from_start'] < 56 else 4.0
    ran_yday = s['run7'][:, s['day'] % 7] > 0
    need_low = s['ds_low'] >= 7
    need_run = (runs7 < target) & ~ran_yday & (ok & RUNNING[None, :]).any(1) & (dtr > 2) & ~need_low
    ok[need_run] &= RUNNING | (np.arange(C) == CI['rest'])
    ok[need_low] &= LOW        # a real rest/recovery day (cross-training here never reset the 7-day count)
    if readiness is not None:
        ok[readiness < P['ready_hard']] &= ~HARD
        ok[readiness < 0.35] &= LOW
    if dtr <= D['no_long_days']:
        ok &= ~LONG[None, :]      # last long run >= 10 days out; race week keeps a short MP run instead
    if dtr <= 2:
        ok &= LOW[None, :] | (np.arange(C) == CI['easy'])[None, :]
    if DIST != 'marathon' and dtr > D['no_long_days'] + 3:
        # Shorter races: keep the weekly long run (aerobic base) once it has slipped 9+ days, when it is allowed
        # and fits today. The marathon's long-run value already does this; at 5-21 km race-pace work outscores it.
        need_long = (s['ds_long'] >= 9) & (ok & LONG[None, :]).any(1)
        ok[need_long] &= LONG | (np.arange(C) == CI['rest'])
    else:
        need_long = np.zeros(n, bool)
    if ctx.get('no_bike'):
        ok[:, CI['xt_intervals']] = False   # travelling: no bike for intervals (easy cross-training = swim / hike)
    ok[:, CI['rest']] = True
    score = np.where(ok, score, -np.inf)
    score[need_run | need_long, CI['rest']] = -1e6
    prim = score.argmax(1)
    if forced is not None:
        prim = np.where(forced >= 0, forced, prim)

    # --- secondary session (strength / mobility), same day, keeps hard days hard
    rows = np.arange(n)
    used = cs['minutes'][rows, prim]
    left = ctx['avail_total'] - used
    sec_score = np.zeros((n, len(SECONDARY)), F)
    dN_now = dN * unit(TAU['N'])
    # Legs (heavy + plyometrics): once a week (minimal dose), ahead of upper body when both fit.
    # Economy gains need ~2x/week for 6-14 weeks and are kept on 1x/week (Blagrove 2018; Llanos-Lagos 2024).
    sec_score[:, 1] = SEC_NM[1] * dN_now - P['w_fatigue'] * SEC_EM[1] * SEC_ECC[1] * ((ml * ml) @ SH_SL) / 100 \
        - P['w_fresh'] * SEC_SYS[1] * (np.exp(-dtr / TAU['atl']) / TAU['atl'] * 0.02) \
        + np.where((s['ds_sl'] >= 6) & (dtr > D['legs_cut']), 1.1, 0.0)
    # Upper body: ~2 sessions / 7 days for the physique goal (no race-day value, so a frequency floor
    # rather than a score; running barely interferes with upper-body hypertrophy: Wilson 2012).
    sec_score[:, 2] = SEC_NM[2] * dN_now + 0.002 + np.where(s['ds_su'] >= 3, 1.0, 0.0) \
        - P['w_fatigue'] * SEC_EM[2] * ((ml * ml) @ SH_SU) / 100
    sec_score[:, 3] = 0.001
    sok = np.ones_like(sec_score, bool)
    sok[:, 1] &= (s['ds_sl'] >= 2) & (dtr > D['legs_cut']) & (ml[:, LOWER].max(1) < P['max_level']) & ~LONG[prim] & (left >= SEC_MIN[1])
    sok[:, 1] &= ~sick
    # Legs: never the day before a likely long run or within 5 days of a checkpoint; 1 / week in the last 7 weeks.
    if ahead:
        long_tomorrow = (ahead[0] >= dur['L']) & (s['ds_long'] + 1 >= np.floor(P['long_gap']))
        sok[:, 1] &= ~long_tomorrow
    if ctx.get('dte', 99) <= 5:
        sok[:, 1] = False
    sok[:, 1] &= s['ds_sl'] >= 6        # once a week
    sok[:, 2] &= (s['ds_su'] >= 2) & (dtr > 5) & (ml[:, UPPER].max(1) < P['max_level']) & (left >= SEC_MIN[2]) & ~sick
    sok[:, 3] &= (left >= 15) & ~sick
    if ctx.get('no_upper'):
        sok[:, 2] = False
    sok[need_low, 1] = False   # a recovery day stays a recovery day for the legs; short upper body is fine
    sec_score = np.where(sok, sec_score, -np.inf)
    sec = sec_score.argmax(1)
    return prim, sec, dur, cs, {'score': score, 'hazard': hazard, 'value': val, 'ok': ok, 'levels': lv,
                                'muscle_level': ml, 'sec_score': sec_score}


def stim_from_choice(prim, sec, cs, n):
    rows = np.arange(n)
    st = {k: cs[k][rows, prim].astype(F) for k in ('minutes', 'aero', 'sys', 'impact', 'run_min', 'thr', 'vo2', 'nm',
                                                  'dur', 'mp', 'hard', 'is_long', 'low')}
    st['longest'] = st['run_min'].copy()
    ecc = CAND_ECC[prim]
    st['mload'] = CAND_SHARE[prim] * st['sys'][:, None]
    st['slow_load'] = st['mload'] * ecc[:, None]
    has = sec > 0
    st['minutes'] += SEC_MIN[sec]
    st['sys'] += SEC_SYS[sec]
    st['nm'] += SEC_NM[sec]
    sl = SEC_SHARE[sec] * SEC_EM[sec][:, None]
    st['mload'] += sl
    st['slow_load'] += sl * SEC_ECC[sec][:, None]
    st['sl'] = (sec == 1).astype(F)
    st['su'] = (sec == 2).astype(F)
    st['low'] = np.where(sec == 1, 0, st['low']).astype(F)   # leg strength ends a recovery day; upper body doesn't
    return st


def apply(s, st, eff_extra=None):
    """Advance one day: add today's stimulus, then overnight recovery."""
    d = s['day']
    lv = levels(s)
    ratio = s['atl'] / np.maximum(s['ctl'], 5.0)
    eff = np.clip(1.1 - 0.6 * np.maximum(0, ratio - 1.3), 0.5, 1.1)
    eff = eff * np.where(s['fer'] < 40, 0.85, 1.0)
    if eff_extra is not None:
        eff = eff * eff_extra
    s['aero_e'] += (st['aero'] * eff - s['aero_e']) / TAU['A']
    s['thr_e'] += (st['thr'] * eff * (0.4 + 0.6 * lv['A']) - s['thr_e']) / TAU['T']
    s['vo2_e'] += (st['vo2'] * eff * (0.3 + 0.7 * lv['A']) - s['vo2_e']) / TAU['V']
    s['nm_e'] += (st['nm'] * eff - s['nm_e']) / TAU['N']
    s['dur_e'] += (st['dur'] * eff * (0.5 + 0.5 * lv['A']) - s['dur_e']) / TAU['D']
    s['mp_e'] += (st['mp'] * eff * (0.3 + 0.7 * lv['D']) - s['mp_e']) / TAU['M']
    s['atl'] += (st['sys'] - s['atl']) / TAU['atl']
    s['ctl'] += (st['sys'] - s['ctl']) / TAU['ctl']
    s['imp_a'] += (st['impact'] - s['imp_a']) / TAU['imp_a']
    s['imp_c'] += (st['impact'] - s['imp_c']) / TAU['imp_c']
    s['fer'] += 0.22 - 0.010 * st['impact']
    s['fer'] = np.clip(s['fer'], 5, 400)
    s['mf_fast'] = (s['mf_fast'] + st['mload']) * DECAY_FAST
    s['mf_slow'] = (s['mf_slow'] + st['slow_load']) * DECAY_SLOW
    s['m_chronic'] += (st['mload'] - s['m_chronic']) / TAU['mch']
    s['run_hist'][:, (d + 1) % 30] = st['longest']
    s['lr_hist'][:, (d + 1) % 42] = st['longest']
    s['imp_hist'][:, (d + 1) % 14] = st['impact']
    s['hard_hist'][:, (d + 1) % 7] = st['hard']
    s['run7'][:, (d + 1) % 7] = (st['run_min'] > 0)
    s['ds_hard'] = np.where(st['hard'] > 0, 0, s['ds_hard'] + 1)
    s['ds_long'] = np.where(st['is_long'] > 0, 0, s['ds_long'] + 1)
    s['ds_sl'] = np.where(st['sl'] > 0, 0, s['ds_sl'] + 1)
    s['ds_su'] = np.where(st['su'] > 0, 0, s['ds_su'] + 1)
    s['ds_low'] = np.where(st['low'] > 0, 0, s['ds_low'] + 1)
    s['injured'] = np.maximum(s['injured'] - 1, 0)
    s['sick'] = np.maximum(s['sick'] - 1, 0)
    s['reinj'] = np.maximum(s['reinj'] - 1, 0)
    s['day'] = d + 1


def event_stim(name, vdot, n):
    """Stimulus of a race / time trial at full effort."""
    dist = EVENTS[name]
    t = phys.race_time(dist, vdot).astype(F)
    st = empty_stim(n)
    em = t * (2.4 if dist <= 10000 else 1.9 if dist < 30000 else 1.8)
    half = dist > 20000
    st.update(minutes=t + 25, sys=em + 25, aero=em + 25, impact=t * 1.2 + 20, run_min=t + 20, longest=t + 20,
              thr=t * (0.5 if dist <= 10000 else 0.35), vo2=t * (0.5 if dist <= 5000 else 0.05 if half else 0.2),
              dur=0.3 * t + np.maximum(0, t - 50), mp=np.where(half, t * 0.5, 0).astype(F),
              hard=np.ones(n, F), is_long=np.full(n, 1.0 if dist > 20000 else 0.0, F))
    st['mload'] = SH_RUN[None, :] * st['sys'][:, None]
    st['slow_load'] = st['mload'] * (1.6 if dist > 20000 else 1.2)
    return st


# ----------------------------------------------------------------------------- simulation

def calendar(start, race_date, availability, events, down_weeks=(), day0=None, overrides=None):
    """Per-day context arrays from settings. `availability` maps weekday (0=Mon) -> (primary, total[, no_upper]) minutes.
    `down_weeks`: ISO dates starting a planned 7-day recovery week. Days after a half are recovery days.
    `day0`: plan start (day_from_start counts from it; defaults to `start`).
    `overrides`: ISO date -> (primary, total[, no_upper]) for days away from home (travel: no bike/gym machines either;
    no_upper drops upper-body strength, e.g. a minimal holiday block)."""
    import datetime as dt
    days = (race_date - start).days
    cal = []
    ev = {dt.date.fromisoformat(k): v for k, v in events.items()}
    downs = [dt.date.fromisoformat(d) for d in down_weeks]
    halves = [d for d, v in ev.items() if v == 'half']
    off = (start - day0).days if day0 else 0
    for i in range(days + 1):
        day = start + dt.timedelta(days=i)
        ov = overrides or {}

        def av(d):
            return ov.get(d.isoformat()) or availability[d.weekday()]
        prim, total = av(day)[:2]
        ahead = [float(av(day + dt.timedelta(days=k))[0]) for k in (1, 2, 3)]
        nxt = [(d - day).days for d in ev if d > day]
        cal.append(dict(date=day, day_from_start=i + off, dtr=days - i, horizon=days + off, avail=float(prim),
                        avail_total=float(total), event=ev.get(day), avail_ahead=ahead,
                        dte=min(nxt) if nxt else 99,
                        down=any(0 <= (day - d).days < 7 for d in downs),
                        post_event=any(1 <= (day - d).days <= 5 for d in halves),
                        no_bike=day.isoformat() in ov,
                        no_upper=len(av(day)) > 2 and bool(av(day)[2])))
    return cal


def simulate(P, init, cal, rng, base_levels=None, weight_ratio=1.0, collect=False, crn_block=None):
    """Run N stochastic athletes to race day. P: dict of (N,) param arrays; init: state (N rows).

    crn_block=k: random draws repeat every k rows so every plan version faces the
    same k athletes' luck (common random numbers).
    """
    s = clone_state(init)
    n = s['aero_e'].shape[0]
    reps = n // crn_block if crn_block else 1
    blk = crn_block or n

    def U():
        return np.tile(rng.random(blk), reps)

    def I(lo, hi):
        return np.tile(rng.integers(lo, hi, blk), reps)

    base_levels = base_levels or {k: v.copy() for k, v in levels(s).items()}
    trace = [] if collect else None
    injuries = np.zeros(n, F)
    long_inj = np.zeros(n, F)
    rows = np.arange(n)
    for ctx in cal[:-1]:
        c = dict(ctx)
        c['avail'] = (np.full(n, ctx['avail'], F) * np.where(U() < 0.05, 0.5, 1.0)).astype(F)
        c['avail_total'] = np.full(n, ctx['avail_total'], F)
        ratio = s['atl'] / np.maximum(s['ctl'], 5.0)
        # Real morning readiness varies a lot (~0.7 +- 0.2 on the app's scale), not 1.0 +- 0.1.
        readiness = (0.72 - 0.5 * np.maximum(0, ratio - 1.1) + 0.18 * np.tile(rng.standard_normal(blk), reps)).astype(F)
        new_sick = (s['sick'] <= 0) & (U() < 0.010)
        s['sick'] = np.where(new_sick, I(2, 6), s['sick']).astype(F)
        if ctx['event']:
            prim = np.zeros(n, np.int64)
            sec = np.zeros(n, np.int64)
            able = (s['injured'] <= 0) & (s['sick'] <= 0)
            v = vdot_now(s, None, base_levels, 1.0)
            st = event_stim(ctx['event'], v, n)
            for k in st:
                if k not in ('mload', 'slow_load'):
                    st[k] = np.where(able, st[k], 0).astype(F)
            st['mload'] *= able[:, None]
            st['slow_load'] *= able[:, None]
            # A race far longer than recent runs is a spike too (Frandsen 2025): build up to checkpoints.
            ratio = st['run_min'] / np.maximum(s['run_hist'].max(1), s['ret_ref'])
            prior = np.where(s['reinj'] > 0, 1.8, 1.0)
            hz = np.where(able, 0.004 * prior * spike_rr(ratio), 0.0)
        else:
            prim, sec, dur, cs, info = choose(s, P, c, readiness=readiness, rng=rng)
            missed = U() < 0.06
            prim = np.where(missed, 0, prim)
            sec = np.where(missed, 0, sec)
            st = stim_from_choice(prim, sec, cs, n)
            hz = info['hazard'][rows, prim]
        hurt = (U() < hz) & (s['injured'] <= 0)
        injuries += hurt
        # Most running injuries cost 1-4 weeks; ~30 % (bone stress, tendinopathy) cost 5-10 weeks.
        layoff = np.where(U() < 0.3, I(35, 71), I(7, 29))
        s['injured'] = np.where(hurt, layoff, s['injured']).astype(F)
        long_inj += hurt & (layoff >= 14)
        s['reinj'] = np.where(hurt, s['injured'] + 42, s['reinj']).astype(F)
        if collect:
            trace.append(dict(prim=prim.copy(), sec=sec.copy(), run_min=st['run_min'].copy(),
                              minutes=st['minutes'].copy(), impact=st['impact'].copy(),
                              thr=st['thr'].copy(), vo2=st['vo2'].copy(), mp=st['mp'].copy()))
        apply(s, st)
    t, vdot = race_minutes(s, base_levels, weight_ratio)
    # Injured on race day = DNS; most minor illness (a cold) still starts, so ~30 % of "sick" count.
    dns = (s['injured'] > 0) | ((s['sick'] > 0) & (U() < 0.3))
    t = np.where(dns, DNS_MINUTES, t)
    return dict(time=t, vdot=vdot, dns=dns, injuries=injuries, long_injuries=long_inj, state=s, trace=trace)


def sample_population(seed, n, rng, vdot_sd=2.5, fer_sd=25.0, resp_sd=0.40, fade_sd=0.03, wfrac=(0.0, 1.2)):
    """Stochastic athletes around a seed dict or a real (N=1) state: individual response, baseline
    fitness, how well the marathon distance suits them, how much of the planned weight loss they
    achieve and iron status are uncertain. Wide until a time trial pins VDOT down (HERITAGE: large
    individual variation in trainability, Bouchard 1999)."""
    if isinstance(seed.get('mf_fast'), np.ndarray):
        s = clone_state(seed, n)
        vb, fer = float(seed['vdot_base'][0]), float(seed['fer'][0])
    else:
        s = new_state(n, seed)
        vb, fer = seed['vdot_base'], seed.get('fer', 80)
    s['resp'] = rng.lognormal(0, resp_sd, n).astype(F)
    s['fade_i'] = rng.normal(0, fade_sd * D['fade_sd'] / 0.03, n).astype(F)
    s['wfrac'] = rng.uniform(wfrac[0], wfrac[1], n).astype(F)
    s['vdot_base'] = (vb + rng.normal(0, vdot_sd, n)).astype(F)
    s['fer'] = np.clip(fer + rng.normal(0, fer_sd, n), 15, 300).astype(F)
    return s
