"""Тесты view-функций: разграничение прав доступа (студент/ассистент/преподаватель/
администратор, "свои" и "чужие" подгруппы) и ключевые пользовательские сценарии."""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import Attendance, Defense, LabReport, LaboratoryWork, Student
from core.tests.helpers import make_student, make_subgroup, make_teacher

User = get_user_model()
PASSWORD = 'secret123'


class LoginRequiredAndRoleRedirectTests(TestCase):
    def test_anonymous_user_is_redirected_to_login(self):
        protected_urls = [
            reverse('teacher_dashboard'), reverse('student_dashboard'),
            reverse('assistant_dashboard'), reverse('manage_users'),
        ]
        for url in protected_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse('login'), response.url)

    def test_home_redirects_each_role_to_its_own_dashboard(self):
        teacher = make_teacher(email='t@example.com', password=PASSWORD)
        subgroup = make_subgroup(teacher)
        student = make_student(subgroup, email='s@example.com', password=PASSWORD)

        cases = [
            (teacher.profile.user, reverse('teacher_dashboard')),
            (student.profile.user, reverse('student_dashboard')),
        ]
        for user, expected_url in cases:
            with self.subTest(user=user.email):
                self.client.force_login(user)
                response = self.client.get(reverse('home'))
                self.assertRedirects(response, expected_url)
                self.client.logout()


class AdminOnlyViewsTests(TestCase):
    def setUp(self):
        self.admin_teacher = make_teacher(email='admin@example.com', password=PASSWORD, is_admin=True)
        self.plain_teacher = make_teacher(email='plain@example.com', password=PASSWORD, is_admin=False)
        self.admin_only_urls = [
            reverse('manage_users'), reverse('manage_lab_works'),
            reverse('manage_subgroups'), reverse('discipline_settings'),
            reverse('criteria_management'), reverse('create_user'),
        ]

    def test_non_admin_teacher_is_redirected_away_from_admin_pages(self):
        self.client.force_login(self.plain_teacher.profile.user)
        for url in self.admin_only_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, reverse('teacher_dashboard'))

    def test_admin_teacher_can_access_admin_pages(self):
        self.client.force_login(self.admin_teacher.profile.user)
        for url in self.admin_only_urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)


class SubgroupOwnershipPermissionTests(TestCase):
    """Преподаватель может редактировать данные только своих подгрупп, даже если видит все."""

    def setUp(self):
        self.owner_teacher = make_teacher(email='owner@example.com', password=PASSWORD)
        self.other_teacher = make_teacher(email='other@example.com', password=PASSWORD)
        self.subgroup = make_subgroup(self.owner_teacher)
        self.student = make_student(self.subgroup)
        self.lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date(2024, 1, 1), defense_deadline=date(2024, 2, 1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )

    def test_owner_teacher_can_open_set_report_date(self):
        self.client.force_login(self.owner_teacher.profile.user)
        url = f"{reverse('set_report_date', args=[self.lab_work.pk])}?student_id={self.student.pk}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_other_teacher_is_denied_set_report_date(self):
        self.client.force_login(self.other_teacher.profile.user)
        url = f"{reverse('set_report_date', args=[self.lab_work.pk])}?student_id={self.student.pk}"
        response = self.client.get(url)
        self.assertRedirects(response, reverse('teacher_dashboard'))
        self.assertFalse(LabReport.objects.filter(student=self.student, lab_work=self.lab_work).exists())

    def test_other_teacher_is_denied_set_defense(self):
        report = LabReport.objects.create(student=self.student, lab_work=self.lab_work, submitted_at=date(2024, 1, 1))
        self.client.force_login(self.other_teacher.profile.user)
        url = reverse('set_defense', args=[self.student.pk, self.lab_work.pk])
        response = self.client.post(url, {'defense_date': '2024-02-01'})
        self.assertRedirects(response, reverse('teacher_dashboard'))
        self.assertFalse(Defense.objects.filter(report=report).exists())


class LessonDateManagementTests(TestCase):
    def setUp(self):
        self.owner_teacher = make_teacher(email='owner@example.com', password=PASSWORD)
        self.other_teacher = make_teacher(email='other@example.com', password=PASSWORD, is_admin=False)
        self.admin_teacher = make_teacher(email='admin@example.com', password=PASSWORD, is_admin=True)
        self.own_subgroup = make_subgroup(self.owner_teacher)
        self.other_subgroup = make_subgroup(self.other_teacher)
        self.own_student = make_student(self.own_subgroup)
        self.other_student = make_student(self.other_subgroup)
        self.lesson_date = date(2024, 3, 1)
        Attendance.objects.create(student=self.own_student, lesson_date=self.lesson_date)
        Attendance.objects.create(student=self.other_student, lesson_date=self.lesson_date)

    def test_add_lesson_date_only_creates_attendance_for_own_subgroup(self):
        new_date = date(2024, 3, 8)
        self.client.force_login(self.owner_teacher.profile.user)
        self.client.post(reverse('add_lesson_date'), {
            'lesson_date': new_date.isoformat(), 'subgroup_id': self.own_subgroup.pk,
        })
        self.assertTrue(Attendance.objects.filter(student=self.own_student, lesson_date=new_date).exists())
        self.assertFalse(Attendance.objects.filter(student=self.other_student, lesson_date=new_date).exists())

    def test_delete_lesson_date_ignores_get_requests(self):
        self.client.force_login(self.owner_teacher.profile.user)
        self.client.get(reverse('delete_lesson_date', args=[self.lesson_date.isoformat()]))
        self.assertEqual(Attendance.objects.filter(lesson_date=self.lesson_date).count(), 2)

    def test_delete_lesson_date_only_removes_own_subgroup_records(self):
        self.client.force_login(self.owner_teacher.profile.user)
        self.client.post(reverse('delete_lesson_date', args=[self.lesson_date.isoformat()]))
        self.assertFalse(Attendance.objects.filter(student=self.own_student, lesson_date=self.lesson_date).exists())
        self.assertTrue(Attendance.objects.filter(student=self.other_student, lesson_date=self.lesson_date).exists())

    def test_admin_deleting_lesson_date_removes_records_in_any_subgroup(self):
        self.client.force_login(self.admin_teacher.profile.user)
        self.client.post(reverse('delete_lesson_date', args=[self.lesson_date.isoformat()]))
        self.assertEqual(Attendance.objects.filter(lesson_date=self.lesson_date).count(), 0)


