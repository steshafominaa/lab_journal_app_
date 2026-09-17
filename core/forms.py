from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Форма входа по email вместо username."""

    username = forms.EmailField(label='Email', widget=forms.EmailInput(attrs={'autofocus': True}))

    error_messages = {
        'invalid_login': 'Введите корректный email и пароль. Обратите внимание, что оба поля могут быть чувствительны к регистру.',
        'inactive': 'Эта учётная запись отключена.',
    }
