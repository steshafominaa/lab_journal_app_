from datetime import date
from openpyxl import Workbook
from openpyxl.utils import get_column_letter
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .models import (
    LaboratoryWork, LabReport, Student, Criterion, ReportReview, CriterionResult, Defense,
    Attendance, SickLeave, DisciplineResult, DisciplineSettings, Subgroup, Profile, Teacher, Assistant,
)
from .grading import (
    compute_student_summary, compute_report_details, compute_defense_details, compute_lab_grade,
)

User = get_user_model()


# Записывает список строк (каждая строка — список ячеек) в новый лист книги openpyxl
# и настраивает ширину столбцов по самому длинному значению в каждом из них.
def _write_xlsx_sheet(worksheet, rows):
    for row in rows:
        worksheet.append(row)
    widths = {}
    for row in rows:
        for col_index, value in enumerate(row, start=1):
            text = '' if value is None else str(value)
            widths[col_index] = max(widths.get(col_index, 0), len(text))
    for col_index, width in widths.items():
        worksheet.column_dimensions[get_column_letter(col_index)].width = min(max(width + 2, 10), 40)


def _xlsx_response(filename, rows):
    workbook = Workbook()
    _write_xlsx_sheet(workbook.active, rows)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    workbook.save(response)
    return response


# Проверка прав: редактировать данные подгруппы может либо админ, либо преподаватель,
# который сам ведёт эту подгруппу.
def _teacher_can_edit_subgroup(teacher, subgroup):
    return teacher.is_admin or (subgroup is not None and subgroup.teacher_id == teacher.pk)


def _require_admin(request):
    """Возвращает Teacher, если пользователь — преподаватель-администратор, иначе None."""
    teacher = getattr(request.user.profile, 'teacher', None)
    if teacher and teacher.is_admin:
        return teacher
    return None


def logout_view(request):
    """Разлогинивает пользователя и по GET, и по POST (стандартный LogoutView Django принимает только POST)."""
    logout(request)
    return redirect('home')


# Видеть данные могут все преподаватели по всем подгруппам (независимо от того, админ или нет).
# Редактировать — только свои подгруппы, это отдельно проверяется через _teacher_can_edit_subgroup.
def _visible_students_for_teacher(teacher):
    return Student.objects.select_related('subgroup', 'profile__user')


# То же самое, но для списка подгрупп (для выпадающего списка фильтра)
def _visible_subgroups_for_teacher(teacher):
    return Subgroup.objects.order_by('subgroup_name')


# Подгруппы, которыми преподаватель владеет сам (используется там, где разрешено
# только собственноручное управление — например, добавление дат занятий)
def _own_subgroups_for_teacher(teacher):
    return Subgroup.objects.filter(teacher=teacher).order_by('subgroup_name')


# Если на эту дату у студента подтверждённая справка — нельзя вручную поставить "не был",
# отметка защищена справкой (используется при сохранении посещаемости)
def _is_protected_by_confirmed_sick_leave(student, lesson_date):
    return SickLeave.objects.filter(
        student=student,
        status='подтверждена',
        start_date__lte=lesson_date,
        end_date__gte=lesson_date,
    ).exists()


# Куда отправить пользователя сразу после входа — зависит от его роли
@login_required
def login_redirect_view(request):
    profile = request.user.profile

    if profile.role == 'teacher':
        return redirect('teacher_dashboard')
    elif profile.role == 'student':
        return redirect('student_dashboard')
    elif profile.role == 'assistant':
        return redirect('assistant_dashboard')

    return redirect('admin:index')


# Страница администратора: список подгрупп + форма создания новой подгруппы.
# Тут же обрабатывается удаление подгруппы (через POST action=delete).
@login_required
def manage_subgroups(request):
    admin_teacher = _require_admin(request)
    if not admin_teacher:
        return redirect('teacher_dashboard')

    error = None
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('subgroup_name', '').strip()
            teacher_id = request.POST.get('teacher_id')
            if not name:
                error = 'Укажите название подгруппы.'
            elif not teacher_id:
                error = 'Выберите преподавателя, ведущего подгруппу.'
            else:
                try:
                    Subgroup.objects.create(subgroup_name=name, teacher_id=teacher_id)
                    return redirect('manage_subgroups')
                except IntegrityError:
                    error = 'Подгруппа с таким названием уже существует.'

        elif action == 'delete':
            subgroup = get_object_or_404(Subgroup, pk=request.POST.get('subgroup_id'))
            if subgroup.students.exists() or subgroup.assistants.exists():
                error = 'Нельзя удалить подгруппу: в ней ещё есть студенты или ассистенты.'
            else:
                subgroup.delete()
                return redirect('manage_subgroups')

    subgroups = Subgroup.objects.select_related('teacher__profile__user').order_by('subgroup_name')
    teachers = Teacher.objects.select_related('profile__user').order_by('profile__user__last_name')

    context = {'subgroups': subgroups, 'teachers': teachers, 'error': error}
    return render(request, 'manage_subgroups.html', context)


# Форма редактирования одной подгруппы (название + преподаватель)
@login_required
def edit_subgroup(request, pk):
    if not _require_admin(request):
        return redirect('teacher_dashboard')

    subgroup = get_object_or_404(Subgroup, pk=pk)
    teachers = Teacher.objects.select_related('profile__user').order_by('profile__user__last_name')
    error = None

    if request.method == 'POST':
        name = request.POST.get('subgroup_name', '').strip()
        teacher_id = request.POST.get('teacher_id')
        if not name or not teacher_id:
            error = 'Заполните название и преподавателя.'
        else:
            try:
                subgroup.subgroup_name = name
                subgroup.teacher_id = teacher_id
                subgroup.save()
                return redirect('manage_subgroups')
            except IntegrityError:
                error = 'Подгруппа с таким названием уже существует.'

    context = {'subgroup': subgroup, 'teachers': teachers, 'error': error}
    return render(request, 'edit_subgroup.html', context)


