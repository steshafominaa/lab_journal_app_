# Небольшие фабрики для создания тестовых данных (пользователи, подгруппы и т.д.),
# чтобы не дублировать одинаковую "обвязку" в каждом тесте.
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model

from core.models import Assistant, LabReport, LaboratoryWork, Profile, Student, Subgroup, Teacher

User = get_user_model()

_counter = {'n': 0}


def _unique_email(prefix):
    _counter['n'] += 1
    return f"{prefix}{_counter['n']}@example.com"


def make_user(email=None, password='pass12345', first_name='Имя', last_name='Фамилия', is_active=True):
    email = email or _unique_email('user')
    user = User.objects.create_user(
        username=email, email=email, password=password,
        first_name=first_name, last_name=last_name,
    )
    if not is_active:
        user.is_active = False
        user.save()
    return user


def make_teacher(email=None, is_admin=False, **kwargs):
    user = make_user(email or _unique_email('teacher'), **kwargs)
    profile = Profile.objects.create(user=user, role='teacher')
    return Teacher.objects.create(profile=profile, is_admin=is_admin)


def make_subgroup(teacher, name=None):
    name = name or f"Группа-{_counter['n'] + 1}"
    _counter['n'] += 1
    return Subgroup.objects.create(subgroup_name=name, teacher=teacher)


def make_student(subgroup, email=None, **kwargs):
    user = make_user(email or _unique_email('student'), **kwargs)
    profile = Profile.objects.create(user=user, role='student')
    return Student.objects.create(profile=profile, subgroup=subgroup)


def make_assistant(subgroup, email=None, **kwargs):
    user = make_user(email or _unique_email('assistant'), **kwargs)
    profile = Profile.objects.create(user=user, role='assistant')
    return Assistant.objects.create(profile=profile, subgroup=subgroup)

def make_admin(email=None, **kwargs):
    """Преподаватель с правами администратора."""
    return make_teacher(email, is_admin=True, **kwargs)


def make_lab_work(title=None, report_weight='0.5', defense_weight='0.5'):
    _counter['n'] += 1
    return LaboratoryWork.objects.create(
        title=title or f"ЛР-{_counter['n']}",
        report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 2, 1),
        report_weight=Decimal(report_weight), defense_weight=Decimal(defense_weight),
    )


def make_report(student, lab_work, submitted_at=None):
    return LabReport.objects.create(student=student, lab_work=lab_work, submitted_at=submitted_at)