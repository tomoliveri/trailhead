"""Running physiology helpers: Daniels/Gilbert VDOT, training paces, HR zones.

Daniels & Gilbert (1979) oxygen-cost and drop-dead curves. All functions accept
numpy arrays so the optimiser can call them vectorised.
"""
import math

import numpy as np

MARATHON_M = 42195.0


def vo2_cost(v_m_per_min):
    """O2 cost (ml/kg/min) of running at velocity v (m/min)."""
    v = np.asarray(v_m_per_min, dtype=np.float64)
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def frac_vo2max(t_min):
    """Fraction of VO2max sustainable for t minutes."""
    t = np.asarray(t_min, dtype=np.float64)
    return 0.8 + 0.1894393 * np.exp(-0.012778 * t) + 0.2989558 * np.exp(-0.1932605 * t)


def vdot_from_race(dist_m, t_min):
    v = dist_m / t_min
    return vo2_cost(v) / frac_vo2max(t_min)


def velocity_for_vo2(vo2):
    """Invert vo2_cost: velocity (m/min) that costs `vo2` ml/kg/min."""
    a, b, c = 0.000104, 0.182258, -4.60 - np.asarray(vo2, dtype=np.float64)
    return (-b + np.sqrt(b * b - 4 * a * c)) / (2 * a)


def race_time(dist_m, vdot, iters=40):
    """Predicted race time (min) for distance at VDOT, vectorised bisection."""
    vdot = np.asarray(vdot, dtype=np.float64)
    lo = np.full(vdot.shape, dist_m / 450.0)   # absurdly fast
    hi = np.full(vdot.shape, dist_m / 60.0)    # walking
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        faster = vdot_from_race(dist_m, mid) > vdot  # at mid the required VDOT exceeds ours -> too fast
        lo = np.where(faster, mid, lo)
        hi = np.where(faster, hi, mid)
    return 0.5 * (lo + hi)


def pace_s_per_km(v_m_per_min):
    return 60000.0 / np.asarray(v_m_per_min, dtype=np.float64)


def training_paces(vdot):
    """Daniels training paces (s/km) as (fast, slow) ranges for a scalar VDOT."""
    vdot = float(vdot)

    def at(frac):
        return float(pace_s_per_km(velocity_for_vo2(frac * vdot)))

    m_time = float(race_time(MARATHON_M, vdot))
    hm_time = float(race_time(21097.5, vdot))
    mp = m_time * 60 / 42.195
    hmp = hm_time * 60 / 21.0975
    return {
        'recovery': (at(0.62), at(0.55)),
        'easy': (at(0.70), at(0.62)),
        'long': (at(0.72), at(0.63)),
        'marathon': (mp - 4, mp + 4),
        'half': (hmp - 4, hmp + 4),
        'threshold': (at(0.89), at(0.86)),
        'interval': (at(0.99), at(0.955)),
        'repetition': (at(1.07), at(1.03)),
    }


def fmt_pace(sec_per_km):
    s = int(round(sec_per_km))
    return f"{s // 60}:{s % 60:02d}"


def fmt_hms(minutes):
    s = int(round(minutes * 60))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def hr_zones(hr_max, hr_rest):
    """Garmin-default %HRmax zones plus Karvonen reference ranges (bpm)."""
    pct = [(0.50, 0.60), (0.60, 0.70), (0.70, 0.80), (0.80, 0.90), (0.90, 1.00)]
    return [{'zone': i + 1, 'low': round(hr_max * lo), 'high': round(hr_max * hi)} for i, (lo, hi) in enumerate(pct)]


def hr_cap_for(kind, hr_max, hr_rest):
    """Upper HR (bpm) for easy-type sessions using heart-rate reserve (Karvonen)."""
    hrr = hr_max - hr_rest
    caps = {'recovery': 0.62, 'easy': 0.72, 'long': 0.75, 'marathon': 0.84, 'threshold': 0.90}
    frac = caps.get(kind)
    return None if frac is None else round(hr_rest + frac * hrr)


def vdot_from_hr_run(pace_s_km, avg_hr, hr_max, hr_rest):
    """Estimate VDOT from a steady aerobic run using %HRR ~= %VO2R (Swain & Leutholtz 1997)."""
    if not (pace_s_km and avg_hr and hr_max and hr_rest) or avg_hr <= hr_rest:
        return None
    hrr = (avg_hr - hr_rest) / (hr_max - hr_rest)
    if not 0.5 <= hrr <= 0.92:
        return None
    v = 60000.0 / pace_s_km
    vo2 = float(vo2_cost(v))
    return 3.5 + (vo2 - 3.5) / hrr


def riegel(t1_min, d1_m, d2_m, k=1.06):
    return t1_min * math.pow(d2_m / d1_m, k)
