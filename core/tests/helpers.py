# Небольшие фабрики для создания тестовых данных (пользователи, подгруппы и т.д.),
# чтобы не дублировать одинаковую "обвязку" в каждом тесте.
from django.contrib.auth import get_user_model

from core.models import Assistant, Profile, Student, Subgroup, Teacher

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