# Список всех пользователей для администратора + удаление пользователя
@login_required
def manage_users(request):
    if not _require_admin(request):
        return redirect('teacher_dashboard')

    error = None
    if request.method == 'POST' and request.POST.get('action') == 'delete':
        profile = get_object_or_404(Profile, pk=request.POST.get('profile_id'))
        if profile.user_id == request.user.id:
            error = 'Нельзя удалить свою собственную учётную запись.'
        else:
            try:
                profile.user.delete()
                return redirect('manage_users')
            except ProtectedError:
                error = (
                    'Нельзя удалить пользователя: с ним связаны данные, которые нельзя удалить '
                    '(например, преподаватель ведёт подгруппу или ассистент уже проверял отчёты).'
                )

    profiles = Profile.objects.select_related('user').prefetch_related(
        'teacher__subgroups', 'assistant__subgroup', 'student__subgroup',
    ).order_by('role', 'user__last_name')

    context = {'profiles': profiles, 'error': error}
    return render(request, 'manage_users.html', context)


# Создание нового пользователя (студент/ассистент/преподаватель) администратором.
# Тут же в одной транзакции создаётся и User, и Profile, и роль (Student/Assistant/Teacher).
@login_required
def create_user(request):
    if not _require_admin(request):
        return redirect('teacher_dashboard')

    subgroups = Subgroup.objects.order_by('subgroup_name')
    error = None

    if request.method == 'POST':
        email = request.POST.get('email', '').strip().lower()
        password = request.POST.get('password', '')
        last_name = request.POST.get('last_name', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        patronymic = request.POST.get('patronymic', '').strip()
        role = request.POST.get('role')
        is_admin = request.POST.get('is_admin') == 'on'
        subgroup_id = request.POST.get('subgroup_id')

        if not email or not password or not last_name or not first_name or not role:
            error = 'Заполните email, пароль, фамилию, имя и роль.'
        elif role in ('student', 'assistant') and not subgroup_id:
            error = 'Выберите подгруппу.'
        elif User.objects.filter(email__iexact=email).exists():
            error = 'Пользователь с таким email уже существует.'
        else:
            try:
                with transaction.atomic():
                    user = User.objects.create_user(
                        username=email, email=email, password=password,
                        first_name=first_name, last_name=last_name,
                    )
                    profile = Profile.objects.create(user=user, role=role, patronymic=patronymic)
                    if role == 'teacher':
                        Teacher.objects.create(profile=profile, is_admin=is_admin)
                    elif role == 'assistant':
                        Assistant.objects.create(profile=profile, subgroup_id=subgroup_id)
                    elif role == 'student':
                        Student.objects.create(profile=profile, subgroup_id=subgroup_id)
                return redirect('manage_users')
            except IntegrityError:
                error = 'Пользователь с таким email уже существует.'

    context = {'error': error, 'subgroups': subgroups, 'role_choices': Profile.ROLE_CHOICES}
    return render(request, 'create_user.html', context)


# Редактирование существующего пользователя: ФИО, пароль (если ввели новый), подгруппа/права
@login_required
def edit_user(request, pk):
    if not _require_admin(request):
        return redirect('teacher_dashboard')

    profile = get_object_or_404(Profile, pk=pk)
    user = profile.user
    subgroups = Subgroup.objects.order_by('subgroup_name')
    role_obj = getattr(profile, profile.role, None)
    error = None

    if request.method == 'POST':
        last_name = request.POST.get('last_name', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        patronymic = request.POST.get('patronymic', '').strip()
        password = request.POST.get('password', '')
        subgroup_id = request.POST.get('subgroup_id')
        is_admin = request.POST.get('is_admin') == 'on'

        if not last_name or not first_name:
            error = 'Заполните фамилию и имя.'
        elif profile.role in ('student', 'assistant') and not subgroup_id:
            error = 'Выберите подгруппу.'
        else:
            user.last_name = last_name
            user.first_name = first_name
            if password:
                user.set_password(password)
            user.save()

            profile.patronymic = patronymic
            profile.save()

            if profile.role == 'teacher':
                role_obj.is_admin = is_admin
                role_obj.save()
            elif profile.role == 'assistant':
                role_obj.subgroup_id = subgroup_id
                role_obj.save()
            elif profile.role == 'student':
                role_obj.subgroup_id = subgroup_id
                role_obj.save()

            return redirect('manage_users')

    context = {
        'profile': profile, 'user_obj': user, 'role_obj': role_obj,
        'subgroups': subgroups, 'error': error,
    }
    return render(request, 'edit_user.html', context)


# Проверка данных при создании/редактировании лабораторной работы:
# заполнены поля, веса — числа, сумма весов отчёта и защиты равна 1
def _validate_lab_work_fields(title, report_deadline, defense_deadline, report_weight, defense_weight):
    if not title or not report_deadline or not defense_deadline:
        return 'Заполните название и оба дедлайна.'
    try:
        report_weight_value = float(report_weight)
        defense_weight_value = float(defense_weight)
    except (TypeError, ValueError):
        return 'Введите корректные числа для весов отчёта и защиты.'
    if report_weight_value <= 0 or defense_weight_value <= 0:
        return 'Веса отчёта и защиты должны быть больше нуля.'
    if abs(report_weight_value + defense_weight_value - 1) > 0.001:
        return 'Сумма веса отчёта и веса защиты должна быть равна 1.'
    return None


# Список лабораторных работ для админа + форма добавления новой
@login_required
def manage_lab_works(request):
    if not _require_admin(request):
        return redirect('teacher_dashboard')

    error = None
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'delete':
            LaboratoryWork.objects.filter(pk=request.POST.get('lab_id')).delete()
            return redirect('manage_lab_works')

        title = request.POST.get('title', '').strip()
        report_deadline = request.POST.get('report_deadline')
        defense_deadline = request.POST.get('defense_deadline')
        report_weight = request.POST.get('report_weight')
        defense_weight = request.POST.get('defense_weight')

        error = _validate_lab_work_fields(title, report_deadline, defense_deadline, report_weight, defense_weight)
        if not error:
            try:
                LaboratoryWork.objects.create(
                    title=title, report_deadline=report_deadline, defense_deadline=defense_deadline,
                    report_weight=report_weight, defense_weight=defense_weight,
                )
                return redirect('manage_lab_works')
            except IntegrityError:
                error = 'Лабораторная работа с таким названием уже существует.'

    lab_works = LaboratoryWork.objects.order_by('report_deadline')

    # Для каждой лабораторной — средние баллы за отчёт/защиту/итог по всем студентам дисциплины
    students = list(Student.objects.all())
    lab_rows = []
    for lab_work in lab_works:
        if students:
            grades = [compute_lab_grade(student, lab_work) for student in students]
            avg_report = sum(g['report_score'] for g in grades) / len(grades)
            avg_defense = sum(g['defense_score'] for g in grades) / len(grades)
            avg_lab = sum(g['lab_score'] for g in grades) / len(grades)
        else:
            avg_report = avg_defense = avg_lab = None
        lab_rows.append({
            'lab_work': lab_work,
            'avg_report': avg_report,
            'avg_defense': avg_defense,
            'avg_lab': avg_lab,
        })

    context = {'lab_works': lab_works, 'lab_rows': lab_rows, 'error': error}
    return render(request, 'manage_lab_works.html', context)


# Редактирование одной лабораторной работы
@login_required
def edit_lab_work(request, pk):
    if not _require_admin(request):
        return redirect('teacher_dashboard')

    lab_work = get_object_or_404(LaboratoryWork, pk=pk)
    error = None

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        report_deadline = request.POST.get('report_deadline')
        defense_deadline = request.POST.get('defense_deadline')
        report_weight = request.POST.get('report_weight')
        defense_weight = request.POST.get('defense_weight')

        error = _validate_lab_work_fields(title, report_deadline, defense_deadline, report_weight, defense_weight)
        if not error:
            try:
                lab_work.title = title
                lab_work.report_deadline = report_deadline
                lab_work.defense_deadline = defense_deadline
                lab_work.report_weight = report_weight
                lab_work.defense_weight = defense_weight
                lab_work.save()
                return redirect('manage_lab_works')
            except IntegrityError:
                error = 'Лабораторная работа с таким названием уже существует.'

    context = {'lab_work': lab_work, 'error': error}
    return render(request, 'edit_lab_work.html', context)


# Главная страница преподавателя: доска со всеми подгруппами, студентами и лабами.
# Для каждого студента и каждой лабы собираем клетку с отчётом/защитой/проверкой,
# чтобы в шаблоне просто вывести карточки (это и есть "красивые таблицы" на главной).
@login_required
def teacher_dashboard(request):
    teacher = request.user.profile.teacher
    subgroups = Subgroup.objects.all().order_by('subgroup_name')
    lab_works = list(LaboratoryWork.objects.all())
    students = Student.objects.filter(subgroup__in=subgroups).select_related('subgroup')

    # Заранее вытаскиваем все отчёты/защиты/проверки одним запросом каждый,
    # чтобы не делать отдельный запрос в базу на каждую пару студент+лаба (было бы очень медленно)
    reports = {
        (report.student_id, report.lab_work_id): report
        for report in LabReport.objects.filter(student__in=students)
    }
    defenses = {
        (d.report.student_id, d.report.lab_work_id): d
        for d in Defense.objects.filter(report__student__in=students)
    }
    reviews = {
        (review.report.student_id, review.report.lab_work_id): review
        for review in ReportReview.objects.filter(report__student__in=students)
    }

    subgroup_blocks = []
    for subgroup in subgroups:
        subgroup_students = [s for s in students if s.subgroup_id == subgroup.pk]
        if not subgroup_students:
            continue

        editable = _teacher_can_edit_subgroup(teacher, subgroup)
        is_own = subgroup.teacher_id == teacher.pk

        rows = []
        for student in subgroup_students:
            cells = []
            for lab_work in lab_works:
                report = reports.get((student.pk, lab_work.pk))
                defense = defenses.get((student.pk, lab_work.pk))
                review = reviews.get((student.pk, lab_work.pk))
                has_defense_info = bool(
                    defense and (defense.defense_date or defense.score is not None)
                )
                defense_scored = bool(defense and defense.score is not None)
                cells.append({
                    'lab_work': lab_work,
                    'report': report,
                    'defense': defense,
                    'has_defense_info': has_defense_info,
                    'review': review,
                    'report_details': compute_report_details(student, lab_work) if review else None,
                    'defense_details': compute_defense_details(student, lab_work) if has_defense_info else None,
                    # Итог за лабораторную считаем, только когда есть и оценка за отчёт, и за защиту
                    'lab_score': compute_lab_grade(student, lab_work)['lab_score'] if (review and defense_scored) else None,
                })
            rows.append({'student': student, 'cells': cells})

        subgroup_blocks.append({
            'subgroup': subgroup,
            'editable': editable,
            'is_own': is_own,
            'rows': rows,
        })

    context = {
        'lab_works': lab_works,
        'subgroup_blocks': subgroup_blocks,
        'is_admin': teacher.is_admin,
    }
    return render(request, 'teacher_dashboard.html', context)


# Преподаватель/ассистент отмечает дату, когда студент сдал отчёт
@login_required
def set_report_date(request, lab_id):
    teacher = request.user.profile.teacher
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)
    student_id = request.GET.get('student_id') or request.POST.get('student_id')
    student = get_object_or_404(Student, pk=student_id)

    if not _teacher_can_edit_subgroup(teacher, student.subgroup):
        return redirect('teacher_dashboard')

    report, _ = LabReport.objects.get_or_create(student=student, lab_work=lab_work)

    if request.method == 'POST':
        report.submitted_at = request.POST.get('submitted_at') or None
        report.save()
        return redirect('teacher_dashboard')

    context = {'report': report, 'student': student, 'lab_work': lab_work}
    return render(request, 'set_report_date.html', context)


# Преподаватель отмечает дату, когда студент защитил лабораторную (без оценки — как и с отчётом)
@login_required
def set_defense(request, student_id, lab_id):
    teacher = request.user.profile.teacher
    student = get_object_or_404(Student, pk=student_id)
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)
    report = get_object_or_404(LabReport, student=student, lab_work=lab_work)

    if not _teacher_can_edit_subgroup(teacher, student.subgroup):
        return redirect('teacher_dashboard')

    defense, _ = Defense.objects.get_or_create(
        report=report, defaults={'teacher': teacher, 'defense_date': None}
    )

    if request.method == 'POST':
        defense.defense_date = request.POST.get('defense_date') or None
        defense.save()
        return redirect('teacher_dashboard')

    context = {'defense': defense, 'student': student, 'lab_work': lab_work}
    return render(request, 'set_defense.html', context)


