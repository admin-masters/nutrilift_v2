from django.urls import path
from django.contrib.auth import views as auth
from django.contrib.staticfiles.views import serve
from core import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.SignInView.as_view(), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('join/<uuid:token>/', views.register, name='teacher_register'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('export/', views.export_records, name='export'),
    path('screen/<int:group_id>/', views.screening_form, name='screen_new'),
    path('screenings/<int:screening_id>/', views.screening_detail, name='screening'),
    path('screenings/<int:screening_id>/edit/', views.screening_form, name='screen_edit'),
    path('students/<int:student_id>/', views.student_detail, name='student'),
    path('students/<int:student_id>/rescreen/', views.screening_form, name='rescreen'),
    path('screenings/<int:screening_id>/notify/', views.notify_parent, name='notify'),
    path('screenings/<int:screening_id>/opened/', views.mark_opened, name='mark_opened'),
    path('invite/', views.invite, name='invite'),
    path('team/', views.school_team, name='team'),
    path('guide/', views.guide, name='guide'),
    path('guide/pdf/', views.guide_pdf, name='guide_pdf'),
    path('settings/', views.programme_settings, name='settings'),
    path('outbox/', views.outbox, name='outbox'),
    path('reminders/run/', views.reminders, name='reminders'),
    path('terms/', views.terms, name='terms'),
    path('account/password/', auth.PasswordChangeView.as_view(template_name='registration/password_form.html', success_url='/dashboard/'), name='password_change'),
    path('password-reset/', auth.PasswordResetView.as_view(template_name='registration/password_form.html', email_template_name='registration/password_reset_email.txt'), name='password_reset'),
    path('password-reset/done/', auth.PasswordResetDoneView.as_view(template_name='registration/password_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth.PasswordResetConfirmView.as_view(template_name='registration/password_form.html'), name='password_reset_confirm'),
    path('reset/complete/', auth.PasswordResetCompleteView.as_view(template_name='registration/password_done.html'), name='password_reset_complete'),
    path('health/', views.health, name='health'),
    # Explicit local static serving with DEBUG=False. Replace with proxy serving for EC2.
    path('static/<path:path>', serve, {'insecure': True}),
]
