from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


# Это "движок" проверки логина/пароля. Django по умолчанию ищет пользователя
# по username, а мы ищем по email (регистр не важен, поэтому __iexact).
class EmailBackend(ModelBackend):
    """Позволяет пользователям входить по email вместо username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        email = username or kwargs.get(user_model.USERNAME_FIELD)
        if email is None or password is None:
            return None

        try:
            user = user_model.objects.get(email__iexact=email)
        except (user_model.DoesNotExist, user_model.MultipleObjectsReturned):
            # либо такого email нет, либо (странно) их несколько — в обоих случаях не пускаем
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
