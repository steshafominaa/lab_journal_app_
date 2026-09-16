from datetime import date, timedelta

from .models import (
    LabReport, ReportReview, CriterionResult, Defense, SickLeave,
    DisciplineResult, DisciplineSettings, LaboratoryWork,
)

MAX_PENALTY_WEEKS = 4


def _is_confirmed_sick_on(student, check_date):
    return SickLeave.objects.filter(
        student=student, status='подтверждена',
        start_date__lte=check_date, end_date__gte=check_date,
    ).exists()


def _confirmed_sick_days_between(student, start_date, end_date):
    """Считает дни строго после start_date и до end_date включительно, попавшие в подтверждённую справку."""
    if not start_date or not end_date or end_date <= start_date:
        return 0
    count = 0
    day = start_date + timedelta(days=1)
    while day <= end_date:
        if _is_confirmed_sick_on(student, day):
            count += 1
        day += timedelta(days=1)
    return count


def compute_report_score(student, lab_work):
    try:
        report = LabReport.objects.get(student=student, lab_work=lab_work)
    except LabReport.DoesNotExist:
        return 0

    if not report.submitted_at:
        return 0

    try:
        review = report.review
    except ReportReview.DoesNotExist:
        return 0

    raw_score = sum(float(r.score) for r in CriterionResult.objects.filter(review=review))

    deadline = lab_work.report_deadline
    submitted = report.submitted_at

    if submitted <= deadline:
        return raw_score

    late_days = (submitted - deadline).days
    sick_days = _confirmed_sick_days_between(student, deadline, submitted)
    effective_late_days = max(0, late_days - sick_days)

    if effective_late_days <= 0:
        return raw_score

    weeks = (effective_late_days - 1) // 7 + 1

    if weeks > MAX_PENALTY_WEEKS:
        return 0

    return max(0, raw_score - weeks)


def compute_defense_score(student, lab_work):
    defense = None
    try:
        report = LabReport.objects.get(student=student, lab_work=lab_work)
        defense = report.defense
    except (LabReport.DoesNotExist, Defense.DoesNotExist):
        defense = None

    deadline = lab_work.defense_deadline
    cutoff = defense.defense_date if (defense and defense.defense_date) else date.today()

    missed_weeks = 0
    check_date = deadline
    while check_date < cutoff:
        if not _is_confirmed_sick_on(student, check_date):
            missed_weeks += 1
        check_date += timedelta(days=7)

    if missed_weeks > MAX_PENALTY_WEEKS:
        return 0

    if not defense or defense.score is None:
        return 0

    return max(0, float(defense.score) - missed_weeks)


def compute_lab_grade(student, lab_work):
    report_score = compute_report_score(student, lab_work)
    defense_score = compute_defense_score(student, lab_work)
    lab_score = report_score * float(lab_work.report_weight) + defense_score * float(lab_work.defense_weight)
    return {
        'lab_work': lab_work,
        'report_score': report_score,
        'defense_score': defense_score,
        'lab_score': lab_score,
    }


def compute_student_summary(student):
    lab_works = list(LaboratoryWork.objects.all())
    if not lab_works:
        return None

    grades = [compute_lab_grade(student, lw) for lw in lab_works]

    result, _ = DisciplineResult.objects.get_or_create(student=student)
    bonus = float(result.bonus_points or 0)

    total_lab_score = sum(g['lab_score'] for g in grades)
    average_lab_score = (total_lab_score + bonus) / len(lab_works)

    auto_pass_eligible = all(
        g['report_score'] >= 4 and g['defense_score'] >= 4 for g in grades
    )

    if result.auto_pass_agree and auto_pass_eligible:
        exam_score = average_lab_score
    elif result.exam_score is not None:
        exam_score = float(result.exam_score)
    else:
        exam_score = None

    settings_row = DisciplineSettings.objects.first()
    final_score = None
    if settings_row and exam_score is not None:
        final_score = (
            average_lab_score * float(settings_row.lab_weight)
            + exam_score * float(settings_row.exam_weight)
        )

    return {
        'grades': grades,
        'bonus': bonus,
        'average_lab_score': average_lab_score,
        'auto_pass_eligible': auto_pass_eligible,
        'discipline_result': result,
        'exam_score': exam_score,
        'final_score': final_score,
        'settings': settings_row,
    }