class CreateUserTests(TestCase):
    def setUp(self):
        self.admin_teacher = make_teacher(email='admin@example.com', password=PASSWORD, is_admin=True)
        self.plain_teacher = make_teacher(email='plain@example.com', password=PASSWORD, is_admin=False)
        self.subgroup = make_subgroup(self.admin_teacher)

    def test_admin_can_create_student_user(self):
        self.client.force_login(self.admin_teacher.profile.user)
        response = self.client.post(reverse('create_user'), {
            'email': 'new.student@example.com', 'password': 'pass12345',
            'last_name': 'Новый', 'first_name': 'Студент', 'role': 'student',
            'subgroup_id': self.subgroup.pk,
        })
        self.assertRedirects(response, reverse('manage_users'))
        self.assertTrue(User.objects.filter(email='new.student@example.com').exists())
        self.assertTrue(Student.objects.filter(profile__user__email='new.student@example.com').exists())

    def test_duplicate_email_is_rejected_with_error(self):
        self.client.force_login(self.admin_teacher.profile.user)
        response = self.client.post(reverse('create_user'), {
            'email': 'admin@example.com', 'password': 'pass12345',
            'last_name': 'Дубликат', 'first_name': 'Пользователь', 'role': 'student',
            'subgroup_id': self.subgroup.pk,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'уже существует')

    def test_non_admin_teacher_cannot_create_users(self):
        self.client.force_login(self.plain_teacher.profile.user)
        response = self.client.post(reverse('create_user'), {
            'email': 'blocked@example.com', 'password': 'pass12345',
            'last_name': 'Запрет', 'first_name': 'Тест', 'role': 'student',
            'subgroup_id': self.subgroup.pk,
        })
        self.assertRedirects(response, reverse('teacher_dashboard'))
        self.assertFalse(User.objects.filter(email='blocked@example.com').exists())


class DebtorsReportTests(TestCase):
    """Регрессионные тесты: долг по защите не должен появляться раньше срока
    защиты, даже если сам отчёт не сдан — пока есть время, долгом считается
    только отчёт."""

    def setUp(self):
        self.teacher = make_teacher(email='t@example.com', password=PASSWORD, is_admin=True)
        self.subgroup = make_subgroup(self.teacher)
        self.student = make_student(self.subgroup)
        self.client.force_login(self.teacher.profile.user)

    def test_missed_report_with_future_defense_deadline_reports_only_report_debt(self):
        LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date.today() - timedelta(days=1),
            defense_deadline=date.today() + timedelta(days=30),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        response = self.client.get(reverse('debtors_report'))
        rows = response.context['rows']
        self.assertEqual(len(rows), 1)
        debt_types = {debt['type'] for debt in rows[0]['debts']}
        self.assertEqual(debt_types, {'Отчёт'})

    def test_report_submitted_on_time_with_future_defense_deadline_has_no_debt(self):
        lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date.today() - timedelta(days=10),
            defense_deadline=date.today() + timedelta(days=30),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        LabReport.objects.create(student=self.student, lab_work=lab_work, submitted_at=date.today() - timedelta(days=12))
        response = self.client.get(reverse('debtors_report'))
        self.assertEqual(len(response.context['rows']), 0)

    def test_report_submitted_but_defense_deadline_passed_without_score_reports_only_defense_debt(self):
        lab_work = LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date.today() - timedelta(days=10),
            defense_deadline=date.today() - timedelta(days=1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        LabReport.objects.create(student=self.student, lab_work=lab_work, submitted_at=date.today() - timedelta(days=12))
        response = self.client.get(reverse('debtors_report'))
        rows = response.context['rows']
        self.assertEqual(len(rows), 1)
        debt_types = {debt['type'] for debt in rows[0]['debts']}
        self.assertEqual(debt_types, {'Защита'})

    def test_missed_report_with_defense_deadline_also_passed_reports_both_debts(self):
        LaboratoryWork.objects.create(
            title='ЛР1', report_deadline=date.today() - timedelta(days=10),
            defense_deadline=date.today() - timedelta(days=1),
            report_weight=Decimal('0.5'), defense_weight=Decimal('0.5'),
        )
        response = self.client.get(reverse('debtors_report'))
        rows = response.context['rows']
        self.assertEqual(len(rows), 1)
        debt_types = {debt['type'] for debt in rows[0]['debts']}
        self.assertEqual(debt_types, {'Отчёт', 'Защита'})
