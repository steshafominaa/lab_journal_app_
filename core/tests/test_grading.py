"""Тесты расчёта оценок (core/grading.py) — самой важной бизнес-логики проекта:
баллы за отчёт и защиту, штрафы за просрочку, влияние справок, итог по дисциплине."""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from core.grading import (
    compute_defense_details, compute_lab_grade, compute_report_details,
    compute_student_summary,
)
from core.models import (
    Criterion, CriterionResult, Defense, DisciplineResult, DisciplineSettings,
    LabReport, LaboratoryWork, ReportReview, SickLeave,
)
from core.tests.helpers import make_assistant, make_student, make_subgroup, make_teacher


class ReportScoreTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.subgroup = make_subgroup(self.teacher)
        self.student = make_student(self.subgroup)
        self.assistant = make_assistant(self.subgroup)
        self.lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 2, 1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        self.criterion = Criterion.objects.create(description='Оформление', max_score=Decimal('8'))

    def _review(self, report, score):
        review = ReportReview.objects.create(report=report, assistant=self.assistant, reviewed_at=date.today())
        CriterionResult.objects.create(review=review, criterion=self.criterion, score=Decimal(score))
        return review

    def test_no_report_returns_zero(self):
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details, {'raw_score': 0, 'penalty': 0, 'final_score': 0, 'penalty_weeks': 0})

    def test_report_submitted_but_not_reviewed_returns_zero(self):
        LabReport.objects.create(student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 1))
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details['final_score'], 0)

    def test_report_on_time_has_no_penalty(self):
        report = LabReport.objects.create(student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 1))
        self._review(report, 7)
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details, {'raw_score': 7, 'penalty': 0, 'final_score': 7, 'penalty_weeks': 0})

    def test_report_late_by_four_days_loses_one_week_penalty(self):
        # Дедлайн 1 января, сдал 5 января — 4 дня просрочки = 1 неделя штрафа
        report = LabReport.objects.create(student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 5))
        self._review(report, 7)
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details['penalty_weeks'], 1)
        self.assertEqual(details['final_score'], 6)

    def test_report_late_beyond_four_weeks_burns_whole_score(self):
        # 30 дней просрочки = 5 недель штрафа, это больше MAX_PENALTY_WEEKS (4)
        report = LabReport.objects.create(
            student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 31)
        )
        self._review(report, 7)
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details['final_score'], 0)
        self.assertEqual(details['penalty'], 7)

    def test_confirmed_sick_leave_fully_covering_delay_removes_penalty(self):
        SickLeave.objects.create(
            student=self.student, file='fake.pdf', status='подтверждена',
            start_date=date(2024, 1, 2), end_date=date(2024, 1, 5),
        )
        report = LabReport.objects.create(student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 5))
        self._review(report, 7)
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details['penalty'], 0)
        self.assertEqual(details['final_score'], 7)

    def test_unconfirmed_sick_leave_does_not_remove_penalty(self):
        SickLeave.objects.create(
            student=self.student, file='fake.pdf', status='на рассмотрении',
            start_date=date(2024, 1, 2), end_date=date(2024, 1, 5),
        )
        report = LabReport.objects.create(student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 5))
        self._review(report, 7)
        details = compute_report_details(self.student, self.lab_work)
        self.assertEqual(details['penalty_weeks'], 1)


class DefenseScoreTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.subgroup = make_subgroup(self.teacher)
        self.student = make_student(self.subgroup)
        self.lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 1, 10),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        self.report = LabReport.objects.create(
            student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 1)
        )

    def test_no_defense_yet_with_future_deadline_has_no_penalty(self):
        # Дедлайн защиты ещё не наступил (не считаем недели вперёд) -> штрафа нет и
        # не привязываемся к "сегодня" в тесте.
        future_lab = LaboratoryWork.objects.create(
            title='ЛР2', report_deadline=date.today() + timedelta(days=30),
            defense_deadline=date.today() + timedelta(days=60),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        details = compute_defense_details(self.student, future_lab)
        self.assertEqual(details, {'raw_score': 0, 'penalty': 0, 'final_score': 0, 'penalty_weeks': 0})

    def test_defense_on_time_has_full_score(self):
        Defense.objects.create(
            report=self.report, teacher=self.teacher,
            defense_date=date(2024, 1, 10), score=Decimal('8'),
        )
        details = compute_defense_details(self.student, self.lab_work)
        self.assertEqual(details['final_score'], 8)
        self.assertEqual(details['penalty_weeks'], 0)

    def test_defense_two_weeks_late_loses_two_points(self):
        Defense.objects.create(
            report=self.report, teacher=self.teacher,
            defense_date=date(2024, 1, 24), score=Decimal('8'),
        )
        details = compute_defense_details(self.student, self.lab_work)
        self.assertEqual(details['penalty_weeks'], 2)
        self.assertEqual(details['final_score'], 6)

    def test_defense_beyond_four_weeks_burns_whole_score(self):
        Defense.objects.create(
            report=self.report, teacher=self.teacher,
            defense_date=date(2024, 1, 10) + timedelta(weeks=5), score=Decimal('8'),
        )
        details = compute_defense_details(self.student, self.lab_work)
        self.assertEqual(details['final_score'], 0)
        self.assertEqual(details['penalty'], 8)

    def test_confirmed_sick_leave_on_a_missed_week_reduces_penalty(self):
        # Защита назначена на 2 недели после дедлайна; справка закрывает ровно дедлайн-день,
        # значит из двух "недельных" отметок штрафной будет только одна.
        SickLeave.objects.create(
            student=self.student, file='fake.pdf', status='подтверждена',
            start_date=date(2024, 1, 10), end_date=date(2024, 1, 10),
        )
        Defense.objects.create(
            report=self.report, teacher=self.teacher,
            defense_date=date(2024, 1, 24), score=Decimal('8'),
        )
        details = compute_defense_details(self.student, self.lab_work)
        self.assertEqual(details['penalty_weeks'], 1)
        self.assertEqual(details['final_score'], 7)


class LabGradeAndSummaryTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.subgroup = make_subgroup(self.teacher)
        self.student = make_student(self.subgroup)
        self.assistant = make_assistant(self.subgroup)
        self.criterion = Criterion.objects.create(description='Оформление', max_score=Decimal('8'))

    def _graded_lab(self, title, report_score, defense_score, report_weight='0.5', defense_weight='0.5'):
        lab_work = LaboratoryWork.objects.create(
            title=title, report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 1, 5),
            report_weight=Decimal(report_weight), defense_weight=Decimal(defense_weight),
        )
        report = LabReport.objects.create(student=self.student, lab_work=lab_work, submitted_at=date(2024, 1, 1))
        review = ReportReview.objects.create(report=report, assistant=self.assistant, reviewed_at=date.today())
        CriterionResult.objects.create(review=review, criterion=self.criterion, score=Decimal(report_score))
        Defense.objects.create(
            report=report, teacher=self.teacher, defense_date=date(2024, 1, 5), score=Decimal(defense_score),
        )
        return lab_work

    def test_compute_lab_grade_is_weighted_average_of_report_and_defense(self):
        lab_work = self._graded_lab('ЛР1', report_score=8, defense_score=4, report_weight='0.75', defense_weight='0.25')
        grade = compute_lab_grade(self.student, lab_work)
        self.assertEqual(grade['report_score'], 8)
        self.assertEqual(grade['defense_score'], 4)
        self.assertEqual(grade['lab_score'], 8 * 0.75 + 4 * 0.25)

    def test_summary_is_none_when_no_lab_works_exist(self):
        self.assertIsNone(compute_student_summary(self.student))

    def test_summary_auto_pass_eligible_when_all_labs_at_least_four(self):
        self._graded_lab('ЛР1', report_score=5, defense_score=5)
        self._graded_lab('ЛР2', report_score=4, defense_score=4)
        summary = compute_student_summary(self.student)
        self.assertTrue(summary['auto_pass_eligible'])

    def test_summary_auto_pass_not_eligible_when_one_lab_below_four(self):
        self._graded_lab('ЛР1', report_score=5, defense_score=5)
        self._graded_lab('ЛР2', report_score=3, defense_score=4)
        summary = compute_student_summary(self.student)
        self.assertFalse(summary['auto_pass_eligible'])

    def test_summary_exam_score_uses_average_when_auto_pass_agreed_and_eligible(self):
        self._graded_lab('ЛР1', report_score=5, defense_score=5)
        DisciplineResult.objects.create(student=self.student, auto_pass_agree=True)
        summary = compute_student_summary(self.student)
        self.assertEqual(summary['exam_score'], summary['average_lab_score'])

    def test_summary_exam_score_falls_back_to_manual_value_when_not_auto_pass(self):
        self._graded_lab('ЛР1', report_score=5, defense_score=5)
        DisciplineResult.objects.create(student=self.student, auto_pass_agree=False, exam_score=Decimal('9'))
        summary = compute_student_summary(self.student)
        self.assertEqual(summary['exam_score'], 9)

    def test_summary_exam_score_is_none_without_manual_value_or_auto_pass(self):
        self._graded_lab('ЛР1', report_score=5, defense_score=5)
        summary = compute_student_summary(self.student)
        self.assertIsNone(summary['exam_score'])

    def test_summary_bonus_points_are_added_to_average(self):
        self._graded_lab('ЛР1', report_score=4, defense_score=4)
        DisciplineResult.objects.create(student=self.student, bonus_points=Decimal('2'))
        summary = compute_student_summary(self.student)
        self.assertEqual(summary['average_lab_score'], (4 + 2) / 1)

    def test_summary_final_score_combines_average_and_exam_using_discipline_weights(self):
        self._graded_lab('ЛР1', report_score=8, defense_score=8)
        DisciplineResult.objects.create(student=self.student, exam_score=Decimal('6'))
        DisciplineSettings.objects.create(lab_weight=Decimal('0.6'), exam_weight=Decimal('0.4'))
        summary = compute_student_summary(self.student)
        self.assertAlmostEqual(summary['final_score'], 8 * 0.6 + 6 * 0.4)

    def test_summary_final_score_is_none_without_discipline_settings(self):
        self._graded_lab('ЛР1', report_score=8, defense_score=8)
        DisciplineResult.objects.create(student=self.student, exam_score=Decimal('6'))
        summary = compute_student_summary(self.student)
        self.assertIsNone(summary['final_score'])
