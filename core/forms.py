from django import forms
from django.contrib.auth.forms import AuthenticationForm


class EmailAuthenticationForm(AuthenticationForm):
    """Форма входа по email вместо username."""

    username = forms.EmailField(
        label='Email',
        widget=forms.EmailInput(attrs={'autofocus': True, 'class': 'form-control'}),
    )

    error_messages = {
        'invalid_login': 'Введите корректный email и пароль',
        'inactive': 'Эта учётная запись отключена.',
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password'].widget.attrs.update({'class': 'form-control'})
