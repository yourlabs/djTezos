SECRET_KEY = 'notsecretnotsecretnotsecretnotsecretnotsecret'
INSTALLED_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'djblockchain',
    'djcall',
]
AUTH_USER_MODEL = 'auth.user'
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'db.sqlite3',
    }
}
DEBUG = True
