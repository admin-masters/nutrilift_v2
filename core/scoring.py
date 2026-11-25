import calendar
import json
import math
from datetime import date
from pathlib import Path
from .schema import HEALTH, DIET, label

REFERENCE = json.loads((Path(__file__).parent / 'data/who_bmi_lms.json').read_text()) if (Path(__file__).parent / 'data/who_bmi_lms.json').exists() else {}


def months_between(dob, day):
    return (day.year - dob.year) * 12 + day.month - dob.month - (day.day < dob.day)


def add_months(day, months):
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def lms_z(bmi, l, m, s):
    z = ((bmi / m) ** l - 1) / (l * s) if l else math.log(bmi / m) / s
    def cutoff(sd):
        return m * (1 + l * s * sd) ** (1 / l) if l else m * math.exp(s * sd)
    if z > 3:
        return 3 + (bmi - cutoff(3)) / (cutoff(3) - cutoff(2))
    if z < -3:
        return -3 + (bmi - cutoff(-3)) / (cutoff(-2) - cutoff(-3))
    return z


def bmi_flag(z):
    # Small tolerance avoids floating point errors at exact LMS boundaries.
    if z < -3 - 1e-10:
        return 'red', 'Severe thinness'
    if z > 2 + 1e-10:
        return 'red', 'Obesity'
    if z < -2 - 1e-10:
        return 'yellow', 'Thinness'
    if z > 1 + 1e-10:
        return 'yellow', 'Overweight'
    return 'green', 'BMI within reference range'


def evaluate(answers, day):
    months = months_between(date.fromisoformat(answers['dob']), day)
    findings, bmi, z = [], None, None
    def add(key, text, severity='red'):
        findings.append({'key': key, 'label': text, 'severity': severity})
    if months < 60:
        if answers['muac'] != 'green':
            add('muac', 'MUAC tape: ' + answers['muac'], answers['muac'])
    else:
        bmi = float(answers['weight']) / (float(answers['height']) / 100) ** 2
        l, m, s = REFERENCE[answers['sex']][str(months)]
        z = lms_z(bmi, l, m, s)
        flag, description = bmi_flag(z)
        if flag != 'green':
            add('bmi', description, flag)
    for key, _, trigger in HEALTH:
        if answers[key] == trigger:
            add(key, 'Does not feel healthy' if key == 'healthy' else label(key))
    for key, _ in DIET:
        if key in answers and answers[key] == ('yes' if key == 'snacks' else 'no'):
            add(key, label(key) if key == 'snacks' else label(key) + ': not eaten')
    if answers.get('menarche') == 'yes':
        for key, bad in [('pads', int(answers['pads']) > 4), ('clots', answers['clots'] == 'yes'), ('cycle', answers['cycle'] == 'yes'), ('bleeding_days', int(answers['bleeding_days']) > 10)]:
            if bad:
                add(key, label(key))
    if answers['deworming'] != 'yes':
        add('deworming', 'Deworming status: ' + ('not known' if answers['deworming'] == 'unknown' else 'not taken'), 'yellow' if answers['deworming'] == 'unknown' else 'red')
    if answers['food_security'] != 'often':
        add('food_security', 'Food at home: ' + answers['food_security'] + ' enough')
    result = 'red' if any(f['severity'] == 'red' for f in findings) else 'yellow' if findings else 'green'
    return {'result': result, 'findings': findings, 'bmi': bmi, 'bmi_z': z, 'age_months': months, 'next_screening': add_months(day, 6 if result == 'green' else 3)}
