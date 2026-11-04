"""Race distances the planner supports, and what changes with the distance.

The model was built and calibrated for the marathon. Shorter races use the same physiology (Daniels VDOT already
converts fitness into a finish time for any distance), with the distance-specific pieces scaled:

  * how much a short recent long run and low durability slow you down late in the race (a marathon problem far
    more than a 5 km one),
  * how much durability is worth in training (`dur_val`: less than for the marathon, but a weekly long run still
    builds the aerobic base short races sit on),
  * how long the long run needs to get (half-marathon plans peak around 1:45-2:00, 10 km plans around 75-90 min),
  * how long the taper is (about a week for 5 and 10 km, ~10-13 days for a half, ~3 weeks for a marathon:
    Bosquet 2007; Mujika & Padilla 2003),
  * what "race pace" work means (VO2 effort for a 5 km, between threshold and VO2 for a 10 km, threshold-ish for
    a half, steady for the marathon).

The optimiser's parameter box stays the same for every distance: `taper_days` and `lr_peak` are scaled here, so
precooked starting points and saved policies stay valid.

Couch to 5K is not a race plan: it is a walk/run progression (engine/c25k.py), so it has no simulation profile.
"""

PROFILES = {
    'marathon': dict(label='Marathon', short='marathon', km=42.195, taper_scale=1.0, lr_scale=1.0,
                     lr_full=170.0, dur_val=1.0, lr_amp=0.20, dur_fade=0.12, base_fade=0.02, fade_sd=0.03, peak_week=480.0,
                     no_long_days=9, legs_cut=12, rp_scale=1.0, rp_vo2=0.0, rp_thr=0.4, long_rp=True,
                     goal_b=10, goal_round=5, soft_min=3.0, long_day=90, min_weeks=6, band='marathon'),
    'half': dict(label='Half marathon', short='half marathon', km=21.0975, taper_scale=0.55, lr_scale=0.68,
                 lr_full=110.0, dur_val=0.85, lr_amp=0.08, dur_fade=0.07, base_fade=0.01, fade_sd=0.02, peak_week=430.0,
                 no_long_days=7, legs_cut=9, rp_scale=0.8, rp_vo2=0.05, rp_thr=0.7, long_rp=True,
                 goal_b=5, goal_round=1, soft_min=1.6, long_day=75, min_weeks=6, band='half'),
    '10k': dict(label='10 km', short='10 km', km=10.0, taper_scale=0.42, lr_scale=0.52,
                lr_full=75.0, dur_val=0.7, lr_amp=0.03, dur_fade=0.04, base_fade=0.005, fade_sd=0.015, peak_week=380.0,
                no_long_days=6, legs_cut=7, rp_scale=0.55, rp_vo2=0.35, rp_thr=0.6, long_rp=False,
                goal_b=2, goal_round=1, soft_min=0.8, long_day=60, min_weeks=4, band='race10k'),
    '5k': dict(label='5 km', short='5 km', km=5.0, taper_scale=0.35, lr_scale=0.42,
               lr_full=55.0, dur_val=0.6, lr_amp=0.01, dur_fade=0.02, base_fade=0.0, fade_sd=0.01, peak_week=330.0,
               no_long_days=5, legs_cut=6, rp_scale=0.35, rp_vo2=0.8, rp_thr=0.2, long_rp=False,
               goal_b=1, goal_round=0.5, soft_min=0.4, long_day=45, min_weeks=4, band='race5k'),
}
RACE_KINDS = tuple(PROFILES)
ALL_KINDS = RACE_KINDS + ('c25k',)


def key_of(program):
    """Distance key of a program (older plans have none: they are marathons)."""
    d = ((program or {}).get('race') or {}).get('distance') or 'marathon'
    return d if d in ALL_KINDS else 'marathon'


def profile(key):
    return PROFILES.get(key, PROFILES['marathon'])