# Преподаватель выставляет/меняет оценку и комментарий за уже назначенную защиту
@login_required
def review_defense(request, student_id, lab_id):
    teacher = request.user.profile.teacher
    student = get_object_or_404(Student, pk=student_id)
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)
    report = get_object_or_404(LabReport, student=student, lab_work=lab_work)
    defense = get_object_or_404(Defense, report=report)

    if not _teacher_can_edit_subgroup(teacher, student.subgroup):
        return redirect('teacher_dashboard')

    if request.method == 'POST':
        defense.score = request.POST.get('score') or None
        defense.comment = request.POST.get('comment', '')
        defense.save()
        return redirect('teacher_dashboard')

    defense_details = compute_defense_details(student, lab_work)

    context = {
        'defense': defense, 'student': student, 'lab_work': lab_work,
        'defense_penalty': defense_details['penalty'],
        'defense_final_score': defense_details['final_score'],
    }
    return render(request, 'review_defense.html', context)


# Таблица посещаемости, где можно отмечать статус (был/не был/болел) по датам занятий.
# GET — просто показывает таблицу, POST — сохраняет все изменённые отметки сразу.
@login_required
def attendance_dashboard(request):
    teacher = request.user.profile.teacher
    subgroups = _visible_subgroups_for_teacher(teacher)

    selected_subgroup_id = request.POST.get('subgroup') or request.GET.get('subgroup') or ''
    students_qs = _visible_students_for_teacher(teacher)
    if selected_subgroup_id:
        students_qs = students_qs.filter(subgroup_id=selected_subgroup_id)
    students = list(students_qs)

    # id студентов, отметки которых этому преподавателю разрешено менять
    editable_student_ids = {
        s.pk for s in students if _teacher_can_edit_subgroup(teacher, s.subgroup)
    }

    lesson_dates = sorted(set(
        Attendance.objects.filter(student__in=students).values_list('lesson_date', flat=True)
    ))

    records = {
        (a.student_id, a.lesson_date): a
        for a in Attendance.objects.filter(student__in=students)
    }

    if request.method == 'POST':
        # Форма шлёт кучу полей вида status_<id_студента>_<дата>, разбираем их по одному
        for key, value in request.POST.items():
            if key.startswith('status_'):
                _, student_id, lesson_date = key.split('_', 2)

                # Преподаватель может менять отметки только в своих подгруппах
                if int(student_id) not in editable_student_ids:
                    continue

                current = Attendance.objects.filter(
                    student_id=student_id, lesson_date=lesson_date
                ).first()
                current_status = current.status if current else None

                # Не даём случайно снять статус "болел" на "не был", если это закрыто справкой
                if current_status == 'Б' and value == 'Н':
                    student_obj = get_object_or_404(Student, pk=student_id)
                    if _is_protected_by_confirmed_sick_leave(student_obj, lesson_date):
                        continue

                Attendance.objects.update_or_create(
                    student_id=student_id, lesson_date=lesson_date,
                    defaults={'status': value or None}
                )
        if selected_subgroup_id:
            return redirect(f"{reverse('attendance_dashboard')}?subgroup={selected_subgroup_id}")
        return redirect('attendance_dashboard')

    rows = []
    for student in students:
        cells = []
        for lesson_date in lesson_dates:
            record = records.get((student.pk, lesson_date))
            status = record.status if record else ''
            cells.append({'lesson_date': lesson_date, 'status': status})
        rows.append({
            'student': student,
            'cells': cells,
            'editable': student.pk in editable_student_ids,
        })

    context = {
        'lesson_dates': lesson_dates,
        'rows': rows,
        'status_choices': Attendance.STATUS_CHOICES,
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
    }
    return render(request, 'attendance_dashboard.html', context)


