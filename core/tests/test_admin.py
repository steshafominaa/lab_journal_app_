"""Тесты страниц администратора."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from core.models import (
    Assistant, Criterion, CriterionResult, DisciplineSettings, LaboratoryWork, Profile,
    ReportReview, Student, Subgroup, Teacher,
)
from core.tests.helpers import (
    make_admin, make_assistant, make_lab_work, make_report, make_student, make_subgroup, make_teacher,
)

User = get_user_model()


class AdminTestCase(TestCase):
    def setUp(self):
        self.admin = make_admin(email='admin@example.com')
        self.client.force_login(self.admin.profile.user)


class SubgroupManagementTests(AdminTestCase):


    def test_empty_subgroup_can_be_deleted(self):
        subgroup = make_subgroup(self.admin)
        response = self.client.post(reverse('manage_subgroups'), {'action': 'delete', 'subgroup_id': subgroup.pk})
        self.assertRedirects(response, reverse('manage_subgroups'))
        self.assertFalse(Subgroup.objects.filter(pk=subgroup.pk).exists())

    def test_edit_subgroup(self):
        subgroup = make_subgroup(self.admin, name='Старое')
        other = make_teacher()
        self.assertEqual(self.client.get(reverse('edit_subgroup', args=[subgroup.pk])).status_code, 200)
        response = self.client.post(reverse('edit_subgroup', args=[subgroup.pk]), {
            'subgroup_name': 'Новое', 'teacher_id': other.pk,
        })
        self.assertRedirects(response, reverse('manage_subgroups'))
        subgroup.refresh_from_db()
        self.assertEqual((subgroup.subgroup_name, subgroup.teacher_id), ('Новое', other.pk))


class UserManagementTests(AdminTestCase):
    def setUp(self):
        super().setUp()
        self.subgroup = make_subgroup(self.admin)

    def _create(self, **overrides):
        data = {
            'email': 'new@example.com', 'password': 'pass12345', 'last_name': 'Новый',
            'first_name': 'Пользователь', 'role': 'student', 'subgroup_id': self.subgroup.pk,
        }
        data.update(overrides)
        return self.client.post(reverse('create_user'), data)


    def test_create_user_requires_required_fields(self):
        response = self._create(last_name='')
        self.assertContains(response, 'Заполните email, пароль')
        self.assertFalse(User.objects.filter(email='new@example.com').exists())


    def test_edit_student_changes_name_subgroup_and_password(self):
        student = make_student(self.subgroup)
        other_subgroup = make_subgroup(self.admin)
        url = reverse('edit_user', args=[student.profile.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            'last_name': 'Сидоров', 'first_name': 'Сидор', 'patronymic': 'Сидорович',
            'password': 'newpass12345', 'subgroup_id': other_subgroup.pk,
        })
        self.assertRedirects(response, reverse('manage_users'))
        student = Student.objects.get(pk=student.pk)
        self.assertEqual(student.subgroup, other_subgroup)
        self.assertEqual(student.profile.full_name(), 'Сидоров Сидор Сидорович')
        self.assertTrue(student.profile.user.check_password('newpass12345'))


    def test_teacher_leading_subgroup_cannot_be_deleted(self):
        teacher = make_teacher()
        make_subgroup(teacher)
        response = self.client.post(reverse('manage_users'), {'action': 'delete', 'profile_id': teacher.profile.pk})
        self.assertContains(response, 'Нельзя удалить пользователя')
        self.assertTrue(User.objects.filter(pk=teacher.profile.user_id).exists())


class LabWorkManagementTests(AdminTestCase):
    VALID = {
        'action': 'create', 'title': 'ЛР1', 'report_deadline': '2024-01-01',
        'defense_deadline': '2024-02-01', 'report_weight': '0.4', 'defense_weight': '0.6',
    }


    def test_list_page_computes_averages_for_students(self):
        subgroup = make_subgroup(self.admin)
        student = make_student(subgroup)
        lab_work = make_lab_work()
        make_report(student, lab_work)
        response = self.client.get(reverse('manage_lab_works'))
        row = response.context['lab_rows'][0]
        self.assertEqual((row['avg_report'], row['avg_defense'], row['avg_lab']), (0, 0, 0))


    def test_create_lab_work_validation(self):
        cases = [
            ({'title': ''}, 'Заполните название'),
            ({'report_weight': 'abc'}, 'корректные числа'),
            ({'report_weight': '0', 'defense_weight': '1'}, 'больше нуля'),
            ({'report_weight': '0.7', 'defense_weight': '0.4'}, 'должна быть равна 1'),
        ]
        for changes, message in cases:
            with self.subTest(message=message):
                response = self.client.post(reverse('manage_lab_works'), {**self.VALID, **changes})
                self.assertContains(response, message)
        self.assertEqual(LaboratoryWork.objects.count(), 0)


    def test_edit_lab_work(self):
        lab_work = make_lab_work()
        url = reverse('edit_lab_work', args=[lab_work.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {**self.VALID, 'title': 'Новое название'})
        self.assertRedirects(response, reverse('manage_lab_works'))
        lab_work.refresh_from_db()
        self.assertEqual((lab_work.title, lab_work.defense_weight), ('Новое название', Decimal('0.6')))


class DuplicateNameTests(TransactionTestCase):
    def setUp(self):
        self.admin = make_admin()
        self.client.force_login(self.admin.profile.user)

    def test_duplicate_subgroup_name_is_rejected(self):
        make_subgroup(self.admin, name='РИС-1')
        response = self.client.post(reverse('manage_subgroups'), {
            'action': 'create', 'subgroup_name': 'РИС-1', 'teacher_id': self.admin.pk,
        })
        self.assertContains(response, 'уже существует')
        self.assertEqual(Subgroup.objects.count(), 1)


    def test_duplicate_lab_work_title_is_rejected(self):
        make_lab_work(title='ЛР1')
        response = self.client.post(reverse('manage_lab_works'), {
            'action': 'create', 'title': 'ЛР1', 'report_deadline': '2024-01-01',
            'defense_deadline': '2024-02-01', 'report_weight': '0.5', 'defense_weight': '0.5',
        })
        self.assertContains(response, 'уже существует')
        self.assertEqual(LaboratoryWork.objects.count(), 1)


class DisciplineSettingsTests(AdminTestCase):

    def test_valid_weights_are_saved(self):
        response = self.client.post(reverse('discipline_settings'), {'lab_weight': '0.7', 'exam_weight': '0.3'})
        self.assertRedirects(response, reverse('teacher_dashboard'))
        self.assertEqual(DisciplineSettings.objects.get().lab_weight, Decimal('0.7'))


class CriteriaManagementTests(AdminTestCase):
    def test_create_criterion(self):
        response = self.client.post(reverse('criteria_management'), {'description': 'Оформление', 'max_score': '3'})
        self.assertRedirects(response, reverse('criteria_management'))
        self.assertEqual(Criterion.objects.get().max_score, Decimal('3'))

    def test_criterion_validation(self):
        Criterion.objects.create(description='Теория', max_score=Decimal('6'))
        cases = [
            ({'description': '', 'max_score': '1'}, 'Укажите название'),
            ({'description': 'Код', 'max_score': '0'}, 'больше нуля'),
            ({'description': 'Код', 'max_score': '3'}, 'не может превышать 8'),
            ({'description': 'Код', 'max_score': 'abc'}, 'Введите корректное число'),
        ]
        for data, message in cases:
            with self.subTest(message=message):
                self.assertContains(self.client.post(reverse('criteria_management'), data), message)
        self.assertEqual(Criterion.objects.count(), 1)


    def test_used_criterion_cannot_be_deleted(self):
        subgroup = make_subgroup(self.admin)
        student = make_student(subgroup)
        assistant = make_assistant(subgroup)
        report = make_report(student, make_lab_work())
        review = ReportReview.objects.create(report=report, assistant=assistant, reviewed_at=date.today())
        criterion = Criterion.objects.create(description='Теория', max_score=Decimal('6'))
        CriterionResult.objects.create(review=review, criterion=criterion, score=Decimal('5'))
        response = self.client.post(reverse('criteria_management'), {'delete_id': criterion.pk})
        self.assertContains(response, 'Нельзя удалить критерий')
        self.assertEqual(Criterion.objects.count(), 1)