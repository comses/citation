import os
import configparser

from django.core.exceptions import ImproperlyConfigured

DEBUG = True

ROOT_URLCONF = 'tests.urls'

DIRNAME = os.path.dirname(os.path.dirname(__file__))
BASE_DIR = DIRNAME

DATA_DIR = 'data'

with open(os.path.join(BASE_DIR, "docker/config/django/config.ini")) as f:
    secrets = configparser.ConfigParser(allow_no_value=True)
    secrets.read_string(f.read())


# Adapted from Two Scoops of Django
def get_secret(setting, secrets=secrets):
    try:
        return secrets['DEFAULT'][setting]
    except KeyError:
        error_msg = "Set the {0} config variable".format(setting)
        raise ImproperlyConfigured(error_msg)


DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'USER': get_secret('DB_USER'),
        'PASSWORD': get_secret('DB_PASSWORD'),
        'NAME': get_secret('DB_NAME'),
        'HOST': get_secret('DB_HOST'),
        'PORT': get_secret('DB_PORT'),
    }
}

DJANGO_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
)

THIRD_PARTY_APPS = (
    'rest_framework',
    'django_extensions',
)

CITATION_APPS = ('citation',)

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + CITATION_APPS

# static files configuration, see https://docs.djangoproject.com/en/1.9/ref/settings/#static-files

STATIC_URL = '/static/'
STATIC_ROOT = '/catalog/static/'
STATICFILES_DIRS = (os.path.join(BASE_DIR, 'catalog', 'static').replace('\\', '/'),)

# Media file configuration (for user uploads etc) ####

# Absolute path to the directory that holds media.
# Example: "/home/media/media.lawrence.com/"
MEDIA_ROOT = '/var/www/catalog/uploads'

# URL that handles the media served from MEDIA_ROOT. Make sure to use a
# trailing slash if there is a path component (optional in other cases).
# Examples: "http://media.lawrence.com", "http://example.com/media/"
MEDIA_URL = 'https://catalog.comses.net/uploads/'

# DJANGO REST Framework's Pagination settings
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 15
}


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'root': {
        'level': 'DEBUG',
        'handlers': ['console'],
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'level': 'DEBUG',
            'formatter': 'verbose',
        }
    },
    'formatters': {
        'verbose': {
            'format': '%(asctime)s %(levelname)-7s %(name)s:%(funcName)s:%(lineno)d %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S'
        },
    }
}

SECRET_KEY = get_secret('SECRET_KEY')