# Отчёт по посещаемости (только для просмотра) со скачиванием в CSV
@login_required
def attendance_report(request):
    teacher = request.user.profile.teacher
    subgroups = _visible_subgroups_for_teacher(teacher)

    selected_subgroup_id = request.GET.get('subgroup') or ''
    students_qs = _visible_students_for_teacher(teacher).order_by(
        'profile__user__last_name', 'profile__user__first_name'
    )
    if selected_subgroup_id:
        students_qs = students_qs.filter(subgroup_id=selected_subgroup_id)
    students = list(students_qs)

    lesson_dates = sorted(set(
        Attendance.objects.filter(student__in=students).values_list('lesson_date', flat=True)
    ))
    records = {
        (a.student_id, a.lesson_date): a.status
        for a in Attendance.objects.filter(student__in=students)
    }

    rows = []
    total_present = total_absent = total_sick = 0
    for student in students:
        statuses = [records.get((student.pk, lesson_date)) for lesson_date in lesson_dates]
        present_count = sum(1 for s in statuses if s == 'П')
        absent_count = sum(1 for s in statuses if s == 'Н')
        sick_count = sum(1 for s in statuses if s == 'Б')
        total_present += present_count
        total_absent += absent_count
        total_sick += sick_count
        rows.append({
            'student': student,
            'cells': statuses,
            'present_count': present_count,
            'missed_count': absent_count + sick_count,
        })

    student_count = len(students)
    avg_present = total_present / student_count if student_count else None
    avg_absent = total_absent / student_count if student_count else None
    avg_sick = total_sick / student_count if student_count else None

    # Если в адресе есть ?export=xlsx — отдаём файл для скачивания вместо обычной страницы.
    if request.GET.get('export') == 'xlsx':
        sheet_rows = [
            ['Отчёт по посещаемости'],
            ['Студент'] + [d.strftime('%d.%m.') for d in lesson_dates] + ['Присутствия', 'Пропуски'],
        ]
        for row in rows:
            sheet_rows.append(
                [row['student'].profile.full_name()]
                + [cell or '' for cell in row['cells']]
                + [row['present_count'], row['missed_count']]
            )
        sheet_rows.append([])
        sheet_rows.append(['Среднее число присутствий', avg_present if avg_present is not None else ''])
        sheet_rows.append(['Сред��ее число пропусков', avg_absent if avg_absent is not None else ''])
        sheet_rows.append(['Среднее число пропусков по болезни', avg_sick if avg_sick is not None else ''])
        return _xlsx_response('attendance_report.xlsx', sheet_rows)

    context = {
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
        'lesson_dates': lesson_dates,
        'rows': rows,
        'avg_present': avg_present,
        'avg_absent': avg_absent,
        'avg_sick': avg_sick,
    }
    return render(request, 'attendance_report.html', context)


