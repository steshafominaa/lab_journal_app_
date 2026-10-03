"""Тесты страниц преподавателя."""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.models import (
    Attendance, Criterion, CriterionResult, Defense, DisciplineResult, LabReport,
    ReportReview, SickLeave,
)
from core.tests.helpers import (
    make_assistant, make_lab_work, make_report, make_student, make_subgroup, make_teacher,
)

LESSON = date(2024, 3, 1)


class TwoTeachersTestCase(TestCase):
    def setUp(self):
        self.owner = make_teacher(email='owner@example.com')
        self.other = make_teacher(email='other@example.com')
        self.own_subgroup = make_subgroup(self.owner)
        self.other_subgroup = make_subgroup(self.other)
        self.own_student = make_student(self.own_subgroup)
        self.other_student = make_student(self.other_subgroup)
        self.lab_work = make_lab_work()
        self.client.force_login(self.owner.profile.user)


class ReportAndDefenseDateTests(TwoTeachersTestCase):
    def test_set_report_date_saves_date(self):
        url = reverse('set_report_date', args=[self.lab_work.pk])
        response = self.client.post(url, {'student_id': self.own_student.pk, 'submitted_at': '2024-01-03'})
        self.assertRedirects(response, reverse('teacher_dashboard'))
        report = LabReport.objects.get(student=self.own_student, lab_work=self.lab_work)
        self.assertEqual(report.submitted_at, date(2024, 1, 3))


    def test_set_defense_date(self):
        make_report(self.own_student, self.lab_work)
        url = reverse('set_defense', args=[self.own_student.pk, self.lab_work.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'defense_date': '2024-01-20'})
        self.assertRedirects(response, reverse('teacher_dashboard'))
        self.assertEqual(Defense.objects.get().defense_date, date(2024, 1, 20))


class DefenseScoreTests(TwoTeachersTestCase):
    def setUp(self):
        super().setUp()
        self.report = make_report(self.own_student, self.lab_work)
        self.defense = Defense.objects.create(
            report=self.report, teacher=self.owner, defense_date=date(2024, 2, 1))
        self.url = reverse('review_defense', args=[self.own_student.pk, self.lab_work.pk])

    def test_page_shows_penalty_and_final_score(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['defense_penalty'], 0)


    def test_empty_score_resets_score(self):
        self.defense.score = Decimal('9')
        self.defense.save()
        self.client.post(self.url, {'score': '', 'comment': ''})
        self.defense.refresh_from_db()
        self.assertIsNone(self.defense.score)


class TeacherReviewReportTests(TwoTeachersTestCase):
    def setUp(self):
        super().setUp()
        self.report = make_report(self.own_student, self.lab_work)
        self.criterion = Criterion.objects.create(description='Оформление', max_score=Decimal('8'))
        self.url = reverse('teacher_review_report', args=[self.own_student.pk, self.lab_work.pk])


    def test_teacher_creates_review_using_assistant_of_subgroup(self):
        assistant = make_assistant(self.own_subgroup)
        response = self.client.post(self.url, {f'criterion_{self.criterion.pk}': '6', 'comment': 'Принято'})
        self.assertRedirects(response, reverse('teacher_dashboard'))
        review = ReportReview.objects.get(report=self.report)
        self.assertEqual((review.assistant, review.comment), (assistant, 'Принято'))
        self.assertEqual(CriterionResult.objects.get(review=review).score, Decimal('6'))

    def test_teacher_updates_existing_review(self):
        assistant = make_assistant(self.own_subgroup)
        review = ReportReview.objects.create(report=self.report, assistant=assistant, reviewed_at=date.today())
        CriterionResult.objects.create(review=review, criterion=self.criterion, score=Decimal('3'))
        response = self.client.get(self.url)
        self.assertEqual(response.context['total'], Decimal('3'))
        self.client.post(self.url, {f'criterion_{self.criterion.pk}': '7', 'comment': 'Исправлено'})
        self.assertEqual(CriterionResult.objects.get(review=review).score, Decimal('7'))


