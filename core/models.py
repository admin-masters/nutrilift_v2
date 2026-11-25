import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class School(models.Model):
    name = models.CharField(max_length=180)
    address = models.CharField(max_length=500)
    state = models.CharField(max_length=80, default='Maharashtra')
    district = models.CharField(max_length=80)
    city = models.CharField(max_length=80)
    invitation_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    is_demo = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.name}, {self.district}'


class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=16, choices=[('teacher', 'Teacher'), ('principal', 'Principal'), ('programme', 'SAPA / GOM')])
    school = models.ForeignKey(School, null=True, blank=True, on_delete=models.PROTECT)
    accepted_terms_at = models.DateTimeField(null=True)


class ClassGroup(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='classes')
    grade = models.PositiveSmallIntegerField()
    section = models.CharField(max_length=12)
    teachers = models.ManyToManyField(User, related_name='class_groups', blank=True)

    class Meta:
        ordering = ['school__name', 'grade', 'section']
        constraints = [models.UniqueConstraint(fields=['school', 'grade', 'section'], name='unique_class_group')]

    def __str__(self):
        return f'Class {self.grade} · Section {self.section}'


class Student(models.Model):
    group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, related_name='students')
    academic_year = models.CharField(max_length=9)
    roll_number = models.CharField(max_length=30)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['group', 'academic_year', 'roll_number'], name='unique_student_identity')]


class Screening(models.Model):
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='screenings')
    performed_by = models.ForeignKey(User, on_delete=models.PROTECT)
    screened_on = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    answers = models.JSONField()
    result = models.CharField(max_length=6, choices=[('red', 'Red'), ('yellow', 'Yellow'), ('green', 'Green')])
    findings = models.JSONField(default=list)
    bmi = models.FloatField(null=True)
    bmi_z = models.FloatField(null=True)
    age_months = models.PositiveSmallIntegerField()
    next_screening = models.DateField()
    message_opened_at = models.DateTimeField(null=True)
    message_opened_by = models.ForeignKey(User, null=True, on_delete=models.PROTECT, related_name='opened_messages')
    submission_key = models.UUIDField(unique=True)
    revision = models.PositiveIntegerField(default=1)
    rules_version = models.CharField(max_length=40, default='workbook-v1-ssb-yes')

    class Meta:
        ordering = ['-screened_on', '-created_at', '-id']
        indexes = [models.Index(fields=['screened_on', 'result']), models.Index(fields=['next_screening'])]

    @property
    def pending(self):
        return self.result in ('red', 'yellow') and not self.message_opened_at


class ScreeningRevision(models.Model):
    screening = models.ForeignKey(Screening, on_delete=models.PROTECT, related_name='revisions')
    changed_by = models.ForeignKey(User, on_delete=models.PROTECT)
    changed_at = models.DateTimeField(auto_now_add=True)
    previous = models.JSONField()
    reason = models.CharField(max_length=300)


DEFAULT_MESSAGE = 'नमस्कार {parent}, {school} येथील इयत्ता {class}, तुकडी {section}, हजेरी क्रमांक {roll} यांच्या पोषण तपासणीत पुढील बाबींवर लक्ष देण्याची गरज आढळली: {findings}. कृपया वर्गशिक्षकाशी संपर्क साधा आणि आरोग्य तपासणीसाठी डॉक्टरांचा सल्ला घ्या. पुढील शालेय तपासणी: {next_date}. {video}'


class ProgrammeSettings(models.Model):
    academic_year = models.CharField(max_length=9, default='2026-2027')
    guide_url = models.URLField(blank=True)
    guide_video_url = models.URLField(blank=True)
    red_video_url = models.URLField(blank=True)
    yellow_video_url = models.URLField(blank=True)
    red_message = models.TextField(default=DEFAULT_MESSAGE)
    yellow_message = models.TextField(default=DEFAULT_MESSAGE)
    content_approved = models.BooleanField(default=False)
    school_weekdays = models.CharField(max_length=20, default='0,1,2,3,4', help_text='Monday=0 through Sunday=6. Comma-separated.')
    holidays = models.TextField(blank=True, help_text='One YYYY-MM-DD date per line.')
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        return cls.objects.get_or_create(pk=1)[0]


class LocalEmail(models.Model):
    recipient = models.EmailField()
    subject = models.CharField(max_length=250)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class ReminderRun(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE)
    day = models.DateField()
    pending_count = models.PositiveIntegerField()
    due_count = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['teacher', 'day'], name='one_reminder_per_day')]


class LoginAttempt(models.Model):
    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(default=timezone.now)
