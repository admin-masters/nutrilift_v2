"""Workbook row mapping. English is the canonical scoring vocabulary."""
import json
from pathlib import Path

WORKBOOK = json.loads((Path(__file__).parent / 'data/screening_workbook.json').read_text())
LANGUAGES = list(WORKBOOK)
HEALTH = [('healthy', 35, 'no'), ('pallor', 36, 'yes'), ('fatigue', 37, 'yes'), ('breathlessness', 38, 'yes'), ('infections', 39, 'yes'), ('chronic_illness', 40, 'yes'), ('worms', 41, 'yes'), ('dental', 42, 'yes'), ('night_vision', 43, 'yes'), ('bone_pain', 44, 'yes'), ('poor_appetite', 48, 'yes')]
DIET = [('breakfast', 63), ('lunch', 65), ('leafy_veg', 68), ('vegetables', 70), ('fruit', 72), ('pulses', 74), ('milk', 76), ('egg', 78), ('meat', 80), ('nuts', 82), ('snacks', 87)]
ROWS = dict([(key, row) for key, row, _ in HEALTH] + DIET + [('dob', 13), ('sex', 14), ('weight', 20), ('height', 22), ('muac', 24), ('menarche', 50), ('menarche_age', 51), ('pads', 52), ('clots', 53), ('cycle', 54), ('bleeding_days', 55), ('diet_type', 58), ('deworming', 90), ('deworming_date', 92), ('food_security', 95)])
LABEL_OVERRIDES = {'healthy': 'Does the student feel healthy?', 'poor_appetite': 'Does the student lack appetite or never feel hungry?', 'clots': 'Clots during menstrual bleeding?', 'pads': 'Pads used per day on heavy bleeding days', 'cycle': 'Are menstrual cycles more than 45 days apart?', 'deworming': 'Deworming tablet taken in the last 6–12 months?'}


def label(key, language='English'):
    if language == 'English' and key in LABEL_OVERRIDES:
        return LABEL_OVERRIDES[key]
    row = WORKBOOK.get(language, WORKBOOK['English']).get(str(ROWS.get(key, 0)), {})
    return (row.get('A') or row.get('B') or key).strip()


def prompt(key, language='English'):
    row = ROWS[key]
    data = WORKBOOK[language].get(str(row), {})
    if key in dict(DIET):
        # Meal prompts are on the flag row immediately below the label.
        return data.get('E') or WORKBOOK[language].get(str(row + 1), {}).get('E', '')
    if key in dict((k, r) for k, r, _ in HEALTH):
        return data.get('B', '')
    return ''