# Отчёт по успеваемости: для каждого студента и каждой лабы — баллы за отчёт/защиту/итог,
# плюс средняя оценка, экзамен и итоговая оценка по дисциплине. Тоже можно скачать в CSV.
@login_required
def performance_report(request):
    teacher = request.user.profile.teacher
    subgroups = _visible_subgroups_for_teacher(teacher)

    selected_subgroup_id = request.GET.get('subgroup') or ''
    students_qs = _visible_students_for_teacher(teacher).order_by(
        'profile__user__last_name', 'profile__user__first_name'
    )
    if selected_subgroup_id:
        students_qs = students_qs.filter(subgroup_id=selected_subgroup_id)
    students = list(students_qs)

    lab_works = list(LaboratoryWork.objects.order_by('report_deadline'))

    rows = []
    final_scores = []
    for student in students:
        summary = compute_student_summary(student)
        lab_cells = []
        if summary:
            grades_by_id = {g['lab_work'].pk: g for g in summary['grades']}
            for lab_work in lab_works:
                grade = grades_by_id.get(lab_work.pk)
                lab_cells.append({
                    'report_score': grade['report_score'] if grade else 0,
                    'defense_score': grade['defense_score'] if grade else 0,
                    'lab_score': grade['lab_score'] if grade else 0,
                })
            if summary['final_score'] is not None:
                final_scores.append(summary['final_score'])
        rows.append({'student': student, 'summary': summary, 'lab_cells': lab_cells})

    avg_final_score = sum(final_scores) / len(final_scores) if final_scores else None

    if request.GET.get('export') == 'xlsx':
        header_top = ['Студент']
        header_bottom = ['']
        for index, _lab_work in enumerate(lab_works, start=1):
            header_top += [f'ЛР {index}', '', '']
            header_bottom += ['Отчёт', 'Защита', 'Итог']
        header_top += ['Итог за ЛР', 'Экзамен', 'Итог']
        header_bottom += ['', '', '']

        sheet_rows = [['Отчёт по успеваемости'], header_top, header_bottom]

        for row in rows:
            line = [row['student'].profile.full_name()]
            for cell in row['lab_cells']:
                line += [
                    f"{cell['report_score']:.2f}",
                    f"{cell['defense_score']:.2f}",
                    f"{cell['lab_score']:.2f}",
                ]
            summary = row['summary']
            if summary:
                line.append(f"{summary['average_lab_score']:.2f}")
                line.append(f"{summary['exam_score']:.2f}" if summary['exam_score'] is not None else '—')
                line.append(f"{summary['final_score']:.2f}" if summary['final_score'] is not None else '—')
            else:
                line += ['—', '—', '—']
            sheet_rows.append(line)
        sheet_rows.append([])
        sheet_rows.append(['Средний балл по итоговой оценке', avg_final_score if avg_final_score is not None else ''])
        return _xlsx_response('performance_report.xlsx', sheet_rows)

    context = {
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
        'lab_works': lab_works,
        'rows': rows,
        'avg_final_score': avg_final_score,
    }
    return render(request, 'performance_report.html', context)


