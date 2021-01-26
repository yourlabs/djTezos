from django.conf import settings
import os
import sys

if not settings.configured:
    DB = dict(
        ENGINE='django.db.backends.postgresql',
        USER=os.getenv('POSTGRES_USER', os.getenv('USER')),
        NAME=os.getenv('POSTGRES_DB', 'djblockchain_demo'),
        HOST=os.getenv('POSTGRES_HOST', None),
        PASSWORD=os.getenv('POSTGRES_PASSWORD', None),
    )
    settings.configure(
        ALLOWED_HOSTS='*',
        DATABASES=dict(default=DB),
        DEBUG=True,
        INSTALLED_APPS=(
            'django.contrib.contenttypes',
            'django.contrib.auth',
            'rest_framework',
            'djcall',
            'djblockchain',
        ),
        TEMPLATES = [
            {
                'BACKEND': 'django.template.backends.django.DjangoTemplates',
                'APP_DIRS': True,
                'OPTIONS': {
                    'context_processors': [
                        'django.template.context_processors.debug',
                        'django.template.context_processors.request',
                        'django.contrib.auth.context_processors.auth',
                        'django.contrib.messages.context_processors.messages',
                    ],
                },
            },
        ],
        LOGGING={
            'version': 1,
            'handlers': {
                'console': {
                    'class': 'logging.StreamHandler',
                    'level': 'DEBUG',
                }
            },
            'loggers': {
                name: {
                    'level': 'DEBUG',
                    'handlers': ['console'],
                } for name in (
                    'djblockchain',
                    'djcall',
                )
            },
        },
        MIDDLEWARE=[],
        REST_FRAMEWORK=dict(DEFAULT_AUTHENTICATION_CLASSES=[]),
        ROOT_URLCONF='djblockchain.demo',
        SECRET_KEY='nnot so secretnot so secretnot so secretnot so secretot so secret',
        STATIC_URL='/static/',
    )

    import django
    django.setup()
    from django.core.management import call_command
    call_command('flush', interactive=False)
    call_command('migrate')
    from djblockchain.models import Blockchain
    Blockchain.objects.create(
        name='fake', provider_class='djblockchain.fake.Provider'
    )
    Blockchain.objects.create(
        name='faildeploy', provider_class='djblockchain.fake.FailDeploy'
    )
    Blockchain.objects.create(
        name='failwatch', provider_class='djblockchain.fake.FailWatch'
    )

from django.contrib.auth.models import Group, User, Permission
from djblockchain.models import Account, Blockchain, Transaction

from rest_framework import routers, serializers, viewsets

router = routers.DefaultRouter()
# meta program a basic insecure API for testing purpose
for model in (Group, User, Permission, Account, Blockchain, Transaction):
    router.register(model.__name__.lower(), type(
        model.__name__ + 'ViewSet',
        (viewsets.ModelViewSet,),
        dict(
            queryset=model.objects.all(),
            serializer_class=type(
                model.__name__ + 'Serializer',
                (serializers.HyperlinkedModelSerializer,),
                dict(
                    Meta=type(
                        'Meta',
                        (object,),
                        dict(
                            model=model,
                            fields='__all__',
                        )
                    )
                )
            )
        )
    ))


from django.urls import include, path
urlpatterns = [path('', include(router.urls))]

from django.core import wsgi
application = wsgi.get_wsgi_application()
