import uuid
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import User, School, ClassGroup, Student, Screening, ProgrammeSettings
from core.schema import HEALTH, DIET
from core.scoring import add_months, evaluate


def sample_answers(day):
    answers = {'dob': add_months(day, -132).isoformat(), 'sex': 'male', 'weight': 32.0, 'height': 137.0, 'diet_type': 'lacto', 'deworming': 'yes', 'food_security': 'often'}
    answers.update({key: 'yes' if trigger == 'no' else 'no' for key, _, trigger in HEALTH})
    answers.update({key: 'no' if key == 'snacks' else 'yes' for key, _ in DIET if key not in ['egg', 'meat']})
    return answers


class Command(BaseCommand):
    help = 'Create clearly labelled fictional demo schools and three local test accounts. Safe to run repeatedly.'

    @transaction.atomic
    def handle(self, *args, **kwargs):
        if User.objects.filter(username='teacher@nutrilift.local').exists():
            self.stdout.write('Demo data already exists. No records changed.')
            return
        today = timezone.localdate()
        config = ProgrammeSettings.get()
        year = today.year if today.month >= 6 else today.year - 1
        config.academic_year = f'{year}-{year+1}'
        config.save()
        schools = [School.objects.create(name=name, district=district, city=city, address='Fictional school for local testing', is_demo=True) for name, district, city in [('Vidya Mandir School (Demo)', 'Pune', 'Pune'), ('Zilla Parishad School (Demo)', 'Nashik', 'Nashik'), ('Jeevan Shikshan School (Demo)', 'Pune', 'Baramati')]]
        password = 'NutriLift@2026'
        principal = User.objects.create_user(username='principal@nutrilift.local', email='principal@nutrilift.local', password=password, first_name='Anita Deshmukh', role='principal', school=schools[0], accepted_terms_at=timezone.now())
        teacher = User.objects.create_user(username='teacher@nutrilift.local', email='teacher@nutrilift.local', password=password, first_name='Meera', role='teacher', school=schools[0], accepted_terms_at=timezone.now())
        programme = User.objects.create_user(username='admin@nutrilift.local', email='admin@nutrilift.local', password=password, first_name='Programme Admin', role='programme', accepted_terms_at=timezone.now())
        for index, school in enumerate(schools):
            for grade, section in [(6, 'A'), (6, 'B')]:
                group = ClassGroup.objects.create(school=school, grade=grade, section=section)
                if index == 0:
                    group.teachers.add(teacher)
                for roll in range(1, 15 if index == 0 else 6):
                    student = Student.objects.create(group=group, academic_year=config.academic_year, roll_number=str(roll))
                    day = add_months(today, -4) if roll % 4 == 0 else today - timedelta(days=roll)
                    answers = sample_answers(day)
                    if roll % 3 == 0:
                        answers['pallor'] = 'yes'
                    elif roll % 4 == 0:
                        answers['deworming'] = 'unknown'
                    if roll % 7 == 0:
                        answers['snacks'] = 'yes'
                    result = evaluate(answers, day)
                    screening = Screening.objects.create(student=student, performed_by=teacher if index == 0 else programme, screened_on=day, created_at=timezone.now()-timedelta(days=(today-day).days), answers=answers, submission_key=uuid.uuid4(), **result)
                    if screening.result != 'green' and roll % 2 == 0:
                        screening.message_opened_at = screening.created_at
                        screening.message_opened_by = teacher if index == 0 else programme
                        screening.save()
        self.stdout.write('Created fictional demo data. See README.md for local test sign-ins.')
