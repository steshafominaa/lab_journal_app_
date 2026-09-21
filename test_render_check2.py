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

u1 = User.objects.create_user(username='admin@test.com', email='admin@test.com', password='pass123', first_name='Учитель', last_name='Преподаватель')
p1 = Profile.objects.create(user=u1, role='teacher')
admin_teacher = Teacher.objects.create(profile=p1, is_admin=True)

u2 = User.objects.create_user(username='t2@test.com', email='t2@test.com', password='pass123', first_name='Петр', last_name='Петров')
p2 = Profile.objects.create(user=u2, role='teacher')
teacher2 = Teacher.objects.create(profile=p2, is_admin=False)

sg_b = Subgroup.objects.create(subgroup_name='РИС-24-1-2', teacher=teacher2)

su2 = User.objects.create_user(username='stud2@test.com', email='stud2@test.com', password='pass', first_name='Второй', last_name='Студент')
sp2 = Profile.objects.create(user=su2, role='student')
st2 = Student.objects.create(profile=sp2, subgroup=sg_b)

lw = LaboratoryWork.objects.create(
    title='Типы данных', report_deadline=datetime.date(2020, 1, 1), defense_deadline=datetime.date(2020, 1, 10),
    report_weight=0.5, defense_weight=0.5,
)
report2 = LabReport.objects.create(student=st2, lab_work=lw, submitted_at=datetime.date(2019, 12, 30))

from django.test import Client
client = Client()
client.force_login(u1)
resp = client.post(f'/teacher/defense/{st2.pk}/{lw.pk}/', {'defense_date': '', 'score': '7.5', 'comment': 'ok'})
print("POST:", resp.status_code, resp.get('Location'))

defense = Defense.objects.get(report=report2)
print("DB defense: date=", defense.defense_date, "score=", defense.score)

r3 = client.get('/teacher/')
c3 = r3.content.decode('utf-8')
idx = c3.find('Второй')
print(c3[idx-50:idx+1600])

runner.teardown_databases(old_config)
