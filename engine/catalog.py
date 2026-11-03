"""What each activity does to the body.

Muscle shares sum to ~1 and distribute a session's load (easy-run-minute
equivalents, "EM") across muscle groups. `transfer` is how much of the aerobic
load carries over to running fitness; `impact` is foot-strike load per minute
relative to easy running (drives bone/tendon stress and iron loss).
"""

MUSCLES = ('calves', 'quads', 'hamstrings', 'glutes', 'hip_flexors', 'core', 'back', 'chest_shoulders', 'arms')
MUSCLE_LABELS = {
    'calves': 'Calves & Achilles', 'quads': 'Quads', 'hamstrings': 'Hamstrings', 'glutes': 'Glutes',
    'hip_flexors': 'Hip flexors & adductors', 'core': 'Core', 'back': 'Back', 'chest_shoulders': 'Chest & shoulders',
    'arms': 'Arms',
}

_RUN = {'calves': .32, 'quads': .20, 'hamstrings': .15, 'glutes': .15, 'hip_flexors': .12, 'core': .06}
_WALK = {'calves': .35, 'quads': .20, 'hamstrings': .15, 'glutes': .20, 'hip_flexors': .10}
_BIKE = {'quads': .50, 'glutes': .25, 'calves': .08, 'hamstrings': .10, 'hip_flexors': .07}
_ELLIPTICAL = {'quads': .38, 'glutes': .25, 'calves': .14, 'hamstrings': .10, 'hip_flexors': .08, 'arms': .05}
_ROW = {'back': .30, 'quads': .22, 'glutes': .14, 'hamstrings': .10, 'arms': .12, 'core': .12}
_SWIM = {'back': .30, 'chest_shoulders': .30, 'arms': .15, 'core': .15, 'hip_flexors': .05, 'calves': .05}
_SPORT = {'calves': .25, 'quads': .22, 'hamstrings': .15, 'glutes': .15, 'hip_flexors': .1, 'core': .08, 'chest_shoulders': .05}
_YOGA = {'core': .3, 'hip_flexors': .2, 'hamstrings': .15, 'back': .15, 'chest_shoulders': .1, 'glutes': .1}

# id: label, emoji, transfer to running aerobic fitness, impact/min, muscle shares, default RPE, eccentric factor
ACTIVITIES = {
    'run':        dict(label='Run', icon='🏃', transfer=1.0, impact=1.0, muscles=_RUN, rpe=4, ecc=1.0, is_run=True),
    'treadmill':  dict(label='Treadmill run', icon='🏃', transfer=1.0, impact=0.9, muscles=_RUN, rpe=4, ecc=0.9, is_run=True),
    'trail':      dict(label='Trail run', icon='⛰️', transfer=1.0, impact=0.9, muscles=_RUN, rpe=5, ecc=1.2, is_run=True),
    'bike':       dict(label='Bike', icon='🚴', transfer=0.65, impact=0.0, muscles=_BIKE, rpe=4, ecc=0.3),
    'elliptical': dict(label='Elliptical', icon='🌀', transfer=0.8, impact=0.1, muscles=_ELLIPTICAL, rpe=4, ecc=0.4),
    'row':        dict(label='Rowing', icon='🚣', transfer=0.6, impact=0.0, muscles=_ROW, rpe=5, ecc=0.4),
    'swim':       dict(label='Swim', icon='🏊', transfer=0.45, impact=0.0, muscles=_SWIM, rpe=4, ecc=0.2),
    'walk':       dict(label='Walk', icon='🚶', transfer=0.3, impact=0.25, muscles=_WALK, rpe=2, ecc=0.5),
    'hike':       dict(label='Hike', icon='🥾', transfer=0.45, impact=0.4, muscles=_WALK, rpe=3, ecc=1.1),
    'strength':   dict(label='Gym / strength', icon='🏋️', transfer=0.1, impact=0.0, muscles=None, rpe=6, ecc=1.5),
    'mobility':   dict(label='Mobility / yoga', icon='🧘', transfer=0.05, impact=0.0, muscles=_YOGA, rpe=2, ecc=0.1),
    'sport':      dict(label='Sport', icon='⚽', transfer=0.6, impact=0.7, muscles=_SPORT, rpe=6, ecc=1.2),
    'sauna':      dict(label='Sauna', icon='♨', transfer=0.0, impact=0.0, muscles={}, rpe=1, ecc=0.0, load=0.0),
    'cold':       dict(label='Ice bath', icon='❄', transfer=0.0, impact=0.0, muscles={}, rpe=1, ecc=0.0, load=0.0),
    'rest':       dict(label='Rest day', icon='🌙', transfer=0.0, impact=0.0, muscles={}, rpe=1, ecc=0.0, load=0.0),
    'other':      dict(label='Other', icon='✨', transfer=0.4, impact=0.2, muscles=_SPORT, rpe=4, ecc=0.6),
}