class AttendanceTests(TwoTeachersTestCase):
    def setUp(self):
        super().setUp()
        self.own_record = Attendance.objects.create(student=self.own_student, lesson_date=LESSON)
        self.other_record = Attendance.objects.create(student=self.other_student, lesson_date=LESSON)

    def _key(self, student):
        return f'status_{student.pk}_{LESSON.isoformat()}'


    def test_saving_statuses_changes_only_own_students(self):
        response = self.client.post(reverse('attendance_dashboard'), {
            self._key(self.own_student): 'П', self._key(self.other_student): 'П',
        })
        self.assertRedirects(response, reverse('attendance_dashboard'))
        self.own_record.refresh_from_db()
        self.other_record.refresh_from_db()
        self.assertEqual((self.own_record.status, self.other_record.status), ('П', None))


    def test_confirmed_sick_leave_protects_status_from_being_set_to_absent(self):
        self.own_record.status = 'Б'
        self.own_record.save()
        SickLeave.objects.create(
            student=self.own_student, file='fake.pdf', status='подтверждена',
            start_date=LESSON, end_date=LESSON,
        )
        self.client.post(reverse('attendance_dashboard'), {self._key(self.own_student): 'Н'})
        self.own_record.refresh_from_db()
        self.assertEqual(self.own_record.status, 'Б')


    def test_add_lesson_date_requires_own_subgroup_and_date(self):
        url = reverse('add_lesson_date')
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {'lesson_date': '2024-03-08', 'subgroup_id': self.other_subgroup.pk})
        self.assertContains(response, 'Выберите свою подгруппу')
        self.assertFalse(Attendance.objects.filter(lesson_date=date(2024, 3, 8)).exists())

    def test_delete_lesson_date_keeps_subgroup_filter(self):
        response = self.client.post(
            reverse('delete_lesson_date', args=[LESSON.isoformat()]), {'subgroup': self.own_subgroup.pk})
        self.assertRedirects(
            response, f"{reverse('attendance_dashboard')}?subgroup={self.own_subgroup.pk}")


class SickLeaveReviewTests(TwoTeachersTestCase):
    def setUp(self):
        super().setUp()
        self.sick_leave = SickLeave.objects.create(student=self.own_student, file='own.pdf')
        self.other_sick_leave = SickLeave.objects.create(student=self.other_student, file='other.pdf')
        self.url = reverse('review_sick_leave', args=[self.sick_leave.pk])
        for day in (date(2024, 3, 1), date(2024, 3, 5), date(2024, 3, 20)):
            Attendance.objects.create(student=self.own_student, lesson_date=day, status='Н')


    def test_confirming_converts_absences_inside_period_to_sick(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.post(self.url, {
            'start_date': '2024-03-01', 'end_date': '2024-03-10', 'status': 'подтверждена',
        })
        self.assertRedirects(response, reverse('sick_leave_dashboard'))
        statuses = {a.lesson_date: a.status for a in Attendance.objects.filter(student=self.own_student)}
        self.assertEqual(statuses, {date(2024, 3, 1): 'Б', date(2024, 3, 5): 'Б', date(2024, 3, 20): 'Н'})


class ResultsDashboardTests(TwoTeachersTestCase):


    def test_saving_bonus_and_exam_for_own_students_only(self):
        response = self.client.post(reverse('results_dashboard'), {
            f'bonus_{self.own_student.pk}': '1.5', f'exam_{self.own_student.pk}': '8',
            f'bonus_{self.other_student.pk}': '2', f'exam_{self.other_student.pk}': '9',
        })
        self.assertRedirects(response, reverse('results_dashboard'), fetch_redirect_response=False)
        own = DisciplineResult.objects.get(student=self.own_student)
        self.assertEqual((own.bonus_points, own.exam_score), (Decimal('1.5'), Decimal('8')))
        self.assertFalse(DisciplineResult.objects.filter(student=self.other_student).exists())

    def test_saving_with_subgroup_filter_keeps_the_filter(self):
        response = self.client.post(reverse('results_dashboard'), {'subgroup': self.own_subgroup.pk})
        self.assertRedirects(response, f"{reverse('results_dashboard')}?subgroup={self.own_subgroup.pk}")