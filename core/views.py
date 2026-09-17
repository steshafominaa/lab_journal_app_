import csv
from datetime import date
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
from .grading import compute_student_summary, compute_report_details, compute_defense_details

User = get_user_model()


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


def _visible_students_for_teacher(teacher):
    if teacher.is_admin:
        return Student.objects.select_related('subgroup', 'profile__user')
    return Student.objects.filter(subgroup__in=teacher.subgroups.all()).select_related('subgroup', 'profile__user')


def _visible_subgroups_for_teacher(teacher):
    if teacher.is_admin:
        return Subgroup.objects.order_by('subgroup_name')
    return teacher.subgroups.order_by('subgroup_name')


def _is_protected_by_confirmed_sick_leave(student, lesson_date):
    return SickLeave.objects.filter(
        student=student,
        status='подтверждена',
        start_date__lte=lesson_date,
        end_date__gte=lesson_date,
    ).exists()


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
    context = {'lab_works': lab_works, 'error': error}
    return render(request, 'manage_lab_works.html', context)


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


@login_required
def teacher_dashboard(request):
    teacher = request.user.profile.teacher
    subgroups = Subgroup.objects.all().order_by('subgroup_name')
    lab_works = list(LaboratoryWork.objects.all())
    students = Student.objects.filter(subgroup__in=subgroups).select_related('subgroup')

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

        rows = []
        for student in subgroup_students:
            cells = []
            for lab_work in lab_works:
                report = reports.get((student.pk, lab_work.pk))
                defense = defenses.get((student.pk, lab_work.pk))
                review = reviews.get((student.pk, lab_work.pk))
                cells.append({
                    'lab_work': lab_work,
                    'report': report,
                    'defense': defense,
                    'review': review,
                    'report_details': compute_report_details(student, lab_work) if review else None,
                    'defense_details': compute_defense_details(student, lab_work) if defense else None,
                })
            rows.append({'student': student, 'cells': cells})

        subgroup_blocks.append({
            'subgroup': subgroup,
            'editable': editable,
            'rows': rows,
        })

    context = {
        'lab_works': lab_works,
        'subgroup_blocks': subgroup_blocks,
        'is_admin': teacher.is_admin,
    }
    return render(request, 'teacher_dashboard.html', context)


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
    return render(request, 'set_defense.html', context)


@login_required
def attendance_dashboard(request):
    teacher = request.user.profile.teacher
    subgroups = _visible_subgroups_for_teacher(teacher)

    selected_subgroup_id = request.POST.get('subgroup') or request.GET.get('subgroup') or ''
    students = _visible_students_for_teacher(teacher)
    if selected_subgroup_id:
        students = students.filter(subgroup_id=selected_subgroup_id)

    lesson_dates = sorted(set(
        Attendance.objects.filter(student__in=students).values_list('lesson_date', flat=True)
    ))

    records = {
        (a.student_id, a.lesson_date): a
        for a in Attendance.objects.filter(student__in=students)
    }

    if request.method == 'POST':
        for key, value in request.POST.items():
            if key.startswith('status_'):
                _, student_id, lesson_date = key.split('_', 2)

                current = Attendance.objects.filter(
                    student_id=student_id, lesson_date=lesson_date
                ).first()
                current_status = current.status if current else None

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
            cells.append({'lesson_date': lesson_date, 'status': record.status if record else ''})
        rows.append({'student': student, 'cells': cells})

    context = {
        'lesson_dates': lesson_dates,
        'rows': rows,
        'status_choices': Attendance.STATUS_CHOICES,
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
    }
    return render(request, 'attendance_dashboard.html', context)


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
    for student in students:
        statuses = [records.get((student.pk, lesson_date)) for lesson_date in lesson_dates]
        rows.append({
            'student': student,
            'cells': statuses,
            'present_count': sum(1 for s in statuses if s == 'П'),
            'missed_count': sum(1 for s in statuses if s in ('Н', 'Б')),
        })

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="attendance_report.csv"'
        response.write('\ufeff')
        writer = csv.writer(response, delimiter=';')
        writer.writerow(['Отчет по посещаемости'])
        writer.writerow(
            ['Студент'] + [d.strftime('%d.%m.') for d in lesson_dates] + ['Присутствовал', 'Пропущено']
        )
        for row in rows:
            writer.writerow(
                [row['student'].profile.full_name()]
                + [cell or '' for cell in row['cells']]
                + [row['present_count'], row['missed_count']]
            )
        return response

    context = {
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
        'lesson_dates': lesson_dates,
        'rows': rows,
    }
    return render(request, 'attendance_report.html', context)


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
        rows.append({'student': student, 'summary': summary, 'lab_cells': lab_cells})

    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="performance_report.csv"'
        response.write('\ufeff')
        writer = csv.writer(response, delimiter=';')
        writer.writerow(['Отчет по успеваемости'])

        header_top = ['Студент']
        header_bottom = ['']
        for index, _lab_work in enumerate(lab_works, start=1):
            header_top += [f'ЛР {index}', '', '']
            header_bottom += ['Отчет', 'Защита', 'Итог']
        header_top += ['Итог за ЛР', 'Экзамен', 'Итог']
        header_bottom += ['', '', '']
        writer.writerow(header_top)
        writer.writerow(header_bottom)

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
                line.append(f"{summary['exam_score']:.2f}" if summary['exam_score'] is not None else '')
                line.append(f"{summary['final_score']:.2f}" if summary['final_score'] is not None else '')
            else:
                line += ['', '', '']
            writer.writerow(line)
        return response

    context = {
        'subgroups': subgroups,
        'selected_subgroup_id': selected_subgroup_id,
        'lab_works': lab_works,
        'rows': rows,
    }
    return render(request, 'performance_report.html', context)


