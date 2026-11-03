"""Small, session-aware food guide. Goals are planning aids, not intake tracking.

Daily carbohydrate/protein: Thomas, Erdman & Burke, 2016 joint position statement.
During: AIS sports-food carbohydrate guidance. Recovery: SDA Recovery Nutrition.
The existing workout's gel schedule stays authoritative; one gel means 25 g carbs.
"""
import datetime as dt
import math


SOURCES = [
    {'label': 'Daily fuelling · joint position statement', 'url': 'https://pubmed.ncbi.nlm.nih.gov/26920240/'},
    {'label': 'During exercise · AIS', 'url': 'https://www.ausport.gov.au/ais/nutrition/supplements/group_a/sports-foods2/sports-drink/how-and-when-do-i-use-it'},
    {'label': 'Recovery · Sports Dietitians Australia', 'url': 'https://www.sportsdietitians.com.au/wp-content/uploads/2020/07/Recovery-Nutrition.pdf'},
]
QUALITY = {'threshold', 'vo2', 'hills', 'mp_run', 'xt_intervals', 'tt5k', 'tt10k', 'half', 'race'}


def daily_targets(w, program, minutes, strength_minutes, resting, next_long):
    """Daily energy and carbohydrate targets by training phase.

    Starting goals, not measured expenditure. Personal guide supplies the 160 g
    protein / 70 g fat anchors and day-type floors; former food UI supplies the
    planned-minute energy estimate. Exercise food is included, never added twice.
    """
    date = w['date']
    phase = 'A' if date < '2026-12-14' else 'B' if date < '2027-01-03' else 'C' if date < '2027-02-17' else 'D'
    kind = 'rest' if resting else w['kind']
    key = kind in QUALITY or kind in ('long', 'long_mp')
    day_type = 'rest' if resting and not strength_minutes else 'long' if key and minutes > 90 else 'hard' if key or strength_minutes and minutes else 'easy'
    floors = {'A': (2200, 2500, 2800, 3100), 'B': (2300, 2600, 2900, 3200),
              'C': (2500, 2800, 3100, 3500), 'D': (2400, 2700, 3000, 3400)}
    maintenance = {'A': 2400, 'B': 2380, 'C': 2350, 'D': 2400}[phase]
    deficit = 0 if key else {'A': 400, 'B': 280, 'C': 0, 'D': 0}[phase]
    bonus = 150 if key and phase in ('C', 'D') else 0
    cost = 0 if resting else minutes * (6 if w.get('sport') == 'cycling' else 10 if phase == 'C' else 9)
    kcal = max(floors[phase][('rest', 'easy', 'hard', 'long').index(day_type)],
               int(round((maintenance - deficit + bonus + cost + 4 * strength_minutes) / 50) * 50))
    if next_long:
        kcal = max(kcal, floors[phase][2])
    protein, fat = 160, 70
    carbs = math.floor((kcal - 4 * protein - 9 * fat) / 4 + .5)
    race = dt.date.fromisoformat(program['race']['date'])
    dtr = (race - dt.date.fromisoformat(date)).days
    if dtr in (1, 2):
        carbs = round(program['athlete']['weight_kg'] * (10 if dtr == 1 else 7))
        fat = 50
        kcal = carbs * 4 + protein * 4 + fat * 9
    return dict(kcal=kcal, carbs_g=carbs, protein_g=protein, fat_g=fat, phase=phase, day_type=day_type)


