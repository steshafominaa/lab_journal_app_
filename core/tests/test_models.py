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