@login_required
def add_lesson_date(request):
    teacher = request.user.profile.teacher
    if teacher.is_admin:
        students = Student.objects.all()
    else:
        students = Student.objects.filter(subgroup__in=teacher.subgroups.all())

    if request.method == 'POST':
        lesson_date = request.POST.get('lesson_date')
        if lesson_date:
            for student in students:
                Attendance.objects.get_or_create(
                    student=student, lesson_date=lesson_date, defaults={'status': None}
                )
        return redirect('attendance_dashboard')

    return render(request, 'add_lesson_date.html')


@login_required
def add_sick_leave(request):
    student = request.user.profile.student

    if request.method == 'POST' and request.FILES.get('file'):
        SickLeave.objects.create(student=student, file=request.FILES['file'])
        return redirect('student_dashboard')

    return render(request, 'add_sick_leave.html')


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

        if sick_leave.status == 'подтверждена' and sick_leave.start_date and sick_leave.end_date:
            Attendance.objects.filter(
                student=sick_leave.student,
                status='Н',
                lesson_date__gte=sick_leave.start_date,
                lesson_date__lte=sick_leave.end_date,
            ).update(status='Б')

        return redirect('sick_leave_dashboard')

    return render(request, 'review_sick_leave.html', {'sick_leave': sick_leave})


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
        rows.append({'student': student, 'summary': summary})

    context = {'rows': rows, 'subgroups': subgroups, 'selected_subgroup_id': selected_subgroup_id}
    return render(request, 'results_dashboard.html', context)


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
                    error = 'Су��ма максимальных баллов по всем критериям не может превышать 8.'
                else:
                    Criterion.objects.create(description=description, max_score=max_score_value)
                    return redirect('criteria_management')
            except (TypeError, ValueError):
                error = 'Введите корректное число.'

    context = {'criteria': criteria, 'total_max': total_max, 'error': error}
    return render(request, 'criteria_management.html', context)

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


@login_required
def teacher_review_report(request, student_id, lab_id):
    teacher = request.user.profile.teacher
    student = get_object_or_404(Student, pk=student_id)
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)

    if not teacher.is_admin and student.subgroup not in teacher.subgroups.all():
        return redirect('teacher_dashboard')

    report = get_object_or_404(LabReport, student=student, lab_work=lab_work)
    review = get_object_or_404(ReportReview, report=report)

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
