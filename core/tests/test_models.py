"""Тесты моделей: вычисление ФИО и ограничения целостности данных (уникальность,
защита от удаления связанных записей), которые важны для корректности бизнес-логики."""
from datetime import date
from decimal import Decimal

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.test import TestCase

from core.models import (
    Attendance, Criterion, CriterionResult, LabReport, LaboratoryWork, Profile,
    ReportReview,
)
from core.tests.helpers import make_assistant, make_student, make_subgroup, make_teacher


class ProfileFullNameTests(TestCase):
    def test_full_name_combines_last_first_and_patronymic(self):
        teacher = make_teacher(last_name='Иванов', first_name='Иван')
        teacher.profile.patronymic = 'Иванович'
        teacher.profile.save()
        self.assertEqual(teacher.profile.full_name(), 'Иванов Иван Иванович')

    def test_full_name_skips_missing_patronymic(self):
        teacher = make_teacher(last_name='Петров', first_name='Пётр')
        self.assertEqual(teacher.profile.full_name(), 'Петров Пётр')

    def test_full_name_falls_back_to_username_when_no_names_set(self):
        teacher = make_teacher(last_name='', first_name='', email='noname@example.com')
        self.assertEqual(teacher.profile.full_name(), 'noname@example.com')


class UniqueConstraintTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher()
        self.subgroup = make_subgroup(self.teacher)
        self.student = make_student(self.subgroup)
        self.assistant = make_assistant(self.subgroup)
        self.lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 2, 1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )

    def test_student_cannot_have_two_reports_for_same_lab_work(self):
        LabReport.objects.create(student=self.student, lab_work=self.lab_work)
        with self.assertRaises(IntegrityError):
            LabReport.objects.create(student=self.student, lab_work=self.lab_work)

    def test_student_cannot_have_two_attendance_records_for_same_date(self):
        Attendance.objects.create(student=self.student, lesson_date=date(2024, 1, 1), status='П')
        with self.assertRaises(IntegrityError):
            Attendance.objects.create(student=self.student, lesson_date=date(2024, 1, 1), status='Н')

    def test_review_cannot_have_two_results_for_same_criterion(self):
        report = LabReport.objects.create(student=self.student, lab_work=self.lab_work)
        review = ReportReview.objects.create(report=report, assistant=self.assistant, reviewed_at=date.today())
        criterion = Criterion.objects.create(description='Оформление', max_score=Decimal('8'))
        CriterionResult.objects.create(review=review, criterion=criterion, score=Decimal('5'))
        with self.assertRaises(IntegrityError):
            CriterionResult.objects.create(review=review, criterion=criterion, score=Decimal('6'))


class ProtectedDeleteTests(TestCase):
    def test_teacher_cannot_be_deleted_while_owning_a_subgroup(self):
        teacher = make_teacher()
        make_subgroup(teacher)
        with self.assertRaises(ProtectedError):
            teacher.delete()

    def test_criterion_cannot_be_deleted_while_used_in_a_review(self):
        teacher = make_teacher()
        subgroup = make_subgroup(teacher)
        student = make_student(subgroup)
        assistant = make_assistant(subgroup)
        lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 2, 1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        report = LabReport.objects.create(student=student, lab_work=lab_work)
        review = ReportReview.objects.create(report=report, assistant=assistant, reviewed_at=date.today())
        criterion = Criterion.objects.create(description='Оформление', max_score=Decimal('8'))
        CriterionResult.objects.create(review=review, criterion=criterion, score=Decimal('5'))
        with self.assertRaises(ProtectedError):
            criterion.delete()

    def test_assistant_cannot_be_deleted_while_having_a_review(self):
        teacher = make_teacher()
        subgroup = make_subgroup(teacher)
        student = make_student(subgroup)
        assistant = make_assistant(subgroup)
        lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 2, 1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        report = LabReport.objects.create(student=student, lab_work=lab_work)
        ReportReview.objects.create(report=report, assistant=assistant, reviewed_at=date.today())
        with self.assertRaises(ProtectedError):
            assistant.delete()