# Strength exercises: muscle shares, eccentric factor, and whether they count
# toward running economy (heavy/explosive lower body; Blagrove et al. 2018).
EXERCISES = {
    'Romanian deadlift':      dict(m={'hamstrings': .5, 'glutes': .3, 'back': .15, 'core': .05}, ecc=1.5, economy=1.0),
    'Bulgarian split squat':  dict(m={'quads': .45, 'glutes': .35, 'hamstrings': .1, 'hip_flexors': .1}, ecc=1.4, economy=1.0),
    'Nordic curl':            dict(m={'hamstrings': 1.0}, ecc=2.2, economy=0.6),
    'Single-leg RDL':         dict(m={'hamstrings': .45, 'glutes': .4, 'core': .15}, ecc=1.3, economy=0.8),
    'Standing calf raise':    dict(m={'calves': 1.0}, ecc=1.2, economy=0.8),
    'Bent-knee calf raise':   dict(m={'calves': 1.0}, ecc=1.2, economy=0.8),
    'Tibialis raise':         dict(m={'calves': 1.0}, ecc=0.6, economy=0.3),
    'Glute bridge':           dict(m={'glutes': .7, 'hamstrings': .3}, ecc=0.8, economy=0.5),
    'Step-up':                dict(m={'quads': .5, 'glutes': .4, 'calves': .1}, ecc=1.0, economy=0.9),
    'Goblet squat':           dict(m={'quads': .55, 'glutes': .35, 'core': .1}, ecc=1.2, economy=0.8),
    'Copenhagen plank':       dict(m={'hip_flexors': .7, 'core': .3}, ecc=1.0, economy=0.4),
    'Lateral band walk':      dict(m={'glutes': 1.0}, ecc=0.5, economy=0.3),
    'Pogo hops':              dict(m={'calves': .8, 'quads': .2}, ecc=1.3, economy=1.2, impact=0.6),
    'Skipping (A-skips)':     dict(m={'calves': .5, 'hip_flexors': .3, 'quads': .2}, ecc=1.0, economy=1.0, impact=0.5),
    'Drop jump':              dict(m={'calves': .45, 'quads': .35, 'glutes': .2}, ecc=1.6, economy=1.3, impact=0.6),
    'Single-leg hops':        dict(m={'calves': .7, 'quads': .2, 'glutes': .1}, ecc=1.4, economy=1.2, impact=0.6),
    'Box jump':               dict(m={'quads': .5, 'glutes': .3, 'calves': .2}, ecc=1.0, economy=1.2, impact=0.4),
    'DB row':                 dict(m={'back': .75, 'arms': .25}, ecc=0.8, economy=0.1),
    'Lat pulldown':           dict(m={'back': .7, 'arms': .3}, ecc=0.8, economy=0.1),
    'Face pull':              dict(m={'back': .6, 'chest_shoulders': .4}, ecc=0.6, economy=0.1),
    'Band pull-apart':        dict(m={'back': .6, 'chest_shoulders': .4}, ecc=0.4, economy=0.05),
    'Push-up':                dict(m={'chest_shoulders': .65, 'arms': .2, 'core': .15}, ecc=0.8, economy=0.0),
    'KB row':                 dict(m={'back': .75, 'arms': .25}, ecc=0.8, economy=0.1),
    'Chin-up':                dict(m={'back': .65, 'arms': .35}, ecc=0.9, economy=0.1),
    'Reverse fly':            dict(m={'back': .6, 'chest_shoulders': .4}, ecc=0.5, economy=0.1),
    'Shoulder-tap plank':     dict(m={'core': .85, 'chest_shoulders': .15}, ecc=0.3, economy=0.3),
    'Backpack row':           dict(m={'back': .75, 'arms': .25}, ecc=0.8, economy=0.1),
    'Incline DB press':       dict(m={'chest_shoulders': .75, 'arms': .25}, ecc=0.8, economy=0.0),
    'Lateral raise':          dict(m={'chest_shoulders': 1.0}, ecc=0.6, economy=0.0),
    'Incline DB curl':        dict(m={'arms': 1.0}, ecc=0.8, economy=0.0),
    'Farmer carry':           dict(m={'core': .4, 'back': .3, 'arms': .3}, ecc=0.4, economy=0.3),
    'Pallof press':           dict(m={'core': 1.0}, ecc=0.4, economy=0.3),
    'Dead bug':               dict(m={'core': 1.0}, ecc=0.3, economy=0.2),
    'Side plank':             dict(m={'core': .8, 'hip_flexors': .2}, ecc=0.3, economy=0.3),
    'Plank':                  dict(m={'core': 1.0}, ecc=0.3, economy=0.2),
}

# Garmin FIT sport / sub_sport -> activity id
GARMIN_SPORT = {
    'running': 'run', 'trail_running': 'trail', 'treadmill': 'treadmill', 'cycling': 'bike', 'indoor_cycling': 'bike',
    'e_biking': 'bike', 'walking': 'walk', 'hiking': 'hike', 'swimming': 'swim', 'lap_swimming': 'swim',
    'open_water': 'swim', 'rowing': 'row', 'indoor_rowing': 'row', 'training': 'strength',
    'strength_training': 'strength', 'fitness_equipment': 'elliptical', 'elliptical': 'elliptical',
    'yoga': 'mobility', 'pilates': 'mobility', 'flexibility_training': 'mobility', 'stair_climbing': 'elliptical',
    'soccer': 'sport', 'tennis': 'sport', 'basketball': 'sport', 'generic': 'other',
}

# Session "types" the user can tag a run with; used to credit the right adaptation.
RUN_TYPES = {
    'easy': 'Easy', 'long': 'Long run', 'recovery': 'Recovery', 'strides': 'Easy + strides', 'tempo': 'Tempo / threshold',
    'intervals': 'Intervals (VO2)', 'hills': 'Hills', 'marathon_pace': 'Marathon pace', 'race': 'Race / time trial',
}
