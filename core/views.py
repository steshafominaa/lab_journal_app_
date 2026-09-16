from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404

from .models import (
    LaboratoryWork, LabReport, Student, Criterion, ReportReview, CriterionResult, Defense,
    Attendance, SickLeave,
)


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
def teacher_dashboard(request):
    teacher = request.user.profile.teacher
    students = Student.objects.filter(subgroup=teacher.subgroups.first())
    lab_works = list(LaboratoryWork.objects.all())

    reports = {
        (report.student_id, report.lab_work_id): report
        for report in LabReport.objects.filter(student__in=students)
    }
    defenses = {
        (d.report.student_id, d.report.lab_work_id): d
        for d in Defense.objects.filter(report__student__in=students)
    }

    rows = []
    for student in students:
        cells = []
        for lab_work in lab_works:
            report = reports.get((student.pk, lab_work.pk))
            defense = defenses.get((student.pk, lab_work.pk))
            cells.append({
                'lab_work': lab_work,
                'report': report,
                'defense': defense,
            })
        rows.append({'student': student, 'cells': cells})

    context = {
        'lab_works': lab_works,
        'rows': rows,
    }
    return render(request, 'teacher_dashboard.html', context)


@login_required
def set_report_date(request, lab_id):
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)
    student_id = request.GET.get('student_id') or request.POST.get('student_id')
    student = get_object_or_404(Student, pk=student_id)

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

    defense, _ = Defense.objects.get_or_create(
        report=report, defaults={'teacher': teacher, 'defense_date': None}
    )

    if request.method == 'POST':
        defense.defense_date = request.POST.get('defense_date') or None
        defense.score = request.POST.get('score') or None
        defense.comment = request.POST.get('comment', '')
        defense.save()
        return redirect('teacher_dashboard')

    context = {'defense': defense, 'student': student, 'lab_work': lab_work}
    return render(request, 'set_defense.html', context)


@login_required
def attendance_dashboard(request):
    teacher = request.user.profile.teacher
    students = Student.objects.filter(subgroup=teacher.subgroups.first())

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
        return redirect('attendance_dashboard')

    rows = []
    for student in students:
        cells = []
        for lesson_date in lesson_dates:
            record = records.get((student.pk, lesson_date))
            cells.append({'lesson_date': lesson_date, 'status': record.status if record else ''})
        rows.append({'student': student, 'cells': cells})

    context = {'lesson_dates': lesson_dates, 'rows': rows, 'status_choices': Attendance.STATUS_CHOICES}
    return render(request, 'attendance_dashboard.html', context)


@login_required
def add_lesson_date(request):
    teacher = request.user.profile.teacher
    students = Student.objects.filter(subgroup=teacher.subgroups.first())

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
    students = Student.objects.filter(subgroup=teacher.subgroups.first())
    sick_leaves = SickLeave.objects.filter(student__in=students).order_by('-pk')

    context = {'sick_leaves': sick_leaves}
    return render(request, 'sick_leave_dashboard.html', context)


@login_required
def review_sick_leave(request, sick_leave_id):
    sick_leave = get_object_or_404(SickLeave, pk=sick_leave_id)

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
        review_total = None
        if review:
            review_total = sum((r.score or 0) for r in results_by_review.get(review.pk, []))
        defense = defenses.get(lab_work.pk)
        rows.append({
            'lab_work': lab_work,
            'report': report,
            'review': review,
            'review_total': review_total,
            'defense': defense,
        })

    sick_leaves = SickLeave.objects.filter(student=student).order_by('-pk')
    attendance_records = Attendance.objects.filter(student=student).order_by('lesson_date')

    context = {'rows': rows, 'sick_leaves': sick_leaves, 'attendance_records': attendance_records}
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

    context = {'lab_works': lab_works, 'rows': rows}
    return render(request, 'assistant_dashboard.html', context)


@login_required
def review_report(request, student_id, lab_id):
    assistant = request.user.profile.assistant
    student = get_object_or_404(Student, pk=student_id)
    lab_work = get_object_or_404(LaboratoryWork, pk=lab_id)
    report = get_object_or_404(LabReport, student=student, lab_work=lab_work)

    review, _ = ReportReview.objects.get_or_create(
        report=report, defaults={'assistant': assistant, 'comment': ''}
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

    context = {
        'student': student, 'lab_work': lab_work, 'review': review,
        'criteria_rows': criteria_rows, 'total': total,
    }
    return render(request, 'review_report.html', context)