def guide(w, program, next_workout=None, resting=False):
    kind = 'rest' if resting else w['kind']
    sec = None if resting else w.get('secondary')
    strength = bool(sec and sec['kind'].startswith('strength'))
    minutes = 0 if resting else max(0, w.get('minutes', 0) - (sec['est_min'] if sec and sec['kind'] != 'mobility' else 0))
    recovery = kind in ('rest', 'recovery')
    hard = kind in QUALITY
    long = kind in ('long', 'long_mp', 'half', 'race')
    label = 'Rest & repair' if recovery else 'Easy training'
    if minutes >= 60 or hard:
        label = 'Training fuel'
    if minutes >= 120:
        label = 'Long-session fuel'
    note = 'These are whole-day starting goals from your nutrition plan, including meals, snacks, drinks and gels—not extra food on top. Calories are estimated from the planned workload, not measured burn. Adjust for hunger, recovery and your weight trend.'
    next_sec = (next_workout or {}).get('secondary')
    next_minutes = (next_workout or {}).get('minutes', 0) - (next_sec['est_min'] if next_sec and next_sec['kind'] != 'mobility' else 0)
    next_long = next_workout and (next_workout['kind'] in ('half', 'race') or next_workout['kind'] in ('long', 'long_mp') and next_minutes >= 90)
    if next_long:
        note += ' Tomorrow is a long run or race: include generous rice, pasta, potato or bread portions today, even if resting.'
    race = dt.date.fromisoformat(program['race']['date'])
    days_to_race = (race - dt.date.fromisoformat(w['date'])).days
    if days_to_race in (1, 2):
        label = 'Race fuelling'
        note += ' Use your rehearsed carb load: smaller, frequent low-fibre meals and snacks. Spread it across the day.'
    macros = [
        {'name': 'Carbs', 'foods': 'Oats, bread, rice, pasta, potatoes and fruit. A cup of cooked rice has roughly 45 g carbs; a banana about 25 g.'},
        {'name': 'Protein', 'foods': 'Aim for 4 meals/snacks with about 40 g protein each. Use chicken, fish, tofu, eggs, Greek yoghurt or a shake when convenient; check labels.'},
        {'name': 'Fats', 'foods': 'Include olive oil, avocado, nuts or seeds with meals. Keep fat and fibre lighter just before running if they upset your stomach.'},
    ]
    targets = daily_targets(w, program, minutes, sec['est_min'] if strength else 0, recovery, next_long)
    for m, key in zip(macros, ('carbs_g', 'protein_g', 'fat_g')):
        m['grams'] = [targets[key], targets[key]]
    meals = [
        {'label': 'Breakfast', 'protein_g': 40, 'carbs_g': round(targets['carbs_g'] * .25), 'example': 'Oats + milk + Greek yoghurt + fruit, or eggs + toast + yoghurt.'},
        {'label': 'Lunch', 'protein_g': 40, 'carbs_g': round(targets['carbs_g'] * .30), 'example': 'Rice / pasta / potatoes with chicken, fish, tofu or beans and vegetables.'},
        {'label': 'Dinner', 'protein_g': 40, 'carbs_g': round(targets['carbs_g'] * .30), 'example': 'A protein serve, vegetables and a carb portion sized to the day’s goal.'},
    ]
    meals.append({'label': 'Snacks & workout fuel', 'protein_g': 40, 'carbs_g': targets['carbs_g'] - sum(m['carbs_g'] for m in meals),
                  'example': 'Yoghurt / milk / a protein shake, fruit and toast. Workout gels or sports drink come from this same daily carb total; shift carbs between meals as needed.'})
    if recovery:
        before = 'Eat regular meals. Keep protein spread through the day; rest days still support muscle repair. No pre-workout snack needed for a gentle walk.'
        during = 'No gels needed. Drink normally with meals and to thirst.'
        after = 'No special recovery shake needed. Have your normal meal: rice or potatoes, chicken / fish / tofu, and vegetables.'
    else:
        before = ('2–3 h before: a familiar carb-rich breakfast, such as toast with jam, banana and yoghurt. If starting soon, have a small, easy-to-digest snack instead.' if long or hard else
                  '30–60 min before: a banana or toast with jam if hungry or training before breakfast. If you have eaten recently, no extra snack is needed.')
        during = 'No gels needed for this short session. Water to thirst.'
        if hard and 45 <= minutes <= 75:
            during = 'A gel is optional for the hard effort; a few sips of sports drink can also work. No need to force a full hourly gel schedule.'
        after = ('Within about 1–2 h, have a meal with 25–35 g protein and a generous carb portion: oats + milk + Greek yoghurt + fruit, or rice + chicken / tofu. Breakfast or dinner can be the recovery meal.' if long or hard or minutes >= 75 else
                 'Your next normal meal is enough: include carbs and 25–35 g protein, e.g. eggs + toast + yoghurt, or rice + chicken / tofu. A shake is optional, not required.')
    schedule = []
    rate = 0
    if not recovery and (w.get('fuel_plan') or minutes > 75):
        plan = w.get('fuel_plan') or {'first_s': 25 * 60, 'every_s': 50 * 60}
        first, every = plan['first_s'] / 60, plan['every_s'] / 60
        rate = round(25 * 60 / every)
        schedule = list(range(round(first), math.ceil(minutes - 5), round(every)))
        during = f'About {rate} g carbs/hour. With 25 g gels: first at {round(first)} min, then every {round(every)} min. Take water with gels unless the packet says otherwise.'
        during += ' Sports drink and chews count towards the same total; check the carbohydrate amount on your gel.'
        if rate > 60:
            during += ' Use a practised glucose + fructose mix; build tolerance in training.'
        elif not w.get('fuel_plan'):
            during += ' A banana or sports drink can replace gels on the bike or elliptical.'
    if strength:
        after += ' For the later strength session, a normal meal beforehand and protein at the following meal are enough; no extra gel or shake is required.'
    # Reserve workout carbs first, then split the remainder across food. Never
    # suggest a snack allowance smaller than the gels already prescribed.
    food_carbs = max(0, targets['carbs_g'] - 25 * len(schedule))
    for meal, fraction in zip(meals[:3], (.25, .30, .30)):
        meal['carbs_g'] = round(food_carbs * fraction)
    meals[-1]['carbs_g'] = targets['carbs_g'] - sum(m['carbs_g'] for m in meals[:3])
    return {'label': label, 'resting': recovery, 'macros': macros, 'note': note,
            'targets': targets, 'meals': meals,
            'before': before, 'during': during, 'after': after,
            'gel_minutes': schedule, 'gel_count': len(schedule), 'carbs_per_hour': rate,
            'hydration': 'Drink to thirst during exercise. In heat or long, sweaty sessions, take fluids and consider electrolytes; avoid forcing water.',
            'sources': SOURCES}


def annotate(days, program, logs):
    for i, w in enumerate(days):
        next_w = days[i + 1] if i + 1 < len(days) else None
        todays = [x for x in logs if x['date'] == w['date'] and not x.get('deleted')]
        rested = any(x['kind'] == 'rest' for x in todays) and not any(float(x.get('duration_min') or 0) > 0 for x in todays)
        w['nutrition'] = guide(w, program, next_w, resting=rested)
        # Allows Today to switch immediately after a locally rendered rest-day scenario.
        w['rest_nutrition'] = guide(w, program, next_w, resting=True)
