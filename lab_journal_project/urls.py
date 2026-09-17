from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.urls import path, include
from core import views
from core.forms import EmailAuthenticationForm

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/login/', LoginView.as_view(
        template_name='registration/login.html', authentication_form=EmailAuthenticationForm,
    ), name='login'),
    path('accounts/logout/', views.logout_view, name='logout'),
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
    path('teacher/admin/subgroups/', views.manage_subgroups, name='manage_subgroups'),
    path('teacher/admin/subgroups/<int:pk>/edit/', views.edit_subgroup, name='edit_subgroup'),
    path('teacher/admin/users/', views.manage_users, name='manage_users'),
    path('teacher/admin/users/create/', views.create_user, name='create_user'),
    path('teacher/admin/users/<int:pk>/edit/', views.edit_user, name='edit_user'),
    path('teacher/admin/lab-works/', views.manage_lab_works, name='manage_lab_works'),
    path('teacher/admin/lab-works/<int:pk>/edit/', views.edit_lab_work, name='edit_lab_work'),
    path('teacher/reports/attendance/', views.attendance_report, name='attendance_report'),
    path('teacher/reports/performance/', views.performance_report, name='performance_report'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