# Отчёт по должникам: у кого просрочен отчёт или защита и дедлайн уже прошёл
@login_required
def debtors_report(request):
    teacher = request.user.profile.teacher
    subgroups = _visible_subgroups_for_teacher(teacher)

    selected_subgroup_id = request.GET.get('subgroup') or ''
    students_qs = _visible_students_for_teacher(teacher).order_by(
        'profile__user__last_name', 'profile__user__first_name'
    )
    if selected_subgroup_id:
        students_qs = students_qs.filter(subgroup_id=selected_subgroup_id)
    students = list(students_qs)

    lab_works = list(LaboratoryWork.objects.order_by('report_deadline'))
    today = date.today()

    reports_by_key = {
        (r.student_id, r.lab_work_id): r
        for r in LabReport.objects.filter(student__in=students, lab_work__in=lab_works)
    }
    defenses_by_report_id = {
        d.report_id: d for d in Defense.objects.filter(report__student__in=students, report__lab_work__in=lab_works)
    }

    debts_by_student = {}
    for student in students:
        student_debts = []
        for lab_work in lab_works:
            report = reports_by_key.get((student.pk, lab_work.pk))

            # Дедлайн отчёта прошёл, а отчёт не сдан — это долг
            report_missing = lab_work.report_deadline < today and (not report or not report.submitted_at)
            if report_missing:
                student_debts.append({
                    'lab_work': lab_work,
                    'type': 'Отчёт',
                    'deadline': lab_work.report_deadline,
                })

            # Дедлайн защиты прошёл, а оценки за защиту нет — тоже долг;
            # если отчёт не сдан, защита по нему невозможна в принципе, поэтому
            # это тоже долг, даже если дедлайн защиты ещё не наступил
            defense = defenses_by_report_id.get(report.pk) if report else None
            if report_missing or (lab_work.defense_deadline < today and (not defense or defense.score is None)):
                student_debts.append({
                    'lab_work': lab_work,
                    'type': 'Защита',
                    'deadline': lab_work.defense_deadline,
                })

        if student_debts:
            debts_by_student[student] = student_debts

    rows = [
        {'student': student, 'debts': debts}
        for student, debts in debts_by_student.items()
    ]

    if request.GET.get('export') == 'xlsx':
        sheet_rows = [
            [f'Отчёт по должникам на {today.strftime("%d.%m.%Y")}'],
            ['Студент', 'Подгруппа', 'Лабораторная работа', 'Не сдано', 'Дедлайн'],
        ]
        for row in rows:
            for debt in row['debts']:
                sheet_rows.append([
                    row['student'].profile.full_name(),
                    row['student'].subgroup.subgroup_name,
                    debt['lab_work'].title,
                    debt['type'],
                    debt['deadline'].strftime('%d.%m.%Y'),
                ])
        return _xlsx_response('debtors_report.xlsx', sheet_rows)

    context = {
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
        'rows': rows,
        'today': today,
    }
    return render(request, 'debtors_report.html', context)


# Просто страница со ссылками на все отчёты
@login_required
def reports_hub(request):
    teacher = request.user.profile.teacher
    return render(request, 'reports_hub.html', {'is_admin': teacher.is_admin})


# Добавляет новую дату занятия и создаёт пустые (без статуса) отметки посещаемости
# для студентов ОДНОЙ выбранной подгруппы. Каждый преподаватель, включая администратора,
# может добавлять даты только для своих со��ственных подгрупп, и только по одной за раз.
@login_required
def add_lesson_date(request):
    teacher = request.user.profile.teacher
    own_subgroups = _own_subgroups_for_teacher(teacher)

    error = None
    if request.method == 'POST':
        lesson_date = request.POST.get('lesson_date')
        subgroup = own_subgroups.filter(pk=request.POST.get('subgroup_id')).first()
        if not lesson_date or not subgroup:
            error = 'Выберите свою подгруппу и дату занятия.'
        else:
            for student in Student.objects.filter(subgroup=subgroup):
                Attendance.objects.get_or_create(
                    student=student, lesson_date=lesson_date, defaults={'status': None}
                )
            return redirect(f"{reverse('attendance_dashboard')}?subgroup={subgroup.pk}")

    return render(request, 'add_lesson_date.html', {'subgroups': own_subgroups, 'error': error})


# Удаляет дату занятия и все связанные отметки посещаемости. Преподаватель может
# удалить дату только у студентов своих собственных подгрупп (администратор — у всех);
# отметки других подгрупп с той же календарной датой при этом не трогаются.
@login_required
def delete_lesson_date(request, lesson_date):
    if request.method != 'POST':
        return redirect('attendance_dashboard')

    teacher = request.user.profile.teacher
    editable_students = Student.objects.filter(
        subgroup__in=_own_subgroups_for_teacher(teacher)
    ) if not teacher.is_admin else Student.objects.all()

    Attendance.objects.filter(student__in=editable_students, lesson_date=lesson_date).delete()

    selected_subgroup_id = request.POST.get('subgroup') or ''
    if selected_subgroup_id:
        return redirect(f"{reverse('attendance_dashboard')}?subgroup={selected_subgroup_id}")
    return redirect('attendance_dashboard')


# Студент загружает файл со справкой (дальше преподаватель проставит даты и статус)
@login_required
def add_sick_leave(request):
    student = request.user.profile.student

    if request.method == 'POST' and request.FILES.get('file'):
        SickLeave.objects.create(student=student, file=request.FILES['file'])
        return redirect('student_dashboard')

    return render(request, 'add_sick_leave.html')


# Список всех загруженных справок для преподавателя, чтобы их рассмотреть
@login_required
def sick_leave_dashboard(request):
    teacher = request.user.profile.teacher
    if teacher.is_admin:
        students = Student.objects.select_related('subgroup')
    else:
        students = Student.objects.filter(subgroup__in=teacher.subgroups.all()).select_related('subgroup')
    sick_leaves = SickLeave.objects.filter(student__in=students).select_related('student__subgroup').order_by('-pk')

    context = {'sick_leaves': sick_leaves}
    return render(request, 'sick_leave_dashboard.html', context)


