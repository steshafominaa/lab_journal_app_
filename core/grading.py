# Тут вся логика подсчёта оценок: сколько баллов за отчёт, сколько за защиту,
# как штрафуются опоздания и как из всего этого собирается итоговая оценка по дисциплине.
from datetime import date, timedelta

from .models import (
    LabReport, ReportReview, CriterionResult, Defense, SickLeave,
    DisciplineResult, DisciplineSettings, LaboratoryWork,
)

# После скольких недель просрочки оценка сгорает совсем (штраф = вся оценка)
MAX_PENALTY_WEEKS = 4


def is_confirmed_sick_on(student, check_date):
    # Проверяем, есть ли у студента подтверждённая справка, которая закрывает этот день.
    # Если да — этот день не считается опозданием.
    return SickLeave.objects.filter(
        student=student, status='подтверждена',
        start_date__lte=check_date, end_date__gte=check_date,
    ).exists()


def _confirmed_sick_days_between(student, start_date, end_date):
    """Считает дни строго после start_date и до end_date включительно, попавшие в подтверждённую справку."""
    if not start_date or not end_date or end_date <= start_date:
        return 0
    # Идём по дням от дедлайна до даты сдачи и считаем, сколько из них закрыто справкой
    count = 0
    day = start_date + timedelta(days=1)
    while day <= end_date:
        if is_confirmed_sick_on(student, day):
            count += 1
        day += timedelta(days=1)
    return count


def compute_report_details(student, lab_work):
    """Возвращает баллы за отчёт: сырую сумму по критериям, штраф и итог с учётом штрафа."""
    empty = {'raw_score': 0, 'penalty': 0, 'final_score': 0, 'penalty_weeks': 0}

    # Если отчёта нет, он не сдан или ещё не проверен ассистентом — баллов пока нет
    try:
        report = LabReport.objects.get(student=student, lab_work=lab_work)
    except LabReport.DoesNotExist:
        return empty

    if not report.submitted_at:
        return empty

    try:
        review = report.review
    except ReportReview.DoesNotExist:
        return empty

    # Сырой балл — это просто сумма баллов по всем критериям проверки
    raw_score = sum(float(r.score) for r in CriterionResult.objects.filter(review=review))

    deadline = lab_work.report_deadline
    submitted = report.submitted_at

    # Сдал в срок — штрафа нет, отдаём сырой балл как есть
    if submitted <= deadline:
        return {'raw_score': raw_score, 'penalty': 0, 'final_score': raw_score, 'penalty_weeks': 0}

    # Считаем, на сколько дней опоздал, и вычитаем из этого дни, закрытые справкой
    late_days = (submitted - deadline).days
    sick_days = _confirmed_sick_days_between(student, deadline, submitted)
    effective_late_days = max(0, late_days - sick_days)

    # Если справка закрыла всё опоздание — штрафа нет
    if effective_late_days <= 0:
        return {'raw_score': raw_score, 'penalty': 0, 'final_score': raw_score, 'penalty_weeks': 0}

    # Округляем опоздание вверх до полных недель (1-7 дней = 1 неделя штрафа и т.д.)
    weeks = (effective_late_days - 1) // 7 + 1

    # Опоздал больше чем на MAX_PENALTY_WEEKS недель — сгорает вся оценка
    if weeks > MAX_PENALTY_WEEKS:
        return {'raw_score': raw_score, 'penalty': raw_score, 'final_score': 0, 'penalty_weeks': weeks}

    # Иначе вычитаем по одному баллу за каждую неделю опоздания, но не уходим в минус
    final_score = max(0, raw_score - weeks)
    return {'raw_score': raw_score, 'penalty': raw_score - final_score, 'final_score': final_score, 'penalty_weeks': weeks}


def compute_defense_details(student, lab_work):
    """Возвращает баллы за защиту: выставленную оценку, штраф и итог с учётом штрафа."""
    defense = None
    try:
        report = LabReport.objects.get(student=student, lab_work=lab_work)
        defense = report.defense
    except (LabReport.DoesNotExist, Defense.DoesNotExist):
        defense = None

    deadline = lab_work.defense_deadline
    # Если защита уже прошла — считаем штраф до даты защиты, иначе до сегодняшнего дня
    cutoff = defense.defense_date if (defense and defense.defense_date) else date.today()

    # Для защиты штраф считается по неделям (по датам занятий), а не по дням, как для отчёта.
    # Идём неделя за неделей от дедлайна и считаем пропущенные (не закрытые справкой) недели.
    missed_weeks = 0
    check_date = deadline
    while check_date < cutoff:
        if not is_confirmed_sick_on(student, check_date):
            missed_weeks += 1
        check_date += timedelta(days=7)

    raw_score = float(defense.score) if (defense and defense.score is not None) else 0

    # Слишком много пропущенных недель — оценка сгорает
    if missed_weeks > MAX_PENALTY_WEEKS:
        return {'raw_score': raw_score, 'penalty': raw_score, 'final_score': 0, 'penalty_weeks': missed_weeks}

    # Оценки за защиту ещё нет — баллов пока нет, но штрафные недели уже могут копиться
    if not defense or defense.score is None:
        return {'raw_score': 0, 'penalty': 0, 'final_score': 0, 'penalty_weeks': missed_weeks}

    final_score = max(0, raw_score - missed_weeks)
    return {'raw_score': raw_score, 'penalty': raw_score - final_score, 'final_score': final_score, 'penalty_weeks': missed_weeks}


def compute_lab_grade(student, lab_work):
    # Оценка за лабу = оценка за отчёт и оценка за защиту, каждая со своим весом
    # (веса задаются при создании лабораторной работы, report_weight + defense_weight = 1)
    report_score = compute_report_details(student, lab_work)['final_score']
    defense_score = compute_defense_details(student, lab_work)['final_score']
    lab_score = report_score * float(lab_work.report_weight) + defense_score * float(lab_work.defense_weight)
    return {
        'lab_work': lab_work,
        'report_score': report_score,
        'defense_score': defense_score,
        'lab_score': lab_score,
    }


def compute_student_summary(student):
    # Собираем итог по всем лабораторным работам сразу: средний балл, доступность автомата,
    # оценку за экзамен и итоговую оценку по дисциплине.
    lab_works = list(LaboratoryWork.objects.all())
    if not lab_works:
        return None

    grades = [compute_lab_grade(student, lw) for lw in lab_works]

    # get_or_create — если у студента ещё нет строки с бонусами/экзаменом, создаём пустую
    result, _ = DisciplineResult.objects.get_or_create(student=student)
    bonus = float(result.bonus_points or 0)

    # Средний балл за лабы = (сумма оценок за все лабы + бонус) / количество лаб
    total_lab_score = sum(g['lab_score'] for g in grades)
    average_lab_score = (total_lab_score + bonus) / len(lab_works)

    # "Автомат" доступен только если по каждой лабе и отчёт, и защита не ниже 4 баллов
    auto_pass_eligible = all(
        g['report_score'] >= 4 and g['defense_score'] >= 4 for g in grades
    )

    # Если студент согласился на автомат и имеет на него право — оценка за экзамен
    # берётся равной среднему баллу за лабы. Иначе берём то, что вручную поставил преподаватель.
    if result.auto_pass_agree and auto_pass_eligible:
        exam_score = average_lab_score
    elif result.exam_score is not None:
        exam_score = float(result.exam_score)
    else:
        exam_score = None

    # Итоговая оценка по дисциплине = средняя за лабы и экзамен, смешанные по весам
    # из общих настроек дисциплины (DisciplineSettings)
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