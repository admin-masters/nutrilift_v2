import re
from datetime import date
from string import Formatter
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone
from .models import User, ProgrammeSettings
from .schema import HEALTH, DIET, ROWS, label, prompt
from .scoring import months_between

YES_NO = [('', 'Choose an answer'), ('yes', 'Yes'), ('no', 'No')]


class SignInForm(AuthenticationForm):
    username = forms.EmailField(label='Email address', widget=forms.EmailInput(attrs={'autocomplete': 'username', 'placeholder': 'you@school.edu'}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={'autocomplete': 'current-password', 'placeholder': 'Your password'}))


class RegistrationForm(forms.Form):
    name = forms.CharField(max_length=120, label='Your full name')
    email = forms.EmailField(label='Email address')
    terms = forms.BooleanField(label='I accept the programme terms and privacy notice.')

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account already uses this email. Please sign in.')
        return email


class SchoolRegistrationForm(RegistrationForm):
    school_name = forms.CharField(max_length=180, label='School name')
    address = forms.CharField(max_length=500, widget=forms.Textarea(attrs={'rows': 2}))
    state = forms.CharField(max_length=80, initial='Maharashtra')
    district = forms.CharField(max_length=80)
    city = forms.CharField(max_length=80)
    field_order = ['school_name', 'address', 'state', 'district', 'city', 'name', 'email', 'terms']


class TeacherRegistrationForm(RegistrationForm):
    grade = forms.TypedChoiceField(choices=[(n, f'Class {n}') for n in range(1, 13)], coerce=int, label='Class')
    section = forms.RegexField(r'^[A-Za-z0-9]{1,12}$', max_length=12, initial='A')
    field_order = ['name', 'email', 'grade', 'section', 'terms']

    def clean_section(self):
        return self.cleaned_data['section'].upper()


class ScreeningForm(forms.Form):
    roll_number = forms.RegexField(r'^[A-Za-z0-9][A-Za-z0-9-]{0,29}$', label='Roll number', max_length=30)
    dob = forms.DateField(label='Date of birth', widget=forms.DateInput(attrs={'type': 'date'}))
    sex = forms.ChoiceField(choices=[('', 'Select sex'), ('male', 'Male'), ('female', 'Female')])
    weight = forms.FloatField(min_value=2, max_value=250, label='Weight (kg)', widget=forms.NumberInput(attrs={'step': '0.1'}))
    height = forms.FloatField(min_value=40, max_value=230, label='Height (cm)', widget=forms.NumberInput(attrs={'step': '0.1'}))
    muac = forms.ChoiceField(required=False, choices=[('', 'Select tape colour'), ('red', 'Red'), ('yellow', 'Yellow'), ('green', 'Green')])
    menarche = forms.ChoiceField(required=False, choices=YES_NO)
    menarche_age = forms.IntegerField(required=False, min_value=5, max_value=18)
    pads = forms.TypedChoiceField(required=False, choices=[('', 'Select number')] + [(i, str(i)) for i in range(1, 11)], coerce=int)
    clots = forms.ChoiceField(required=False, choices=YES_NO)
    cycle = forms.ChoiceField(required=False, choices=YES_NO)
    bleeding_days = forms.IntegerField(required=False, min_value=1, max_value=60)
    diet_type = forms.ChoiceField(choices=[('', 'Select usual diet'), ('lacto', 'Lacto-vegetarian'), ('ovo', 'Lacto-ovo-vegetarian (includes eggs)'), ('nonveg', 'Non-vegetarian')])
    deworming = forms.ChoiceField(choices=YES_NO + [('unknown', "Don’t know")])
    deworming_date = forms.DateField(required=False, label='Approximate deworming date (if known)', widget=forms.DateInput(attrs={'type': 'date'}))
    food_security = forms.ChoiceField(choices=[('', 'Choose an answer'), ('often', 'Often true'), ('sometimes', 'Sometimes true'), ('never', 'Never true')])
    submission_key = forms.UUIDField(widget=forms.HiddenInput())
    revision = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    correction_reason = forms.CharField(required=False, max_length=300, label='Reason for correction')

    def __init__(self, *args, day=None, editing=False, language='English', **kwargs):
        super().__init__(*args, **kwargs)
        self.day = day or timezone.localdate()
        self.editing = editing
        self.fields['dob'].widget.attrs['max'] = self.day.isoformat()
        self.fields['correction_reason'].required = editing
        for key, _, _ in HEALTH:
            self.fields[key] = forms.ChoiceField(choices=YES_NO)
        for key, _ in DIET:
            self.fields[key] = forms.ChoiceField(choices=YES_NO, required=key not in ('egg', 'meat'))
        for key in ROWS:
            if key in self.fields:
                self.fields[key].label = label(key, language)
                self.fields[key].help_text = prompt(key, language)
        self.groups = [
            ('A', 'Student details', ['roll_number', 'dob', 'sex']),
            ('B', 'Growth measurements', ['weight', 'height', 'muac']),
            ('C', 'Quick health check', [k for k, _, _ in HEALTH]),
            ('C2', 'Adolescent girls', ['menarche', 'menarche_age', 'pads', 'clots', 'cycle', 'bleeding_days']),
            ('D', 'Diet & diversity', ['diet_type'] + [k for k, _ in DIET]),
            ('E', 'Programme support', ['deworming', 'deworming_date']),
            ('F', 'Food security', ['food_security'])]
        self.sections = [{'code': code, 'title': title, 'fields': [self[k] for k in keys]} for code, title, keys in self.groups]

    def clean_roll_number(self):
        value = self.cleaned_data['roll_number'].upper()
        return str(int(value)) if value.isdigit() else value

    def clean(self):
        a = super().clean()
        dob = a.get('dob')
        if not dob:
            return a
        months = months_between(dob, self.day)
        if not 6 <= months < 228:
            self.add_error('dob', 'Screening supports children from 6 months up to their 19th birthday. Check the date of birth.')
            return a
        required = []
        if months < 60:
            required.append('muac')
        else:
            a.pop('muac', None)
        adolescent = months >= 120 and a.get('sex') == 'female'
        if adolescent:
            required.append('menarche')
        else:
            a.pop('menarche', None)
        for key in ['menarche_age', 'pads', 'clots', 'cycle', 'bleeding_days']:
            if adolescent and a.get('menarche') == 'yes':
                required.append(key)
            else:
                a.pop(key, None)
        if a.get('menarche_age') and a['menarche_age'] > months // 12:
            self.add_error('menarche_age', 'Age at first period cannot exceed the student’s current age.')
        for key, diets in [('egg', ['ovo', 'nonveg']), ('meat', ['nonveg'])]:
            if a.get('diet_type') in diets:
                required.append(key)
            else:
                a.pop(key, None)
        if a.get('deworming') != 'yes':
            a.pop('deworming_date', None)
        elif a.get('deworming_date') and not dob <= a['deworming_date'] <= self.day:
            self.add_error('deworming_date', 'Enter a date between birth and the screening date.')
        for key in required:
            if not a.get(key) and key not in self.errors:
                self.add_error(key, 'Please complete this question.')
        return a

    def answers(self):
        return {k: v.isoformat() if isinstance(v, date) else v for k, v in self.cleaned_data.items() if k in ROWS and v not in (None, '')}


