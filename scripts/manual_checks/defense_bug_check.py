import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lab_journal_project.settings')
import lab_journal_project.settings as s
s.DATABASES['default'] = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}
s.ALLOWED_HOSTS = ['testserver']
django.setup()

from django.test.runner import DiscoverRunner
runner = DiscoverRunner()
old_config = runner.setup_databases()

from django.contrib.auth import get_user_model
from core.models import Profile, Teacher, Subgroup, Student, LaboratoryWork, LabReport, Defense
import datetime

User = get_user_model()

u1 = User.objects.create_user(username='admin@test.com', email='admin@test.com', password='pass123', first_name='Иван', last_name='Иванов')
p1 = Profile.objects.create(user=u1, role='teacher')
admin_teacher = Teacher.objects.create(profile=p1, is_admin=True)

u2 = User.objects.create_user(username='t2@test.com', email='t2@test.com', password='pass123', first_name='Петр', last_name='Петров')
p2 = Profile.objects.create(user=u2, role='teacher')
teacher2 = Teacher.objects.create(profile=p2, is_admin=False)

sg_b = Subgroup.objects.create(subgroup_name='B', teacher=teacher2)  # owned by teacher2, not admin

su1 = User.objects.create_user(username='stud@test.com', email='stud@test.com', password='pass', first_name='Студент', last_name='Тестов')
sp1 = Profile.objects.create(user=su1, role='student')
st1 = Student.objects.create(profile=sp1, subgroup=sg_b)

lw = LaboratoryWork.objects.create(
    title='ЛР1', report_deadline=datetime.date(2020, 1, 1), defense_deadline=datetime.date(2020, 1, 10),
    report_weight=0.5, defense_weight=0.5,
)
report = LabReport.objects.create(student=st1, lab_work=lw, submitted_at=datetime.date(2019, 12, 30))

from django.test import Client
client = Client()
client.force_login(u1)  # admin, not owner of sg_b

# Admin sets defense score+date for a student NOT in their own subgroup
resp = client.post(f'/teacher/defense/{st1.pk}/{lw.pk}/', {
    'defense_date': '2020-01-05',
    'score': '8',
    'comment': 'Хороший ответ',
})
print("POST set_defense status:", resp.status_code, resp.get('Location'))

defense = Defense.objects.get(report=report)
print("DB state: defense_date=", defense.defense_date, "score=", defense.score, "comment=", defense.comment)

# Revisit edit page - should show saved values
resp_edit = client.get(f'/teacher/defense/{st1.pk}/{lw.pk}/')
content_edit = resp_edit.content.decode('utf-8')
print("Edit page shows date 2020-01-05:", '2020-01-05' in content_edit)
print("Edit page shows score 8:", 'value="8.0"' in content_edit or 'value="8"' in content_edit)

# Now check dashboard
resp_dash = client.get('/teacher/')
content_dash = resp_dash.content.decode('utf-8')
print("\nDashboard shows defense date 05.01.2020:", '05.01.2020' in content_dash)
print("Dashboard shows 'защита не проведена':", 'защита не проведена' in content_dash)
idx = content_dash.find('Студент Тестов')
print(content_dash[idx:idx+1500])

runner.teardown_databases(old_config)
