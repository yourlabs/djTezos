import datetime
import importlib
import json
import logging
import random
import requests.exceptions
import string
import sys
import time
import traceback
import uuid

try:
    import uwsgi
except ImportError:
    uwsgi = None

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db import close_old_connections
from django.db.models import Q, signals
from django.utils.translation import gettext_lazy as _

from cryptography.hazmat.primitives.ciphers import (
    Cipher, algorithms, modes)
from cryptography.hazmat.backends import default_backend

from djcall.models import Caller

from model_utils.managers import (
    InheritanceManagerMixin,
    InheritanceQuerySetMixin,
)

from .exceptions import PermanentError, TemporaryError

logger = logging.getLogger('djtezos')


SETTINGS = dict(
    PROVIDERS=(
        ('djtezos.tezos.Provider', 'Tezos'),
        ('djtezos.fake.Provider', 'Test'),
        ('djtezos.fake.FailDeploy', 'Test that fails deploy'),
        ('djtezos.fake.FailWatch', 'Test that fails watch'),
    )
)
SETTINGS.update(getattr(settings, 'DJBLOCKCHAIN', {}))


KEY = settings.SECRET_KEY.encode('utf8')[:32]
IV = settings.SECRET_KEY.encode('utf8')[-16:]


def cipher():
    return Cipher(
        algorithms.AES(KEY),
        modes.CBC(IV),
        backend=default_backend()
    )


def encrypt(secret):
    encryptor = cipher().encryptor()
    return encryptor.update(secret) + encryptor.finalize()


def decrypt(secret):
    decryptor = cipher().decryptor()
    return decryptor.update(secret) + decryptor.finalize()


class Account(models.Model):
    created_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=True,
    )
    address = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )
    blockchain = models.ForeignKey(
        'Blockchain',
        on_delete=models.CASCADE,
    )
    crypted_key = models.BinaryField()
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    balance = models.DecimalField(
        max_digits=18,
        decimal_places=9,
        blank=True,
        editable=False,
        default=0,
    )
    name = models.CharField(max_length=100)

    def __str__(self):
        balance = int(self.balance) if self.balance else 0
        return f'{self.name} {balance}tz'

    @property
    def provider(self):
        return self.blockchain.provider

    @property
    def private_key(self):
        return decrypt(self.crypted_key) if self.crypted_key else None

    def get_balance(self):
        return self.provider.get_balance(self.address, self.private_key)

    @property
    def codename(self):
        return self.blockchain.endpoint.rstrip('/').split('/')[-1]

    def get_tzkt_api_url(self):
        return f'https://api.{self.codename}.tzkt.io/v1/accounts/{self.address}'

    def get_tzkt_url(self):
        return f'https://{self.codename}.tzkt.io/{self.address}/'

    def generate_private_key(self):
        if self.crypted_key or not self.owner:
            return

        passphrase = ''.join(
            random.choice(string.ascii_letters) for i in range(42)
        )

        self.address, private_key = (
            self.blockchain.provider.create_wallet(passphrase)
        )

        self.crypted_key = encrypt(private_key)


class Blockchain(models.Model):
    name = models.CharField(max_length=100)
    endpoint = models.CharField(max_length=255)
    explorer = models.CharField(max_length=255, null=True, blank=True)
    provider_class = models.CharField(
        max_length=255,
        choices=SETTINGS['PROVIDERS'],
        default='djtezos.fake.Provider',
    )
    confirmation_blocks = models.IntegerField(default=0)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    max_level = models.PositiveIntegerField(default=None, blank=True, null=True)
    min_level = models.PositiveIntegerField(default=None, blank=True, null=True)

    def __str__(self):
        return self.name

    @property
    def provider(self):
        parts = self.provider_class.split('.')
        mod = importlib.import_module(
            '.'.join(parts[:-1])
        )
        return getattr(mod, parts[-1])(self)


class TransactionQuerySet(InheritanceQuerySetMixin, models.QuerySet):
    def for_user(self, user):
        return self.filter(
            Q(sender__owner=user)
            | Q(receiver__owner=user)
            | Q(users=user)
        )


class TransactionManager(InheritanceManagerMixin, models.Manager):
    def get_queryset(self):
        return TransactionQuerySet(self.model)