class ResourceURLField(forms.URLField):
    def __init__(self, *args, **kwargs):
        kwargs['assume_scheme'] = 'https'
        super().__init__(*args, **kwargs)

    def validate(self, value):
        super().validate(value)
        if value and not value.startswith(('https://', 'http://')):
            raise forms.ValidationError('Use an HTTP or HTTPS link.')


class SettingsForm(forms.ModelForm):
    class Meta:
        model = ProgrammeSettings
        exclude = ['academic_year']
        field_classes = {key: ResourceURLField for key in ['guide_url', 'guide_video_url', 'red_video_url', 'yellow_video_url']}
        labels = {'guide_url': 'Screening guide PDF URL', 'guide_video_url': 'Teacher screening video URL', 'red_video_url': 'Marathi parent video URL for red results', 'yellow_video_url': 'Marathi parent video URL for yellow results', 'red_message': 'Marathi message for red results', 'yellow_message': 'Marathi message for yellow results', 'content_approved': 'Messages and resources have been approved by the programme team', 'school_weekdays': 'School days', 'holidays': 'School holidays'}
        widgets = {'red_message': forms.Textarea(attrs={'rows': 5}), 'yellow_message': forms.Textarea(attrs={'rows': 5}), 'holidays': forms.Textarea(attrs={'rows': 3})}

    def clean_school_weekdays(self):
        value = self.cleaned_data['school_weekdays']
        if not re.fullmatch(r'[0-6](,[0-6])*', value):
            raise forms.ValidationError('Use weekday numbers 0–6, separated by commas.')
        return value

    def clean_holidays(self):
        value = self.cleaned_data['holidays']
        try:
            for item in value.splitlines():
                if item.strip():
                    date.fromisoformat(item.strip())
        except ValueError:
            raise forms.ValidationError('Use one YYYY-MM-DD date per line.')
        return value

    def clean(self):
        a = super().clean()
        allowed = {'parent', 'school', 'class', 'section', 'roll', 'findings', 'next_date', 'video'}
        for key in ['red_message', 'yellow_message']:
            try:
                for _, field, spec, conv in Formatter().parse(a.get(key, '')):
                    if field is not None and (field not in allowed or spec or conv):
                        self.add_error(key, 'Use only the supported placeholders shown below.')
                        break
            except ValueError:
                self.add_error(key, 'Check the message placeholder braces.')
        if a.get('content_approved'):
            for key in ['red_video_url', 'yellow_video_url', 'guide_url', 'guide_video_url']:
                if not a.get(key):
                    self.add_error(key, 'Add this resource before marking content approved.')
        return a