@login_required
def review_sick_leave(request, sick_leave_id):
    teacher = request.user.profile.teacher
    sick_leave = get_object_or_404(SickLeave, pk=sick_leave_id)

    if not _teacher_can_edit_subgroup(teacher, sick_leave.student.subgroup):
        return redirect('sick_leave_dashboard')

    if request.method == 'POST':
        sick_leave.start_date = request.POST.get('start_date') or None
        sick_leave.end_date = request.POST.get('end_date') or None
        sick_leave.status = request.POST.get('status')
        sick_leave.save()

        # Если справку подтвердили — все "не был" за этот период автоматически
        # меняем на "болел", чтобы это не считалось прогулом
        if sick_leave.status == 'подтверждена' and sick_leave.start_date and sick_leave.end_date:
            Attendance.objects.filter(
                student=sick_leave.student,
                status='Н',
                lesson_date__gte=sick_leave.start_date,
                lesson_date__lte=sick_leave.end_date,
            ).update(status='Б')

        return redirect('sick_leave_dashboard')

    return render(request, 'review_sick_leave.html', {'sick_leave': sick_leave})


# Итоги по дисциплине для преподавателя: тут выставляют бонусные баллы
# и оценку за экзамен (если студент не идёт ав��оматом)
@login_required
def results_dashboard(request):
    teacher = request.user.profile.teacher
    subgroups = _visible_subgroups_for_teacher(teacher)

    selected_subgroup_id = request.POST.get('subgroup') or request.GET.get('subgroup') or ''
    students = _visible_students_for_teacher(teacher)
    if selected_subgroup_id:
        students = students.filter(subgroup_id=selected_subgroup_id)

    if request.method == 'POST':
        for student in students:
            # Бонусы и экзамен можно менять только своим подгруппам (админу — любым)
            if not _teacher_can_edit_subgroup(teacher, student.subgroup):
                continue
            result, _ = DisciplineResult.objects.get_or_create(student=student)
            bonus_key = f'bonus_{student.pk}'
            exam_key = f'exam_{student.pk}'
            if bonus_key in request.POST:
                result.bonus_points = request.POST.get(bonus_key) or 0
            if exam_key in request.POST and request.POST.get(exam_key):
                result.exam_score = request.POST.get(exam_key)
            result.save()
        if selected_subgroup_id:
            return redirect(f"{reverse('results_dashboard')}?subgroup={selected_subgroup_id}")
        return redirect('results_dashboard')

    rows = []
    for student in students:
        summary = compute_student_summary(student)
        rows.append({
            'student': student,
            'summary': summary,
            'editable': _teacher_can_edit_subgroup(teacher, student.subgroup),
        })

    context = {
        'rows': rows,
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
    }
    return render(request, 'results_dashboard.html', context)


# Настройки дисциплины (веса лаб и экзамена в итоговой оценке). Одна строка настроек на всех.
@login_required
def discipline_settings_view(request):
    teacher = request.user.profile.teacher
    if not teacher.is_admin:
        return redirect('teacher_dashboard')

    settings_row, _ = DisciplineSettings.objects.get_or_create(
        defaults={'lab_weight': 0.5, 'exam_weight': 0.5}
    )

    error = None
    if request.method == 'POST':
        lab_weight = request.POST.get('lab_weight')
        exam_weight = request.POST.get('exam_weight')
        try:
            if abs(float(lab_weight) + float(exam_weight) - 1) > 0.001:
                error = 'Сумма весов должна быть равна 1.'
            else:
                settings_row.lab_weight = lab_weight
                settings_row.exam_weight = exam_weight
                settings_row.save()
                return redirect('teacher_dashboard')
        except (TypeError, ValueError):
            error = 'Введите корректные числа.'

    return render(request, 'discipline_settings.html', {'settings': settings_row, 'error': error})

# Критерии оценивания отчёта (по ним ассистент проверяет отчёты). Сумма всех
# максимальных баллов не может быть больше 8 — это ограничение проверяется тут.
@login_required
def criteria_management(request):
    teacher = request.user.profile.teacher
    if not teacher.is_admin:
        return redirect('teacher_dashboard')

    criteria = Criterion.objects.all().order_by('pk')
    total_max = sum(float(c.max_score) for c in criteria)

    error = None
    if request.method == 'POST':
        if 'delete_id' in request.POST:
            try:
                Criterion.objects.filter(pk=request.POST.get('delete_id')).delete()
                return redirect('criteria_management')
            except ProtectedError:
                error = 'Нельзя удалить критерий: он уже используется в проверенных отчётах.'
        else:
            description = request.POST.get('description', '').strip()
            max_score_raw = request.POST.get('max_score')
            try:
                max_score_value = float(max_score_raw)
                if not description:
                    error = 'Укажите название критерия.'
                elif max_score_value <= 0:
                    error = 'Максимальный балл должен быть больше нуля.'
                elif total_max + max_score_value > 8:
                    error = 'Сумма максимальных баллов по всем критериям не может превышать 8.'
                else:
                    Criterion.objects.create(description=description, max_score=max_score_value)
                    return redirect('criteria_management')
            except (TypeError, ValueError):
                error = 'Введите корректное число.'

    context = {'criteria': criteria, 'total_max': total_max, 'error': error}
    return render(request, 'criteria_management.html', context)

# Студент соглашается или отказывается от "автомата" (оценка за экзамен = средний балл за лабы)
@login_required
def set_auto_pass_agree(request):
    student = request.user.profile.student
    summary = compute_student_summary(student)

    if request.method == 'POST' and summary and summary['auto_pass_eligible']:
        agree = request.POST.get('agree') == 'yes'
        result, _ = DisciplineResult.objects.get_or_create(student=student)
        result.auto_pass_agree = agree
        result.save()

    return redirect('student_dashboard')


