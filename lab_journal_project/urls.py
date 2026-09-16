from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', views.login_redirect_view, name='home'),
    path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('student/', views.student_dashboard, name='student_dashboard'),
    path('assistant/', views.assistant_dashboard, name='assistant_dashboard'),
    path('teacher/lab/<int:lab_id>/submit/', views.set_report_date, name='set_report_date'),
    path('assistant/review/<int:student_id>/<int:lab_id>/', views.review_report, name='review_report'),
    path('teacher/defense/<int:student_id>/<int:lab_id>/', views.set_defense, name='set_defense'),
    path('teacher/attendance/', views.attendance_dashboard, name='attendance_dashboard'),
    path('teacher/attendance/add/', views.add_lesson_date, name='add_lesson_date'),
    path('student/sick-leave/add/', views.add_sick_leave, name='add_sick_leave'),
    path('teacher/sick-leave/', views.sick_leave_dashboard, name='sick_leave_dashboard'),
    path('teacher/sick-leave/<int:sick_leave_id>/', views.review_sick_leave, name='review_sick_leave'),
    path('teacher/results/', views.results_dashboard, name='results_dashboard'),
    path('teacher/discipline-settings/', views.discipline_settings_view, name='discipline_settings'),
    path('teacher/criteria/', views.criteria_management, name='criteria_management'),
    path('teacher/review/<int:student_id>/<int:lab_id>/', views.teacher_review_report, name='teacher_review_report'),
    path('student/auto-pass/', views.set_auto_pass_agree, name='set_auto_pass_agree'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
