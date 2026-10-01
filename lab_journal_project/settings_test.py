# Настройки для запуска тестов без реального MySQL-сервера (например, в CI
# или в песочнице без поднятой базы). Используются только командой
# `manage.py test --settings=lab_journal_project.settings_test`; "боевые"
# settings.py с MySQL при этом не меняются.
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