# Личный кабинет студента: его оценки по лабам, посещаемость, итог по дисциплине и справки
@login_required
def student_dashboard(request):
    student = request.user.profile.student
    lab_works = list(LaboratoryWork.objects.all())

    reports = {r.lab_work_id: r for r in LabReport.objects.filter(student=student)}
    reviews = {
        rv.report.lab_work_id: rv
        for rv in ReportReview.objects.filter(report__student=student)
    }
    results_by_review = {}
    for review in reviews.values():
        results_by_review[review.pk] = list(CriterionResult.objects.filter(review=review))

    defenses = {
        d.report.lab_work_id: d
        for d in Defense.objects.filter(report__student=student)
    }

    rows = []
    for lab_work in lab_works:
        report = reports.get(lab_work.pk)
        review = reviews.get(lab_work.pk)
        defense = defenses.get(lab_work.pk)
        rows.append({
            'lab_work': lab_work,
            'report': report,
            'review': review,
            'report_details': compute_report_details(student, lab_work) if review else None,
            'defense': defense,
            'defense_details': compute_defense_details(student, lab_work) if defense else None,
        })

    sick_leaves = SickLeave.objects.filter(student=student).order_by('-pk')
    attendance_records = Attendance.objects.filter(student=student).order_by('lesson_date')
    summary = compute_student_summary(student)

    context = {
        'student': student,
        'rows': rows,
        'sick_leaves': sick_leaves,
        'attendance_records': attendance_records,
        'summary': summary,
    }
    return render(request, 'student_dashboard.html', context)


# Личный кабинет ассистента: список студентов его подгруппы и статус проверки их отчётов
@login_required
def assistant_dashboard(request):
    assistant = request.user.profile.assistant
    students = Student.objects.filter(subgroup=assistant.subgroup)
    lab_works = list(LaboratoryWork.objects.all())

    reports = {
        (report.student_id, report.lab_work_id): report
        for report in LabReport.objects.filter(student__in=students)
    }
    reviews = {
        (review.report.student_id, review.report.lab_work_id): review
        for review in ReportReview.objects.filter(report__student__in=students)
    }

    rows = []
    for student in students:
        cells = []
        for lab_work in lab_works:
            report = reports.get((student.pk, lab_work.pk))
            review = reviews.get((student.pk, lab_work.pk)) if report else None
            cells.append({'lab_work': lab_work, 'report': report, 'review': review})
        rows.append({'student': student, 'cells': cells})

    context = {'lab_works': lab_works, 'rows': rows, 'assistant': assistant}
    return render(request, 'assistant_dashboard.html', context)


# Ассистент проверяет отчёт: выставляет баллы по каждому критерию и пишет комментарий
@login_required
def review_report(request, student_id, lab_id):
    assistant = request.user.profile.assistant
    student = get_object_or_404(Student, pk=student_id)
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)
    report = get_object_or_404(LabReport, student=student, lab_work=lab_work)

    review, _ = ReportReview.objects.get_or_create(
        report=report, defaults={'assistant': assistant, 'comment': '', 'reviewed_at': date.today()}
    )

    criteria = Criterion.objects.all()
    results = {r.criterion_id: r for r in CriterionResult.objects.filter(review=review)}

    if request.method == 'POST':
        for criterion in criteria:
            score = request.POST.get(f'criterion_{criterion.pk}') or 0
            CriterionResult.objects.update_or_create(
                review=review, criterion=criterion, defaults={'score': score}
            )
        review.comment = request.POST.get('comment', '')
        review.save()
        return redirect('assistant_dashboard')

    criteria_rows = [
        {'criterion': c, 'result': results.get(c.pk)} for c in criteria
    ]
    total = sum((r.score or 0) for r in results.values())
    report_details = compute_report_details(student, lab_work)

    context = {
        'student': student, 'lab_work': lab_work, 'review': review,
        'criteria_rows': criteria_rows, 'total': total,
        'report_penalty': report_details['penalty'],
        'report_final_score': report_details['final_score'],
    }
    return render(request, 'review_report.html', context)


# То же самое, что review_report, но со стороны преподавателя — он может
# перепроверить/поправить уже выставленные ассистентом баллы за отчёт
@login_required
def teacher_review_report(request, student_id, lab_id):
    teacher = request.user.profile.teacher
    student = get_object_or_404(Student, pk=student_id)
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)

    if not teacher.is_admin and student.subgroup not in teacher.subgroups.all():
        return redirect('teacher_dashboard')

    report = get_object_or_404(LabReport, student=student, lab_work=lab_work)
    review = ReportReview.objects.filter(report=report).first()
    
    criteria = Criterion.objects.all()
    results = {r.criterion_id: r for r in CriterionResult.objects.filter(review=review)} if review else {}
    
    if request.method == 'POST':
        if review is None:
            assistant = (
                Assistant.objects.filter(subgroup=student.subgroup).first()
                or Assistant.objects.first()
            )
            review = ReportReview.objects.create(
                report=report, assistant=assistant, comment='', reviewed_at=date.today()
            )
        for criterion in criteria:
            score = request.POST.get(f'criterion_{criterion.pk}') or 0
            CriterionResult.objects.update_or_create(
                review=review, criterion=criterion, defaults={'score': score}
            )
        review.comment = request.POST.get('comment', '')
        review.reviewed_at = date.today()
        review.save()
        return redirect('teacher_dashboard')

    criteria_rows = [
        {'criterion': c, 'result': results.get(c.pk)} for c in criteria
    ]
    total = sum((r.score or 0) for r in results.values())
    report_details = compute_report_details(student, lab_work)

    context = {
        'student': student, 'lab_work': lab_work, 'review': review,
        'criteria_rows': criteria_rows, 'total': total,
        'report_penalty': report_details['penalty'],
        'report_final_score': report_details['final_score'],
        'is_teacher_view': True,
    }
    return render(request, 'review_report.html', context)
