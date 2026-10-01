"""Тесты входа по email: backend (core/auth_backends.py) и сама страница логина."""
from django.contrib.auth import authenticate
from django.test import TestCase
from django.urls import reverse

from core.tests.helpers import make_teacher


class EmailBackendTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher(email='Teacher@Example.com', password='secret123')

    def test_authenticates_with_exact_email(self):
        user = authenticate(username='Teacher@Example.com', password='secret123')
        self.assertIsNotNone(user)
        self.assertEqual(user.pk, self.teacher.profile.user_id)

    def test_authenticates_case_insensitively(self):
        user = authenticate(username='teacher@example.com', password='secret123')
        self.assertIsNotNone(user)

    def test_rejects_wrong_password(self):
        user = authenticate(username='teacher@example.com', password='wrong-password')
        self.assertIsNone(user)

    def test_rejects_unknown_email(self):
        user = authenticate(username='nobody@example.com', password='secret123')
        self.assertIsNone(user)

    def test_rejects_inactive_user(self):
        make_teacher(email='inactive@example.com', password='secret123', is_active=False)
        user = authenticate(username='inactive@example.com', password='secret123')
        self.assertIsNone(user)


class LoginViewTests(TestCase):
    def setUp(self):
        self.teacher = make_teacher(email='login@example.com', password='secret123')

    def test_valid_email_and_password_logs_in_and_redirects(self):
        response = self.client.post(reverse('login'), {'username': 'login@example.com', 'password': 'secret123'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_invalid_credentials_show_error_and_do_not_log_in(self):
        response = self.client.post(reverse('login'), {'username': 'login@example.com', 'password': 'wrong'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
