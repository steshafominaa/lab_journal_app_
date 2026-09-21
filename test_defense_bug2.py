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

sg_a = Subgroup.objects.create(subgroup_name='A', teacher=admin_teacher)

su1 = User.objects.create_user(username='stud@test.com', email='stud@test.com', password='pass', first_name='Студент', last_name='Тестов')
sp1 = Profile.objects.create(user=su1, role='student')
st1 = Student.objects.create(profile=sp1, subgroup=sg_a)

lw = LaboratoryWork.objects.create(
    title='ЛР1', report_deadline=datetime.date(2020, 1, 1), defense_deadline=datetime.date(2020, 1, 10),
    report_weight=0.5, defense_weight=0.5,
)
report = LabReport.objects.create(student=st1, lab_work=lw, submitted_at=datetime.date(2019, 12, 30))

from django.test import Client
client = Client()
client.force_login(u1)

# Admin sets ONLY score+comment, leaves date blank (common real-world scenario)
resp = client.post(f'/teacher/defense/{st1.pk}/{lw.pk}/', {
    'defense_date': '',
    'score': '8',
    'comment': 'Хороший ответ',
})
print("POST status:", resp.status_code)

defense = Defense.objects.get(report=report)
print("DB: date=", defense.defense_date, "score=", defense.score)

resp_dash = client.get('/teacher/')
content_dash = resp_dash.content.decode('utf-8')
print("Dashboard shows 'защита не проведена':", 'защита не проведена' in content_dash)
print("Dashboard shows score 8:", '8.00' in content_dash)

runner.teardown_databases(old_config)