class Transaction(models.Model):
    id = models.UUIDField(
        primary_key=True,
        editable=False,
        default=uuid.uuid4
    )
    sender = models.ForeignKey(
        'Account',
        related_name='transactions_sent',
        null=True,
        on_delete=models.CASCADE,
    )
    receiver = models.ForeignKey(
        'Account',
        related_name='transactions_received',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
    )
    created_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now_add=True,
    )
    updated_at = models.DateTimeField(
        null=True,
        blank=True,
        auto_now=True,
    )
    txhash = models.CharField(
        unique=True,
        max_length=255,
        null=True,
        blank=True,
    )
    gasprice = models.BigIntegerField(blank=True, null=True)
    gas = models.BigIntegerField(blank=True, null=True)
    contract_address = models.CharField(max_length=255, null=True)
    contract_name = models.CharField(max_length=100, null=True)
    contract_source = models.TextField(null=True, blank=True)
    contract_micheline = models.JSONField(null=True, blank=True, default=list)
    contract = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='call_set',
    )
    function = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        db_index=True,
    )
    args = models.JSONField(null=True, default=list, blank=True)
    args_mich = models.JSONField(null=True, default=list, blank=True)
    amount = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Amount in xTZ',
        db_index=True,
    )
    level = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
    )
    last_fail = models.DateTimeField(
        null=True,
        blank=True,
        auto_now_add=True,
    )

    STATE_CHOICES = (
        ('held', _('Held')),
        ('aborted', _('Aborted')),
        ('deploy', _('To deploy')),
        ('deploying', _('Deploying')),
        ('retrying', _('Retrying')),
        ('watch', _('To watch')),
        ('watching', _('Watching')),
        ('done', _('Finished')),
    )
    state = models.CharField(
        choices=STATE_CHOICES,
        default='held',
        max_length=200,
        db_index=True,
    )
    error = models.TextField(blank=True)
    history = models.JSONField(default=list)
    states = [i[0] for i in STATE_CHOICES]

    objects = TransactionManager()

    def __str__(self):
        if self.txhash:
            return self.txhash
        elif self.function:
            return f'{self.contract_name}.{self.function}()'
        elif self.contract_name:
            return self.contract_name
        elif self.amount:
            return f'{self.amount}xTZ'
        else:
            return str(self.pk)

    @property
    def blockchain(self):
        if self.sender:
            return self.sender.blockchain

    @property
    def explorer_link(self):
        return self.blockchain.explorer.format(self.txhash)

    @property
    def provider(self):
        return self.sender.blockchain.provider

    def save(self, *args, **kwargs):
        if (
            not self.amount
            and not self.function
            and not self.contract_micheline
            and not self.contract_address
        ):
            raise ValidationError('Requires amount, function or micheline')

        if self.contract_id and not self.contract_name:
            self.contract_name = self.contract.contract_name

        if self.contract_id and not self.contract_address:
            self.contract_address = self.contract.contract_address

        if self.state not in self.states:
            raise Exception('Invalid state', self.state)

        return super().save(*args, **kwargs)

    def call(self, **kwargs):
        return Transaction.objects.create(
            contract=self,
            **kwargs
        )

    def state_set(self, state):
        self.state = state
        self.history.append([
            self.state,
            int(datetime.datetime.now().strftime('%s')),
        ])
        self.save()
        logger.info(f'Tx({self}).state set to {self.state}')
        # ensure commit happens, is it really necessary ?
        # not sure why not
        # django.db.connection.close()
        # close_old_connections()

    def get_tzkt_url(self):
        code = self.blockchain.endpoint.rstrip('/').split('/')[-1]
        return f'https://{code}.tzkt.io/{self.txhash}/'

    def get_better_url(self):
        return f'https://better-call.dev/search?text={self.txhash or self.contract_address}'


class ContractManager(TransactionManager):
    def get_queryset(self):
        return super().get_queryset().filter(function=None, amount=None)


class Contract(Transaction):
    objects = ContractManager()

    class Meta:
        proxy = True


class CallManager(TransactionManager):
    def get_queryset(self):
        return super().get_queryset().exclude(function=None)


class Call(Transaction):
    objects = CallManager()

    class Meta:
        proxy = True


class TransferManager(TransactionManager):
    def get_queryset(self):
        return super().get_queryset().exclude(amount=None)


class Transfer(Transaction):
    objects = TransferManager()

    class Meta:
        proxy = True
