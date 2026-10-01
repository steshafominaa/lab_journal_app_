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
from core.models import Profile, Teacher, Subgroup, Student, LaboratoryWork, LabReport, Defense, ReportReview, CriterionResult
import datetime

User = get_user_model()

u1 = User.objects.create_user(username='admin@test.com', email='admin@test.com', password='pass123', first_name='Учитель', last_name='Преподаватель')
p1 = Profile.objects.create(user=u1, role='teacher')
admin_teacher = Teacher.objects.create(profile=p1, is_admin=True)

u2 = User.objects.create_user(username='t2@test.com', email='t2@test.com', password='pass123', first_name='Петр', last_name='Петров')
p2 = Profile.objects.create(user=u2, role='teacher')
teacher2 = Teacher.objects.create(profile=p2, is_admin=False)

sg_a = Subgroup.objects.create(subgroup_name='РИС-24-1-1', teacher=admin_teacher)
sg_b = Subgroup.objects.create(subgroup_name='РИС-24-1-2', teacher=teacher2)

su1 = User.objects.create_user(username='stud@test.com', email='stud@test.com', password='pass', first_name='Ученик', last_name='Студент')
sp1 = Profile.objects.create(user=su1, role='student')
st1 = Student.objects.create(profile=sp1, subgroup=sg_a)

su2 = User.objects.create_user(username='stud2@test.com', email='stud2@test.com', password='pass', first_name='Второй', last_name='Студент')
sp2 = Profile.objects.create(user=su2, role='student')
st2 = Student.objects.create(profile=sp2, subgroup=sg_b)

lw = LaboratoryWork.objects.create(
    title='Типы данных', report_deadline=datetime.date(2020, 1, 1), defense_deadline=datetime.date(2020, 1, 10),
    report_weight=0.5, defense_weight=0.5,
)
report = LabReport.objects.create(student=st1, lab_work=lw, submitted_at=datetime.date(2019, 12, 30))
report2 = LabReport.objects.create(student=st2, lab_work=lw, submitted_at=datetime.date(2019, 12, 30))

from django.test import Client
client = Client()
client.force_login(u1)

# admin sets defense with only score, no date, for a student in another teacher's subgroup
resp = client.post(f'/teacher/defense/{st2.pk}/{lw.pk}/', {'defense_date': '', 'score': '7.5', 'comment': 'ok'})
print("set_defense POST:", resp.status_code)

pages = ['/teacher/', '/teacher/users/', '/accounts/login/', '/teacher/discipline-settings/', '/teacher/lab-works/']
for url in pages:
    try:
        r = client.get(url)
        print(url, "->", r.status_code, len(r.content), "bytes")
    except Exception as e:
        print(url, "-> EXCEPTION:", repr(e))

# logout and check login page (unauthenticated) + wrong login
client.logout()
r = client.get('/accounts/login/')
print('/accounts/login/ (anon) ->', r.status_code)
r2 = client.post('/accounts/login/', {'username': 'wrong@test.com', 'password': 'bad'})
content = r2.content.decode('utf-8')
print('login error status:', r2.status_code)
print('contains "Введите корректный email и пароль":', 'Введите корректный email и пароль' in content)
print('contains old long message:', 'чувствительны к регистру' in content)
print('contains errorlist:', 'errorlist' in content)

# check dashboard shows the admin-set defense (score, no date) for teacher2's subgroup
client.force_login(u1)
r3 = client.get('/teacher/')
c3 = r3.content.decode('utf-8')
print('\nDashboard contains "итог: 7.50":', 'итог: 7.50' in c3)
print('Dashboard contains "защита не проведена" anywhere (ok if for others):', c3.count('защита не проведена'))
print('Dashboard contains "ваша подгруппа":', 'ваша подгруппа' in c3)
print('Dashboard contains "доступно для редактирования":', 'доступно для редактирования' in c3)
print('Dashboard contains disabled defense pill for non-editable:', 'btn-pill-disabled' in c3)

runner.teardown_databases(old_config)
